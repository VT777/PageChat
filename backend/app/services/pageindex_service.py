import sys
import json
import asyncio
import re
import time
import base64
from pathlib import Path
from typing import Optional, Dict, Any, List

# 添加 pageindex 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import PyPDF2

from pageindex.page_index import page_index_main, page_index_main_with_page_list
from pageindex.utils import config, get_nodes, get_page_tokens, structure_to_list
from pageindex.page_index_md import md_to_tree
from app.core.config import (
    INDEXES_DIR,
    build_effective_pageindex_config,
    PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED,
    PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES,
    PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS,
    PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD,
    PAGEINDEX_UNPARSEABLE_PAGES_BALANCED_THRESHOLD,
    PAGEINDEX_UNPARSEABLE_RATIO_BALANCED_THRESHOLD,
    VISION_TOC_STRICT_TARGET_RATIO,
    VISION_TOC_STRICT_MAX_GAP_PAGES,
    VISION_TOC_STRICT_MAX_RECOVERY_ROUNDS,
    VISUAL_MAX_CONSECUTIVE_FAIL_PAGES,
    VISUAL_VLM_MAX_CONCURRENCY,
    VISUAL_VLM_PAGE_MAX_ATTEMPTS,
    VISUAL_PAGE_TIMEOUT_SECONDS,
    OCR_MAX_CONCURRENCY,
    OCR_MIN_IMAGE_AREA_RATIO,
    OCR_MIN_IMAGE_SIDE_PX,
)
from app.prompts.pageindex_prompts import (
    QUERY_VERIFICATION_PROMPT,
    FAST_DOC_LIGHT_SUMMARY_PROMPT,
)
from app.services.multi_format_adapter import generate_multi_format_index
from app.services.ocr_service import OCRService
from app.services.runtime_settings_service import runtime_settings_service


async def check_query_appearance(
    query: str, node_text: str, model: str = "qwen3.6-flash"
) -> dict:
    """
    验证用户查询是否出现在节点文本中

    Returns:
        {
            "query_appears": "yes" | "no" | "partial",
            "confidence": 0.0-1.0,
            "reasoning": str
        }
    """
    from app.core.llm import async_chat_completion

    if not node_text or len(node_text.strip()) < 10:
        return {
            "query_appears": "no",
            "confidence": 0.0,
            "reasoning": "节点文本为空或过短",
        }

    truncated_text = node_text[:800]

    # 使用优化后的查询验证提示词
    prompt = QUERY_VERIFICATION_PROMPT.format(query=query, content=truncated_text)

    try:
        response = await async_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            model=model,
        )
        content = response.choices[0].message.content

        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        else:
            return {
                "query_appears": "no",
                "confidence": 0.0,
                "reasoning": "failed to parse response",
            }
    except Exception as e:
        print(f"check_query_appearance error: {e}")
        return {"query_appears": "no", "confidence": 0.0, "reasoning": str(e)}


async def verify_candidate_nodes(
    candidates: List[dict],
    query: str,
    nodes: List[dict],
    model: str = "qwen3.6-flash",
) -> List[dict]:
    """
    验证 LLM 选择的候选节点是否真的包含查询内容

    Args:
        candidates: LLM 返回的候选列表
        query: 用户查询
        nodes: 所有节点的完整信息 (from structure_to_list)
        model: 验证用的模型

    Returns:
        带验证分数的候选列表
    """
    node_dict = {n.get("node_id"): n for n in nodes}
    verified_results = []

    async def verify_one(candidate):
        node_id = candidate.get("node_id")
        if node_id in node_dict:
            node = node_dict[node_id]
            text = node.get("text", "") or ""
            return await check_query_appearance(query, text, model)
        else:
            return {
                "query_appears": "no",
                "confidence": 0.0,
                "reasoning": "node not found",
            }

    verification_coroutines = [verify_one(c) for c in candidates]
    verification_results = await asyncio.gather(
        *verification_coroutines, return_exceptions=True
    )

    for candidate, verification in zip(candidates, verification_results):
        if isinstance(verification, Exception):
            candidate["verification_passed"] = False
            candidate["verification_confidence"] = 0.0
            candidate["verification_reasoning"] = str(verification)
        else:
            candidate["verification_passed"] = verification.get("query_appears") in (
                "yes",
                "partial",
            )
            candidate["verification_confidence"] = verification.get("confidence", 0.0)
            candidate["verification_reasoning"] = verification.get("reasoning", "")

            if not candidate["verification_passed"]:
                candidate["relevance"] = candidate.get("relevance", 0.5) * 0.3

        verified_results.append(candidate)

    return verified_results


class PageIndexService:
    """PageIndex 服务 - 生成和查询树状索引"""

    def __init__(self):
        self.opt = self._build_opt()

    @staticmethod
    def _persist_failure_diagnostics(doc_id: str, payload: Dict[str, Any]) -> None:
        try:
            INDEXES_DIR.mkdir(parents=True, exist_ok=True)
            index_path = INDEXES_DIR / f"{doc_id}.json"
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[VISION_DIAG] failed to persist diagnostics doc={doc_id}: {e}")

    def _build_opt(self, mode_override: Optional[str] = None):
        condition = mode_override in {"smart", "fast", "balanced"}
        mode = (
            str(mode_override).strip().lower()
            if condition
            else runtime_settings_service.get_settings().get(
                "pageindex_mode", "balanced"
            )
        )
        return config(**build_effective_pageindex_config(mode=mode))

    @staticmethod
    def _normalize_page_text_for_ocr(text: str) -> str:
        t = re.sub(r"\s+", " ", str(text or "")).strip()
        return t

    async def _ocr_pages_for_toc_validation(
        self, file_path: Path, page_indices: List[int]
    ) -> Dict[int, str]:
        """Phase 0.5: 对指定页面做轻量 OCR，用于 TOC 验证。

        返回: {物理页码(1-indexed): OCR文本}
        """
        if not page_indices:
            return {}

        import base64
        import io
        from pageindex.vlm_utils import render_pages_to_images

        images = render_pages_to_images(str(file_path), page_indices, dpi=150)
        if not images:
            return {}

        ocr_service = OCRService()
        sem = asyncio.Semaphore(max(1, int(OCR_MAX_CONCURRENCY)))

        async def ocr_single(img_info):
            page_num = img_info["page_index"] + 1  # 0-indexed → 1-indexed
            async with sem:
                result = await ocr_service.ocr_image_base64(
                    img_info["image_base64"], page_num=page_num
                )
            return page_num, result.text if result.ok else ""

        results = await asyncio.gather(*[ocr_single(img) for img in images])
        return {
            page_num: text for page_num, text in results if text
        }

    async def _run_full_pdf_ocr_by_images(
        self, file_path: Path, page_count: int
    ) -> Dict[str, Any]:
        if page_count <= 0:
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": [],
            }

        try:
            import pymupdf
        except Exception:
            return {
                "ocr_pages": [],
                "ocr_coverage": 0.0,
                "ocr_missing_pages": list(range(1, page_count + 1)),
            }

        ocr_service = OCRService()
        sem = asyncio.Semaphore(max(1, int(OCR_MAX_CONCURRENCY)))

        def _block_sort_key(bbox: List[float]) -> tuple[float, float]:
            try:
                x0, y0, _, _ = [float(v) for v in bbox]
                return (y0, x0)
            except Exception:
                return (0.0, 0.0)

        def collect_page_blocks(page) -> List[Dict[str, Any]]:
            d = page.get_text("dict") or {}
            blocks = d.get("blocks") or []
            out: List[Dict[str, Any]] = []
            for blk in blocks:
                if not isinstance(blk, dict):
                    continue
                btype = int(blk.get("type") or 0)
                bbox = blk.get("bbox") or [0, 0, 0, 0]
                if len(bbox) != 4:
                    bbox = [0, 0, 0, 0]
                if btype == 0:
                    texts: List[str] = []
                    for ln in blk.get("lines") or []:
                        for sp in ln.get("spans") or []:
                            tx = str(sp.get("text") or "")
                            if tx.strip():
                                texts.append(tx)
                    txt = re.sub(r"\s+", " ", "".join(texts)).strip()
                    if txt:
                        out.append({"kind": "text", "bbox": bbox, "text": txt})
                elif btype == 1:
                    img_bytes = blk.get("image")
                    if isinstance(img_bytes, (bytes, bytearray)) and img_bytes:
                        out.append(
                            {"kind": "image", "bbox": bbox, "image": bytes(img_bytes)}
                        )
            out.sort(key=lambda item: _block_sort_key(item.get("bbox") or [0, 0, 0, 0]))
            return out

        def should_ocr_image_block(page_rect, bbox) -> bool:
            try:
                x0, y0, x1, y1 = [float(v) for v in bbox]
            except Exception:
                return False
            w = max(0.0, x1 - x0)
            h = max(0.0, y1 - y0)
            if w < float(OCR_MIN_IMAGE_SIDE_PX) or h < float(OCR_MIN_IMAGE_SIDE_PX):
                return False
            page_area = max(1.0, float(page_rect.width) * float(page_rect.height))
            ratio = (w * h) / page_area
            return ratio >= float(OCR_MIN_IMAGE_AREA_RATIO)

        page_inputs: List[Dict[str, Any]] = []
        doc = pymupdf.open(str(file_path))
        try:
            for page_num in range(1, min(page_count, len(doc)) + 1):
                page = doc[page_num - 1]
                blocks = collect_page_blocks(page)
                page_rect = page.rect
                ordered_blocks: List[Dict[str, Any]] = []
                for blk in blocks:
                    if blk.get("kind") == "text":
                        ordered_blocks.append(
                            {
                                "kind": "text",
                                "bbox": blk.get("bbox") or [0, 0, 0, 0],
                                "text": str(blk.get("text") or ""),
                            }
                        )
                        continue
                    if blk.get("kind") != "image":
                        continue
                    bbox = blk.get("bbox") or [0, 0, 0, 0]
                    should_ocr = should_ocr_image_block(page_rect, bbox)
                    image_b64 = ""
                    if should_ocr:
                        img_bytes = blk.get("image") or b""
                        if img_bytes:
                            image_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    ordered_blocks.append(
                        {
                            "kind": "image",
                            "bbox": bbox,
                            "ocr_target": should_ocr and bool(image_b64),
                            "image_b64": image_b64,
                        }
                    )
                page_inputs.append(
                    {
                        "page_num": page_num,
                        "ordered_blocks": ordered_blocks,
                    }
                )
        finally:
            doc.close()

        async def parse_page(page_input: Dict[str, Any]) -> Dict[str, Any]:
            page_num = int(page_input.get("page_num") or 0)
            ordered_blocks = list(page_input.get("ordered_blocks") or [])
            merged_text_parts: List[str] = []
            image_targets = 0
            image_ocr_hits = 0

            for blk in ordered_blocks:
                kind = blk.get("kind")
                if kind == "text":
                    tx = str(blk.get("text") or "")
                    if tx.strip():
                        merged_text_parts.append(tx)
                    continue
                if kind != "image":
                    continue
                if not bool(blk.get("ocr_target")):
                    continue

                image_targets += 1
                image_b64 = str(blk.get("image_b64") or "")
                if not image_b64:
                    continue
                async with sem:
                    r = await ocr_service.ocr_image_base64(image_b64, page_num)
                if r.ok and r.text:
                    merged_text_parts.append(r.text)
                    image_ocr_hits += 1

            merged_text = self._normalize_page_text_for_ocr(
                "\n".join(merged_text_parts)
            )
            return {
                "page_num": page_num,
                "text": merged_text,
                "ok": bool(image_ocr_hits > 0 or merged_text),
                "ocr_image_targets": image_targets,
                "ocr_image_hits": image_ocr_hits,
                "error": "" if merged_text else "no_image_block_ocr_text",
            }

        rows = await asyncio.gather(*(parse_page(x) for x in page_inputs))
        rows = sorted(rows, key=lambda x: int(x.get("page_num") or 0))

        success = sum(1 for x in rows if x.get("text"))
        missing = [int(x["page_num"]) for x in rows if not x.get("text")]
        return {
            "ocr_pages": rows,
            "ocr_coverage": (success / page_count) if page_count > 0 else 0.0,
            "ocr_missing_pages": missing,
        }

    @staticmethod
    def _build_page_list_with_ocr_overlay(
        base_page_list: List[Any], ocr_pages: List[Dict[str, Any]], model: str
    ) -> List[Any]:
        try:
            import litellm
        except Exception:
            litellm = None

        ocr_map = {
            int(item.get("page_num") or 0): str(item.get("text") or "")
            for item in (ocr_pages or [])
            if int(item.get("page_num") or 0) > 0
        }
        merged: List[Any] = []
        for idx, page in enumerate(base_page_list, start=1):
            original_text = ""
            if isinstance(page, (list, tuple)) and len(page) >= 1:
                original_text = str(page[0] or "")

            text = str(ocr_map.get(idx) or original_text)
            if litellm is not None:
                try:
                    token_length = litellm.token_counter(model=model, text=text)
                except Exception:
                    token_length = len(text) // 4
            else:
                token_length = len(text) // 4
            merged.append((text, token_length))
        return merged

    @staticmethod
    def _build_toc_outline_text(
        structure_data: Any, max_titles: int = PAGEINDEX_FAST_LIGHT_SUMMARY_MAX_TITLES
    ) -> str:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return ""

        lines: List[str] = []
        for node in nodes[:max_titles]:
            title = PageIndexService._normalize_title(node.get("title") or "")
            if not title or PageIndexService._is_noise_title(title):
                continue
            level = str(node.get("node_id") or "").count(".") + 1
            indent = "  " * max(0, level - 1)
            lines.append(f"{indent}- {title}")
        return "\n".join(lines)

    async def _generate_fast_light_doc_summary(
        self, structure_data: Any, file_path: Path
    ) -> str:
        if not PAGEINDEX_FAST_LIGHT_SUMMARY_ENABLED:
            print(
                f"[FAST_SUMMARY] skipped disabled doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')}"
            )
            return ""

        toc_outline = self._build_toc_outline_text(structure_data)
        if not toc_outline:
            print(f"[FAST_SUMMARY] skipped empty_toc doc={file_path.name}")
            return ""

        prompt = FAST_DOC_LIGHT_SUMMARY_PROMPT.format(
            doc_name=file_path.name,
            file_type=file_path.suffix.lower(),
            toc_outline=toc_outline,
        )
        start_time = time.perf_counter()
        deadline = start_time + PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS
        attempt = 0

        from app.core.llm import async_chat_completion

        while True:
            attempt += 1
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                print(
                    f"[FAST_SUMMARY] status=timeout doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} attempts={attempt - 1} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms}"
                )
                return ""

            try:
                response = await asyncio.wait_for(
                    async_chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        model=self.opt.model,
                        temperature=0,
                        max_tokens=120,
                    ),
                    timeout=remaining,
                )
                summary = (response.choices[0].message.content or "").strip().strip('"')
                summary = summary[:180]
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                if summary:
                    print(
                        f"[FAST_SUMMARY] status=ok doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} attempts={attempt} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms}"
                    )
                    return summary

                print(
                    f"[FAST_SUMMARY] status=empty_output doc={file_path.name} attempt={attempt} remaining_s={round(max(0.0, deadline - time.perf_counter()), 2)}"
                )
            except Exception as e:
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                print(
                    f"[FAST_SUMMARY] status=retry_error doc={file_path.name} mode={getattr(self.opt, 'index_mode', 'unknown')} model={self.opt.model} attempt={attempt} timeout_s={PAGEINDEX_FAST_LIGHT_SUMMARY_TIMEOUT_SECONDS} toc_len={len(toc_outline)} prompt_len={len(prompt)} elapsed_ms={elapsed_ms} error_type={type(e).__name__} error={e}"
                )

            sleep_time = min(0.8, max(0.1, deadline - time.perf_counter()))
            if sleep_time <= 0:
                continue
            await asyncio.sleep(sleep_time)

    @staticmethod
    def _normalize_title(title: str) -> str:
        t = re.sub(r"\s+", " ", (title or "").strip())
        if not t:
            return ""

        watermark_fragments = [
            "请务必阅读正文之后的免责声明及其项下所有内容",
            "获取更多维度报告数据，请访问亿欧网",
            "获取更多维度报告数据 ，请访问亿欧网",
            "www.iyiou.com",
        ]
        for fragment in watermark_fragments:
            t = t.replace(fragment, " ")

        t = re.sub(r"^[◆•●\-\*u\s]+", "", t)
        t = re.sub(r"(?i)^chapter\s*\d+[a-zA-Z]*[\s:：.\-]*", "", t)
        t = re.sub(r"^第\s*\d+\s*[章节部分卷篇]\s*", "", t)
        t = re.sub(r"^\d+(?:\.\d+)*[\s:：.\-]*", "", t)
        t = re.sub(r"\s+", " ", t).strip(" -:：|·")
        return t

    @staticmethod
    def _is_common_readable_char(ch: str) -> bool:
        if "\u4e00" <= ch <= "\u9fff":
            return True
        if ch.isascii() and (
            ch.isalnum() or ch in " \n\t.,:;!?()[]{}<>-_/\\'\"%&+*#@$"
        ):
            return True
        if ch in "·—：，。、《》；（）【】“”‘’、":
            return True
        return False

    @staticmethod
    def _iter_nodes_mutable(structure_data: Any):
        if isinstance(structure_data, list):
            for node in structure_data:
                if isinstance(node, dict):
                    yield node
                    children = node.get("nodes")
                    if isinstance(children, list):
                        yield from PageIndexService._iter_nodes_mutable(children)
        elif isinstance(structure_data, dict):
            yield structure_data
            children = structure_data.get("nodes")
            if isinstance(children, list):
                yield from PageIndexService._iter_nodes_mutable(children)

    @staticmethod
    def _is_noise_title(title: str) -> bool:
        t = PageIndexService._normalize_title(title)
        if not t:
            return True
        if len(t) <= 1:
            return True
        if re.fullmatch(r"\d+", t):
            return True
        if re.fullmatch(r"\d{4}\.\d+", t):
            return True
        if re.fullmatch(r"\d{4}[./-]\d{1,2}([./-]\d{1,2})?", t):
            return True
        if re.fullmatch(r"\d{4}年\d{1,2}月(\d{1,2}日)?", t):
            return True
        if re.fullmatch(r"(?i)chapter\s*\d+", t):
            return True
        if re.fullmatch(r"(?i)(preface|contents|introduction|appendix)", t):
            return True
        if re.fullmatch(r"[A-Z]{2,5}", t):
            return True
        if re.fullmatch(r"[A-Za-z]{1,5}\d*", t):
            return True
        if re.fullmatch(r"[A-Za-z]{1,6}", t):
            return True

        noise_keywords = [
            "免责声明",
            "风险提示",
            "分析师",
            "邮箱",
            "电话",
            "版权",
            "www.",
            "@",
        ]
        if any(k in t for k in noise_keywords):
            return True

        readable = sum(1 for ch in t if PageIndexService._is_common_readable_char(ch))
        if readable / max(1, len(t)) < 0.72:
            return True

        cjk_count = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        ascii_alpha = sum(1 for ch in t if ch.isascii() and ch.isalpha())
        digit_count = sum(1 for ch in t if ch.isdigit())
        if cjk_count == 0 and ascii_alpha <= 5 and len(t) <= 8:
            return True
        if digit_count / max(1, len(t)) > 0.45 and cjk_count < 2:
            return True
        return False

    @staticmethod
    def _extract_heading_from_text(text: str) -> str:
        if not text:
            return ""
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        for line in lines[:40]:
            normalized = PageIndexService._normalize_title(line)
            if len(normalized) < 3 or len(normalized) > 60:
                continue
            if PageIndexService._is_noise_title(normalized):
                continue
            return normalized
        return ""

    @staticmethod
    def _compute_structure_quality(structure_data: Any) -> Dict[str, Any]:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return {
                "score": 0.0,
                "node_count": 0,
                "bad_ratio": 1.0,
                "max_depth": 0,
            }

        titles = [
            PageIndexService._normalize_title(n.get("title") or "") for n in nodes
        ]
        bad = sum(1 for t in titles if PageIndexService._is_noise_title(t))
        bad_ratio = bad / len(titles)
        short_ratio = sum(1 for t in titles if len(t) <= 4) / len(titles)
        unique_ratio = len({t for t in titles if t}) / len(titles)
        depths = [str(n.get("node_id") or "").count(".") + 1 for n in nodes]
        max_depth = max(depths) if depths else 0

        score = 1.0 - bad_ratio
        if len(nodes) <= 1:
            score -= 0.35
        if max_depth <= 1 and len(nodes) >= 6:
            score -= 0.15
        if short_ratio > 0.4 and len(nodes) >= 4:
            score -= 0.12
        if unique_ratio < 0.6 and len(nodes) >= 5:
            score -= 0.1
        score = max(0.0, min(1.0, score))

        return {
            "score": score,
            "node_count": len(nodes),
            "bad_ratio": bad_ratio,
            "max_depth": max_depth,
            "short_ratio": short_ratio,
            "unique_ratio": unique_ratio,
        }

    @staticmethod
    def _repair_structure_titles(structure_data: Any) -> Any:
        for node in PageIndexService._iter_nodes_mutable(structure_data):
            title = PageIndexService._normalize_title(node.get("title") or "")
            if title != (node.get("title") or ""):
                node["title"] = title
            if not title or PageIndexService._is_noise_title(title):
                candidate = PageIndexService._extract_heading_from_text(
                    node.get("text", "")
                )
                if candidate:
                    node["title"] = candidate
                continue

            if re.fullmatch(r"(?i)chapter\s*\d+", title) or re.fullmatch(
                r"\d{4}\.\d+", title
            ):
                candidate = PageIndexService._extract_heading_from_text(
                    node.get("text", "")
                )
                if candidate and candidate != title:
                    node["title"] = candidate

        def filter_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            out = []
            seen_titles = set()
            for n in nodes:
                children = n.get("nodes")
                if isinstance(children, list):
                    n["nodes"] = filter_nodes(children)
                title = PageIndexService._normalize_title(n.get("title") or "")
                n["title"] = title
                title_key = title.lower()
                if (
                    title
                    and not PageIndexService._is_noise_title(title)
                    and title_key not in seen_titles
                ):
                    seen_titles.add(title_key)
                    out.append(n)
            return out

        if isinstance(structure_data, list):
            return filter_nodes(structure_data)
        if isinstance(structure_data, dict):
            title = PageIndexService._normalize_title(structure_data.get("title") or "")
            if not title or PageIndexService._is_noise_title(title):
                candidate = PageIndexService._extract_heading_from_text(
                    structure_data.get("text", "")
                )
                if candidate:
                    structure_data["title"] = candidate
            return structure_data
        return structure_data

    @staticmethod
    def _build_segment_fallback_toc(page_count: Optional[int]) -> List[Dict[str, Any]]:
        total = int(page_count or 0)
        if total <= 0:
            return []
        segment = 8 if total >= 40 else 5
        nodes = []
        idx = 1
        for start in range(1, total + 1, segment):
            end = min(total, start + segment - 1)
            nodes.append(
                {
                    "node_id": f"{idx:04d}",
                    "title": f"第{idx}部分（第{start}-{end}页）",
                    "start_index": start,
                    "end_index": end,
                    "nodes": [],
                }
            )
            idx += 1
        return nodes

    @staticmethod
    def _extract_llm_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts).strip()
        return ""

    async def _generate_fast_visual_page_summaries(
        self,
        file_path: Path,
        page_numbers: List[int],
        max_attempts_override: Optional[int] = None,
        per_page_timeout_override: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not page_numbers:
            return []

        from app.core.llm import pdf_page_to_base64
        from app.services.model_gateway import ModelGateway

        gateway = ModelGateway()
        max_concurrency = max(1, int(VISUAL_VLM_MAX_CONCURRENCY))
        max_attempts = max(
            1,
            int(
                max_attempts_override
                if max_attempts_override is not None
                else VISUAL_VLM_PAGE_MAX_ATTEMPTS
            ),
        )
        per_page_timeout = max(
            5,
            int(
                per_page_timeout_override
                if per_page_timeout_override is not None
                else VISUAL_PAGE_TIMEOUT_SECONDS
            ),
        )
        semaphore = asyncio.Semaphore(max_concurrency)

        async def summarize_one(page_num: int) -> Optional[Dict[str, Any]]:
            async with semaphore:
                image_b64 = pdf_page_to_base64(str(file_path), page_num)
                if not image_b64:
                    return None

                prompt = (
                    "请阅读这页PDF图片内容，提炼1句用于检索的中文摘要，"
                    "重点保留主题、关键术语、图表结论。不要编造，输出不超过60字。"
                )
                image_url = f"data:image/jpeg;base64,{image_b64}"
                for _ in range(max_attempts):
                    try:
                        response = await asyncio.wait_for(
                            gateway.vision_enrich_pdf_page(prompt, image_url),
                            timeout=per_page_timeout,
                        )
                        content = self._extract_llm_text_content(
                            response.choices[0].message.content
                        )
                        content = re.sub(r"\s+", " ", content).strip().strip('"')
                        if content:
                            return {"page_num": page_num, "summary": content[:120]}
                    except Exception:
                        continue
                return None

        unique_pages = sorted({int(p) for p in page_numbers if int(p) > 0})
        # 分批并行，避免一次创建过多 pending task 导致事件循环不稳定
        batch_size = max(2, max_concurrency * 2)
        results: List[Optional[Dict[str, Any]]] = []
        for i in range(0, len(unique_pages), batch_size):
            batch = unique_pages[i : i + batch_size]
            batch_results = await asyncio.gather(*(summarize_one(p) for p in batch))
            results.extend(batch_results)

        summaries = [r for r in results if r]
        summaries.sort(key=lambda x: x["page_num"])
        return summaries

    @staticmethod
    def _inject_visual_summaries_into_structure(
        structure_data: Any, visual_summaries: List[Dict[str, Any]]
    ) -> None:
        if not visual_summaries:
            return

        nodes = structure_to_list(structure_data)
        if not nodes:
            return

        def _safe_int(v: Any) -> Optional[int]:
            try:
                return int(v)
            except Exception:
                return None

        for item in visual_summaries:
            page_num = _safe_int(item.get("page_num"))
            summary = (item.get("summary") or "").strip()
            if not page_num or not summary:
                continue

            candidates = []
            for n in nodes:
                start = _safe_int(n.get("start_index"))
                end = _safe_int(n.get("end_index"))
                if start is None or end is None:
                    continue
                if start <= page_num <= end:
                    candidates.append((end - start, n))

            if not candidates:
                continue

            _, target = min(candidates, key=lambda x: x[0])
            marker = f"[视觉摘要 p.{page_num}] {summary}"

            text = (target.get("text") or "").strip()
            if marker not in text:
                target["text"] = (text + "\n" + marker).strip()

            node_summary = (target.get("summary") or "").strip()
            if not node_summary:
                target["summary"] = summary
            elif summary not in node_summary:
                target["summary"] = (node_summary + "；" + summary)[:260]

    @staticmethod
    def _looks_like_segment_fallback_toc(structure_data: Any) -> bool:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return False
        sample = nodes[: min(6, len(nodes))]
        fallback_hits = 0
        for node in sample:
            title = (node.get("title") or "").strip()
            if re.match(r"^第\d+部分（第\d+-\d+页）$", title) or re.match(
                r"^第\d+部分[:：]", title
            ):
                fallback_hits += 1
        return fallback_hits >= max(2, len(sample) - 1)

    @staticmethod
    def _summary_to_toc_title(summary: str, max_len: int = 30) -> str:
        text = re.sub(r"\s+", " ", (summary or "").strip())
        if not text:
            return ""

        text = re.sub(
            r"^(该文档|本页|本案例|该案例|该报告|案例展示|文档显示|内容展示)[：:，,\s]*",
            "",
            text,
        )
        first_clause = re.split(r"[。；;]", text, maxsplit=1)[0]
        first_clause = first_clause.strip("，,:：。;； ")
        if len(first_clause) < 8:
            first_clause = text[: max_len + 8]
        if len(first_clause) > max_len:
            first_clause = first_clause[:max_len].rstrip()
        return first_clause

    @staticmethod
    def _extract_title_keywords(title: str) -> set[str]:
        t = (title or "").lower().strip()
        if not t:
            return set()
        tokens = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{1,3}", t)
        return {x for x in tokens if len(x.strip()) >= 1}

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        ka = PageIndexService._extract_title_keywords(a)
        kb = PageIndexService._extract_title_keywords(b)
        if not ka or not kb:
            return 0.0
        inter = len(ka & kb)
        union = len(ka | kb)
        if union == 0:
            return 0.0
        return inter / union

    @staticmethod
    def _is_semantic_toc_title(title: str) -> bool:
        t = (title or "").strip()
        if not t:
            return False
        m = re.match(r"^第\d+部分[:：](.+)$", t)
        if m:
            payload = m.group(1).strip()
            return len(payload) >= 8 and not PageIndexService._is_noise_title(payload)
        return len(t) >= 6 and not PageIndexService._is_noise_title(t)

    @staticmethod
    def _max_toc_span_for_page_count(page_count: int) -> int:
        if page_count <= 60:
            return 4
        if page_count <= 120:
            return 6
        return 8

    @staticmethod
    def _densify_toc_by_max_span(
        toc_nodes: List[Dict[str, Any]], page_count: int
    ) -> List[Dict[str, Any]]:
        if not toc_nodes:
            return toc_nodes

        max_span = PageIndexService._max_toc_span_for_page_count(page_count)
        densified: List[Dict[str, Any]] = []
        for node in toc_nodes:
            start = int(node.get("start_index") or 0)
            end = int(node.get("end_index") or 0)
            if start <= 0 or end <= 0 or end < start:
                continue
            span = end - start + 1
            title = (node.get("title") or "").strip()
            summary = (node.get("summary") or title or "").strip()[:220]

            if span <= max_span:
                normalized = dict(node)
                normalized["summary"] = summary
                normalized["nodes"] = []
                if title and f"第{start}-{end}页" not in title:
                    normalized["title"] = f"{title}（第{start}-{end}页）"
                densified.append(normalized)
                continue

            seg_idx = 1
            for seg_start in range(start, end + 1, max_span):
                seg_end = min(end, seg_start + max_span - 1)
                seg_title = title
                if title:
                    seg_title = f"{title}（第{seg_start}-{seg_end}页）"
                else:
                    seg_title = f"章节片段（第{seg_start}-{seg_end}页）"
                densified.append(
                    {
                        "title": seg_title,
                        "summary": summary,
                        "start_index": seg_start,
                        "end_index": seg_end,
                        "nodes": [],
                    }
                )
                seg_idx += 1

        for idx, node in enumerate(densified, start=1):
            node["node_id"] = f"{idx:04d}"
        return densified

    @staticmethod
    def _ensure_structure_node_summaries(structure_data: Any) -> None:
        for node in structure_to_list(structure_data):
            summary = (node.get("summary") or "").strip()
            if summary:
                continue
            title = (node.get("title") or "").strip()
            text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
            fallback = title or text[:120]
            if fallback:
                node["summary"] = fallback[:220]

    @staticmethod
    def _merge_visual_summaries_for_section(summaries: List[str]) -> str:
        cleaned: List[str] = []
        seen = set()
        for item in summaries:
            s = re.sub(r"\s+", " ", str(item or "")).strip().strip("。；; ")
            if not s:
                continue
            key = s[:80]
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(s)

        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0][:220]
        merged = "；".join(cleaned[:3])
        return merged[:260]

    @staticmethod
    def _enrich_toc_nodes_with_visual_evidence(
        toc_nodes: List[Dict[str, Any]], visual_summaries: List[Dict[str, Any]]
    ) -> None:
        if not toc_nodes:
            return

        page_summary: Dict[int, str] = {}
        for item in visual_summaries or []:
            try:
                p = int(item.get("page_num") or 0)
            except Exception:
                continue
            s = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            if p > 0 and s and p not in page_summary:
                page_summary[p] = s

        for node in toc_nodes:
            try:
                start = int(node.get("start_index") or 0)
                end = int(node.get("end_index") or 0)
            except Exception:
                start, end = 0, 0

            evidence_pages: List[int] = []
            evidence_summaries: List[str] = []
            if start > 0 and end >= start:
                for p in range(start, end + 1):
                    if p in page_summary:
                        evidence_pages.append(p)
                        evidence_summaries.append(page_summary[p])

            section_summary = PageIndexService._merge_visual_summaries_for_section(
                evidence_summaries
            )
            if section_summary:
                node["summary"] = section_summary
                node["summary_source"] = "vision_segment"
            else:
                fallback = (node.get("summary") or "").strip() or (
                    node.get("title") or ""
                ).strip()
                if fallback:
                    node["summary"] = fallback[:260]
                    node["summary_source"] = "fallback"

            node["evidence_pages"] = evidence_pages

    @staticmethod
    def _collect_node_evidence(
        node: Dict[str, Any],
        page_summary: Dict[int, str],
        page_count: int,
    ) -> tuple[List[int], List[str]]:
        try:
            start = int(node.get("start_index") or 0)
            end = int(node.get("end_index") or 0)
        except Exception:
            start, end = 0, 0

        if start <= 0 or end < start:
            return [], []

        pages = [p for p in range(start, end + 1) if p in page_summary]

        # 节点摘要要求是区间级语义：当节点内证据不足时，补充邻页证据
        min_evidence = 3 if (end - start + 1) <= 2 else 2
        if len(pages) < min_evidence:
            for delta in (1, 2, 3):
                left = start - delta
                right = end + delta
                if left >= 1 and left in page_summary and left not in pages:
                    pages.append(left)
                if right <= page_count and right in page_summary and right not in pages:
                    pages.append(right)
                if len(pages) >= min_evidence:
                    break

        pages = sorted(set(pages))
        summaries = [page_summary[p] for p in pages if p in page_summary]
        return pages, summaries

    @staticmethod
    def _fallback_node_summary(
        node: Dict[str, Any], evidence_summaries: List[str]
    ) -> str:
        merged = PageIndexService._merge_visual_summaries_for_section(
            evidence_summaries
        )
        if merged:
            return merged[:260]
        title = (node.get("title") or "").strip()
        text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()
        fallback = title or text[:180]
        return fallback[:260]

    async def _rewrite_balanced_node_summaries(
        self,
        structure_data: Any,
        visual_summaries: List[Dict[str, Any]],
        page_count: int,
    ) -> None:
        nodes = structure_to_list(structure_data)
        if not nodes:
            return

        from app.core.llm import async_chat_completion

        page_summary: Dict[int, str] = {}
        for item in visual_summaries or []:
            try:
                p = int(item.get("page_num") or 0)
            except Exception:
                continue
            s = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            if p > 0 and s and p not in page_summary:
                page_summary[p] = s

        sem = asyncio.Semaphore(8)

        async def rewrite_one(node: Dict[str, Any]) -> None:
            evidence_pages, evidence_summaries = self._collect_node_evidence(
                node=node,
                page_summary=page_summary,
                page_count=page_count,
            )
            node["evidence_pages"] = evidence_pages

            title = (node.get("title") or "").strip()
            start = node.get("start_index")
            end = node.get("end_index")
            node_text = re.sub(r"\s+", " ", str(node.get("text") or "")).strip()[:500]

            evidence_block = "\n".join(
                f"- p.{p}: {page_summary.get(p, '')}" for p in evidence_pages[:6]
            )
            if not evidence_block:
                evidence_block = "- 无视觉证据"

            prompt = (
                "你是文档摘要助手。请基于一个章节(多页区间)生成节点级摘要。\n"
                f"章节标题: {title or '未命名章节'}\n"
                f"章节页码: {start}-{end}\n"
                f"章节文本证据(可能为空): {node_text or '无'}\n"
                "章节视觉证据:\n"
                f"{evidence_block}\n\n"
                "要求:\n"
                "1) 输出1-2句中文摘要，40-160字；\n"
                "2) 必须概括整个章节区间，不要写'本页'；\n"
                "3) 仅基于给定证据，不得编造。\n"
                "只输出摘要正文。"
            )

            summary = ""
            try:
                async with sem:
                    resp = await asyncio.wait_for(
                        async_chat_completion(
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.1,
                            model=self.opt.model,
                        ),
                        timeout=8,
                    )
                summary = self._extract_llm_text_content(
                    resp.choices[0].message.content
                )
                summary = re.sub(r"\s+", " ", summary).strip().strip('"')
                if summary == title or "本页" in summary:
                    summary = ""
            except Exception:
                summary = ""

            if not summary:
                summary = self._fallback_node_summary(node, evidence_summaries)

            node["summary"] = summary[:260]
            node["summary_source"] = "llm_node"

        await asyncio.gather(*(rewrite_one(node) for node in nodes))

    @staticmethod
    def _max_visual_gap(page_count: int, visual_summaries: List[Dict[str, Any]]) -> int:
        if page_count <= 0:
            return 0
        pages = sorted(
            {
                int(item.get("page_num"))
                for item in visual_summaries
                if item.get("page_num")
            }
        )
        if not pages:
            return page_count

        max_gap = max(0, pages[0] - 1, page_count - pages[-1])
        for i in range(len(pages) - 1):
            gap = pages[i + 1] - pages[i] - 1
            if gap > max_gap:
                max_gap = gap
        return max_gap

    @staticmethod
    def _build_visual_recovery_targets(
        page_count: int,
        existing_pages: set[int],
        gate_reason: Optional[str],
        target_ratio: float,
        max_gap_target: int = 2,
    ) -> List[int]:
        if page_count <= 0:
            return []

        needed = max(1, int(round(page_count * target_ratio)))
        targets: set[int] = set()

        # 1) 全局均匀补点，先满足基础覆盖率目标
        sample_count = min(page_count, max(needed, 12))
        if sample_count <= 1:
            targets.add(page_count)
        else:
            for i in range(sample_count):
                p = int(round(1 + i * (page_count - 1) / (sample_count - 1)))
                if p not in existing_pages:
                    targets.add(p)

        # 2) 大间隙优先补点（中点 + 四分位），降低目录“盲区”
        all_pages = sorted(existing_pages)
        boundaries = [0] + all_pages + [page_count + 1]
        for i in range(len(boundaries) - 1):
            left = boundaries[i]
            right = boundaries[i + 1]
            gap = right - left - 1
            if gap <= max(1, int(max_gap_target)):
                continue
            candidates = [
                left + (gap // 2),
                left + (gap // 4),
                left + ((gap * 3) // 4),
            ]
            for p in candidates:
                if 1 <= p <= page_count and p not in existing_pages:
                    targets.add(p)

        # 3) 尾段加密，提升问答命中后半部分章节概率
        tail_start = max(1, int(page_count * 0.7))
        for p in range(tail_start, page_count + 1, 2):
            if p not in existing_pages:
                targets.add(p)

        # 4) 结构稀疏时再加强前段抽样，避免前部被压缩成单大段
        if gate_reason in {
            "node_sparse",
            "visual_summary_sparse",
            "coverage_gap_high",
            "coverage_gap_strict",
            "visual_summary_insufficient",
            "node_evidence_sparse",
        }:
            head_end = min(page_count, max(8, int(page_count * 0.25)))
            for p in range(1, head_end + 1, 2):
                if p not in existing_pages:
                    targets.add(p)

        return sorted(targets)

    @staticmethod
    def _build_vision_first_toc_from_visual_summaries(
        page_count: Optional[int], visual_summaries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        total = int(page_count or 0)
        if total <= 0:
            return []

        source = sorted(
            [s for s in visual_summaries if s.get("page_num") and s.get("summary")],
            key=lambda x: int(x["page_num"]),
        )
        if not source:
            return []

        # 第一轮：严格去重，保留语义变化明显的页
        anchors: List[Dict[str, Any]] = []
        prev_title = ""
        for item in source:
            page_num = int(item["page_num"])
            raw_summary = str(item.get("summary") or "").strip()
            title = PageIndexService._summary_to_toc_title(raw_summary)
            if not title:
                continue
            if not anchors:
                anchors.append(
                    {"page_num": page_num, "title": title, "summary": raw_summary}
                )
                prev_title = title
                continue

            prev_page = int(anchors[-1]["page_num"])
            sim = PageIndexService._title_similarity(prev_title, title)
            has_signal_word = any(
                kw in title
                for kw in [
                    "案例",
                    "场景",
                    "系统",
                    "平台",
                    "应用",
                    "项目",
                    "治理",
                    "智能",
                    "模型",
                ]
            )
            if page_num - prev_page >= 2 or sim < 0.62 or has_signal_word:
                anchors.append(
                    {"page_num": page_num, "title": title, "summary": raw_summary}
                )
                prev_title = title

        # 第二轮：如果锚点过少，放宽相似度阈值补锚点
        min_nodes = min(max(6, total // 8), 18)
        if len(anchors) < min_nodes:
            anchors = []
            prev_title = ""
            for item in source:
                page_num = int(item["page_num"])
                raw_summary = str(item.get("summary") or "").strip()
                title = PageIndexService._summary_to_toc_title(raw_summary)
                if not title:
                    continue
                if not anchors:
                    anchors.append(
                        {
                            "page_num": page_num,
                            "title": title,
                            "summary": raw_summary,
                        }
                    )
                    prev_title = title
                    continue
                sim = PageIndexService._title_similarity(prev_title, title)
                if sim < 0.78:
                    anchors.append(
                        {
                            "page_num": page_num,
                            "title": title,
                            "summary": raw_summary,
                        }
                    )
                    prev_title = title

        # 控制节点上限，避免目录过密（保留文末锚点，防止尾部内容丢失）
        max_nodes = 80 if total <= 80 else 60
        if len(anchors) > max_nodes:
            if max_nodes <= 1:
                anchors = [anchors[-1]]
            else:
                n = len(anchors)
                sampled_indices = sorted(
                    {
                        int(round(i * (n - 1) / (max_nodes - 1)))
                        for i in range(max_nodes)
                    }
                )
                anchors = [anchors[i] for i in sampled_indices]

        if not anchors:
            return []

        nodes: List[Dict[str, Any]] = []
        for idx, anchor in enumerate(anchors):
            start = int(anchor["page_num"])
            end = (
                int(anchors[idx + 1]["page_num"]) - 1
                if idx < len(anchors) - 1
                else total
            )
            end = max(start, min(total, end))
            title = anchor["title"]
            if not PageIndexService._is_semantic_toc_title(title):
                title = f"第{idx + 1}部分：{title}" if title else f"第{idx + 1}部分"
            nodes.append(
                {
                    "node_id": f"{idx + 1:04d}",
                    "title": title,
                    "summary": str(anchor.get("summary") or title)[:220],
                    "start_index": start,
                    "end_index": end,
                    "nodes": [],
                }
            )
        return PageIndexService._densify_toc_by_max_span(nodes, total)

    @staticmethod
    def _vision_first_toc_quality_ok(
        toc_nodes: List[Dict[str, Any]], page_count: int
    ) -> bool:
        metrics = PageIndexService._compute_vision_toc_gate_metrics(
            toc_nodes=toc_nodes,
            page_count=page_count,
            # 兼容旧测试语义：仅评估结构质量，不因视觉覆盖率被否决
            visual_summaries=(
                [{"page_num": i + 1, "summary": "ok"} for i in range(page_count)]
                if page_count > 0
                else []
            ),
        )
        ok, _ = PageIndexService._evaluate_vision_toc_gate(metrics)
        return ok

    @staticmethod
    def _compute_vision_toc_gate_metrics(
        toc_nodes: List[Dict[str, Any]],
        page_count: int,
        visual_summaries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        q = PageIndexService._compute_structure_quality(toc_nodes)
        node_count = int(q.get("node_count") or 0)
        semantic_ratio = (
            sum(
                1
                for n in toc_nodes
                if PageIndexService._is_semantic_toc_title(n.get("title") or "")
            )
            / max(1, node_count)
            if node_count > 0
            else 0.0
        )
        last_end = int(toc_nodes[-1].get("end_index") or 0) if toc_nodes else 0
        coverage_ratio = (last_end / page_count) if page_count > 0 else 0.0

        tail_start = max(1, int(page_count * 0.7)) if page_count > 0 else 1
        tail_anchor_count = sum(
            1 for n in toc_nodes if int(n.get("start_index") or 0) >= tail_start
        )
        tail_anchor_ratio = (
            tail_anchor_count / max(1, node_count) if node_count > 0 else 0.0
        )

        visual_summary_ratio = (
            len(visual_summaries) / page_count if page_count > 0 else 0.0
        )

        max_gap_pages = PageIndexService._max_visual_gap(page_count, visual_summaries)
        adjacent_sims: List[float] = []
        for i in range(max(0, len(toc_nodes) - 1)):
            t1 = str(toc_nodes[i].get("title") or "")
            t2 = str(toc_nodes[i + 1].get("title") or "")
            adjacent_sims.append(PageIndexService._title_similarity(t1, t2))
        if adjacent_sims:
            ranked = sorted(adjacent_sims)
            p95_idx = int(round(0.95 * (len(ranked) - 1)))
            adjacent_title_similarity_p95 = ranked[p95_idx]
        else:
            adjacent_title_similarity_p95 = 0.0

        evidence_ok = 0
        for n in toc_nodes:
            start = int(n.get("start_index") or 0)
            end = int(n.get("end_index") or 0)
            span = (end - start + 1) if (start > 0 and end >= start) else 1
            min_evidence = 1 if span <= 2 else 2
            evidence_pages = n.get("evidence_pages") or []
            try:
                evidence_count = len([int(p) for p in evidence_pages])
            except Exception:
                evidence_count = 0
            if evidence_count >= min_evidence:
                evidence_ok += 1
        node_evidence_ratio = (
            evidence_ok / max(1, node_count) if node_count > 0 else 0.0
        )

        return {
            "node_count": node_count,
            "quality_score": float(q.get("score") or 0.0),
            "semantic_ratio": semantic_ratio,
            "coverage_ratio": coverage_ratio,
            "tail_anchor_ratio": tail_anchor_ratio,
            "tail_anchor_count": tail_anchor_count,
            "visual_summary_ratio": visual_summary_ratio,
            "max_gap_pages": max_gap_pages,
            "adjacent_title_similarity_p95": adjacent_title_similarity_p95,
            "node_evidence_ratio": node_evidence_ratio,
            "page_count": page_count,
        }

    @staticmethod
    def _evaluate_vision_toc_gate(metrics: Dict[str, Any]) -> tuple[bool, str]:
        node_count = int(metrics.get("node_count") or 0)
        quality_score = float(metrics.get("quality_score") or 0.0)
        semantic_ratio = float(metrics.get("semantic_ratio") or 0.0)
        coverage_ratio = float(metrics.get("coverage_ratio") or 0.0)
        tail_anchor_ratio = float(metrics.get("tail_anchor_ratio") or 0.0)
        visual_summary_ratio = float(metrics.get("visual_summary_ratio") or 0.0)
        max_gap_pages = int(metrics.get("max_gap_pages") or 0)
        adjacent_title_similarity_p95 = float(
            metrics.get("adjacent_title_similarity_p95") or 0.0
        )
        page_count = int(metrics.get("page_count") or 0)

        min_nodes = 4 if page_count <= 40 else 5
        if node_count < min_nodes:
            return False, "node_sparse"
        if quality_score < 0.45:
            return False, "quality_low"
        if semantic_ratio < 0.6:
            return False, "semantic_low"
        if coverage_ratio < 0.9:
            return False, "coverage_low"
        if page_count >= 24 and max_gap_pages > max(6, page_count // 5):
            return False, "coverage_gap_high"
        if page_count >= 24 and tail_anchor_ratio < 0.12:
            return False, "anchor_sparse_tail"
        if visual_summary_ratio < 0.12:
            return False, "visual_summary_sparse"
        if page_count >= 24 and adjacent_title_similarity_p95 > 0.92:
            return False, "title_redundant"
        return True, "ok"

    @staticmethod
    def _evaluate_vision_toc_gate_strict(metrics: Dict[str, Any]) -> tuple[bool, str]:
        ok, reason = PageIndexService._evaluate_vision_toc_gate(metrics)
        if not ok:
            return ok, reason

        visual_summary_ratio = float(metrics.get("visual_summary_ratio") or 0.0)
        max_gap_pages = int(metrics.get("max_gap_pages") or 0)
        node_evidence_ratio = float(metrics.get("node_evidence_ratio") or 0.0)

        if visual_summary_ratio < float(VISION_TOC_STRICT_TARGET_RATIO):
            return False, "visual_summary_insufficient"
        if max_gap_pages > int(VISION_TOC_STRICT_MAX_GAP_PAGES):
            return False, "coverage_gap_strict"
        if node_evidence_ratio < 0.9:
            return False, "node_evidence_sparse"
        return True, "ok"

    async def _repair_vision_tail_once(
        self,
        file_path: Path,
        page_count: int,
        visual_summaries: List[Dict[str, Any]],
        gate_reason: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if page_count <= 0:
            return visual_summaries

        target_ratio = float(VISION_TOC_STRICT_TARGET_RATIO)
        max_gap_target = int(VISION_TOC_STRICT_MAX_GAP_PAGES)
        max_rounds = max(1, int(VISION_TOC_STRICT_MAX_RECOVERY_ROUNDS))
        merged = list(visual_summaries)

        for _ in range(max_rounds):
            existing_pages = {
                int(item.get("page_num")) for item in merged if item.get("page_num")
            }
            coverage_ratio = len(existing_pages) / max(1, page_count)
            max_gap_pages = self._max_visual_gap(page_count, merged)
            if coverage_ratio >= target_ratio and max_gap_pages <= max_gap_target:
                break

            target_pages = self._build_visual_recovery_targets(
                page_count=page_count,
                existing_pages=existing_pages,
                gate_reason=gate_reason,
                target_ratio=target_ratio,
                max_gap_target=max_gap_target,
            )
            if not target_pages:
                break

            extra = await self._generate_fast_visual_page_summaries(
                file_path,
                target_pages,
                max_attempts_override=max(3, int(VISUAL_VLM_PAGE_MAX_ATTEMPTS)),
                per_page_timeout_override=max(18, int(VISUAL_PAGE_TIMEOUT_SECONDS)),
            )
            if not extra:
                break

            before = len(existing_pages)
            for item in extra:
                p = int(item.get("page_num") or 0)
                if p > 0 and p not in existing_pages:
                    merged.append(item)
                    existing_pages.add(p)
            if len(existing_pages) == before:
                break

            merged.sort(key=lambda x: int(x["page_num"]))
        return merged

    @staticmethod
    def _vision_gate_reason_to_error(reason: str) -> str:
        mapping = {
            "coverage_low": "VISION_TOC_COVERAGE_LOW",
            "coverage_gap_high": "VISION_TOC_COVERAGE_LOW",
            "coverage_gap_strict": "VISION_TOC_COVERAGE_LOW",
            "anchor_sparse_tail": "VISION_TOC_ANCHOR_SPARSE_TAIL",
            "semantic_low": "VISION_TOC_EVIDENCE_MISMATCH",
            "visual_summary_sparse": "VISION_TOC_INSUFFICIENT_STRUCTURE",
            "visual_summary_insufficient": "VISION_TOC_INSUFFICIENT_STRUCTURE",
            "node_sparse": "VISION_TOC_INSUFFICIENT_STRUCTURE",
            "node_evidence_sparse": "VISION_TOC_EVIDENCE_MISMATCH",
            "title_redundant": "VISION_TOC_EVIDENCE_MISMATCH",
            "quality_low": "VISION_TOC_QUALITY_TOO_LOW",
        }
        return mapping.get(reason, "VISION_TOC_QUALITY_TOO_LOW")

    @staticmethod
    def _build_visual_fallback_toc(
        page_count: Optional[int], visual_summaries: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        total = int(page_count or 0)
        if total <= 0:
            return []

        if not visual_summaries:
            return PageIndexService._build_segment_fallback_toc(total)

        sorted_summaries = sorted(
            [s for s in visual_summaries if s.get("page_num") and s.get("summary")],
            key=lambda x: int(x["page_num"]),
        )
        if not sorted_summaries:
            return PageIndexService._build_segment_fallback_toc(total)

        segment = 6 if total >= 36 else 4
        nodes: List[Dict[str, Any]] = []
        idx = 1
        for start in range(1, total + 1, segment):
            end = min(total, start + segment - 1)
            anchor = next(
                (
                    item
                    for item in sorted_summaries
                    if start <= int(item["page_num"]) <= end
                ),
                None,
            )
            anchor_text = ""
            if anchor:
                anchor_text = re.sub(
                    r"\s+", " ", str(anchor.get("summary") or "")
                ).strip()
            if anchor_text:
                title = f"第{idx}部分：{anchor_text[:24]}"
            else:
                title = f"第{idx}部分（第{start}-{end}页）"

            nodes.append(
                {
                    "node_id": f"{idx:04d}",
                    "title": title,
                    "summary": (anchor_text or title)[:220],
                    "start_index": start,
                    "end_index": end,
                    "nodes": [],
                }
            )
            idx += 1
        return nodes

    async def _enhance_balanced_fallback_with_visual(
        self,
        result: Dict[str, Any],
        file_path: Path,
        pre_analysis: Dict[str, Any],
    ) -> None:
        if not self._looks_like_segment_fallback_toc(result.get("structure", result)):
            return
        if float(pre_analysis.get("unparseable_ratio") or 0.0) <= 0.5:
            return

        vlm_needed_pages = [
            int(p) for p in (pre_analysis.get("vlm_needed_pages") or [])
        ]
        if not vlm_needed_pages:
            return

        visual_summaries = await self._generate_fast_visual_page_summaries(
            file_path, vlm_needed_pages
        )
        if not visual_summaries:
            return

        result["visual_page_summaries"] = visual_summaries
        result["structure"] = self._build_visual_fallback_toc(
            result.get("page_count"), visual_summaries
        )

        q = self._compute_structure_quality(result.get("structure", []))
        tq = (
            result.get("toc_quality")
            if isinstance(result.get("toc_quality"), dict)
            else {}
        )
        tq["after"] = q
        tq["visual_enhanced"] = True
        result["toc_quality"] = tq

    @staticmethod
    def _score_text_quality(text: str) -> float:
        t = (text or "").strip()
        if not t:
            return 0.0

        length = len(t)
        readable = sum(1 for ch in t if PageIndexService._is_common_readable_char(ch))
        readable_ratio = readable / max(1, length)

        cjk_count = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
        ascii_alpha = sum(1 for ch in t if ch.isascii() and ch.isalpha())
        alpha_count = cjk_count + ascii_alpha
        digit_count = sum(1 for ch in t if ch.isdigit())

        structure_signal = 0.0
        if re.search(r"第\s*\d+\s*[章节部分卷篇]", t):
            structure_signal += 0.12
        if re.search(r"\b\d+(?:\.\d+){1,3}\b", t):
            structure_signal += 0.08

        density = min(1.0, length / 280.0)
        alpha_ratio = alpha_count / max(1, length)
        digit_penalty = 0.2 if digit_count / max(1, length) > 0.35 else 0.0
        short_penalty = 0.2 if length < 24 else 0.0

        score = (
            0.42 * readable_ratio
            + 0.22 * alpha_ratio
            + 0.18 * density
            + structure_signal
            - digit_penalty
            - short_penalty
        )
        return max(0.0, min(1.0, score))

    @staticmethod
    def _extract_pdf_text_pypdf2(file_path: Path) -> List[str]:
        texts: List[str] = []
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    texts.append((page.extract_text() or "").strip())
                except Exception:
                    texts.append("")
        return texts

    @staticmethod
    def _extract_pdf_text_pymupdf(file_path: Path) -> tuple[List[str], List[bool]]:
        import pymupdf

        texts: List[str] = []
        has_images: List[bool] = []
        doc = pymupdf.open(str(file_path))
        try:
            for page in doc:
                texts.append((page.get_text("text") or "").strip())
                has_images.append(len(page.get_images(full=True)) > 0)
        finally:
            doc.close()
        return texts, has_images

    @staticmethod
    def _pre_analyze_pdf(file_path: Path) -> Dict[str, Any]:
        try:
            texts_pymupdf, has_images = PageIndexService._extract_pdf_text_pymupdf(
                file_path
            )
            texts_pypdf2 = PageIndexService._extract_pdf_text_pypdf2(file_path)
        except Exception:
            return {
                "page_count": 0,
                "unparseable_pages": 0,
                "unparseable_ratio": 0.0,
                "vlm_needed_pages": [],
                "preferred_parser": "PyPDF2",
                "parser_quality": {"PyPDF2": 0.0, "PyMuPDF": 0.0},
            }

        page_count = min(len(texts_pymupdf), len(texts_pypdf2))
        unparseable_pages = 0
        vlm_needed_pages: List[int] = []
        parser_scores = {"PyPDF2": 0.0, "PyMuPDF": 0.0}

        for idx in range(page_count):
            text_mu = texts_pymupdf[idx]
            text_py = texts_pypdf2[idx]
            score_mu = PageIndexService._score_text_quality(text_mu)
            score_py = PageIndexService._score_text_quality(text_py)
            parser_scores["PyMuPDF"] += score_mu
            parser_scores["PyPDF2"] += score_py

            best_score = score_mu if score_mu >= score_py else score_py
            parseable = best_score >= 0.42
            if not parseable:
                unparseable_pages += 1

            has_visual = has_images[idx] if idx < len(has_images) else False
            if has_visual or not parseable:
                vlm_needed_pages.append(idx + 1)

        if page_count > 0:
            parser_scores = {
                "PyPDF2": parser_scores["PyPDF2"] / page_count,
                "PyMuPDF": parser_scores["PyMuPDF"] / page_count,
            }

        preferred_parser = (
            "PyMuPDF"
            if parser_scores["PyMuPDF"] >= parser_scores["PyPDF2"]
            else "PyPDF2"
        )

        return {
            "page_count": page_count,
            "unparseable_pages": unparseable_pages,
            "unparseable_ratio": (unparseable_pages / page_count)
            if page_count
            else 0.0,
            "vlm_needed_pages": vlm_needed_pages,
            "preferred_parser": preferred_parser,
            "parser_quality": parser_scores,
            "image_pages": sum(1 for x in has_images[:page_count] if x),
        }

    @staticmethod
    def _decide_pdf_route(
        requested_mode: str, pre_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        requested = (requested_mode or "balanced").strip().lower()
        if requested not in {"smart", "fast", "balanced"}:
            requested = "balanced"

        execution_mode = "fast" if requested == "smart" else requested
        reasons: List[str] = []

        return {
            "requested_mode": requested,
            "execution_mode": execution_mode,
            "escalated_from_pre_analysis": execution_mode == "balanced"
            and requested == "smart",
            "escalated_from_fast_quality": False,
            "reasons": reasons,
        }

    @staticmethod
    def _should_escalate_fast_by_toc_quality(toc_quality_score: float) -> bool:
        try:
            score = float(toc_quality_score)
        except (TypeError, ValueError):
            score = 0.0
        return score < PAGEINDEX_FAST_TOC_QUALITY_ESCALATE_THRESHOLD

    @staticmethod
    def _flatten_structure_nodes(nodes: Any) -> List[Dict[str, Any]]:
        if not isinstance(nodes, list):
            return []
        out: List[Dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            out.append(node)
            out.extend(
                PageIndexService._flatten_structure_nodes(node.get("nodes") or [])
            )
        return out

    @staticmethod
    def _evaluate_fast_toc_readiness(result: Any) -> Dict[str, Any]:
        structure = result.get("structure") if isinstance(result, dict) else result
        nodes = PageIndexService._flatten_structure_nodes(structure)
        if not nodes:
            return {"ok": False, "reason": "empty_structure"}

        missing_ranges = 0
        invalid_ranges = 0
        max_end = 0
        for node in nodes:
            start = node.get("start_index")
            end = node.get("end_index")
            if not isinstance(start, int) or not isinstance(end, int):
                missing_ranges += 1
                continue
            if end < start:
                invalid_ranges += 1
            if end > max_end:
                max_end = end

        if missing_ranges > 0:
            return {
                "ok": False,
                "reason": f"missing_ranges={missing_ranges}",
                "missing_ranges": missing_ranges,
                "invalid_ranges": invalid_ranges,
            }
        if invalid_ranges > 0:
            return {
                "ok": False,
                "reason": f"invalid_ranges={invalid_ranges}",
                "missing_ranges": missing_ranges,
                "invalid_ranges": invalid_ranges,
            }

        page_count = (
            int(result.get("page_count") or 0) if isinstance(result, dict) else 0
        )
        if page_count > 0 and max_end < page_count:
            return {
                "ok": False,
                "reason": f"coverage_end_lt_page_count={max_end}/{page_count}",
                "max_end": max_end,
                "page_count": page_count,
            }

        return {
            "ok": True,
            "reason": "ok",
            "node_count": len(nodes),
            "max_end": max_end,
            "page_count": page_count,
        }

    @staticmethod
    def _vision_first_required(pre_analysis: Dict[str, Any]) -> bool:
        unparseable_pages = int(pre_analysis.get("unparseable_pages") or 0)
        unparseable_ratio = float(pre_analysis.get("unparseable_ratio") or 0.0)
        return unparseable_ratio >= 0.8 or unparseable_pages >= 60

    @staticmethod
    def _compute_pdf_text_health(
        file_path: Path, pre_analysis: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        pre = pre_analysis or PageIndexService._pre_analyze_pdf(file_path)
        total = int(pre.get("page_count") or 0)
        unparseable = int(pre.get("unparseable_pages") or 0)
        ratio = float(pre.get("unparseable_ratio") or 0.0)
        return {
            "total_pages": total,
            "empty_ratio": ratio,
            "short_ratio": ratio,
            "weird_ratio": ratio,
            "garbled_ratio": ratio,
            "unparseable_pages": unparseable,
            "unparseable_ratio": ratio,
        }

    @staticmethod
    def calculate_visual_coverage(page_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate visual coverage and downgrade reasons for one document."""
        visual_required_pages = 0
        visual_success_pages = 0
        consecutive_failures = 0
        downgrade_reasons: List[Dict[str, Any]] = []

        for index, page in enumerate(page_results, start=1):
            if not page.get("needs_visual", True):
                continue

            visual_required_pages += 1
            page_number = page.get("page", index)
            visual_success = bool(page.get("visual_success", False))
            parseable = page.get("parseable", True)

            processing_seconds = page.get("processing_seconds")
            try:
                processing_seconds = float(processing_seconds)
            except (TypeError, ValueError):
                processing_seconds = None

            timeout_hit = (
                processing_seconds is not None
                and processing_seconds > VISUAL_PAGE_TIMEOUT_SECONDS
            )
            failure = (not visual_success) or (not parseable) or timeout_hit

            if failure:
                consecutive_failures += 1
            else:
                consecutive_failures = 0
                visual_success_pages += 1

            reason: Optional[Dict[str, Any]] = None
            if not parseable:
                reason = {"page": page_number, "code": "UNPARSEABLE_PAGE"}
            elif timeout_hit:
                reason = {
                    "page": page_number,
                    "code": "PAGE_TIMEOUT",
                    "processing_seconds": processing_seconds,
                    "threshold_seconds": VISUAL_PAGE_TIMEOUT_SECONDS,
                }
            elif failure and consecutive_failures >= VISUAL_MAX_CONSECUTIVE_FAIL_PAGES:
                reason = {
                    "page": page_number,
                    "code": "CONSECUTIVE_PAGE_FAILURES",
                    "consecutive_failures": consecutive_failures,
                    "threshold": VISUAL_MAX_CONSECUTIVE_FAIL_PAGES,
                }

            if reason is not None:
                downgrade_reasons.append(reason)

        if visual_required_pages == 0:
            visual_coverage = 1.0
            downgrade_rate = 0.0
        else:
            visual_coverage = visual_success_pages / visual_required_pages
            downgrade_rate = len(downgrade_reasons) / visual_required_pages

        return {
            "visual_required_pages": visual_required_pages,
            "visual_success_pages": visual_success_pages,
            "visual_coverage": visual_coverage,
            "downgraded": bool(downgrade_reasons),
            "downgraded_pages": len(downgrade_reasons),
            "daily_downgrade_rate": downgrade_rate,
            "downgrade_reasons": downgrade_reasons,
        }

    async def _generate_index_v2(
        self, file_path: Path, doc_id: str, mode_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """v3 重构版：pdf_analyzer → fast/balanced(text|visual) → post_processing → node_filler"""
        from pageindex.pdf_analyzer import analyze_pdf_structure
        from pageindex.fast_toc import try_fast_toc
        from pageindex.balanced_toc import (
            decide_balanced_path,
            build_balanced_toc_visual,
            build_balanced_toc_text,
            _vlm_detect_anchors,
        )
        from pageindex.post_processing import post_process_toc
        from pageindex.node_filler import (
            fill_node_text,
            ocr_image_pages,
            generate_summaries,
            generate_doc_description,
            write_node_ids,
        )

        model = getattr(self.opt, "model", "qwen3.6-flash")
        requested_mode = mode_override or "smart"

        # ─── Phase 0: 文档预分析 ───
        print(f"[INDEX-V3] Phase 0: analyzing {file_path.name}")
        analysis = analyze_pdf_structure(str(file_path))
        page_count = analysis["page_count"]
        page_list = list(analysis["page_list"])

        # 路由决策
        has_code_toc = analysis["code_toc"]["items"] is not None
        if requested_mode == "smart":
            execution_mode = "fast" if has_code_toc else "balanced"
        else:
            execution_mode = requested_mode

        balanced_path = None
        if execution_mode == "balanced":
            balanced_path = decide_balanced_path(analysis)

        print(
            f"[INDEX-V3] Route: requested={requested_mode}, execution={execution_mode}, "
            f"balanced_path={balanced_path}, code_toc={analysis['code_toc']['source']}, "
            f"pages={page_count}, text_coverage={analysis['text_coverage']:.0%}"
        )

        # ─── Phase 0.5: 锚点检测（所有 balanced 文档）───
        # P2-fix: 所有 balanced 文档都先跑锚点检测，获取 dividers 信息
        anchors = None
        ocr_text_map = None
        dividers = []  # Initialize for all execution modes
        if execution_mode == "balanced":
            print("[INDEX-V3] Phase 0.5: anchor detection for all balanced documents")
            anchors = await _vlm_detect_anchors(str(file_path), model)
            dividers = anchors.get("chapter_dividers", [])
            print(f"[INDEX-V3] Phase 0.5: detected {len(dividers)} dividers")
            
            # 图片型文档额外做 OCR
            if balanced_path == "visual" and (analysis.get("is_image_only_pdf") or analysis["text_coverage"] < 0.3):
                print("[INDEX-V3] Phase 0.5: pre-TOC OCR for image-only PDF")
                toc_pages = anchors.get("toc_pages", [])
                if toc_pages:
                    pages_to_ocr = sorted(set(
                        [p - 1 for p in toc_pages]  # 0-indexed 目录页
                        + list(range(
                            max(toc_pages),
                            min(max(toc_pages) + 6, page_count)
                        ))  # 目录后 5 页
                    ))
                    print(
                        f"[INDEX-V3] Phase 0.5: OCR {len(pages_to_ocr)} pages "
                        f"(toc_pages={toc_pages})"
                    )
                    ocr_text_map = await self._ocr_pages_for_toc_validation(
                        file_path, pages_to_ocr
                    )
                    print(
                        f"[INDEX-V3] Phase 0.5: OCR done, "
                        f"{len(ocr_text_map)} pages with text"
                    )

        # ─── Phase 1: TOC 构建 ───
        toc_items = None
        toc_source = None

        if execution_mode == "fast":
            print("[INDEX-V3] Phase 1: trying fast TOC")
            fast_result = await try_fast_toc(analysis, model)
            if fast_result and not fast_result.get("quality_check_failed"):
                toc_items = fast_result["toc_items"]
                toc_source = fast_result["source"]
            elif fast_result and fast_result.get("quality_check_failed"):
                # P1-fix: Fast TOC quality check failed, but we have items - escalate to balanced
                print("[INDEX-V3] Fast TOC quality check failed, escalating to balanced")
                execution_mode = "balanced"
                balanced_path = "visual"  # Force visual for better accuracy
            elif requested_mode == "fast":
                raise ValueError(
                    "FAST_TOC_INCOMPLETE: code extraction + validation failed"
                )
            else:
                print("[INDEX-V3] Fast failed, escalating to balanced")
                execution_mode = "balanced"
                balanced_path = decide_balanced_path(analysis)

        if execution_mode == "balanced":
            if balanced_path == "text":
                print("[INDEX-V3] Phase 1: balanced TEXT (LLM)")
                # P2-fix: 传入 dividers 修正 Text 路径结果
                text_dividers = anchors.get("chapter_dividers", []) if anchors else []
                balanced_result = await build_balanced_toc_text(
                    analysis, model, dividers=text_dividers
                )
                
                # P5-fix: Check text path quality, fallback to visual if poor
                toc_items = balanced_result["toc_items"]
                top_level = [it for it in toc_items if "." not in str(it.get("structure", ""))]
                has_large_nodes = any(
                    (toc_items[i+1].get("physical_index", page_count+1) - it.get("physical_index", 0)) > 15
                    for i, it in enumerate(toc_items[:-1])
                ) if len(toc_items) > 1 else False
                
                if len(top_level) < 3 and len(toc_items) > 10 and has_large_nodes:
                    print(f"[INDEX-V3] Text path quality poor: {len(top_level)} top-level, {len(toc_items)} items, large nodes detected")
                    print("[INDEX-V3] Falling back to VISUAL path")
                    balanced_path = "visual"
                    balanced_result = await build_balanced_toc_visual(
                        str(file_path), analysis, model,
                        anchors=anchors,
                        ocr_text_map=ocr_text_map,
                    )
                    toc_items = balanced_result["toc_items"]
                    toc_source = balanced_result["source"]
                else:
                    toc_source = balanced_result["source"]
            else:
                print("[INDEX-V3] Phase 1: balanced VISUAL (VLM)")
                balanced_result = await build_balanced_toc_visual(
                    str(file_path), analysis, model,
                    anchors=anchors,
                    ocr_text_map=ocr_text_map,
                )
                toc_items = balanced_result["toc_items"]
                toc_source = balanced_result["source"]

        # ─── Phase 1.5: OCR 图片页 ───
        needs_ocr = (
            len(analysis.get("image_only_pages", [])) > 0
            or len(analysis.get("garbled_pages", [])) > 0
        )
        if needs_ocr:
            print(
                f"[INDEX-V3] OCR: {len(analysis.get('image_only_pages', []))} image "
                f"+ {len(analysis.get('garbled_pages', []))} garbled pages"
            )
            page_list = await ocr_image_pages(
                analysis,
                page_list,
                ocr_service_fn=self._run_full_pdf_ocr_by_images,
            )
            analysis["page_list"] = page_list

        # ─── Phase 2: 后处理 (post_processing.py v3) ───
        print(f"[INDEX-V3] Phase 2: post-processing {len(toc_items)} items")
        toc_tree, completeness = post_process_toc(toc_items, page_count, dividers=dividers)

        if completeness.get("needs_repair"):
            print(f"[INDEX-V3] Coverage needs repair: {completeness}")
            # TODO: gap 修复（对 gaps 区域补充分析")

        # ─── Phase 2.5: LLM 质量检查 ───
        try:
            from pageindex.post_processing import llm_quality_check
            quality_result = await llm_quality_check(
                tree=toc_tree,
                toc_items=toc_items,
                page_count=page_count,
                source=toc_source or "unknown",
                has_dividers=bool(anchors and anchors.get("chapter_dividers")),
                divider_count=len(anchors.get("chapter_dividers", [])) if anchors else 0,
                model=model,
            )
            result["llm_quality_check"] = quality_result
            
            # 根据质检结果修复
            if quality_result.get("needs_repair"):
                print(f"[INDEX-V3] LLM quality check suggests repairs")
                for suggestion in quality_result.get("suggestions", []):
                    if "子章节" in suggestion or "拆分" in suggestion:
                        print(f"[INDEX-V3] Triggering sub-chapter extraction for large nodes")
                        # 标记需要子章节提取
                        break
        except Exception as e:
            print(f"[INDEX-V3] LLM quality check skipped: {e}")

        # 大节点递归拆分（balanced 模式）
        if execution_mode == "balanced":
            import asyncio as _aio
            from pageindex.page_index import process_large_node_recursively, JsonLogger

            logger = JsonLogger(str(file_path))
            tasks = [
                process_large_node_recursively(node, page_list, self.opt, logger=logger)
                for node in toc_tree
            ]
            await _aio.gather(*tasks)

        # ─── Phase 3: 节点填充 + 摘要 ───
        print(f"[INDEX-V3] Phase 3: filling nodes + summaries (mode={execution_mode})")
        fill_node_text(toc_tree, page_list)
        write_node_ids(toc_tree)
        await generate_summaries(toc_tree, model=model, mode=execution_mode)

        doc_description = await generate_doc_description(
            toc_tree, model=model, file_name=file_path.name
        )

        # ─── 构建输出 ───
        result = {
            "doc_name": file_path.name,
            "doc_description": doc_description,
            "page_count": page_count,
            "structure": toc_tree,
            "route_decision": {
                "requested_mode": requested_mode,
                "execution_mode": execution_mode,
                "balanced_path": balanced_path,
                "toc_source": toc_source,
                "text_coverage": analysis["text_coverage"],
                "is_image_only_pdf": analysis.get("is_image_only_pdf", False),
            },
            "completeness": completeness,
            "ocr_used": needs_ocr,
        }

        # 保存索引文件
        index_path = INDEXES_DIR / f"{doc_id}.json"
        import json

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[INDEX-V2] Saved index: {index_path}")

        return {"index_path": str(index_path), "structure": result}

    async def generate_index(
        self, file_path: str, doc_id: str, mode_override: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成文档的 PageIndex 树状索引 — 路由到 v2 重构版

        Args:
            file_path: 文档文件路径
            doc_id: 文档 ID

        Returns:
            索引结果字典
        """
        file_path = Path(file_path)

        # PDF 文件走 v2 重构版
        if file_path.suffix.lower() == ".pdf":
            return await self._generate_index_v2(file_path, doc_id, mode_override)

        # 非 PDF 文件走旧流程
        self.opt = self._build_opt(mode_override=mode_override)

        visual_coverage = None
        if file_path.suffix.lower() == ".pdf":
            pre_analysis = self._pre_analyze_pdf(file_path)
            route = self._decide_pdf_route(
                getattr(self.opt, "index_mode", "balanced"),
                pre_analysis,
            )

            page_count = int(pre_analysis.get("page_count") or 0)
            has_images = int(pre_analysis.get("image_pages") or 0) > 0
            ocr_used = False
            ocr_pages: List[Dict[str, Any]] = []
            ocr_coverage = 0.0
            ocr_missing_pages: List[int] = []
            ocr_page_list: Optional[List[Any]] = None

            if has_images and page_count > 0:
                print(f"[OCR] start image-block OCR doc={doc_id} pages={page_count}")
                ocr_result = await self._run_full_pdf_ocr_by_images(
                    file_path, page_count
                )
                ocr_pages = list(ocr_result.get("ocr_pages") or [])
                ocr_coverage = float(ocr_result.get("ocr_coverage") or 0.0)
                ocr_missing_pages = [
                    int(p) for p in (ocr_result.get("ocr_missing_pages") or [])
                ]
                ocr_used = True
                base_page_list = get_page_tokens(
                    str(file_path),
                    model=getattr(self.opt, "model", None),
                    pdf_parser=pre_analysis.get("preferred_parser", "PyPDF2"),
                )
                ocr_page_list = self._build_page_list_with_ocr_overlay(
                    base_page_list=base_page_list,
                    ocr_pages=ocr_pages,
                    model=getattr(self.opt, "model", "qwen3.6-flash"),
                )
                print(
                    f"[OCR] done doc={doc_id} coverage={round(ocr_coverage, 4)} missing={len(ocr_missing_pages)}"
                )

            execution_mode = route["execution_mode"]
            self.opt = self._build_opt(mode_override=execution_mode)
            setattr(
                self.opt,
                "pdf_parser",
                pre_analysis.get("preferred_parser", "PyPDF2"),
            )
            setattr(self.opt, "file_path", str(file_path))

            # ─── 两轮 Fast TOC 提取（OCR 前 + OCR 后）───
            fast_toc_result = None
            if execution_mode in ("fast", "smart"):
                import pageindex.page_index as _pi_mod

                extract_toc_code_only = _pi_mod.extract_toc_code_only
                validate_and_finalize_toc = _pi_mod.validate_and_finalize_toc
                _extract_toc_by_regex = _pi_mod._extract_toc_by_regex

                # 第一轮：用 pymupdf 原始文本（OCR 之前）
                raw_page_list = None
                try:
                    raw_page_list = get_page_tokens(
                        str(file_path),
                        model=getattr(self.opt, "model", None),
                        pdf_parser=pre_analysis.get("preferred_parser", "PyPDF2"),
                    )
                    toc_items, source = extract_toc_code_only(
                        str(file_path), raw_page_list
                    )
                except Exception as e:
                    print(f"[FAST-TOC] Round 1 error: {e}")
                    toc_items, source = None, None

                # 第二轮：如果第一轮没成功且有 OCR 文本，用 OCR 文本再跑 Level 3
                if not toc_items and ocr_page_list:
                    try:
                        toc_items = _extract_toc_by_regex(ocr_page_list)
                        if toc_items:
                            source = "regex_ocr"
                            print(
                                f"[FAST-TOC] Level 3 OCR round: {len(toc_items)} items"
                            )
                    except Exception as e:
                        print(f"[FAST-TOC] Round 2 error: {e}")

                # 校验
                if toc_items:
                    try:
                        # 使用 OCR page_list（如果有）或原始 page_list 进行 offset 校正
                        correction_page_list = ocr_page_list or raw_page_list
                        fast_toc_result = await validate_and_finalize_toc(
                            toc_items,
                            source,
                            page_count,
                            model=getattr(self.opt, "model", None),
                            page_list=correction_page_list,
                        )
                    except Exception as e:
                        print(f"[FAST-TOC] Validation error: {e}")

                if not fast_toc_result:
                    requested = route.get("requested_mode", execution_mode)
                    if requested == "fast":
                        raise ValueError(
                            "FAST_TOC_INCOMPLETE: code extraction + validation failed"
                        )
                    # smart 模式：升级到 balanced
                    print(
                        "[FAST-TOC] Smart mode: fast extraction failed, escalating to balanced"
                    )
                    execution_mode = "balanced"
                    route["execution_mode"] = "balanced"
                    route["escalated_from_fast_quality"] = True
                    self.opt = self._build_opt(mode_override="balanced")
                    setattr(
                        self.opt,
                        "pdf_parser",
                        pre_analysis.get("preferred_parser", "PyPDF2"),
                    )
                    setattr(self.opt, "file_path", str(file_path))
                    fast_toc_result = None  # balanced 不用 fast result

            def run_pageindex(opt_obj):
                if ocr_page_list is None:
                    return page_index_main(
                        str(file_path), opt_obj, fast_toc_result=fast_toc_result
                    )
                return page_index_main_with_page_list(
                    doc_name=file_path.name,
                    page_list=ocr_page_list,
                    opt=opt_obj,
                    fast_toc_result=fast_toc_result,
                )

            def run_balanced_once(reason: str) -> Dict[str, Any]:
                nonlocal execution_mode
                balanced_opt = self._build_opt(mode_override="balanced")
                setattr(
                    balanced_opt,
                    "pdf_parser",
                    pre_analysis.get("preferred_parser", "PyPDF2"),
                )
                execution_mode = "balanced"
                route["execution_mode"] = "balanced"
                route["escalated_from_fast_quality"] = True
                route["reasons"].append(reason)
                self.opt = balanced_opt
                return run_pageindex(balanced_opt)

            try:
                result = run_pageindex(self.opt)
            except ValueError as e:
                msg = str(e)
                if (
                    execution_mode == "fast"
                    and route.get("requested_mode") == "smart"
                    and msg.startswith("FAST_TOC_INCOMPLETE")
                ):
                    result = run_balanced_once(f"smart_fast_unavailable:{msg}")
                else:
                    raise

            if execution_mode == "fast":
                fast_gate = self._evaluate_fast_toc_readiness(result)
                route["fast_gate"] = fast_gate
                if not fast_gate.get("ok", False):
                    reason = str(fast_gate.get("reason") or "unknown")
                    if route.get("requested_mode") == "fast":
                        raise ValueError(f"FAST_TOC_INCOMPLETE: {reason}")
                    result = run_balanced_once(f"smart_fast_unavailable:{reason}")
            result["pre_analysis"] = pre_analysis
            result["route_decision"] = route
            result["ocr_used"] = ocr_used
            result["ocr_coverage"] = ocr_coverage
            result["ocr_missing_pages"] = ocr_missing_pages

            # 主流程质量门控：仅 balanced 模式执行
            if execution_mode == "fast":
                structure_data = result.get("structure", result)
                # Fast mode skips LLM-based node summaries, fill from title/text
                self._ensure_structure_node_summaries(structure_data)
                quality = self._compute_structure_quality(structure_data)
                result["toc_quality"] = {
                    "before": quality,
                    "after": quality,
                    "text_health": self._compute_pdf_text_health(
                        file_path, pre_analysis
                    ),
                    "repaired": False,
                }
            else:
                structure_data = result.get("structure", result)
                quality_before = self._compute_structure_quality(structure_data)
                text_health = self._compute_pdf_text_health(file_path, pre_analysis)
                result["toc_quality"] = {
                    "before": quality_before,
                    "after": quality_before,
                    "text_health": text_health,
                    "repaired": False,
                }

            if execution_mode == "fast":
                # Fast mode: no visual processing, skip expensive computation
                result["visual_coverage"] = {
                    "visual_required_pages": 0,
                    "visual_success_pages": 0,
                    "visual_coverage": 1.0,
                    "downgraded": False,
                    "downgraded_pages": 0,
                    "daily_downgrade_rate": 0.0,
                    "downgrade_reasons": [],
                }
            else:
                page_results = result.get("visual_page_results", [])
                if not isinstance(page_results, list):
                    page_results = []
                visual_coverage = self.calculate_visual_coverage(page_results)
                if visual_coverage.get("visual_required_pages", 0) == 0:
                    visual_summaries = result.get("visual_page_summaries")
                    if isinstance(visual_summaries, list) and visual_summaries:
                        required = len(pre_analysis.get("vlm_needed_pages") or [])
                        success = len(visual_summaries)
                        visual_coverage = {
                            "visual_required_pages": required,
                            "visual_success_pages": success,
                            "visual_coverage": (success / required)
                            if required
                            else 1.0,
                            "downgraded": success < required,
                            "downgraded_pages": max(0, required - success),
                            "daily_downgrade_rate": ((required - success) / required)
                            if required
                            else 0.0,
                            "downgrade_reasons": [],
                        }
                result["visual_coverage"] = visual_coverage
        elif file_path.suffix.lower() in [".md", ".markdown"]:
            # Markdown 优先走规则化目录解析（更快、更稳定）
            adapted = generate_multi_format_index(file_path)
            if adapted is not None:
                result = adapted
            else:
                # 兜底兼容：保留原有 md_to_tree 路径
                result = await md_to_tree(
                    md_path=str(file_path),
                    if_thinning=False,
                    min_token_threshold=None,
                    if_add_node_summary=self.opt.if_add_node_summary,
                    summary_token_threshold=200,
                    if_add_doc_description=self.opt.if_add_doc_description,
                    if_add_node_text=self.opt.if_add_node_text,
                    if_add_node_id="yes",
                    model=self.opt.model,
                )
        else:
            adapted = generate_multi_format_index(file_path)
            if adapted is None:
                raise ValueError(f"Unsupported file type: {file_path.suffix}")
            result = adapted

        # 索引文件在后处理后落盘，确保包含最终摘要/质量元信息
        index_path = INDEXES_DIR / f"{doc_id}.json"

        doc_description = ""
        page_count = None
        if isinstance(result, dict):
            doc_description = result.get("doc_description", "") or ""
            if "page_count" in result:
                page_count = result.get("page_count")
            elif file_path.suffix.lower() == ".pdf":
                # 从 PDF 文件获取实际页数
                try:
                    with open(file_path, "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        page_count = len(pdf_reader.pages)
                except Exception as e:
                    print(f"[WARN] Failed to get PDF page count from {file_path}: {e}")
                    page_count = None

            # Fast 模式：同流程内生成轻量文档摘要；超时或失败直接跳过
            if (
                not doc_description
                and getattr(self.opt, "index_mode", "balanced") == "fast"
            ):
                structure_data = result.get("structure", result)
                doc_description = await self._generate_fast_light_doc_summary(
                    structure_data, file_path
                )
                if doc_description:
                    result["doc_description"] = doc_description
                else:
                    print(
                        f"[FAST_SUMMARY] final=empty doc={file_path.name} doc_id={doc_id}"
                    )

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return {
            "index_path": str(index_path),
            "structure": result,
            "doc_description": doc_description,
            "page_count": page_count,
            "visual_coverage": visual_coverage,
            "index_mode": getattr(self.opt, "index_mode", "balanced"),
        }

    async def load_index(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """加载文档的索引"""
        index_path = INDEXES_DIR / f"{doc_id}.json"
        if not index_path.exists():
            return None

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[PageIndexService] Warning: Index file corrupted for doc {doc_id}: {e}")
            return None

    @staticmethod
    def _build_search_structure_summary(
        nodes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        summary_rows: List[Dict[str, Any]] = []
        for node in nodes:
            summary = (node.get("summary") or "").strip()
            if not summary and node.get("text"):
                summary = str(node.get("text") or "")[:160]
            if not summary:
                summary = str(node.get("title") or "")[:160]

            start = node.get("start_index")
            end = node.get("end_index")
            pages = ""
            if start is not None and end is not None:
                pages = f"{start}-{end}"

            summary_rows.append(
                {
                    "node_id": node.get("node_id"),
                    "title": node.get("title"),
                    "summary": summary[:160] if summary else "",
                    "pages": pages,
                }
            )
        return summary_rows

    @staticmethod
    def _visual_summary_keyword_search(
        query: str,
        visual_summaries: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        doc_id: str,
        doc_name: str,
    ) -> List[Dict[str, Any]]:
        import re as _re

        q = (query or "").lower().replace(" ", "")
        if not q or not visual_summaries:
            return []

        raw_tokens = _re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", q)
        stopwords = set("搜索一下帮找一下请什么是的有吗呢了啊关于介绍下帮我")
        kws = [t for t in raw_tokens if len(t) > 1 or t not in stopwords]
        if not kws:
            kws = [q]

        node_ranges: List[Dict[str, Any]] = []
        for n in nodes:
            try:
                s = int(n.get("start_index") or 0)
                e = int(n.get("end_index") or 0)
            except Exception:
                continue
            if s > 0 and e >= s:
                node_ranges.append(n)

        candidates: List[Dict[str, Any]] = []
        for item in visual_summaries:
            page = int(item.get("page_num") or 0)
            summary = re.sub(r"\s+", " ", str(item.get("summary") or "")).strip()
            if page <= 0 or not summary:
                continue
            hay = summary.lower().replace(" ", "")
            hit_count = sum(1 for kw in kws if kw and kw in hay)
            if q in hay:
                hit_count += 2
            if hit_count <= 0:
                continue

            target = None
            for n in node_ranges:
                s = int(n.get("start_index") or 0)
                e = int(n.get("end_index") or 0)
                if s <= page <= e:
                    target = n
                    break
            if target is None:
                continue

            score = min(0.92, 0.45 + 0.08 * hit_count)
            candidates.append(
                {
                    "document_id": doc_id,
                    "document_name": doc_name,
                    "node_id": target.get("node_id"),
                    "node_title": target.get("title"),
                    "start_index": target.get("start_index"),
                    "end_index": target.get("end_index"),
                    "summary": summary[:300],
                    "full_text": summary,
                    "reasoning": f"visual_summary_hit:p.{page}",
                    "relevance": round(score, 3),
                    "source": "visual_summary",
                }
            )

        dedup: Dict[str, Dict[str, Any]] = {}
        for item in sorted(
            candidates, key=lambda x: x.get("relevance", 0), reverse=True
        ):
            nid = str(item.get("node_id") or "")
            if not nid:
                continue
            if nid not in dedup:
                dedup[nid] = item
        return list(dedup.values())[:3]

    async def search_in_structure_async(
        self, structure: Dict[str, Any], query: str, doc_id: str, doc_name: str
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 进行推理式检索（PageIndex 核心功能）

        模拟人类专家如何浏览文档找到相关内容
        """
        from app.core.llm import async_chat_completion
        from app.services.cache_service import cache_service

        # 检查缓存
        cached_result = cache_service.get_search_result(query, [doc_id])
        if cached_result is not None:
            print(f"[CACHE] Search cache hit for query: {query[:30]}...")
            return cached_result

        # 处理索引文件格式
        if "structure" in structure:
            structure_data = structure["structure"]
        else:
            structure_data = structure
        visual_summaries = (
            structure.get("visual_page_summaries", [])
            if isinstance(structure, dict)
            else []
        )

        # 构建树状结构的摘要（包含页码，提升章节定位能力）
        nodes = structure_to_list(structure_data)
        structure_summary = self._build_search_structure_summary(nodes)

        prompt = f"""分析文档目录结构，找出与用户查询最相关的章节。

目录结构:
{json.dumps(structure_summary, ensure_ascii=False, indent=2)}

用户查询: {query}

返回最相关的 2-3 个章节，JSON 格式:
[{{"node_id": "节点ID", "reasoning": "相关原因", "relevance_score": 0.0-1.0}}]

只返回 JSON，不要其他内容。"""

        try:
            response = await async_chat_completion(
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                model="qwen3.6-flash",  # 使用快速模型
            )

            content = response.choices[0].message.content

            # 解析 JSON
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                llm_results = json.loads(json_match.group())
            else:
                llm_results = []

            # 转换为标准格式
            results = []
            node_dict = {n.get("node_id"): n for n in nodes}

            for item in llm_results:
                node_id = item.get("node_id")
                if node_id in node_dict:
                    node = node_dict[node_id]
                    # 获取文本内容
                    text = node.get("text", "")

                    results.append(
                        {
                            "document_id": doc_id,
                            "document_name": doc_name,
                            "node_id": node_id,
                            "node_title": node.get("title"),
                            "start_index": node.get("start_index"),
                            "end_index": node.get("end_index"),
                            "summary": text[:300] if text else "",  # 摘要用于展示
                            "full_text": text,  # 完整原文用于推理
                            "reasoning": item.get("reasoning", ""),
                            "relevance": item.get("relevance_score", 0.5),
                        }
                    )

            if results:
                verified_results = await verify_candidate_nodes(
                    candidates=results,
                    query=query,
                    nodes=nodes,
                    model="qwen3.6-flash",
                )
                results = verified_results

                filtered_results = [
                    r
                    for r in results
                    if not (
                        r.get("verification_passed") == False
                        and r.get("verification_confidence", 0) > 0.7
                    )
                ]

                if not filtered_results and results:
                    filtered_results = [results[0]]

                results = filtered_results

            visual_candidates = self._visual_summary_keyword_search(
                query=query,
                visual_summaries=(
                    visual_summaries if isinstance(visual_summaries, list) else []
                ),
                nodes=nodes,
                doc_id=doc_id,
                doc_name=doc_name,
            )
            if visual_candidates:
                existing_ids = {str(x.get("node_id") or "") for x in results}
                for vc in visual_candidates:
                    nid = str(vc.get("node_id") or "")
                    if nid and nid not in existing_ids:
                        results.append(vc)
                        existing_ids.add(nid)

            # 按相关度和验证置信度综合排序
            results.sort(
                key=lambda x: (
                    x.get("relevance", 0)
                    * max(x.get("verification_confidence", 0.5), 0.1)
                ),
                reverse=True,
            )

            final_results = results[:3]

            # 缓存结果
            cache_service.set_search_result(query, [doc_id], final_results)

            return final_results

        except Exception as e:
            print(f"LLM search error: {e}")
            # 降级到简单搜索
            return self._simple_search(structure_data, query, doc_id, doc_name)

    def _simple_search(
        self, structure_data: Dict[str, Any], query: str, doc_id: str, doc_name: str
    ) -> List[Dict[str, Any]]:
        """
        关键词搜索：先全串匹配，无结果则拆词/拆字匹配
        """
        import re as _re

        nodes = structure_to_list(structure_data)
        results = []

        # 清理查询
        query_clean = query.lower().replace(" ", "")

        # 提取关键词：英文词 + 中文2字词 + 中文单字
        stopwords = set("搜索一下帮找一下请什么是的有吗呢了啊关于介绍下帮我")
        raw_tokens = _re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", query_clean)
        # 保留英文词和不在停用词表中的中文字符
        keywords = [t for t in raw_tokens if len(t) > 1 or t not in stopwords]
        # 同时生成相邻两字组合（模拟中文分词）
        bigrams = []
        cn_chars = [t for t in raw_tokens if len(t) == 1 and t not in stopwords]
        for i in range(len(cn_chars) - 1):
            bigrams.append(cn_chars[i] + cn_chars[i + 1])
        all_keywords = keywords + bigrams

        for node in nodes:
            title = node.get("title", "")
            text = node.get("text", "")
            summary = (node.get("summary") or "")[:100]
            title_lower = title.lower().replace(" ", "")
            text_lower = text.lower().replace(" ", "")
            search_content = f"{title} {text} {summary}".lower().replace(" ", "")

            # 第一级：全串匹配
            if query_clean in search_content:
                results.append(
                    {
                        "document_id": doc_id,
                        "document_name": doc_name,
                        "node_id": node.get("node_id"),
                        "node_title": title,
                        "start_index": node.get("start_index"),
                        "end_index": node.get("end_index"),
                        "summary": text[:200] if text else "",
                        "relevance": 0.9,
                    }
                )
                continue

            # 第二级：关键词/拆字匹配
            if all_keywords:
                hit_count = sum(1 for kw in all_keywords if kw in search_content)
                title_hits = sum(1 for kw in all_keywords if kw in title_lower)
                text_hits = sum(1 for kw in all_keywords if kw in text_lower)
                min_hits = min(2, len(all_keywords)) if len(all_keywords) >= 2 else 1
                if hit_count >= min_hits:
                    # 标题命中加分，文本命中密度加分
                    base = 0.3 + hit_count * 0.05
                    title_bonus = title_hits * 0.15
                    text_density = min(text_hits * 0.02, 0.2)
                    results.append(
                        {
                            "document_id": doc_id,
                            "document_name": doc_name,
                            "node_id": node.get("node_id"),
                            "node_title": title,
                            "start_index": node.get("start_index"),
                            "end_index": node.get("end_index"),
                            "summary": text[:200] if text else "",
                            "relevance": round(
                                min(base + title_bonus + text_density, 0.89), 2
                            ),
                        }
                    )

        # 按相关度排序
        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return results[:3]

    def search_in_structure(
        self, structure: Dict[str, Any], query: str, doc_id: str, doc_name: str
    ) -> List[Dict[str, Any]]:
        """
        同步版本的搜索（用于兼容）
        """
        # 处理索引文件格式
        if "structure" in structure:
            structure_data = structure["structure"]
        else:
            structure_data = structure

        return self._simple_search(structure_data, query, doc_id, doc_name)

    async def reasoning_search(
        self,
        structure: Dict[str, Any],
        query: str,
        doc_id: str,
        doc_name: str,
        pdf_text: str = None,
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 进行推理式检索（PageIndex 核心功能）

        模拟人类专家如何浏览文档找到相关内容
        """
        from app.core.llm import async_chat_completion

        # 构建树状结构的摘要
        nodes = structure_to_list(structure)
        structure_summary = self._build_search_structure_summary(nodes)

        prompt = f"""你是一个文档检索专家。给定一个文档的目录结构和用户的查询，你需要找出最相关的章节。

文档目录结构:
{json.dumps(structure_summary, ensure_ascii=False, indent=2)}

用户查询: {query}

请分析哪些章节最可能包含用户需要的信息，并返回结果。

返回格式 (JSON):
[
    {{
        "node_id": "节点ID",
        "title": "章节标题",
        "reasoning": "为什么这个章节相关",
        "relevance_score": 0.0-1.0
    }}
]

只返回 JSON，不要其他内容。"""

        try:
            response = await async_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个文档检索专家，擅长根据目录结构找到相关内容。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
            )

            content = response.choices[0].message.content

            # 解析 JSON
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                llm_results = json.loads(json_match.group())
            else:
                llm_results = []

            # 转换为标准格式
            results = []
            node_dict = {n.get("node_id"): n for n in nodes}

            for item in llm_results:
                node_id = item.get("node_id")
                if node_id in node_dict:
                    node = node_dict[node_id]
                    results.append(
                        {
                            "document_id": doc_id,
                            "document_name": doc_name,
                            "node_id": node_id,
                            "node_title": node.get("title"),
                            "start_index": node.get("start_index"),
                            "end_index": node.get("end_index"),
                            "summary": node.get("summary", ""),
                            "reasoning": item.get("reasoning", ""),
                            "relevance": item.get("relevance_score", 0.5),
                        }
                    )

            # 按相关度排序
            results.sort(key=lambda x: x["relevance"], reverse=True)
            return results[:5]

        except Exception as e:
            print(f"Reasoning search error: {e}")
            # 降级到简单搜索
            return self.search_in_structure(structure, query, doc_id, doc_name)
