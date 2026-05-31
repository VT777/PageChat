import os
import json
import copy
import math
import random
import re
import asyncio
from collections import Counter
from .utils import *
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# P2-7: 复用 pdf_analyzer 的代码 TOC 提取函数
from pageindex.pdf_analyzer import (
    extract_toc_from_bookmarks as _pdf_analyzer_extract_bookmarks,
    extract_toc_from_link_annotations as _pdf_analyzer_extract_links,
    extract_toc_by_regex as _pdf_analyzer_extract_regex,
)
from app.prompts.pageindex_prompts import (
    CHECK_TITLE_APPEARANCE_PROMPT,
    CHECK_TITLE_APPEARANCE_BATCH_PROMPT,
    TITLE_START_PROMPT,
    TITLE_START_BATCH_PROMPT,
    TOC_DETECTOR_SINGLE_PROMPT,
    TOC_DETECTOR_BATCH_PROMPT,
    TOC_EXTRACTION_COMPLETENESS_PROMPT,
    TOC_TRANSFORMATION_COMPLETENESS_PROMPT,
    EXTRACT_TOC_CONTENT_PROMPT,
    DETECT_PAGE_INDEX_PROMPT,
    TOC_INDEX_EXTRACT_PROMPT,
    TOC_TRANSFORM_INIT_PROMPT,
    TOC_TRANSFORM_CONTINUE_PROMPT,
    TOC_GENERATE_INIT_PROMPT,
    TOC_GENERATE_CONTINUE_PROMPT,
)

# Import quality validator
from pageindex.validation import QualityValidator


################### check title in page #########################################################
async def check_title_appearance(item, page_list, start_index=1, model=None):
    title = item["title"]
    if "physical_index" not in item or item["physical_index"] is None:
        return {
            "list_index": item.get("list_index"),
            "answer": "no",
            "title": title,
            "page_number": None,
        }

    page_number = item["physical_index"]
    page_text = page_list[page_number - start_index][0]

    prompt = CHECK_TITLE_APPEARANCE_PROMPT.format(title=title, page_text=page_text)

    response = await ChatGPT_API_async(model=model, prompt=prompt)
    response = extract_json(response)
    if "answer" in response:
        answer = response["answer"]
    else:
        answer = "no"
    return {
        "list_index": item["list_index"],
        "answer": answer,
        "title": title,
        "page_number": page_number,
    }


def _parse_json_array(text):
    """Robustly parse a JSON array from LLM response text.

    Handles: markdown fences, leading/trailing text, missing commas, trailing commas.
    Returns list on success, raises ValueError on failure.
    """
    if not text or not text.strip():
        raise ValueError("Empty response")

    s = text.strip()

    # Strip markdown code fence
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
        s = s.strip()

    # Find the outermost [...] in the response
    start = s.find("[")
    if start == -1:
        raise ValueError("No '[' found in response")
    depth = 0
    end = -1
    for i in range(start, len(s)):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise ValueError("No matching ']' found")

    candidate = s[start : end + 1]

    # Try direct parse
    try:
        result = json.loads(candidate)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fix trailing comma before ]
    fixed = re.sub(r",\s*]", "]", candidate)
    try:
        result = json.loads(fixed)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fix missing commas between } {
    fixed2 = re.sub(r"\}\s*\{", "},{", fixed)
    try:
        result = json.loads(fixed2)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    raise ValueError(f"Cannot parse JSON array from: {candidate[:200]}")


async def check_title_appearance_batch(
    items, page_list, start_index=1, model=None, batch_size=10
):
    """Batch-check multiple (title, page) pairs in fewer LLM calls.

    Args:
        items: List of dicts with 'id', 'title', 'physical_index', 'list_index'
        page_list: List of (content, token_length) tuples
        start_index: Starting page number (usually 1)
        model: LLM model name
        batch_size: Max items per batch (default 10)

    Returns:
        Dict mapping item id -> answer ('yes' or 'no')
    """
    if not items:
        return {}

    # Filter out items with None physical_index
    valid_items = [
        it
        for it in items
        if it.get("physical_index") is not None
        and it["physical_index"] - start_index < len(page_list)
    ]

    if not valid_items:
        return {it.get("id", it.get("list_index")): "no" for it in items}

    all_results = {}
    batches = [
        valid_items[i : i + batch_size] for i in range(0, len(valid_items), batch_size)
    ]

    async def _process_batch(batch):
        """Process one batch of items."""
        # Build batch_items, keeping physical_index for fallback
        batch_items = []
        for it in batch:
            page_idx = it["physical_index"] - start_index
            if 0 <= page_idx < len(page_list):
                page_text = page_list[page_idx][0][:2000]
                batch_items.append(
                    {
                        "id": it.get("id", it.get("list_index")),
                        "title": it["title"],
                        "page_text": page_text,
                        "physical_index": it["physical_index"],  # Keep for fallback
                    }
                )

        if not batch_items:
            return {}

        # Build prompt with only id/title/page_text (exclude physical_index)
        prompt_items = [
            {"id": bi["id"], "title": bi["title"], "page_text": bi["page_text"]}
            for bi in batch_items
        ]
        items_json = json.dumps(prompt_items, ensure_ascii=False)
        prompt = CHECK_TITLE_APPEARANCE_BATCH_PROMPT.format(items_json=items_json)

        try:
            response = await ChatGPT_API_async(model=model, prompt=prompt)
            parsed = _parse_json_array(response)
            # Force id to int — LLM may return string "0" instead of int 0
            return {int(r["id"]): r.get("answer", "no") for r in parsed if "id" in r}
        except Exception as e:
            # Fallback: process items individually
            print(f"[BATCH-FALLBACK] check_title_appearance batch failed: {e}")
            results = {}
            for bi in batch_items:
                try:
                    single_item = {
                        "title": bi["title"],
                        "physical_index": bi["physical_index"],
                        "list_index": bi["id"],
                    }
                    r = await check_title_appearance(
                        single_item, page_list, start_index, model
                    )
                    results[bi["id"]] = r["answer"]
                except Exception as e2:
                    print(
                        f"[BATCH-FALLBACK] Individual check failed for {bi['id']}: {e2}"
                    )
                    results[bi["id"]] = "no"
            return results

    # Process all batches concurrently
    batch_results = await asyncio.gather(*[_process_batch(b) for b in batches])
    for br in batch_results:
        all_results.update(br)

    # Add results for items that were filtered out (invalid physical_index)
    for it in items:
        item_id = it.get("id", it.get("list_index"))
        if item_id not in all_results:
            all_results[item_id] = "no"

    return all_results


async def check_title_appearance_in_start(title, page_text, model=None, logger=None):
    prompt = TITLE_START_PROMPT.format(title=title, page_text=page_text)

    response = await ChatGPT_API_async(model=model, prompt=prompt)
    response = extract_json(response)
    if logger:
        logger.info(f"Response: {response}")
    return response.get("start_begin", "no")


async def check_title_start_batch(
    items, page_list, start_index=1, model=None, batch_size=10
):
    """Batch-check multiple (title, page) pairs for start position in fewer LLM calls.

    Args:
        items: List of dicts with 'id', 'title', 'physical_index'
        page_list: List of (content, token_length) tuples
        start_index: Starting page number (usually 1)
        model: LLM model name
        batch_size: Max items per batch (default 10)

    Returns:
        Dict mapping item id -> start_begin ('yes' or 'no')
    """
    if not items:
        return {}

    # Filter out items with None physical_index
    valid_items = [
        it
        for it in items
        if it.get("physical_index") is not None
        and it["physical_index"] - start_index < len(page_list)
    ]

    if not valid_items:
        return {it.get("id", it.get("list_index")): "no" for it in items}

    all_results = {}
    batches = [
        valid_items[i : i + batch_size] for i in range(0, len(valid_items), batch_size)
    ]

    async def _process_batch(batch):
        """Process one batch of items."""
        batch_items = []
        for it in batch:
            page_idx = it["physical_index"] - start_index
            if 0 <= page_idx < len(page_list):
                page_text = page_list[page_idx][0][:2000]
                batch_items.append(
                    {
                        "id": it.get("id", it.get("list_index")),
                        "title": it["title"],
                        "page_text": page_text,
                    }
                )

        if not batch_items:
            return {}

        # Build prompt with only id/title/page_text
        items_json = json.dumps(batch_items, ensure_ascii=False)
        prompt = TITLE_START_BATCH_PROMPT.format(items_json=items_json)

        try:
            response = await ChatGPT_API_async(model=model, prompt=prompt)
            parsed = _parse_json_array(response)
            # Force id to int — LLM may return string "0" instead of int 0
            return {
                int(r["id"]): r.get("start_begin", "no") for r in parsed if "id" in r
            }
        except Exception as e:
            # Fallback: process items individually
            print(f"[BATCH-FALLBACK] check_title_start batch failed: {e}")
            results = {}
            for bi in batch_items:
                try:
                    r = await check_title_appearance_in_start(
                        bi["title"], bi["page_text"], model
                    )
                    results[bi["id"]] = r
                except Exception as e2:
                    print(
                        f"[BATCH-FALLBACK] Individual start check failed for {bi['id']}: {e2}"
                    )
                    results[bi["id"]] = "no"
            return results

    # Process all batches concurrently
    batch_results = await asyncio.gather(*[_process_batch(b) for b in batches])
    for br in batch_results:
        all_results.update(br)

    # Add results for items that were filtered out
    for it in items:
        item_id = it.get("id", it.get("list_index"))
        if item_id not in all_results:
            all_results[item_id] = "no"

    return all_results


async def check_title_appearance_in_start_concurrent(
    structure, page_list, model=None, logger=None
):
    if logger:
        logger.info("Checking title appearance in start concurrently (batched)")

    # skip items without physical_index
    for item in structure:
        if item.get("physical_index") is None:
            item["appear_start"] = "no"

    # Prepare items for batch processing
    items_for_batch = []
    valid_items = []
    for item in structure:
        if item.get("physical_index") is not None:
            items_for_batch.append(
                {
                    "id": item.get("list_index", id(item)),
                    "title": item["title"],
                    "physical_index": item["physical_index"],
                    "list_index": item.get("list_index"),
                }
            )
            valid_items.append(item)

    if not items_for_batch:
        return structure

    # Batch process all items
    try:
        results = await check_title_start_batch(
            items_for_batch, page_list, start_index=1, model=model, batch_size=10
        )

        # Map results back to items
        for item, batch_item in zip(valid_items, items_for_batch):
            item_id = batch_item["id"]
            if item_id in results:
                item["appear_start"] = results[item_id]
            else:
                item["appear_start"] = "no"
                if logger:
                    logger.warning(
                        f"No result for item {item['title']}, defaulting to 'no'"
                    )
    except Exception as e:
        if logger:
            logger.error(
                f"Batch processing failed, falling back to individual calls: {e}"
            )
        # Fallback: process individually
        tasks = []
        for item in valid_items:
            page_text = page_list[item["physical_index"] - 1][0]
            tasks.append(
                check_title_appearance_in_start(
                    item["title"], page_text, model=model, logger=logger
                )
            )

        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        for item, result in zip(valid_items, task_results):
            if isinstance(result, Exception):
                if logger:
                    logger.error(f"Error checking start for {item['title']}: {result}")
                item["appear_start"] = "no"
            else:
                item["appear_start"] = result

    return structure


def toc_detector_single_page(content, model=None):
    prompt = TOC_DETECTOR_SINGLE_PROMPT.format(content=content)

    response = ChatGPT_API(model=model, prompt=prompt)
    # print('response', response)
    json_content = extract_json(response)
    return json_content["toc_detected"]


def toc_detector_batch(page_contents, model=None, batch_size=15):
    """
    批量检测多页内容中哪些包含目录

    Args:
        page_contents: [(page_index, content), ...] 页码和内容列表
        model: LLM模型
        batch_size: 每批处理的页数，默认5页

    Returns:
        list: 包含目录的页码列表
    """
    if not page_contents:
        return []

    # 分批处理
    all_toc_pages = []
    total_pages = len(page_contents)

    for batch_start in range(0, total_pages, batch_size):
        batch_end = min(batch_start + batch_size, total_pages)
        batch = page_contents[batch_start:batch_end]

        # 构建批量检测的prompt
        pages_text = "\n\n---PAGE_BREAK---\n\n".join(
            [
                f"[Page {idx}]\n{content[:1000]}"  # 限制每页1000字符控制token
                for idx, content in batch
            ]
        )

        prompt = TOC_DETECTOR_BATCH_PROMPT.format(pages_content=pages_text)

        try:
            response = ChatGPT_API(model=model, prompt=prompt)
            json_content = extract_json(response)

            # 获取检测到的页码（批次内索引）
            batch_toc_indices = json_content.get("pages_with_toc")
            if batch_toc_indices is None:
                batch_toc_indices = json_content.get("toc_pages", [])

            # 转换为实际页码
            for idx in batch_toc_indices:
                if 0 <= idx < len(batch):
                    actual_page_index = batch[idx][0]
                    all_toc_pages.append(actual_page_index)

        except Exception as e:
            print(f"Batch TOC detection error for pages {batch_start}-{batch_end}: {e}")
            # 批量检测失败，回退到单页检测
            for idx, content in batch:
                try:
                    result = toc_detector_single_page(content, model=model)
                    if result == "yes":
                        all_toc_pages.append(idx)
                except:
                    pass

    return sorted(all_toc_pages)


def check_if_toc_extraction_is_complete(content, toc, model=None):
    prompt = TOC_EXTRACTION_COMPLETENESS_PROMPT.format(content=content, toc=toc)
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    completed = None
    if isinstance(json_content, dict):
        completed = json_content.get("completed")
    if isinstance(completed, str) and completed.strip().lower() in {"yes", "no"}:
        return completed.strip().lower()
    return "no"


def check_if_toc_transformation_is_complete(content, toc, model=None):
    prompt = TOC_TRANSFORMATION_COMPLETENESS_PROMPT.format(
        raw_toc=content,
        cleaned_toc=toc,
    )
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    completed = None
    if isinstance(json_content, dict):
        completed = json_content.get("completed")
    if isinstance(completed, str) and completed.strip().lower() in {"yes", "no"}:
        return completed.strip().lower()
    return "no"


def _normalize_toc_items(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("table_of_contents", "toc", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if "title" in payload and (
            "physical_index" in payload or "page" in payload or "structure" in payload
        ):
            return [payload]
    return []


def extract_toc_content(content, model=None):
    prompt = EXTRACT_TOC_CONTENT_PROMPT.format(content=content)

    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    if_complete = check_if_toc_transformation_is_complete(content, response, model)
    if if_complete == "yes" and finish_reason == "finished":
        return response

    chat_history = [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": response},
    ]
    prompt = TOC_TRANSFORM_CONTINUE_PROMPT.format(
        toc_content=content,
        partial_json=response,
    )
    new_response, finish_reason = ChatGPT_API_with_finish_reason(
        model=model, prompt=prompt, chat_history=chat_history
    )
    response = response + new_response
    if_complete = check_if_toc_transformation_is_complete(content, response, model)

    attempt = 0
    max_attempts = 5

    while not (if_complete == "yes" and finish_reason == "finished"):
        attempt += 1
        if attempt > max_attempts:
            raise Exception(
                "Failed to complete table of contents after maximum retries"
            )

        chat_history = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ]
        prompt = TOC_TRANSFORM_CONTINUE_PROMPT.format(
            toc_content=content,
            partial_json=response,
        )
        new_response, finish_reason = ChatGPT_API_with_finish_reason(
            model=model, prompt=prompt, chat_history=chat_history
        )
        response = response + new_response
        if_complete = check_if_toc_transformation_is_complete(content, response, model)

    return response


def detect_page_index(toc_content, model=None):
    print("start detect_page_index")

    def has_clear_page_number_signal(text: str) -> bool:
        content = str(text or "")
        if not content.strip():
            return False

        clear_hits = 0
        # Common TOC separator styles: dots/colon/multi-space before page number.
        clear_hits += len(
            re.findall(
                r"(?:[:：]|\.{2,}|…{2,}|\s{2,})([1-9]\d{0,3})(?=\s*(?:\n|$))",
                content,
            )
        )
        # Per-line styles like: 标题 ...... 12 / 标题: 12
        clear_hits += len(
            re.findall(
                r"[^\n:：]{2,120}(?:[:：]|\.{2,}|…{2,}|\s{2,})([1-9]\d{0,3})(?=\s*(?:\n|$))",
                content,
            )
        )

        ambiguous_suffix_hits = len(
            re.findall(r"[\u4e00-\u9fffA-Za-z][0-9]{2}(?=\s|$)", content)
        )

        if clear_hits >= 2:
            return True
        if clear_hits == 1 and ambiguous_suffix_hits == 0:
            return True
        return False

    prompt = DETECT_PAGE_INDEX_PROMPT.format(toc_content=toc_content)

    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    llm_decision = "no"
    if isinstance(json_content, dict):
        val = str(json_content.get("page_index_given_in_toc") or "").strip().lower()
        if val in {"yes", "no"}:
            llm_decision = val

    if llm_decision == "yes" and not has_clear_page_number_signal(toc_content):
        return "no"
    return llm_decision


def toc_extractor(page_list, toc_page_list, model):
    def transform_dots_to_colon(text):
        text = re.sub(r"\.{5,}", ": ", text)
        # Handle dots separated by spaces
        text = re.sub(r"(?:\. ){5,}\.?", ": ", text)
        return text

    toc_content = ""
    for page_index in toc_page_list:
        toc_content += page_list[page_index][0]
    toc_content = transform_dots_to_colon(toc_content)
    has_page_index = detect_page_index(toc_content, model=model)

    return {"toc_content": toc_content, "page_index_given_in_toc": has_page_index}


def toc_index_extractor(toc, content, model=None):
    print("start toc_index_extractor")
    prompt = TOC_INDEX_EXTRACT_PROMPT.format(
        toc=str(toc),
        content=content,
    )
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    return json_content


def toc_transformer(toc_content, model=None):
    print("start toc_transformer")
    prompt = TOC_TRANSFORM_INIT_PROMPT.format(toc_content=toc_content)
    last_complete, finish_reason = ChatGPT_API_with_finish_reason(
        model=model, prompt=prompt
    )
    if_complete = check_if_toc_transformation_is_complete(
        toc_content, last_complete, model
    )
    if if_complete == "yes" and finish_reason == "finished":
        last_complete = extract_json(last_complete)
        cleaned_response = convert_page_to_int(last_complete["table_of_contents"])
        return cleaned_response

    last_complete = get_json_content(last_complete)
    max_continuation_attempts = 5
    continuation_count = 0
    while (
        not (if_complete == "yes" and finish_reason == "finished")
        and continuation_count < max_continuation_attempts
    ):
        continuation_count += 1
        position = last_complete.rfind("}")
        if position != -1:
            last_complete = last_complete[: position + 2]
        prompt = TOC_TRANSFORM_CONTINUE_PROMPT.format(
            toc_content=toc_content,
            partial_json=last_complete,
        )

        new_complete, finish_reason = ChatGPT_API_with_finish_reason(
            model=model, prompt=prompt
        )

        if new_complete.startswith("```json"):
            new_complete = get_json_content(new_complete)
            last_complete = last_complete + new_complete

        if_complete = check_if_toc_transformation_is_complete(
            toc_content, last_complete, model
        )

    last_complete = json.loads(last_complete)

    cleaned_response = convert_page_to_int(last_complete["table_of_contents"])
    return cleaned_response


def find_toc_pages(start_page_index, page_list, opt, logger=None):
    """查找包含目录的页面（优化版：批量检测）"""
    print("start find_toc_pages (optimized with batch detection)")

    def looks_like_toc_page(text: str) -> bool:
        content = str(text or "")
        if not content.strip():
            return False

        compact = re.sub(r"\s+", " ", content)
        heading_with_page = re.findall(
            r"(?:第[一二三四五六七八九十百零〇两\d]+[章节部分篇]"
            r"|\d{1,2}(?:\.\d{1,2}){0,3}"
            r"|[一二三四五六七八九十百零〇两]+、"
            r"|[（(][一二三四五六七八九十百零〇两\d]+[)）]"
            r"|图\s*\d+"
            r"|表\s*\d+)"
            r"\s*[^\n:：]{1,80}[:：]\s*\d{1,4}",
            compact,
        )
        if "目录" in content and len(heading_with_page) >= 2:
            return True
        return len(heading_with_page) >= 3

    def enrich_toc_pages(initial_pages: list[int]) -> list[int]:
        if not initial_pages:
            return []

        enriched = sorted(set(initial_pages))

        # fill missed pages inside detected TOC range
        left = max(start_page_index, enriched[0])
        right = min(end_page - 1, enriched[-1])
        for page_idx in range(left, right + 1):
            if page_idx not in enriched and looks_like_toc_page(page_list[page_idx][0]):
                enriched.append(page_idx)

        # look ahead up to 2 pages after the last TOC page
        cursor = max(enriched) + 1
        tail_limit = min(end_page - 1, max(enriched) + 2)
        while cursor <= tail_limit:
            if looks_like_toc_page(page_list[cursor][0]):
                enriched.append(cursor)
                cursor += 1
                continue
            break

        return sorted(set(enriched))

    # 准备要检测的页面列表
    pages_to_check = []
    end_page = min(start_page_index + opt.toc_check_page_num, len(page_list))

    for i in range(start_page_index, end_page):
        pages_to_check.append((i, page_list[i][0]))

    if not pages_to_check:
        if logger:
            logger.info("No pages to check for TOC")
        return []

    # 使用批量检测（每批5页）
    toc_page_list = toc_detector_batch(pages_to_check, model=opt.model, batch_size=5)
    toc_page_list = enrich_toc_pages(toc_page_list)

    # 排序并记录日志
    toc_page_list = sorted(toc_page_list)

    if toc_page_list:
        if logger:
            logger.info(f"Found TOC pages: {toc_page_list}")
        print(f"Batch TOC detection found pages: {toc_page_list}")
    else:
        if logger:
            logger.info("No toc found")
        print("Batch TOC detection: no TOC found")

    return toc_page_list


def remove_page_number(data):
    if isinstance(data, dict):
        data.pop("page_number", None)
        for key in list(data.keys()):
            if "nodes" in key:
                remove_page_number(data[key])
    elif isinstance(data, list):
        for item in data:
            remove_page_number(item)
    return data


def extract_matching_page_pairs(toc_page, toc_physical_index, start_page_index):
    pairs = []
    for phy_item in toc_physical_index:
        for page_item in toc_page:
            if phy_item.get("title") == page_item.get("title"):
                physical_index = phy_item.get("physical_index")
                if (
                    physical_index is not None
                    and int(physical_index) >= start_page_index
                ):
                    pairs.append(
                        {
                            "title": phy_item.get("title"),
                            "page": page_item.get("page"),
                            "physical_index": physical_index,
                        }
                    )
    return pairs


def calculate_page_offset(pairs):
    differences = []
    for pair in pairs:
        try:
            physical_index = pair["physical_index"]
            page_number = pair["page"]
            difference = physical_index - page_number
            differences.append(difference)
        except (KeyError, TypeError):
            continue

    if not differences:
        return None

    difference_counts = {}
    for diff in differences:
        difference_counts[diff] = difference_counts.get(diff, 0) + 1

    most_common = max(difference_counts.items(), key=lambda x: x[1])[0]

    return most_common


def add_page_offset_to_toc_json(data, offset):
    if offset is None:
        raise ValueError("offset_unresolved: page offset is None")
    if not isinstance(offset, int):
        raise ValueError(f"offset_invalid_type: {type(offset).__name__}")

    for i in range(len(data)):
        if data[i].get("page") is not None and isinstance(data[i]["page"], int):
            data[i]["physical_index"] = data[i]["page"] + offset
            del data[i]["page"]

    return data


def page_list_to_group_text(
    page_contents, token_lengths, max_tokens=60000, overlap_page=1
):
    num_tokens = sum(token_lengths)

    if num_tokens <= max_tokens:
        # merge all pages into one text
        page_text = "".join(page_contents)
        return [page_text]

    subsets = []
    current_subset = []
    current_token_count = 0

    expected_parts_num = math.ceil(num_tokens / max_tokens)
    average_tokens_per_part = math.ceil(
        ((num_tokens / expected_parts_num) + max_tokens) / 2
    )

    for i, (page_content, page_tokens) in enumerate(zip(page_contents, token_lengths)):
        if current_token_count + page_tokens > average_tokens_per_part:
            subsets.append("".join(current_subset))
            # Start new subset from overlap if specified
            overlap_start = max(i - overlap_page, 0)
            current_subset = page_contents[overlap_start:i]
            current_token_count = sum(token_lengths[overlap_start:i])

        # Add current page to the subset
        current_subset.append(page_content)
        current_token_count += page_tokens

    # Add the last subset if it contains any pages
    if current_subset:
        subsets.append("".join(current_subset))

    print("divide page_list to groups", len(subsets))
    return subsets


def add_page_number_to_toc(part, structure, model=None):
    fill_prompt_seq = """
    You are given an JSON structure of a document and a partial part of the document. Your task is to check if the title that is described in the structure is started in the partial given document.

    The provided text contains tags like <physical_index_X> and </physical_index_X> to indicate the start and end of page X. 

    If the full target section starts in the partial given document, insert the given JSON structure with the "start": "yes", and "start_index": "<physical_index_X>".

    If the full target section does not start in the partial given document, insert "start": "no",  "start_index": None.

    The response should be in the following format. 
        [
            {
                "structure": <structure index, "x.x.x" or None> (string),
                "title": <title of the section>,
                "start": "<yes or no>",
                "physical_index": "<physical_index_X> (keep the format)" or None
            },
            ...
        ]    
    The given structure contains the result of the previous part, you need to fill the result of the current part, do not change the previous result.
    Directly return the final JSON structure. Do not output anything else."""

    prompt = (
        fill_prompt_seq
        + f"\n\nCurrent Partial Document:\n{part}\n\nGiven Structure\n{json.dumps(structure, indent=2)}\n"
    )
    current_json_raw = ChatGPT_API(model=model, prompt=prompt)
    json_result = extract_json(current_json_raw)

    for item in json_result:
        if "start" in item:
            del item["start"]
    return json_result


def remove_first_physical_index_section(text):
    """
    Removes the first section between <physical_index_X> and </physical_index_X> tags,
    and returns the remaining text.
    """
    pattern = r"<physical_index_\d+>.*?</physical_index_\d+>"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        # Remove the first matched section
        return text.replace(match.group(0), "", 1)
    return text


### add verify completeness
def generate_toc_continue(toc_content, part, model="gpt-4o-2024-11-20"):
    print("start generate_toc_continue")
    prompt = TOC_GENERATE_CONTINUE_PROMPT.format(
        part=part,
        toc_content=json.dumps(toc_content, indent=2),
    )
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)
    if finish_reason == "finished":
        return _normalize_toc_items(extract_json(response))
    else:
        raise Exception(f"finish reason: {finish_reason}")


### add verify completeness
def generate_toc_init(part, model=None):
    print("start generate_toc_init")
    prompt = TOC_GENERATE_INIT_PROMPT.format(part=part)
    response, finish_reason = ChatGPT_API_with_finish_reason(model=model, prompt=prompt)

    if finish_reason == "finished":
        return _normalize_toc_items(extract_json(response))
    else:
        raise Exception(f"finish reason: {finish_reason}")


def process_no_toc(page_list, start_index=1, model=None, logger=None):
    page_contents = []
    token_lengths = []
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index - start_index][0]}\n</physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))
    group_texts = page_list_to_group_text(page_contents, token_lengths)
    logger.info(f"len(group_texts): {len(group_texts)}")

    toc_with_page_number = _normalize_toc_items(
        generate_toc_init(group_texts[0], model)
    )
    for group_text in group_texts[1:]:
        toc_with_page_number_additional = _normalize_toc_items(
            generate_toc_continue(toc_with_page_number, group_text, model)
        )
        if not isinstance(toc_with_page_number, list):
            toc_with_page_number = _normalize_toc_items(toc_with_page_number)
        toc_with_page_number.extend(toc_with_page_number_additional)
    logger.info(f"generate_toc: {toc_with_page_number}")

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    logger.info(f"convert_physical_index_to_int: {toc_with_page_number}")

    return toc_with_page_number


def _normalize_heading_line(line: str) -> str:
    s = line.replace("\u3000", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _line_digit_ratio(line: str) -> float:
    if not line:
        return 0.0
    digits = sum(ch.isdigit() for ch in line)
    return digits / max(len(line), 1)


def _looks_like_table_row(line: str) -> bool:
    if not line:
        return False
    # Financial table rows often have many numbers and separators/columns
    if _line_digit_ratio(line) > 0.45:
        return True
    if re.search(r"\d{1,3}(,\d{3})+(\.\d+)?", line):
        return True
    if re.search(r"\b(本报告期|上年同期|调整前|调整后|单位[:：]|币种[:：])\b", line):
        return True
    if len(re.findall(r"\s{2,}", line)) >= 2:
        return True
    return False


def _is_noise_line(line: str, repeated_lines: set[str]) -> bool:
    if not line:
        return True
    # Repeated header/footer lines
    if line in repeated_lines:
        return True
    # Typical report headers/footers and securities metadata
    if re.search(r"(证券代码|证券简称|第[一二三四五六七八九十0-9]+季度报告)", line):
        return True
    if re.search(r"^\d+\s*/\s*\d+$", line):
        return True
    if len(line) > 120:
        return True
    if re.match(r"^[\W_]+$", line):
        return True
    return False


def _build_comprehensive_heading_patterns() -> list[tuple[re.Pattern, int, str]]:
    """
    Returns list of (compiled_pattern, level, kind)
    level: 1/2/3 heading depth hint
    kind: semantic kind for scoring
    """
    patterns: list[tuple[re.Pattern, int, str]] = [
        # Chinese chapter forms: 第X章/节/部分/篇
        (
            re.compile(r"^(第[一二三四五六七八九十百零〇两\d]+[章节部分篇])\s*(.+)$"),
            1,
            "cn_chapter",
        ),
        # Chinese list heading: 一、 二、 ...
        (re.compile(r"^([一二三四五六七八九十百零〇两]+、)\s*(.+)$"), 1, "cn_list"),
        # Chinese subsection: （一） （二）...
        (re.compile(r"^（([一二三四五六七八九十百零〇两]+)）\s*(.+)$"), 2, "cn_sub"),
        # Number subsection: （1） -- intentionally lower confidence in filtering
        (re.compile(r"^[（(](\d{1,2})[)）]\s*(.+)$"), 3, "num_sub"),
        # Arabic headings: 1 / 1.1 / 1.1.1
        (re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})[、.．\s]+(.+)$"), 1, "num_heading"),
        # English chapter forms
        (
            re.compile(r"^(Chapter|Section|Part)\s+([A-Za-z0-9IVXivx]+)[:.\-\s]+(.+)$"),
            1,
            "en_chapter",
        ),
        # Financial statement anchors
        (
            re.compile(
                r"^(合并资产负债表|合并利润表|合并现金流量表|母公司资产负债表|母公司利润表|母公司现金流量表)$"
            ),
            1,
            "financial_anchor",
        ),
    ]
    return patterns


def _score_heading_candidate(line: str, kind: str) -> float:
    score = 0.0
    if kind in {"cn_chapter", "cn_list", "num_heading", "en_chapter"}:
        score += 0.65
    elif kind in {"cn_sub"}:
        score += 0.42
    elif kind in {"num_sub"}:
        score += 0.30
    elif kind in {"financial_anchor"}:
        score += 0.80

    # Financial report keywords boost
    if re.search(
        r"(主要财务数据|股东信息|季度财务报表|财务报表|审计意见|管理层)", line
    ):
        score += 0.20

    # Penalties
    if _looks_like_table_row(line):
        score -= 0.50
    elif _line_digit_ratio(line) > 0.32:
        score -= 0.25

    return score


def extract_sections_by_rules(page_list, start_index=1, logger=None):
    """
    Rule-based section extraction for no-TOC documents.
    Returns flat TOC list compatible with existing pipeline.
    """
    patterns = _build_comprehensive_heading_patterns()

    # Build repeated-line set for header/footer suppression
    all_lines: list[str] = []
    for text, _ in page_list:
        for raw in text.splitlines():
            line = _normalize_heading_line(raw)
            if line:
                all_lines.append(line)

    line_counts = Counter(all_lines)
    repeated_threshold = max(2, int(len(page_list) * 0.5))
    repeated_lines = {
        line for line, c in line_counts.items() if c >= repeated_threshold
    }

    candidates = []
    for page_offset, (text, _) in enumerate(page_list):
        physical_index = start_index + page_offset
        lines = text.splitlines()
        non_noise_rank = 0
        for line_no, raw in enumerate(lines):
            line = _normalize_heading_line(raw)
            if _is_noise_line(line, repeated_lines):
                continue
            non_noise_rank += 1

            matched = None
            level = 1
            kind = ""
            for pat, lvl, k in patterns:
                m = pat.match(line)
                if m:
                    matched = m
                    level = lvl
                    kind = k
                    break

            if not matched:
                continue

            score = _score_heading_candidate(line, kind)
            threshold = 0.45 if kind == "financial_anchor" else 0.55
            if score < threshold:
                continue

            # Additional anti-noise filters for numeric pseudo headings in tables
            if kind in {"num_heading", "num_sub"}:
                # Keep numeric headings only near top of a page
                if non_noise_rank > 15:
                    continue
                # Rows ending with many numbers are likely table rows
                trailing_nums = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", line)
                if len(trailing_nums) >= 2:
                    continue

            # Common finance table rows contain colon-like labels and values
            if kind in {"cn_list", "cn_sub", "num_heading", "num_sub"}:
                if re.search(
                    r"(净利润|每股收益|综合收益|经营活动|投资活动|筹资活动)", line
                ) and _looks_like_table_row(line):
                    continue

            # Build structure string
            structure = None
            if kind == "num_heading":
                structure = matched.group(1)
            elif kind in {"cn_chapter", "cn_list"}:
                # use sequential top-level index for stable tree building
                structure = None
            elif kind == "cn_sub":
                structure = None
            elif kind == "num_sub":
                structure = None
            elif kind == "en_chapter":
                structure = None
            elif kind == "financial_anchor":
                structure = None

            candidates.append(
                {
                    "title": line,
                    "physical_index": physical_index,
                    "level_hint": level,
                    "kind": kind,
                    "line_no": line_no,
                    "structure": structure,
                }
            )

    # Per-page pruning: keep the most likely headings only
    priority = {
        "financial_anchor": 5,
        "cn_chapter": 4,
        "cn_list": 4,
        "en_chapter": 4,
        "cn_sub": 3,
        "num_heading": 2,
        "num_sub": 1,
    }
    by_page = {}
    for c in candidates:
        by_page.setdefault(c["physical_index"], []).append(c)

    pruned = []
    for _, items in by_page.items():
        items_sorted = sorted(
            items,
            key=lambda x: (priority.get(x["kind"], 0), -x["line_no"]),
            reverse=True,
        )
        # cap headings per page to avoid table-induced explosion
        pruned.extend(items_sorted[:4])

    candidates = pruned

    # Deduplicate same title+page and stable sort
    dedup = {}
    for c in candidates:
        key = (c["title"], c["physical_index"])
        if key not in dedup:
            dedup[key] = c

    ordered = sorted(dedup.values(), key=lambda x: (x["physical_index"], x["line_no"]))

    # Assign structures if missing
    top_counter = 0
    last_top = 0
    sub_counter = 0
    for item in ordered:
        if item["structure"]:
            # explicit numeric heading
            continue
        if item["level_hint"] <= 1:
            top_counter += 1
            last_top = top_counter
            sub_counter = 0
            item["structure"] = str(top_counter)
        elif item["level_hint"] == 2 and last_top > 0:
            sub_counter += 1
            item["structure"] = f"{last_top}.{sub_counter}"
        elif last_top > 0:
            sub_counter += 1
            item["structure"] = f"{last_top}.{sub_counter}"
        else:
            top_counter += 1
            last_top = top_counter
            item["structure"] = str(top_counter)

    toc = [
        {
            "structure": item["structure"],
            "title": item["title"],
            "physical_index": item["physical_index"],
        }
        for item in ordered
    ]

    if logger is not None:
        logger.info(
            {
                "rule_extract": {
                    "total_candidates": len(candidates),
                    "deduped": len(toc),
                    "repeated_lines_filtered": len(repeated_lines),
                }
            }
        )

    return toc


def is_rule_toc_reliable(toc: list[dict], logger=None) -> bool:
    if not toc:
        return False

    level1 = [x for x in toc if str(x.get("structure", "")).count(".") == 0]
    if len(level1) < 3:
        return False

    joined_titles = " ".join(x.get("title", "") for x in toc)
    anchor_hit = bool(
        re.search(
            r"(主要财务数据|股东信息|季度财务报表|合并资产负债表|合并利润表|合并现金流量表)",
            joined_titles,
        )
    )
    if logger is not None:
        logger.info(
            {
                "rule_gate": {
                    "level1_count": len(level1),
                    "anchor_hit": anchor_hit,
                }
            }
        )
    return anchor_hit


async def generate_toc_with_specialized_prompt(
    page_list, doc_type: str, start_index=1, model=None, logger=None
):
    """
    Generate table of contents using specialized prompt for document type

    Args:
        page_list: List of (text, token_count) tuples
        doc_type: Document type (financial_report, academic_paper, etc.)
        start_index: Starting page index
        model: LLM model to use
        logger: Logger instance

    Returns:
        List of TOC items
    """
    # Deprecated path: keep function for backward compatibility.
    # It now reuses the generic generation prompt path.
    system_prompt = None

    # Prepare page contents
    page_contents = []
    token_lengths = []
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index - start_index][0]}\n</physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))

    # Group texts if too long
    group_texts = page_list_to_group_text(page_contents, token_lengths)
    logger.info(
        f"[Specialized TOC] Processing {len(group_texts)} text groups for {doc_type}"
    )

    # Use the existing general no-TOC generation path
    toc_result = generate_toc_init(group_texts[0], model)
    for group_text in group_texts[1:]:
        toc_result.extend(generate_toc_continue(toc_result, group_text, model))

    # Convert physical_index format
    toc_result = convert_physical_index_to_int(toc_result)

    logger.info(f"[Specialized TOC] Generated {len(toc_result)} items for {doc_type}")

    return toc_result


def process_toc_no_page_numbers(
    toc_content, toc_page_list, page_list, start_index=1, model=None, logger=None
):
    page_contents = []
    token_lengths = []
    toc_content = toc_transformer(toc_content, model)
    logger.info(f"toc_transformer: {toc_content}")
    for page_index in range(start_index, start_index + len(page_list)):
        page_text = f"<physical_index_{page_index}>\n{page_list[page_index - start_index][0]}\n</physical_index_{page_index}>\n\n"
        page_contents.append(page_text)
        token_lengths.append(count_tokens(page_text, model))

    group_texts = page_list_to_group_text(page_contents, token_lengths)
    logger.info(f"len(group_texts): {len(group_texts)}")

    toc_with_page_number = copy.deepcopy(toc_content)
    for group_text in group_texts:
        toc_with_page_number = add_page_number_to_toc(
            group_text, toc_with_page_number, model
        )
    logger.info(f"add_page_number_to_toc: {toc_with_page_number}")

    toc_with_page_number = convert_physical_index_to_int(toc_with_page_number)
    logger.info(f"convert_physical_index_to_int: {toc_with_page_number}")

    return toc_with_page_number


def process_toc_with_page_numbers(
    toc_content,
    toc_page_list,
    page_list,
    toc_check_page_num=None,
    toc_content_match_page_num=15,
    model=None,
    logger=None,
):
    toc_with_page_number = toc_transformer(toc_content, model)
    logger.info(f"toc_with_page_number: {toc_with_page_number}")

    toc_no_page_number = remove_page_number(copy.deepcopy(toc_with_page_number))

    start_page_index = toc_page_list[-1] + 1
    main_content = ""
    # Use toc_content_match_page_num (wider) for content matching, not toc_check_page_num (narrower)
    match_range = toc_content_match_page_num or toc_check_page_num or 15
    for page_index in range(
        start_page_index, min(start_page_index + match_range, len(page_list))
    ):
        main_content += f"<physical_index_{page_index + 1}>\n{page_list[page_index][0]}\n</physical_index_{page_index + 1}>\n\n"

    toc_with_physical_index = toc_index_extractor(
        toc_no_page_number, main_content, model
    )
    logger.info(f"toc_with_physical_index: {toc_with_physical_index}")

    toc_with_physical_index = convert_physical_index_to_int(toc_with_physical_index)
    logger.info(f"toc_with_physical_index: {toc_with_physical_index}")

    matching_pairs = extract_matching_page_pairs(
        toc_with_page_number, toc_with_physical_index, start_page_index
    )
    logger.info(f"matching_pairs: {matching_pairs}")

    if len(toc_with_page_number) >= 3 and len(matching_pairs) < 2:
        raise ValueError(
            f"TOC_PAGE_MAPPING_WEAK: insufficient_anchor_pairs={len(matching_pairs)}"
        )

    offset = calculate_page_offset(matching_pairs)
    logger.info(f"offset: {offset}")

    toc_with_page_number = add_page_offset_to_toc_json(toc_with_page_number, offset)
    logger.info(f"toc_with_page_number: {toc_with_page_number}")

    toc_with_page_number = process_none_page_numbers(
        toc_with_page_number, page_list, model=model
    )
    logger.info(f"toc_with_page_number: {toc_with_page_number}")

    return toc_with_page_number


##check if needed to process none page numbers
def process_none_page_numbers(toc_items, page_list, start_index=1, model=None):
    for i, item in enumerate(toc_items):
        if "physical_index" not in item:
            # logger.info(f"fix item: {item}")
            # Find previous physical_index
            prev_physical_index = 0  # Default if no previous item exists
            for j in range(i - 1, -1, -1):
                if toc_items[j].get("physical_index") is not None:
                    prev_physical_index = toc_items[j]["physical_index"]
                    break

            # Find next physical_index
            next_physical_index = -1  # Default if no next item exists
            for j in range(i + 1, len(toc_items)):
                if toc_items[j].get("physical_index") is not None:
                    next_physical_index = toc_items[j]["physical_index"]
                    break

            page_contents = []
            for page_index in range(prev_physical_index, next_physical_index + 1):
                # Add bounds checking to prevent IndexError
                list_index = page_index - start_index
                if list_index >= 0 and list_index < len(page_list):
                    page_text = f"<physical_index_{page_index}>\n{page_list[list_index][0]}\n</physical_index_{page_index}>\n\n"
                    page_contents.append(page_text)
                else:
                    continue

            item_copy = copy.deepcopy(item)
            del item_copy["page"]
            result = add_page_number_to_toc(page_contents, item_copy, model)
            if isinstance(result[0]["physical_index"], str) and result[0][
                "physical_index"
            ].startswith("<physical_index"):
                item["physical_index"] = int(
                    result[0]["physical_index"].split("_")[-1].rstrip(">").strip()
                )
                del item["page"]

    return toc_items


def _assess_no_toc_range_quality(toc_items, page_count):
    score = 1.0
    issues = []

    page_indices = []
    for item in toc_items or []:
        idx = item.get("physical_index")
        if isinstance(idx, int):
            page_indices.append(idx)
            continue
        if isinstance(idx, str):
            m = re.search(r"physical_index_(\d+)", idx)
            if m:
                page_indices.append(int(m.group(1)))

    if not page_indices:
        return {"score": 0.0, "issues": ["no_valid_physical_index"]}

    unique_pages = sorted(set(page_indices))
    dominant_count = max(page_indices.count(p) for p in unique_pages)
    dominant_ratio = dominant_count / max(1, len(page_indices))
    coverage_span = max(unique_pages) - min(unique_pages) + 1

    if len(toc_items or []) >= 4 and len(unique_pages) <= 2:
        score -= 0.45
        issues.append(f"low_unique_pages={len(unique_pages)}")

    if dominant_ratio >= 0.6:
        score -= 0.35
        issues.append(f"dominant_single_page={round(dominant_ratio, 3)}")

    if page_count >= 12 and coverage_span < max(4, int(page_count * 0.35)):
        score -= 0.25
        issues.append(f"narrow_span={coverage_span}/{page_count}")

    return {"score": max(0.0, score), "issues": issues}


################### Fast TOC: three-level extraction ##############################


def extract_toc_from_pdf_bookmarks(doc_path):
    """Level 1: 从 PDF 原生书签提取 TOC。零 LLM 调用。

    P2-7: 复用 pdf_analyzer 的统一入口。
    """
    try:
        import pymupdf

        doc = pymupdf.open(str(doc_path))
        result = _pdf_analyzer_extract_bookmarks(doc)
        doc.close()
        return result
    except Exception:
        return None


def extract_toc_from_link_annotations(doc_path, max_scan_pages=20):
    """Level 2: 从 TOC 页面的链接注解提取。精确页码，零 LLM 调用。"""
    try:
        import pymupdf

        doc = pymupdf.open(str(doc_path))
    except Exception:
        return None

    try:
        result = _pdf_analyzer_extract_links(doc, max_scan_pages=max_scan_pages)
        doc.close()
        return result
    except Exception:
        doc.close()
        return None


def find_toc_pages_by_rules(page_list):
    """Level 3: 正则检测 TOC 文本页面。不受页数限制，扫描直到特征消失。

    P3-10: 增强启发式规则，提高目录页检测的准确性和鲁棒性。
    """
    toc_pages = []
    TOC_LINE_PATTERN = re.compile(
        r"(?:"
        r"第[一二三四五六七八九十百零〇两\d]+[章节部分篇]"
        r"|[\d]{1,2}(?:\.[\d]{1,2}){0,3}"
        r"|[一二三四五六七八九十]+、"
        r"|[（(][一二三四五六七八九十\d]+[)）]"
        r")\s*[^\n]{2,80}[.…:\s·]+\d{1,4}"
    )

    for i, (text, _) in enumerate(page_list):
        if not text or not text.strip():
            continue

        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # P3-10: 增强启发式评分
        score = 0.0

        # 1. 包含"目录"或"Contents"标题 → +0.3
        header = text_stripped[:300]
        if "目录" in header or "contents" in text_lower[:300]:
            score += 0.3

        # 2. 大量点线 + 页码模式（.... 12）→ +0.4
        dot_page_matches = re.findall(r'[.·…]{3,}\s*\d{1,4}', text_stripped)
        if len(dot_page_matches) >= 5:
            score += 0.4
        elif len(dot_page_matches) >= 3:
            score += 0.2

        # 3. 多级编号行密度 → +0.3
        matches = TOC_LINE_PATTERN.findall(text_stripped)
        if len(matches) >= 5:
            score += 0.3
        elif len(matches) >= 3:
            score += 0.15

        # 判定：score >= 0.5 视为目录页
        is_toc = score >= 0.5 or len(matches) >= 3

        if is_toc:
            toc_pages.append(i)
        elif toc_pages and (score >= 0.2 or len(matches) >= 1):
            toc_pages.append(i)  # TOC 尾页可能行数少
        elif toc_pages:
            break  # 连续性断了
    return toc_pages


def _parse_toc_text_to_items(toc_text):
    """从 TOC 纯文本中正则解析条目列表（Level 3 用）。

    支持格式：
    - 第一章 标题..........1
    - 1.1 标题..........3
    - 一、标题..........5
    - （一）标题..........7
    - (1) 标题..........9
    """
    pattern = re.compile(
        r"^("
        r"(?:第[一二三四五六七八九十百零〇两\d]+[章节部分篇][：:\s]*)?"
        r"(?:[\d]{1,2}(?:\.[\d]{1,2}){0,3}\s+)?"
        r"(?:[一二三四五六七八九十]+、)?"
        r"(?:[（(][一二三四五六七八九十\d]+[)）]\s*)?"
        r")"
        r"([^\n.…·]{2,80})"
        r"[.…·\s\u00b7\u2026]+(\d{1,4})\s*$",
        re.MULTILINE,
    )
    items = []
    for match in pattern.finditer(toc_text):
        prefix = match.group(1).strip()
        title_body = match.group(2).strip()
        page = int(match.group(3))

        title = f"{prefix} {title_body}".strip() if prefix else title_body
        if not title or page <= 0:
            continue

        # Try to extract structure number from prefix
        num_match = re.match(r"([\d]{1,2}(?:\.[\d]{1,2}){0,3})", prefix)
        structure = num_match.group(1) if num_match else None
        items.append({"title": title, "physical_index": page, "_num": structure})

    if len(items) < 3:
        return None

    # 用 _num 构建 structure，没有编号的用序号
    top_counter = 0
    for item in items:
        num = item.pop("_num", None)
        if num:
            item["structure"] = num
        else:
            top_counter += 1
            item["structure"] = str(top_counter)

    return items


def _levels_to_structure(items):
    """将 level-based items 转换为 structure-based ("1", "1.1", "1.2", "2", ...)"""
    counters = {}
    result = []
    for item in items:
        level = item["level"]
        # Reset deeper counters
        for k in list(counters.keys()):
            if k > level:
                del counters[k]
        counters[level] = counters.get(level, 0) + 1

        parts = [str(counters[lv]) for lv in sorted(counters.keys())]
        result.append(
            {
                "structure": ".".join(parts),
                "title": item["title"],
                "physical_index": item["physical_index"],
            }
        )
    return result


def _infer_structure_from_titles(items):
    """从标题格式推断 structure 编号（用于 Level 2 link annotations）。"""
    result = []
    for item in items:
        title = item["title"]
        # 尝试匹配 "1.2.3 标题" 或 "第X章"
        m = re.match(r"^(\d+(?:\.\d+)*)\s+", title)
        if m:
            result.append(
                {
                    "structure": m.group(1),
                    "title": title[m.end() :].strip() or title,
                    "physical_index": item["physical_index"],
                }
            )
        else:
            # 检查 "第X章" 模式
            m2 = re.match(
                r"^第([一二三四五六七八九十百零〇两\d]+)[章节部分篇][：:\s]*(.+)",
                title,
            )
            if m2:
                result.append(
                    {
                        "structure": str(
                            len([r for r in result if "." not in r["structure"]]) + 1
                        ),
                        "title": title,
                        "physical_index": item["physical_index"],
                    }
                )
            else:
                # 无法推断，用最后一个顶级编号的子编号
                if result:
                    parent = result[-1]["structure"].split(".")[0]
                    sub_count = len(
                        [r for r in result if r["structure"].startswith(parent + ".")]
                    )
                    result.append(
                        {
                            "structure": f"{parent}.{sub_count + 1}",
                            "title": title,
                            "physical_index": item["physical_index"],
                        }
                    )
                else:
                    result.append(
                        {
                            "structure": "1",
                            "title": title,
                            "physical_index": item["physical_index"],
                        }
                    )
    return result


def extract_toc_code_only(doc_path, page_list=None):
    """纯代码 TOC 提取（< 10ms）。不调用 LLM。

    Args:
        doc_path: PDF 文件完整路径（Level 1/2 需要）
        page_list: [(text, token_count), ...] 页面列表（Level 3 需要）

    Returns:
        (toc_items, source) 或 (None, None)
    """
    toc_items = None
    source = None

    # Level 1: PDF 书签
    if doc_path and os.path.isfile(str(doc_path)):
        toc_items = extract_toc_from_pdf_bookmarks(str(doc_path))
        if toc_items:
            source = "bookmarks"
            print(f"[FAST-TOC] Level 1 (bookmarks): {len(toc_items)} items")

    # Level 2: Link Annotations
    if not toc_items and doc_path and os.path.isfile(str(doc_path)):
        toc_items = extract_toc_from_link_annotations(str(doc_path))
        if toc_items:
            source = "links"
            print(f"[FAST-TOC] Level 2 (link annotations): {len(toc_items)} items")

    # Level 3: 正则解析 TOC 文本
    if not toc_items and page_list:
        toc_items = _extract_toc_by_regex(page_list)
        if toc_items:
            source = "regex"

    if not toc_items:
        return None, None

    return toc_items, source


def _extract_toc_by_regex(page_list):
    """Level 3: 从 page_list 文本中正则提取 TOC 条目。

    P2-7: 复用 pdf_analyzer 的统一入口。
    """
    # page_list 是 [(text, token_count), ...] 格式，提取纯文本
    page_texts = [page[0] if isinstance(page, (list, tuple)) and len(page) >= 1 else str(page)
                  for page in page_list]
    result = _pdf_analyzer_extract_regex(page_texts)
    if result:
        print(
            f"[FAST-TOC] Level 3 (regex): {len(result)} items"
        )
    return result


def _calculate_offset_for_regex_toc(toc_items, page_list):
    """对 Level 3 正则提取的 TOC 计算 offset 校正。

    正则提取的页码是逻辑页码（TOC 上印的数字），需要转换为物理页码。
    方法：取前 N 个标题，在 page_list 中搜索，计算偏移量。
    """
    if not page_list or len(page_list) < 2:
        return 0

    offsets = []
    checked = 0
    for item in toc_items[:15]:
        logical_page = item["physical_index"]
        title = item["title"].strip()
        if not title or len(title) < 3:
            continue

        search_key = title[:20].strip()
        found = False
        for phys_idx, (page_text, _) in enumerate(page_list):
            if search_key in page_text:
                actual_physical = phys_idx + 1
                offset = actual_physical - logical_page
                offsets.append(offset)
                found = True
                break

        if found:
            checked += 1
            if checked >= 5:
                break

    if not offsets:
        return 0

    offsets.sort()
    median = offsets[len(offsets) // 2]
    if median != 0:
        print(
            f"[FAST-TOC] Offset correction: median={median} "
            f"(from {len(offsets)} samples, range=[{offsets[0]}..{offsets[-1]}])"
        )
    return median


def _verify_toc_content_match(toc_items, page_list, sample_size=12):
    """抽样验证 TOC 条目标题是否出现在对应页面上。

    Returns:
        {"match_rate": 0.0-1.0, "offset_median": 0, "mismatches": [...], "total_checked": int}
    """
    if not page_list or len(page_list) < 2 or not toc_items:
        return {
            "match_rate": 0,
            "offset_median": 0,
            "mismatches": [],
            "total_checked": 0,
        }

    n = len(toc_items)
    if n <= sample_size:
        indices = list(range(n))
    else:
        # 前 4 + 中间 4 + 最后 4
        step = max(1, n // 4)
        indices = (
            list(range(0, min(4, n)))
            + list(range(n // 2 - 2, n // 2 + 2))
            + list(range(n - 4, n))
        )
        indices = sorted(set(i for i in indices if 0 <= i < n))

    matches = 0
    offsets = []
    mismatches = []

    for i in indices:
        item = toc_items[i]
        title = item["title"].strip()
        claimed_page = item.get("physical_index")

        if (
            not title
            or not claimed_page
            or claimed_page < 1
            or claimed_page > len(page_list)
        ):
            mismatches.append(
                {"index": i, "title": title[:40], "reason": "invalid_page"}
            )
            continue

        search_key = title[:30].strip()
        if len(search_key) < 3:
            mismatches.append(
                {"index": i, "title": title[:40], "reason": "title_too_short"}
            )
            continue

        found_page = None
        # 在 claimed_page 附近搜索（±5 页窗口）
        for delta in range(-5, 6):
            page_idx = claimed_page - 1 + delta
            if 0 <= page_idx < len(page_list):
                if search_key in page_list[page_idx][0]:
                    found_page = page_idx + 1
                    break

        if found_page == claimed_page:
            matches += 1
        elif found_page is not None:
            offsets.append(found_page - claimed_page)
            mismatches.append(
                {
                    "index": i,
                    "title": title[:40],
                    "claimed": claimed_page,
                    "actual": found_page,
                }
            )
        else:
            mismatches.append(
                {
                    "index": i,
                    "title": title[:40],
                    "claimed": claimed_page,
                    "reason": "not_found_nearby",
                }
            )

    total = len(indices)
    match_rate = matches / total if total > 0 else 0
    offset_median = 0
    if offsets:
        offsets.sort()
        offset_median = offsets[len(offsets) // 2]

    return {
        "match_rate": match_rate,
        "offset_median": offset_median,
        "mismatches": mismatches,
        "total_checked": total,
    }


async def validate_and_finalize_toc(
    toc_items, source, page_count, model=None, page_list=None
):
    """代码预检 + offset 校正 + LLM 轻校验。

    Returns:
        dict: {"toc_items": [...], "source": str, "valid": True}
        None: 校验不通过
    """
    from app.prompts.pageindex_prompts import TOC_LIGHT_VALIDATION_PROMPT

    if not toc_items or len(toc_items) < 2:
        return None

    # Level 3 正则提取的页码是逻辑页码，需要 offset 校正
    if source in ("regex", "regex_ocr") and page_list:
        offset = _calculate_offset_for_regex_toc(toc_items, page_list)
        if offset != 0:
            for item in toc_items:
                item["physical_index"] = max(1, item["physical_index"] + offset)

    # 代码预检：覆盖度
    last_page = max(item["physical_index"] for item in toc_items)
    if last_page < page_count * 0.5:
        print(
            f"[FAST-TOC] Coverage FAILED: last_page={last_page}, "
            f"page_count={page_count}, ratio={last_page / page_count:.1%}"
        )
        return None

    # 内容匹配检查（所有来源都执行）
    content_check = _verify_toc_content_match(toc_items, page_list)
    print(
        f"[FAST-TOC] Content match: {content_check['match_rate']:.0%} "
        f"({content_check['total_checked']} checked, "
        f"offset_median={content_check['offset_median']:+d})"
    )

    # 匹配率太低，直接拒绝
    if content_check["match_rate"] < 0.2:
        print(
            f"[FAST-TOC] Content match too low ({content_check['match_rate']:.0%}), rejecting"
        )
        return None

    # 如果有系统性偏移，应用校正
    if content_check["offset_median"] != 0:
        offset = content_check["offset_median"]
        for item in toc_items:
            item["physical_index"] = max(1, item["physical_index"] + offset)
        print(f"[FAST-TOC] Content-based offset correction: {offset:+d}")

    # LLM 轻校验
    toc_outline = "\n".join(
        f"  {item.get('structure', '?')} {item['title']}  -> p.{item['physical_index']}"
        for item in toc_items
    )

    # 构建不匹配详情
    mismatch_details = "无"
    if content_check["mismatches"]:
        parts = []
        for m in content_check["mismatches"][:5]:
            if "actual" in m:
                parts.append(
                    f"条目{m['index']} '{m['title']}' 声称p.{m['claimed']} 实际p.{m['actual']}"
                )
            else:
                parts.append(
                    f"条目{m['index']} '{m['title']}' 声称p.{m.get('claimed', '?')} 未找到({m.get('reason', '')})"
                )
        mismatch_details = "; ".join(parts)

    prompt = TOC_LIGHT_VALIDATION_PROMPT.format(
        page_count=page_count,
        toc_count=len(toc_items),
        toc_outline=toc_outline,
        match_rate=content_check["match_rate"],
        offset_median=content_check["offset_median"],
        mismatch_details=mismatch_details,
    )
    try:
        response = await ChatGPT_API_async(model=model, prompt=prompt)
        parsed = extract_json(response)
        valid = parsed.get("valid", "no") if isinstance(parsed, dict) else "no"
        reason = parsed.get("reason", "") if isinstance(parsed, dict) else ""
        print(f"[FAST-TOC] LLM validation: valid={valid}, reason={reason}")
        if valid != "yes":
            print(f"[FAST-TOC] LLM rejected TOC: {reason}")
            return None
    except Exception as e:
        # LLM 校验失败时，如果覆盖度 >= 0.7 则接受
        if last_page >= page_count * 0.7:
            print(
                f"[FAST-TOC] LLM error: {e}, accepting (coverage {last_page / page_count:.0%})"
            )
        else:
            print(f"[FAST-TOC] LLM error: {e}, rejecting")
            return None

    return {"toc_items": toc_items, "source": source, "valid": True}


####################################################################################


def check_toc(page_list, opt=None):
    toc_page_list = find_toc_pages(start_page_index=0, page_list=page_list, opt=opt)

    # Extend with regex-detected TOC pages (catches pages LLM missed)
    rule_pages = find_toc_pages_by_rules(page_list)
    if rule_pages:
        merged = sorted(set(toc_page_list) | set(rule_pages))
        if len(merged) > len(toc_page_list):
            print(
                f"check_toc: extended TOC pages {toc_page_list} -> {merged} via regex"
            )
            toc_page_list = merged

    if len(toc_page_list) == 0:
        print("no toc found")
        return {
            "toc_content": None,
            "toc_page_list": [],
            "page_index_given_in_toc": "no",
        }
    else:
        print("toc found")
        toc_json = toc_extractor(page_list, toc_page_list, opt.model)

        if toc_json["page_index_given_in_toc"] == "yes":
            print("index found")
            return {
                "toc_content": toc_json["toc_content"],
                "toc_page_list": toc_page_list,
                "page_index_given_in_toc": "yes",
            }
        else:
            current_start_index = toc_page_list[-1] + 1

            while (
                toc_json["page_index_given_in_toc"] == "no"
                and current_start_index < len(page_list)
                and current_start_index < opt.toc_check_page_num
            ):
                additional_toc_pages = find_toc_pages(
                    start_page_index=current_start_index, page_list=page_list, opt=opt
                )

                if len(additional_toc_pages) == 0:
                    break

                additional_toc_json = toc_extractor(
                    page_list, additional_toc_pages, opt.model
                )
                if additional_toc_json["page_index_given_in_toc"] == "yes":
                    print("index found")
                    return {
                        "toc_content": additional_toc_json["toc_content"],
                        "toc_page_list": additional_toc_pages,
                        "page_index_given_in_toc": "yes",
                    }

                else:
                    current_start_index = additional_toc_pages[-1] + 1
            print("index not found")
            return {
                "toc_content": toc_json["toc_content"],
                "toc_page_list": toc_page_list,
                "page_index_given_in_toc": "no",
            }


################### fix incorrect toc #########################################################
async def single_toc_item_index_fixer(
    section_title, content, model="gpt-4o-2024-11-20"
):
    toc_extractor_prompt = """
    You are given a section title and several pages of a document, your job is to find the physical index of the start page of the section in the partial document.

    The provided pages contains tags like <physical_index_X> and </physical_index_X> to indicate the start and end of page X.

    Reply in a JSON format:
    {
        "thinking": <explain which page, started and closed by <physical_index_X>, contains the start of this section>,
        "physical_index": "<physical_index_X>" (keep the format)
    }
    Directly return the final JSON structure. Do not output anything else."""

    prompt = (
        toc_extractor_prompt
        + "\nSection Title:\n"
        + str(section_title)
        + "\nDocument pages:\n"
        + content
    )
    response = ChatGPT_API(model=model, prompt=prompt)
    json_content = extract_json(response)
    return convert_physical_index_to_int(json_content["physical_index"])


async def fix_incorrect_toc(
    toc_with_page_number,
    page_list,
    incorrect_results,
    start_index=1,
    model=None,
    logger=None,
):
    print(f"start fix_incorrect_toc with {len(incorrect_results)} incorrect results")
    incorrect_indices = {result["list_index"] for result in incorrect_results}

    end_index = len(page_list) + start_index - 1

    incorrect_results_and_range_logs = []

    # Helper function to process and check a single incorrect item
    async def process_and_check_item(incorrect_item):
        list_index = incorrect_item["list_index"]

        # Check if list_index is valid
        if list_index < 0 or list_index >= len(toc_with_page_number):
            # Return an invalid result for out-of-bounds indices
            return {
                "list_index": list_index,
                "title": incorrect_item["title"],
                "physical_index": incorrect_item.get("physical_index"),
                "is_valid": False,
            }

        # Find the previous correct item
        prev_correct = None
        for i in range(list_index - 1, -1, -1):
            if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                physical_index = toc_with_page_number[i].get("physical_index")
                if physical_index is not None:
                    prev_correct = physical_index
                    break
        # If no previous correct item found, use start_index
        if prev_correct is None:
            prev_correct = start_index - 1

        # Find the next correct item
        next_correct = None
        for i in range(list_index + 1, len(toc_with_page_number)):
            if i not in incorrect_indices and i >= 0 and i < len(toc_with_page_number):
                physical_index = toc_with_page_number[i].get("physical_index")
                if physical_index is not None:
                    next_correct = physical_index
                    break
        # If no next correct item found, use end_index
        if next_correct is None:
            next_correct = end_index

        incorrect_results_and_range_logs.append(
            {
                "list_index": list_index,
                "title": incorrect_item["title"],
                "prev_correct": prev_correct,
                "next_correct": next_correct,
            }
        )

        page_contents = []
        for page_index in range(prev_correct, next_correct + 1):
            # Add bounds checking to prevent IndexError
            page_list_idx = page_index - start_index
            if page_list_idx >= 0 and page_list_idx < len(page_list):
                page_text = f"<physical_index_{page_index}>\n{page_list[page_list_idx][0]}\n</physical_index_{page_index}>\n\n"
                page_contents.append(page_text)
            else:
                continue
        content_range = "".join(page_contents)

        physical_index_int = await single_toc_item_index_fixer(
            incorrect_item["title"], content_range, model
        )

        # Check if the result is correct
        check_item = incorrect_item.copy()
        check_item["physical_index"] = physical_index_int
        check_result = await check_title_appearance(
            check_item, page_list, start_index, model
        )

        return {
            "list_index": list_index,
            "title": incorrect_item["title"],
            "physical_index": physical_index_int,
            "is_valid": check_result["answer"] == "yes",
        }

    # Process incorrect items concurrently
    tasks = [process_and_check_item(item) for item in incorrect_results]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for item, result in zip(incorrect_results, results):
        if isinstance(result, Exception):
            print(f"Processing item {item} generated an exception: {result}")
            continue
    results = [result for result in results if not isinstance(result, Exception)]

    # Update the toc_with_page_number with the fixed indices and check for any invalid results
    invalid_results = []
    for result in results:
        if result["is_valid"]:
            # Add bounds checking to prevent IndexError
            list_idx = result["list_index"]
            if 0 <= list_idx < len(toc_with_page_number):
                toc_with_page_number[list_idx]["physical_index"] = result[
                    "physical_index"
                ]
            else:
                # Index is out of bounds, treat as invalid
                invalid_results.append(
                    {
                        "list_index": result["list_index"],
                        "title": result["title"],
                        "physical_index": result["physical_index"],
                    }
                )
        else:
            invalid_results.append(
                {
                    "list_index": result["list_index"],
                    "title": result["title"],
                    "physical_index": result["physical_index"],
                }
            )

    logger.info(f"incorrect_results_and_range_logs: {incorrect_results_and_range_logs}")
    logger.info(f"invalid_results: {invalid_results}")

    return toc_with_page_number, invalid_results


async def fix_incorrect_toc_with_retries(
    toc_with_page_number,
    page_list,
    incorrect_results,
    start_index=1,
    max_attempts=3,
    model=None,
    logger=None,
):
    print("start fix_incorrect_toc")
    fix_attempt = 0
    current_toc = toc_with_page_number
    current_incorrect = incorrect_results

    while current_incorrect:
        print(f"Fixing {len(current_incorrect)} incorrect results")

        current_toc, current_incorrect = await fix_incorrect_toc(
            current_toc, page_list, current_incorrect, start_index, model, logger
        )

        fix_attempt += 1
        if fix_attempt >= max_attempts:
            logger.info("Maximum fix attempts reached")
            break

    return current_toc, current_incorrect


################### verify toc #########################################################
async def verify_toc(page_list, list_result, start_index=1, N=None, model=None):
    print("start verify_toc")
    # Find the last non-None physical_index
    last_physical_index = None
    for item in reversed(list_result):
        if item.get("physical_index") is not None:
            last_physical_index = item["physical_index"]
            break

    # Early return only if no valid physical indices at all
    if last_physical_index is None:
        return 0, []

    # Detect degenerate case: all items point to the same page (almost certainly wrong)
    valid_indices = [
        item["physical_index"]
        for item in list_result
        if item.get("physical_index") is not None
    ]
    if len(set(valid_indices)) == 1 and len(valid_indices) > 1 and len(page_list) > 3:
        print(
            f"[WARN] All {len(valid_indices)} items point to page {valid_indices[0]} — treating as 0% accuracy"
        )
        return 0, [
            {
                "list_index": i,
                "title": item.get("title", ""),
                "page_number": item.get("physical_index"),
                "answer": "no",
            }
            for i, item in enumerate(list_result)
            if item.get("physical_index") is not None
        ]

    # Determine which items to check
    total_items = len(list_result)
    if N is None:
        # Auto-sample for large documents (>25 items)
        if total_items > 25:
            N = max(20, int(total_items * 0.7))
            print(f"auto-sampling {N} of {total_items} items for verification")
            sample_indices = random.sample(range(0, total_items), N)
        else:
            print("check all items")
            sample_indices = range(0, total_items)
    else:
        N = min(N, total_items)
        print(f"check {N} items")
        sample_indices = random.sample(range(0, total_items), N)

    # Prepare items with their list indices
    indexed_sample_list = []
    for idx in sample_indices:
        item = list_result[idx]
        # Skip items with None physical_index (these were invalidated by validate_and_truncate_physical_indices)
        if item.get("physical_index") is not None:
            item_with_index = item.copy()
            item_with_index["list_index"] = idx  # Add the original index in list_result
            indexed_sample_list.append(item_with_index)

    # Run checks in batches for better performance
    batch_results = await check_title_appearance_batch(
        indexed_sample_list, page_list, start_index, model, batch_size=10
    )

    # Convert batch results to list format matching original interface
    results = []
    for item in indexed_sample_list:
        item_id = item.get("list_index", item.get("id"))
        # Defensive: try both int and str keys since LLM may return either type
        answer = batch_results.get(item_id) or batch_results.get(str(item_id)) or "no"
        results.append(
            {
                "list_index": item_id,
                "answer": answer,
                "title": item["title"],
                "page_number": item["physical_index"],
            }
        )

    # Process results
    correct_count = 0
    incorrect_results = []
    for result in results:
        if result["answer"] == "yes":
            correct_count += 1
        else:
            incorrect_results.append(result)

    # Calculate accuracy
    checked_count = len(results)
    accuracy = correct_count / checked_count if checked_count > 0 else 0
    print(f"accuracy: {accuracy * 100:.2f}%")
    return accuracy, incorrect_results


################### main process #########################################################
async def meta_processor(
    page_list,
    mode=None,
    toc_content=None,
    toc_page_list=None,
    start_index=1,
    opt=None,
    logger=None,
    doc_type="general",
    doc_type_confidence=0.0,
    hooks=None,
):
    print(mode)
    print(f"start_index: {start_index}")
    print(f"doc_type: {doc_type} (confidence: {doc_type_confidence})")

    is_balanced_mode = getattr(opt, "index_mode", "balanced") == "balanced"

    # Balanced mode must align with official PageIndex pipeline.
    if is_balanced_mode:
        if mode == "process_toc_with_page_numbers":
            toc_with_page_number = process_toc_with_page_numbers(
                toc_content,
                toc_page_list,
                page_list,
                toc_check_page_num=opt.toc_check_page_num,
                model=opt.model,
                logger=logger,
            )
        elif mode == "process_toc_no_page_numbers":
            toc_with_page_number = process_toc_no_page_numbers(
                toc_content, toc_page_list, page_list, model=opt.model, logger=logger
            )
        else:
            toc_with_page_number = process_no_toc(
                page_list, start_index=start_index, model=opt.model, logger=logger
            )
            
            # Hook: Structure Generation Enhancement
            if hooks is not None and mode == "process_no_toc":
                try:
                    # Build analysis_info with chapter_dividers detection
                    from .pdf_analyzer import analyze_pdf_structure
                    analysis_info = {"chapter_dividers": []}
                    try:
                        if doc and hasattr(doc, 'name'):
                            analysis = analyze_pdf_structure(doc.name)
                            analysis_info["chapter_dividers"] = analysis.get("chapter_dividers", [])
                    except:
                        pass
                    
                    enhanced_structure = await hooks.on_structure_generated(
                        toc_with_page_number, page_list, analysis_info
                    )
                    if enhanced_structure is not None:
                        toc_with_page_number = enhanced_structure
                        logger.info(f"[HOOK] Structure generation enhanced: {len(toc_with_page_number)} items")
                except Exception as e:
                    logger.warning(f"[HOOK] Structure generation enhancement failed: {e}")

        toc_with_page_number = [
            item
            for item in toc_with_page_number
            if item.get("physical_index") is not None
        ]

        toc_with_page_number = validate_and_truncate_physical_indices(
            toc_with_page_number,
            len(page_list),
            start_index=start_index,
            logger=logger,
        )

        accuracy, incorrect_results = await verify_toc(
            page_list,
            toc_with_page_number,
            start_index=start_index,
            model=opt.model,
        )
        
        # Hook: Verification Enhancement
        if hooks is not None and accuracy < 0.8:
            try:
                enhanced_verify = await hooks.on_verify(
                    accuracy, incorrect_results, page_list
                )
                if enhanced_verify is not None:
                    accuracy, incorrect_results = enhanced_verify
                    logger.info(f"[HOOK] Verification enhanced: accuracy={accuracy:.2%}")
            except Exception as e:
                logger.warning(f"[HOOK] Verification enhancement failed: {e}")

        logger.info(
            {
                "mode": "process_toc_with_page_numbers",
                "accuracy": accuracy,
                "incorrect_results": incorrect_results,
            }
        )

        if accuracy == 1.0 and len(incorrect_results) == 0:
            return toc_with_page_number
        if accuracy > 0.6 and len(incorrect_results) > 0:
            # Hook: Fix Incorrect Enhancement
            if hooks is not None:
                try:
                    enhanced_fix = await hooks.on_fix_incorrect(
                        incorrect_results, page_list
                    )
                    if enhanced_fix is not None:
                        incorrect_results = enhanced_fix
                        logger.info(f"[HOOK] Fix incorrect enhanced: {len(incorrect_results)} items")
                except Exception as e:
                    logger.warning(f"[HOOK] Fix incorrect enhancement failed: {e}")
            
            (
                toc_with_page_number,
                incorrect_results,
            ) = await fix_incorrect_toc_with_retries(
                toc_with_page_number,
                page_list,
                incorrect_results,
                start_index=start_index,
                max_attempts=3,
                model=opt.model,
                logger=logger,
            )
            return toc_with_page_number
        if mode == "process_toc_with_page_numbers":
            return await meta_processor(
                page_list,
                mode="process_toc_no_page_numbers",
                toc_content=toc_content,
                toc_page_list=toc_page_list,
                start_index=start_index,
                opt=opt,
                logger=logger,
                doc_type=doc_type,
                doc_type_confidence=doc_type_confidence,
                hooks=hooks,
            )
        if mode == "process_toc_no_page_numbers":
            return await meta_processor(
                page_list,
                mode="process_no_toc",
                start_index=start_index,
                opt=opt,
                logger=logger,
                doc_type=doc_type,
                doc_type_confidence=doc_type_confidence,
                hooks=hooks,
            )
        if mode == "process_no_toc":
            # Last resort: return best-effort result instead of crashing
            print(
                f"[WARN] process_no_toc accuracy={accuracy:.2f}, returning best-effort result"
            )
            return toc_with_page_number
        raise Exception("Processing failed")

    if mode == "process_toc_with_page_numbers":
        try:
            toc_with_page_number = process_toc_with_page_numbers(
                toc_content,
                toc_page_list,
                page_list,
                toc_check_page_num=opt.toc_check_page_num,
                model=opt.model,
                logger=logger,
            )
        except Exception as e:
            if getattr(opt, "index_mode", "balanced") == "fast":
                raise ValueError(f"FAST_TOC_INCOMPLETE: {e}")
            logger.error(
                {
                    "fallback": {
                        "from": "process_toc_with_page_numbers",
                        "to": "process_no_toc",
                        "reason": str(e),
                    }
                }
            )
            return await meta_processor(
                page_list,
                mode="process_no_toc",
                start_index=start_index,
                opt=opt,
                logger=logger,
                doc_type=doc_type,
                doc_type_confidence=doc_type_confidence,
            )
    elif mode == "process_toc_no_page_numbers":
        try:
            toc_with_page_number = process_toc_no_page_numbers(
                toc_content, toc_page_list, page_list, model=opt.model, logger=logger
            )
        except Exception as e:
            logger.error(
                {
                    "fallback": {
                        "from": "process_toc_no_page_numbers",
                        "to": "process_no_toc",
                        "reason": str(e),
                    }
                }
            )
            return await meta_processor(
                page_list,
                mode="process_no_toc",
                start_index=start_index,
                opt=opt,
                logger=logger,
                doc_type=doc_type,
                doc_type_confidence=doc_type_confidence,
            )
    else:
        # process_no_toc mode: rule-first extraction, then LLM fallback
        rule_toc = extract_sections_by_rules(
            page_list, start_index=start_index, logger=logger
        )
        if is_rule_toc_reliable(rule_toc, logger=logger):
            logger.info(
                {
                    "route": "rules_primary",
                    "rule_section_count": len(rule_toc),
                }
            )
            toc_with_page_number = rule_toc
        else:
            logger.info(
                {
                    "route": "llm_fallback",
                    "rule_section_count": len(rule_toc),
                    "doc_type": doc_type,
                    "doc_type_confidence": doc_type_confidence,
                }
            )
            toc_with_page_number = process_no_toc(
                page_list, start_index=start_index, model=opt.model, logger=logger
            )

    # Filter out items with None physical_index, but keep at least one item to avoid empty list
    filtered_toc = [
        item for item in toc_with_page_number if item.get("physical_index") is not None
    ]

    # If all items were filtered out, keep the original list and log warning
    if len(filtered_toc) == 0 and len(toc_with_page_number) > 0:
        logger.warning(
            f"All {len(toc_with_page_number)} TOC items have None physical_index, keeping original list"
        )
        # Try to assign sequential physical_index to items without it
        for i, item in enumerate(toc_with_page_number):
            if item.get("physical_index") is None:
                item["physical_index"] = f"<physical_index_{start_index + i}>"
        filtered_toc = toc_with_page_number

    toc_with_page_number = filtered_toc

    toc_with_page_number = validate_and_truncate_physical_indices(
        toc_with_page_number, len(page_list), start_index=start_index, logger=logger
    )

    # Use new quality validator for comprehensive quality check
    validator = QualityValidator()
    quality_score, quality_issues = validator.validate(
        toc_with_page_number, doc_type, page_list
    )

    if mode == "process_no_toc":
        no_toc_quality = _assess_no_toc_range_quality(
            toc_with_page_number, page_count=len(page_list)
        )
        quality_score = min(
            float(quality_score), float(no_toc_quality.get("score", 0.0))
        )
        for issue in no_toc_quality.get("issues") or []:
            quality_issues.append(f"no_toc_range:{issue}")

    logger.info(
        {
            "mode": mode,
            "doc_type": doc_type,
            "quality_score": quality_score,
            "quality_issues": quality_issues,
        }
    )

    # Quality-based decision logic
    is_fast_mode = getattr(opt, "index_mode", "balanced") == "fast"

    if quality_score >= 0.8:
        logger.info(f"Quality score {quality_score:.2f} >= 0.8, accepting result")
        return toc_with_page_number
    elif quality_score >= 0.6:
        logger.warning(
            f"Quality score {quality_score:.2f} in range [0.6, 0.8), attempting fixes"
        )
        # Fast mode: do NOT silently fallback to slow paths — raise to let caller decide
        if is_fast_mode:
            raise ValueError(
                f"FAST_TOC_INCOMPLETE: quality_score={quality_score:.2f} < 0.8, issues={quality_issues}"
            )
        # Try to fix issues automatically or use specialized prompt if available
        if mode != "process_no_toc" or doc_type == "general":
            # Fall back to lower complexity mode
            if mode == "process_toc_with_page_numbers":
                return await meta_processor(
                    page_list,
                    mode="process_toc_no_page_numbers",
                    toc_content=toc_content,
                    toc_page_list=toc_page_list,
                    start_index=start_index,
                    opt=opt,
                    logger=logger,
                    doc_type=doc_type,
                    doc_type_confidence=doc_type_confidence,
                )
            elif mode == "process_toc_no_page_numbers":
                return await meta_processor(
                    page_list,
                    mode="process_no_toc",
                    start_index=start_index,
                    opt=opt,
                    logger=logger,
                    doc_type=doc_type,
                    doc_type_confidence=doc_type_confidence,
                )
        # For specialized prompts with medium quality, accept with warning
        logger.warning(f"Accepting medium quality result for {doc_type}")
        return toc_with_page_number
    else:
        # Low quality, try fallbacks
        logger.error(f"Quality score {quality_score:.2f} < 0.6, trying fallbacks")
        # Fast mode: do NOT silently fallback to slow paths
        if is_fast_mode:
            raise ValueError(
                f"FAST_TOC_INCOMPLETE: quality_score={quality_score:.2f} < 0.6, issues={quality_issues}"
            )
        if mode == "process_toc_with_page_numbers":
            return await meta_processor(
                page_list,
                mode="process_toc_no_page_numbers",
                toc_content=toc_content,
                toc_page_list=toc_page_list,
                start_index=start_index,
                opt=opt,
                logger=logger,
                doc_type=doc_type,
                doc_type_confidence=doc_type_confidence,
            )
        elif mode == "process_toc_no_page_numbers":
            return await meta_processor(
                page_list,
                mode="process_no_toc",
                start_index=start_index,
                opt=opt,
                logger=logger,
                doc_type=doc_type,
                doc_type_confidence=doc_type_confidence,
            )
        else:
            # Last resort: accept low quality result to avoid complete failure
            logger.warning(
                f"Low quality ({quality_score:.2f}) in final fallback mode, returning result anyway. "
                f"Issues: {quality_issues}"
            )
            return toc_with_page_number


async def process_large_node_recursively(node, page_list, opt=None, logger=None):
    node_page_list = page_list[node["start_index"] - 1 : node["end_index"]]
    token_num = sum([page[1] for page in node_page_list])

    if (
        node["end_index"] - node["start_index"] > opt.max_page_num_each_node
        and token_num >= opt.max_token_num_each_node
    ):
        print(
            "large node:",
            node["title"],
            "start_index:",
            node["start_index"],
            "end_index:",
            node["end_index"],
            "token_num:",
            token_num,
        )

        node_toc_tree = await meta_processor(
            node_page_list,
            mode="process_no_toc",
            start_index=node["start_index"],
            opt=opt,
            logger=logger,
        )
        node_toc_tree = await check_title_appearance_in_start_concurrent(
            node_toc_tree, page_list, model=opt.model, logger=logger
        )

        # Filter out items with None physical_index before post_processing
        valid_node_toc_items = [
            item for item in node_toc_tree if item.get("physical_index") is not None
        ]

        if (
            valid_node_toc_items
            and node["title"].strip() == valid_node_toc_items[0]["title"].strip()
        ):
            node["nodes"] = post_processing(valid_node_toc_items[1:], node["end_index"])
            node["end_index"] = (
                valid_node_toc_items[1]["start_index"]
                if len(valid_node_toc_items) > 1
                else node["end_index"]
            )
        else:
            node["nodes"] = post_processing(valid_node_toc_items, node["end_index"])
            node["end_index"] = (
                valid_node_toc_items[0]["start_index"]
                if valid_node_toc_items
                else node["end_index"]
            )

    if "nodes" in node and node["nodes"]:
        tasks = [
            process_large_node_recursively(child_node, page_list, opt, logger=logger)
            for child_node in node["nodes"]
        ]
        await asyncio.gather(*tasks)

    return node


async def tree_parser(
    page_list,
    opt,
    doc=None,
    logger=None,
    doc_type="general",
    doc_type_confidence=0.0,
    fast_toc_result=None,
    hooks=None,
):
    is_fast_mode = getattr(opt, "index_mode", "balanced") == "fast"
    is_smart_mode = getattr(opt, "index_mode", "balanced") == "smart"

    # ─── Fast TOC result from pre-extraction (OCR 前 + OCR 后两轮代码提取) ───
    if fast_toc_result:
        toc_items = fast_toc_result["toc_items"]
        logger.info(f"Fast TOC via {fast_toc_result['source']}: {len(toc_items)} items")

        # 直接进入 post_processing（跳过 meta_processor/toc_transformer/offset）
        toc_items = convert_physical_index_to_int(toc_items)
        toc_items = validate_and_truncate_physical_indices(
            toc_items, len(page_list), start_index=1, logger=logger
        )
        toc_items = add_preface_if_needed(toc_items)
        toc_tree = post_processing(toc_items, len(page_list))

        # 添加 node_text
        if getattr(opt, "if_add_node_text", "no") == "yes":
            add_node_text(toc_tree, page_list)

        return toc_tree

    # Fast/Smart 没有 fast_toc_result — 说明代码提取失败了
    if is_fast_mode:
        raise ValueError("FAST_TOC_INCOMPLETE: all_extraction_levels_failed")
    if is_smart_mode:
        logger.info(
            "Smart mode: fast TOC extraction failed, falling through to balanced"
        )

        if fast_result:
            toc_items = fast_result["toc_items"]
            logger.info(f"Fast TOC via {fast_result['source']}: {len(toc_items)} items")

            # 直接进入 post_processing（跳过 meta_processor/toc_transformer/offset）
            toc_items = convert_physical_index_to_int(toc_items)
            toc_items = validate_and_truncate_physical_indices(
                toc_items, len(page_list), start_index=1, logger=logger
            )
            toc_items = add_preface_if_needed(toc_items)
            toc_tree = post_processing(toc_items, len(page_list))

            # 添加 node_text
            if getattr(opt, "if_add_node_text", "no") == "yes":
                add_node_text(toc_tree, page_list)

            return toc_tree

        # 三级提取全失败
        if is_fast_mode:
            raise ValueError("FAST_TOC_INCOMPLETE: all_extraction_levels_failed")
        # smart 模式：fall through 到 balanced 逻辑
        logger.info(
            "Smart mode: fast TOC extraction failed, falling through to balanced"
        )

    # ─── Balanced（或 smart fallthrough）: 原有 LLM 流程 ───
    check_toc_result = check_toc(page_list, opt)
    
    # Hook: TOC Detection Enhancement
    if hooks is not None:
        try:
            enhanced_result = await hooks.on_check_toc(page_list, check_toc_result)
            if enhanced_result is not None:
                logger.info(f"[HOOK] TOC detection enhanced: {enhanced_result}")
                check_toc_result = enhanced_result
        except Exception as e:
            logger.warning(f"[HOOK] TOC detection enhancement failed: {e}")
    
    logger.info(check_toc_result)

    has_toc_with_page_numbers = (
        check_toc_result.get("toc_content")
        and check_toc_result["toc_content"].strip()
        and check_toc_result["page_index_given_in_toc"] == "yes"
    )

    if has_toc_with_page_numbers:
        toc_with_page_number = await meta_processor(
            page_list,
            mode="process_toc_with_page_numbers",
            start_index=1,
            toc_content=check_toc_result["toc_content"],
            toc_page_list=check_toc_result["toc_page_list"],
            opt=opt,
            logger=logger,
            doc_type=doc_type,
            doc_type_confidence=doc_type_confidence,
            hooks=hooks,
        )
    else:
        toc_with_page_number = await meta_processor(
            page_list,
            mode="process_no_toc",
            start_index=1,
            opt=opt,
            logger=logger,
            doc_type=doc_type,
            doc_type_confidence=doc_type_confidence,
            hooks=hooks,
        )

    toc_with_page_number = add_preface_if_needed(toc_with_page_number)

    toc_with_page_number = await check_title_appearance_in_start_concurrent(
        toc_with_page_number, page_list, model=opt.model, logger=logger
    )

    # Filter out items with None physical_index before post_processings
    valid_toc_items = [
        item for item in toc_with_page_number if item.get("physical_index") is not None
    ]

    toc_tree = post_processing(valid_toc_items, len(page_list))
    tasks = [
        process_large_node_recursively(node, page_list, opt, logger=logger)
        for node in toc_tree
    ]
    await asyncio.gather(*tasks)

    return toc_tree


def page_index_main(doc, opt=None, fast_toc_result=None, hooks=None):
    logger = JsonLogger(doc)

    is_valid_pdf = (
        isinstance(doc, str) and os.path.isfile(doc) and doc.lower().endswith(".pdf")
    ) or isinstance(doc, BytesIO)
    if not is_valid_pdf:
        raise ValueError(
            "Unsupported input type. Expected a PDF file path or BytesIO object."
        )

    print("Parsing PDF...")
    pdf_parser = getattr(opt, "pdf_parser", "PyPDF2") if opt is not None else "PyPDF2"
    page_list = get_page_tokens(
        doc,
        model=getattr(opt, "model", None),
        pdf_parser=pdf_parser,
    )

    logger.info({"total_page_number": len(page_list)})
    logger.info({"total_token": sum([page[1] for page in page_list])})

    async def page_index_builder():
        # Parse tree with rule-first, LLM-fallback routing
        doc_type = "general"
        confidence = 0.0
        structure = await tree_parser(
            page_list,
            opt,
            doc=doc,
            logger=logger,
            doc_type=doc_type,
            doc_type_confidence=confidence,
            fast_toc_result=fast_toc_result,
            hooks=hooks,
        )

        if opt.if_add_node_id == "yes":
            write_node_id(structure)
        if opt.if_add_node_text == "yes":
            add_node_text(structure, page_list)
        if opt.if_add_node_summary == "yes":
            if opt.if_add_node_text == "no":
                add_node_text(structure, page_list)
            await generate_summaries_for_structure(structure, model=opt.model)
            if opt.if_add_node_text == "no":
                remove_structure_text(structure)
            if opt.if_add_doc_description == "yes":
                # Create a clean structure without unnecessary fields for description generation
                clean_structure = create_clean_structure_for_description(structure)
                doc_description = generate_doc_description(
                    clean_structure, model=opt.model
                )
                return {
                    "doc_name": get_pdf_name(doc),
                    "doc_description": doc_description,
                    "structure": structure,
                    "doc_type": doc_type,
                    "classification_confidence": confidence,
                    "page_count": len(page_list),
                }
        return {
            "doc_name": get_pdf_name(doc),
            "structure": structure,
            "doc_type": doc_type,
            "classification_confidence": confidence,
            "page_count": len(page_list),
        }

    # 检查是否有正在运行的事件循环
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # 如果当前线程已经有事件循环，在新线程中执行，避免嵌套 asyncio.run
        result_holder = {"result": None, "error": None}

        def _runner():
            try:
                result_holder["result"] = asyncio.run(page_index_builder())
            except Exception as e:
                result_holder["error"] = e

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join()

        if result_holder["error"] is not None:
            raise result_holder["error"]
        return result_holder["result"]

    # 如果没有正在运行的事件循环，直接执行
    return asyncio.run(page_index_builder())


def page_index_main_with_page_list(
    doc_name: str, page_list, opt=None, fast_toc_result=None, hooks=None
):
    """使用外部提供的页文本列表构建 PageIndex（用于 OCR 回填场景）。"""
    logger = JsonLogger(doc_name)

    if not isinstance(page_list, list) or len(page_list) == 0:
        raise ValueError("page_list must be a non-empty list")

    logger.info({"total_page_number": len(page_list)})
    logger.info({"total_token": sum([page[1] for page in page_list])})

    async def page_index_builder():
        doc_type = "general"
        confidence = 0.0
        structure = await tree_parser(
            page_list,
            opt,
            doc=doc_name,
            logger=logger,
            doc_type=doc_type,
            doc_type_confidence=confidence,
            fast_toc_result=fast_toc_result,
            hooks=hooks,
        )

        if opt.if_add_node_id == "yes":
            write_node_id(structure)
        if opt.if_add_node_text == "yes":
            add_node_text(structure, page_list)
        if opt.if_add_node_summary == "yes":
            if opt.if_add_node_text == "no":
                add_node_text(structure, page_list)
            await generate_summaries_for_structure(structure, model=opt.model)
            if opt.if_add_node_text == "no":
                remove_structure_text(structure)
            if opt.if_add_doc_description == "yes":
                clean_structure = create_clean_structure_for_description(structure)
                doc_description = generate_doc_description(
                    clean_structure, model=opt.model
                )
                return {
                    "doc_name": doc_name,
                    "doc_description": doc_description,
                    "structure": structure,
                    "doc_type": doc_type,
                    "classification_confidence": confidence,
                    "page_count": len(page_list),
                }
        return {
            "doc_name": doc_name,
            "structure": structure,
            "doc_type": doc_type,
            "classification_confidence": confidence,
            "page_count": len(page_list),
        }

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        result_holder = {"result": None, "error": None}

        def _runner():
            try:
                result_holder["result"] = asyncio.run(page_index_builder())
            except Exception as e:
                result_holder["error"] = e

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join()

        if result_holder["error"] is not None:
            raise result_holder["error"]
        return result_holder["result"]

    return asyncio.run(page_index_builder())


def page_index(
    doc,
    model=None,
    toc_check_page_num=None,
    max_page_num_each_node=None,
    max_token_num_each_node=None,
    if_add_node_id=None,
    if_add_node_summary=None,
    if_add_doc_description=None,
    if_add_node_text=None,
):

    user_opt = {
        arg: value
        for arg, value in locals().items()
        if arg != "doc" and value is not None
    }
    opt = ConfigLoader().load(user_opt)
    return page_index_main(doc, opt)


def validate_and_truncate_physical_indices(
    toc_with_page_number, page_list_length, start_index=1, logger=None
):
    """
    Validates and truncates physical indices that exceed the actual document length.
    This prevents errors when TOC references pages that don't exist in the document (e.g. the file is broken or incomplete).
    """
    if not toc_with_page_number:
        return toc_with_page_number

    max_allowed_page = page_list_length + start_index - 1
    truncated_items = []

    for i, item in enumerate(toc_with_page_number):
        if item.get("physical_index") is not None:
            original_index = item["physical_index"]
            if original_index > max_allowed_page:
                item["physical_index"] = None
                truncated_items.append(
                    {
                        "title": item.get("title", "Unknown"),
                        "original_index": original_index,
                    }
                )
                if logger:
                    logger.info(
                        f"Removed physical_index for '{item.get('title', 'Unknown')}' (was {original_index}, too far beyond document)"
                    )

    if truncated_items and logger:
        logger.info(f"Total removed items: {len(truncated_items)}")

    print(
        f"Document validation: {page_list_length} pages, max allowed index: {max_allowed_page}"
    )
    if truncated_items:
        print(
            f"Truncated {len(truncated_items)} TOC items that exceeded document length"
        )

    return toc_with_page_number
