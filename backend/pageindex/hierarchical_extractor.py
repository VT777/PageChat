"""分层提取路径 — 先提取一级框架，再逐章展开子章节。

适用场景: 长文档(>50页)，结构复杂，有明确章节层次
优势: 子章节完整，页码边界准确，支持多级嵌套
成本: ~5-10次LLM调用（1次框架+每章1次展开）
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pageindex.utils import llm_completion, llm_acompletion, count_tokens
from pageindex.fast_toc import verify_content_match, apply_offset


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

MAX_TOKENS_FRAMEWORK = 8000      # stage=framework 最大token数
MAX_TOKENS_EXPAND = 6000      # stage=expand 每章最大token数
CHAPTER_BATCH_SIZE = 3            # stage=expand 并发章节数
MIN_CHAPTER_PAGES = 2             # 章节最小页数
CHAPTER_EXCERPT_CHARS = 200
LONG_CHAPTER_WINDOW_SIZE = 10
LONG_CHAPTER_WINDOW_OVERLAP = 1
LONG_CHAPTER_WINDOW_THRESHOLD = 25
CONTENT_OUTLINE_GROUP_TOKEN_LIMIT = 10000
CONTENT_OUTLINE_PAGE_CHAR_LIMIT = 4500
MIN_CONTENT_OUTLINE_ITEMS = 2



def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_EXPLICIT_NUMBERING_RE = re.compile(
    r"^\s*(?P<number>\d{1,3}(?:[.]\d{1,3})+)\b"
)
_NUMBERED_STRUCTURE_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3})*$")
_AUTHORITATIVE_UNNUMBERED_STRUCTURES = {
    "abstract",
    "references",
    "acknowledgment",
    "acknowledgement",
    "conclusion",
    "index",
    "preface",
    "contents",
}


def _explicit_numbering_key(title: str) -> Optional[str]:
    """Return a stable key for explicit section numbers such as 1.4 or 2.3.1."""
    normalized = (title or "").replace(chr(0xFF0E), ".")
    match = _EXPLICIT_NUMBERING_RE.match(normalized)
    if not match:
        return None
    return match.group("number")


def _content_outline_structure_key(value: Any) -> str:
    return _coerce_text(value).casefold()


def _is_numbered_structure(structure: Any) -> bool:
    return bool(_NUMBERED_STRUCTURE_RE.fullmatch(_coerce_text(structure)))


def _is_authoritative_heading_item(item: Dict[str, Any]) -> bool:
    structure = _content_outline_structure_key(item.get("structure"))
    title = _coerce_text(item.get("title"))
    page = _physical_index_to_int(item.get("physical_index"))
    if not title or page <= 0:
        return False
    if _is_numbered_structure(structure):
        return True
    return structure in _AUTHORITATIVE_UNNUMBERED_STRUCTURES


def _title_has_own_number(title: Any) -> bool:
    value = _coerce_text(title).replace(chr(0xFF0E), ".")
    return bool(re.match(r"^\s*\d{1,3}(?:\.\d{1,3})*[.)]?\s+\S", value))


def _content_outline_sort_key(item: Dict[str, Any]) -> Tuple[int, Tuple[Any, ...], int]:
    page = _physical_index_to_int(item.get("physical_index")) or 10**9
    structure = _content_outline_structure_key(item.get("structure"))
    order = _coerce_int(item.get("_content_outline_order"), 10**6)
    if structure == "0":
        return (page, (-3, 0), order)
    if structure.startswith("front-"):
        return (page, (-2, order), order)
    if structure == "abstract":
        return (page, (-1, 0), order)
    if _is_numbered_structure(structure):
        parts = tuple(_coerce_int(part, 0) for part in structure.split("."))
        return (page, (0, *parts), order)
    if structure in {"acknowledgment", "acknowledgement"}:
        return (page, (900, 0), order)
    if structure == "references":
        return (page, (910, 0), order)
    if structure == "index":
        return (page, (920, 0), order)
    return (page, (999, order), order)


def _merge_text_heading_facts(
    flat_items: List[Dict[str, Any]],
    *,
    page_texts: List[str],
    physical_start_page: int,
    physical_end_page: int,
) -> List[Dict[str, Any]]:
    """Repair LLM outline facts with high-confidence headings from page text.

    The LLM remains responsible for the document outline, but explicit numbered
    headings and canonical paper sections such as ABSTRACT/REFERENCES are
    reliable page-level evidence. They can safely fill omissions and correct
    start pages without introducing a separate rule-only path.
    """
    try:
        from pageindex.text_heading_extractor import extract_text_headings
    except Exception:
        return flat_items

    heading_items = extract_text_headings(page_texts, start_page=physical_start_page)
    heading_items = [
        dict(item)
        for item in heading_items
        if isinstance(item, dict)
        and physical_start_page
        <= _physical_index_to_int(item.get("physical_index"))
        <= physical_end_page
    ]
    authoritative = [item for item in heading_items if _is_authoritative_heading_item(item)]
    if len(authoritative) < 3:
        return flat_items

    merged: List[Dict[str, Any]] = []
    for order, item in enumerate(flat_items):
        updated = dict(item)
        updated.setdefault("_content_outline_order", order)
        merged.append(updated)

    # If the model labeled the document title as numeric section "1", move it
    # to the deterministic front-matter structure so the real section 1 can
    # remain a separate node.
    front_heading_by_title = {
        _normalize_title_key(item.get("title")): item
        for item in heading_items
        if _content_outline_structure_key(item.get("structure")).startswith("front-")
    }
    if physical_start_page == 1 and front_heading_by_title:
        for item in merged:
            title_key = _normalize_title_key(item.get("title"))
            front = front_heading_by_title.get(title_key)
            if not front:
                continue
            if _is_numbered_structure(item.get("structure")) and not _title_has_own_number(item.get("title")):
                item["structure"] = front.get("structure") or "front-1"
                item["level"] = 1
                item["physical_index"] = _physical_index_to_int(front.get("physical_index"))

    by_structure: Dict[str, Dict[str, Any]] = {}
    for item in merged:
        structure = _content_outline_structure_key(item.get("structure"))
        if structure and structure not in by_structure:
            by_structure[structure] = item

    next_order = len(merged)
    changed = 0
    for heading in authoritative:
        structure = _content_outline_structure_key(heading.get("structure"))
        page = _physical_index_to_int(heading.get("physical_index"))
        if not structure or page <= 0:
            continue
        existing = by_structure.get(structure)
        if existing is not None:
            if _physical_index_to_int(existing.get("physical_index")) != page:
                existing["physical_index"] = page
                existing["source"] = str(existing.get("source") or "llm_content_outline")
                existing["heading_fact_verified"] = True
                changed += 1
            continue

        added = dict(heading)
        added["source"] = "text_heading_fact"
        added["heading_fact_verified"] = True
        added["_content_outline_order"] = next_order
        next_order += 1
        merged.append(added)
        by_structure[structure] = added
        changed += 1

    if changed <= 0:
        return flat_items

    merged.sort(key=_content_outline_sort_key)
    for item in merged:
        item.pop("_content_outline_order", None)
    return merged


# ---------------------------------------------------------------------------
# stage=content_outline: 官方式带物理页标签全文建树
# ---------------------------------------------------------------------------

_CONTENT_OUTLINE_INIT_PROMPT = """You are an expert in extracting hierarchical document structure.

Generate a navigation outline from the provided page text.

Rules:
1. The text contains physical page tags like <physical_index_12>. Use those tags as the start page evidence.
2. Extract meaningful sections and subsections in reading order.
3. Preserve original heading wording when visible; only fix obvious spacing issues.
4. Include meaningful front matter or introductory sections when they start before the first numbered chapter.
5. If the document starts with a prominent document/report/paper title, include it as the first top-level node.
6. Keep visible long headings complete when possible; do not shorten them unless only a shorter heading is visible.
7. Do not invent unsupported sections. If unsure, return fewer items.
8. Return a flat JSON list using structure numbers such as "1", "1.1", "1.2", "2".

Return JSON only:
{{
  "items": [
    {{"structure": "1", "title": "Section title", "physical_index": "<physical_index_1>"}}
  ]
}}

Document text:
{content}
"""


_CONTENT_OUTLINE_CONTINUE_PROMPT = """You are an expert in extracting hierarchical document structure.

Continue the previous outline using only the current page text.

Rules:
1. The text contains physical page tags like <physical_index_12>. Use those tags as the start page evidence.
2. Return only new sections/subsections that start in the current text.
3. Preserve original heading wording when visible; only fix obvious spacing issues.
4. Keep structure numbers consistent with the previous outline.
5. If a new group starts with a prominent document/report/paper title not present in the previous outline, include it as a top-level node.
6. Keep visible long headings complete when possible; do not shorten them unless only a shorter heading is visible.
7. Do not invent unsupported sections. If unsure, return fewer items.

Return JSON only:
{{
  "items": [
    {{"structure": "2", "title": "Next section", "physical_index": "<physical_index_12>"}}
  ]
}}

Previous outline JSON:
{previous}

Current page text:
{content}
"""


def _page_labeled_text(page: int, text: Any) -> str:
    value = _coerce_text(text)
    if len(value) > CONTENT_OUTLINE_PAGE_CHAR_LIMIT:
        value = value[:CONTENT_OUTLINE_PAGE_CHAR_LIMIT]
    return f"<physical_index_{page}>\n{value}\n</physical_index_{page}>"


def _build_page_labeled_groups(page_texts: List[str], *, physical_start_page: int = 1) -> List[str]:
    groups: List[str] = []
    current: List[str] = []
    current_tokens = 0
    for index, text in enumerate(page_texts, start=1):
        labeled = _page_labeled_text(physical_start_page + index - 1, text)
        if not labeled.strip():
            continue
        token_count = max(1, count_tokens(labeled))
        if current and current_tokens + token_count > CONTENT_OUTLINE_GROUP_TOKEN_LIMIT:
            groups.append("\n\n".join(current))
            current = []
            current_tokens = 0
        current.append(labeled)
        current_tokens += token_count
    if current:
        groups.append("\n\n".join(current))
    return groups


def _physical_index_to_int(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = _coerce_text(value)
    if not text:
        return 0
    marker = re.search(r"physical_index_(\d+)", text)
    if marker:
        return _coerce_int(marker.group(1), 0)
    page_marker = re.search(r"\bpage\s*(\d+)\b", text, flags=re.IGNORECASE)
    if page_marker:
        return _coerce_int(page_marker.group(1), 0)
    return _coerce_int(text, 0)


def _extract_outline_payload_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "toc_items", "outline", "structure", "chapters", "sections"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _structure_depth(structure: str) -> int:
    if not structure:
        return 1
    return structure.count(".") + 1


def _normalize_content_outline_items(
    payload: Any,
    *,
    min_page: int,
    max_page: int,
) -> List[Dict[str, Any]]:
    raw_items = _extract_outline_payload_items(payload)
    normalized: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, int]] = set()

    def append_item(item: Dict[str, Any], fallback_structure: str) -> None:
        title = _coerce_text(
            item.get("title")
            or item.get("heading")
            or item.get("name")
        )
        page = _physical_index_to_int(
            item.get("physical_index")
            or item.get("start_page")
            or item.get("start_index")
            or item.get("page")
        )
        if not title or page < min_page or page > max_page:
            return
        structure = _coerce_text(item.get("structure") or fallback_structure)
        if not structure:
            level = max(1, _coerce_int(item.get("level"), 1))
            structure = ".".join("1" for _ in range(level))
        key = (structure, _normalize_title_key(title), page)
        if key in seen:
            return
        seen.add(key)
        normalized.append(
            {
                "structure": structure,
                "title": title,
                "level": _structure_depth(structure),
                "physical_index": page,
                "source": "llm_content_outline",
            }
        )

    def walk(items: List[Dict[str, Any]], parent_structure: str = "") -> None:
        for index, item in enumerate(items, start=1):
            fallback_structure = (
                f"{parent_structure}.{index}" if parent_structure else str(index)
            )
            structure = _coerce_text(item.get("structure") or fallback_structure)
            append_item(item, structure)
            children = item.get("nodes") or item.get("children") or []
            if isinstance(children, list):
                walk([child for child in children if isinstance(child, dict)], structure)

    walk(raw_items)
    return normalized


def _dedupe_content_outline_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, int]] = set()
    for item in items:
        title = _coerce_text(item.get("title"))
        page = _physical_index_to_int(item.get("physical_index"))
        structure = _coerce_text(item.get("structure"))
        key = (structure, _normalize_title_key(title), page)
        if not title or page <= 0 or key in seen:
            continue
        seen.add(key)
        deduped.append(dict(item))
    return deduped


async def extract_page_labeled_content_outline(
    page_texts: List[str],
    model: Optional[str] = None,
    physical_start_page: int = 1,
) -> Optional[Dict[str, Any]]:
    """Build a full-document outline from page-tagged text.

    This mirrors the official PageIndex no-TOC path: each page is labeled with
    its 1-based physical PDF page and the model returns a flat structured list.
    """
    if not page_texts:
        return None

    physical_start_page = max(1, int(physical_start_page or 1))
    groups = _build_page_labeled_groups(page_texts, physical_start_page=physical_start_page)
    if not groups:
        return None

    page_count = len(page_texts)
    physical_end_page = physical_start_page + page_count - 1
    all_items: List[Dict[str, Any]] = []

    from pageindex.post_processing import assign_page_ranges, build_tree, normalize_tree_page_ranges
    from pageindex.utils import extract_json

    for group_index, group in enumerate(groups):
        if group_index == 0:
            prompt = _CONTENT_OUTLINE_INIT_PROMPT.format(content=group)
        else:
            previous = json.dumps(all_items[-80:], ensure_ascii=False, indent=2)
            prompt = _CONTENT_OUTLINE_CONTINUE_PROMPT.format(
                previous=previous,
                content=group,
            )
        response = await llm_acompletion(model, prompt)
        if not response:
            continue
        payload = extract_json(response)
        items = _normalize_content_outline_items(
            payload,
            min_page=physical_start_page,
            max_page=physical_end_page,
        )
        all_items.extend(items)

    flat_items = _dedupe_content_outline_items(all_items)
    if len(flat_items) < MIN_CONTENT_OUTLINE_ITEMS:
        return None
    flat_items = _merge_text_heading_facts(
        flat_items,
        page_texts=page_texts,
        physical_start_page=physical_start_page,
        physical_end_page=physical_end_page,
    )
    flat_items = _dedupe_content_outline_items(flat_items)

    ranged_items = assign_page_ranges([dict(item) for item in flat_items], physical_end_page)
    tree = build_tree(ranged_items)
    tree = normalize_tree_page_ranges(tree, physical_end_page)

    total_nodes = len(flat_items)
    root_count = len(tree)
    confidence = 0.62
    if total_nodes >= max(4, root_count + 2):
        confidence += 0.12
    if root_count >= 3:
        confidence += 0.08

    print(
        "[TOC-CANDIDATE] provider=hierarchical "
        f"stage=content_outline status=ok groups={len(groups)} items={total_nodes}"
    )
    return {
        "items": tree,
        "toc_items": tree,
        "flat_items": ranged_items,
        "structure": "hierarchical",
        "source": "hierarchical_content_outline",
        "confidence": min(confidence, 0.92),
        "stages": {
            "content_outline_groups": len(groups),
            "content_outline_items": total_nodes,
            "content_outline_roots": root_count,
        },
    }

# ---------------------------------------------------------------------------
# stage=framework: 提取一级框架
# ---------------------------------------------------------------------------

_FRAMEWORK_PROMPT = """You are a document structure analyst. Analyze the document excerpts below and extract all top-level chapter titles.

Requirements:
1. Extract only top-level chapters, meaning the largest structural units such as "Chapter 1" or "1. Introduction".
2. For each chapter, return the title and the starting physical page number.
3. Page numbers are 1-based physical PDF pages.
4. Do not omit appendices, references, or other top-level back matter.
5. If the document has front-matter sections such as Contents, Figure List, or Table List, include them only when they are top-level visible document sections.

Return JSON only:
{{
  "chapters": [
    {{"title": "Chapter title", "start_page": 1}}
  ]
}}

Document excerpts, up to the first 300 characters per page:
{content}
"""


async def extract_framework(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[List[Dict]]:
    """Extract the top-level framework for the hierarchical provider.

    Args:
        page_texts: 所有页面的文本列表（0-indexed）
        model: LLM模型名称

    Returns:
        章节列表，每项包含 title 和 start_page
        失败返回 None
    """
    if not page_texts:
        return None

    # 构建摘要：每页取前300字符
    summaries = []
    for i, text in enumerate(page_texts):
        summary = text[:300].replace('\n', ' ').strip()
        if summary:
            summaries.append(f"[Page {i+1}] {summary}")

    content = '\n'.join(summaries)

    # 如果内容太长，截断
    tokens = count_tokens(content)
    if tokens > MAX_TOKENS_FRAMEWORK:
        # 保留首尾，中间采样
        keep_pages = max(3, len(page_texts) // 10)
        head = summaries[:keep_pages]
        tail = summaries[-keep_pages:]
        # 中间每隔N页取一页
        step = max(1, (len(summaries) - 2 * keep_pages) // 20)
        middle = summaries[keep_pages:len(summaries)-keep_pages:step]
        content = '\n'.join(head + middle + tail)

    prompt = _FRAMEWORK_PROMPT.format(content=content)

    try:
        response = await llm_acompletion(model, prompt)
        if not response:
            return None

        # 解析JSON - 使用更健壮的extract_json
        from pageindex.utils import extract_json
        data = extract_json(response)
        if not data:
            print(f"[TOC-CANDIDATE] provider=hierarchical Failed to parse JSON from response")
            return None
        
        chapters = data.get("chapters", [])

        # 验证
        valid_chapters = []
        for ch in chapters:
            title = _coerce_text(ch.get("title"))
            start_page = _coerce_int(ch.get("start_page"), 0)
            if title and start_page > 0:
                valid_chapters.append({
                    "title": title,
                    "start_page": start_page,
                })

        if len(valid_chapters) >= 2:
            print(f"[TOC-CANDIDATE] provider=hierarchical stage=framework status=ok chapters={len(valid_chapters)}")
            return valid_chapters

    except Exception as e:
        print(f"[TOC-CANDIDATE] provider=hierarchical stage=framework status=error error={e}")

    return None


# ---------------------------------------------------------------------------
# stage=expand status=ok chapter= 逐章展开子章节
# ---------------------------------------------------------------------------

_EXPAND_PROMPT = """You are a document structure analyst. Extract subsection titles inside the chapter using only the provided page excerpts.

Chapter metadata:
- Title: {chapter_title}
- Start page: {start_page}
- End page: {end_page}

Requirements:
1. Extract all second-level, third-level, and deeper section headings under this chapter.
2. For each subsection, return title, hierarchy level (2, 3, 4, ...), and 1-based physical start page.
3. Keep original numbering when present, such as "1.1" or "(a)".
4. Titles must be concise headings, not paragraphs, table cells, or body text.
5. If unsure, return fewer items instead of guessing.
6. Ignore headers, footers, page numbers, table cells, and decorative text.
7. Do not return end pages.

Return JSON only:
{{
  "sub_chapters": [
    {{"title": "Subsection title", "level": 2, "page": 5}}
  ]
}}

Page excerpts JSON:
{content}
"""


def _normalize_title_key(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def _page_excerpt(text: Any, max_chars: int = CHAPTER_EXCERPT_CHARS) -> str:
    value = str(text or "").strip()
    return value[:max_chars]


def _chapter_excerpt_windows(
    start_page: int,
    end_page: int,
    page_texts: List[str],
) -> List[List[Dict[str, Any]]]:
    """Build page/excerpt windows for chapter expansion."""
    end_page = min(end_page, len(page_texts))
    if start_page < 1 or start_page > end_page:
        return []

    pages = list(range(start_page, end_page + 1))
    if len(pages) <= LONG_CHAPTER_WINDOW_THRESHOLD:
        return [_page_excerpt_items(pages, page_texts)]

    windows: List[List[Dict[str, Any]]] = []
    step = max(1, LONG_CHAPTER_WINDOW_SIZE - LONG_CHAPTER_WINDOW_OVERLAP)
    index = 0
    while index < len(pages):
        chunk = pages[index:index + LONG_CHAPTER_WINDOW_SIZE]
        if not chunk:
            break
        windows.append(_page_excerpt_items(chunk, page_texts))
        if chunk[-1] == pages[-1]:
            break
        index += step
    return windows


def _page_excerpt_items(pages: List[int], page_texts: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for page in pages:
        if 1 <= page <= len(page_texts):
            items.append(
                {
                    "page": page,
                    "excerpt": _page_excerpt(page_texts[page - 1]),
                }
            )
    return items


def _format_excerpt_window(window: List[Dict[str, Any]]) -> str:
    return json.dumps(window, ensure_ascii=False, indent=2)


def _valid_sub_chapters_from_response(
    response: str,
    *,
    chapter_title: str,
    start_page: int,
    end_page: int,
) -> List[Dict[str, Any]]:
    from pageindex.utils import extract_json

    data = extract_json(response)
    if not data:
        print(f"[TOC-CANDIDATE] provider=hierarchical Failed to parse JSON for '{chapter_title}'")
        return []

    valid: List[Dict[str, Any]] = []
    for sub in data.get("sub_chapters", []):
        if not isinstance(sub, dict):
            continue
        title = _coerce_text(sub.get("title"))
        level = max(2, _coerce_int(sub.get("level"), 2))
        page = _coerce_int(sub.get("page"), 0)

        if title and start_page <= page <= end_page:
            valid.append(
                {
                    "title": title,
                    "level": level,
                    "page": page,
                }
            )
    return valid


def _merge_window_sub_chapters(sub_chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in sorted(
        sub_chapters,
        key=lambda value: (
            _coerce_int(value.get("page"), 0),
            _normalize_title_key(value.get("title")),
        ),
    ):
        title = _coerce_text(item.get("title"))
        page = _coerce_int(item.get("page"), 0)
        key = (_normalize_title_key(title), page)
        if not title or page <= 0 or key in seen:
            continue
        seen.add(key)
        merged.append(
            {
                "title": title,
                "level": max(2, _coerce_int(item.get("level"), 2)),
                "page": page,
            }
        )
    return merged


async def expand_chapter(
    chapter_title: str,
    start_page: int,
    end_page: int,
    page_texts: List[str],
    model: Optional[str] = None,
) -> List[Dict]:
    """stage=expand status=ok chapter= 展开单个章节的子章节。

    Args:
        chapter_title: 章节标题
        start_page: 起始页码（1-indexed）
        end_page: 结束页码（1-indexed）
        page_texts: 所有页面文本
        model: LLM模型

    Returns:
        子章节列表
    """
    if start_page < 1 or start_page > len(page_texts):
        return []

    end_page = min(end_page, len(page_texts))

    windows = _chapter_excerpt_windows(start_page, end_page, page_texts)
    if not windows:
        return []

    valid: List[Dict[str, Any]] = []
    try:
        for window in windows:
            prompt = _EXPAND_PROMPT.format(
                chapter_title=chapter_title,
                start_page=start_page,
                end_page=end_page,
                content=_format_excerpt_window(window),
            )
            response = await llm_acompletion(model, prompt)
            if not response:
                continue
            valid.extend(
                _valid_sub_chapters_from_response(
                    response,
                    chapter_title=chapter_title,
                    start_page=start_page,
                    end_page=end_page,
                )
            )

        merged = _merge_window_sub_chapters(valid)
        print(f"[TOC-CANDIDATE] provider=hierarchical stage=expand status=ok chapter='{chapter_title}' sub_chapters={len(merged)}")
        return merged

    except Exception as e:
        print(f"[TOC-CANDIDATE] provider=hierarchical stage=expand status=error chapter='{chapter_title}' error={e}")

    return []


async def expand_all_chapters(
    chapters: List[Dict],
    page_texts: List[str],
    model: Optional[str] = None,
) -> Dict[int, List[Dict]]:
    """stage=expand status=ok chapter= 并发展开所有章节的子章节。

    Args:
        chapters: chapters extracted by the framework stage
        page_texts: 所有页面文本
        model: LLM模型

    Returns:
        {章节索引: 子章节列表}
    """
    if not chapters:
        return {}

    # 计算每个章节的结束页
    results = {}
    for i, ch in enumerate(chapters):
        start_page = ch["start_page"]
        if i + 1 < len(chapters):
            end_page = chapters[i + 1]["start_page"] - 1
        else:
            end_page = len(page_texts)

        # 确保最小页数
        if end_page - start_page + 1 < MIN_CHAPTER_PAGES:
            end_page = min(start_page + MIN_CHAPTER_PAGES - 1, len(page_texts))

        results[i] = {
            "title": ch["title"],
            "start_page": start_page,
            "end_page": end_page,
            "sub_chapters": [],
        }

    # 分批并发处理
    async def process_batch(batch_indices: List[int]) -> None:
        tasks = []
        for idx in batch_indices:
            info = results[idx]
            task = expand_chapter(
                info["title"],
                info["start_page"],
                info["end_page"],
                page_texts,
                model,
            )
            tasks.append((idx, task))

        # 并发执行
        coros = [t[1] for t in tasks]
        sub_results = await asyncio.gather(*coros, return_exceptions=True)

        for (idx, _), sub_chapters in zip(tasks, sub_results):
            if isinstance(sub_chapters, list):
                results[idx]["sub_chapters"] = sub_chapters

    # 按批次处理
    indices = list(results.keys())
    for i in range(0, len(indices), CHAPTER_BATCH_SIZE):
        batch = indices[i:i + CHAPTER_BATCH_SIZE]
        await process_batch(batch)

    # 转换为返回格式
    return {idx: results[idx]["sub_chapters"] for idx in results}


# ---------------------------------------------------------------------------
# stage=merge: 合并结果
# ---------------------------------------------------------------------------

def merge_results(
    chapters: List[Dict],
    sub_chapters_map: Dict[int, List[Dict]],
) -> List[Dict]:
    """Merge top-level chapters and expanded children into a TOC tree.

    Args:
        chapters: chapters extracted by the framework stage
        sub_chapters_map: child chapters from the expand stage

    Returns:
        完整的目录树结构
    """
    if not chapters:
        return []

    result = []

    for i, ch in enumerate(chapters):
        # 一级章节节点
        chapter_node = {
            "title": ch["title"],
            "structure": str(i + 1),
            "physical_index": ch["start_page"],
            "nodes": [],
        }

        # 添加子章节
        subs = sub_chapters_map.get(i, [])
        if subs:
            # 构建子章节树
            sub_tree = _build_sub_tree(subs, str(i + 1))
            chapter_node["nodes"] = sub_tree

        result.append(chapter_node)

    return result


def _build_sub_tree(sub_chapters: List[Dict], parent_structure: str) -> List[Dict]:
    """根据子章节的 level 构建树形结构。

    Args:
        sub_chapters: 子章节列表，每项包含 title, level, page
        parent_structure: 父章节的structure编号（如 "1"）

    Returns:
        子章节树
    """
    if not sub_chapters:
        return []

    # 按页码排序
    sub_chapters = sorted(sub_chapters, key=lambda x: _coerce_int(x.get("page"), 0))

    parent_prefix = _coerce_text(parent_structure)
    result = []
    stack = []  # (level, node)

    # 子章节计数器
    level_counters: Dict[int, int] = {}
    seen_numbered_nodes: Dict[Tuple[int, str], Dict[str, Any]] = {}

    for sub in sub_chapters:
        level = max(2, _coerce_int(sub.get("level"), 2))
        title = _coerce_text(sub.get("title"))
        page = _coerce_int(sub.get("page"), 0)

        if not title or page <= 0:
            continue

        numbering_key = _explicit_numbering_key(title)
        if numbering_key:
            duplicate_node = seen_numbered_nodes.get((level, numbering_key))
            if duplicate_node is not None:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, duplicate_node))
                continue

        # 生成structure
        level_counters[level] = level_counters.get(level, 0) + 1
        # 重置更深级别的计数器
        for l in list(level_counters.keys()):
            if l > level:
                del level_counters[l]

        # 构建structure路径
        parts = [parent_prefix] if parent_prefix else []
        for l in sorted(level_counters.keys()):
            if l >= 2:
                parts.append(str(level_counters[l]))
        structure = '.'.join(str(part) for part in parts if str(part))

        node = {
            "title": title,
            "structure": structure,
            "physical_index": page,
            "nodes": [],
        }
        if numbering_key:
            seen_numbered_nodes[(level, numbering_key)] = node

        # 找到父节点
        if level <= 2:
            # 二级章节，直接挂到一级下
            result.append(node)
            stack = [(level, node)]
        else:
            # 找合适的父节点
            parent_found = False
            for parent_level, parent_node in reversed(stack):
                if parent_level < level:
                    parent_node.setdefault("nodes", []).append(node)
                    parent_found = True
                    break

            if not parent_found:
                result.append(node)

            # 更新栈
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, node))

    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def extract_hierarchical_toc(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """分层提取主入口。

    Runs the hierarchical provider framework -> expand -> merge flow.

    Args:
        page_texts: 所有页面的文本列表
        model: LLM模型名称

    Returns:
        {
            "items": List[Dict],      # 完整目录树
            "structure": "hierarchical",
            "source": "hierarchical",
            "confidence": float,
            "stages": {
                "framework_chapters": int,
                "expanded_chapters": int,
                "total_sub_chapters": int,
            }
        }
    """
    print("[TOC-CANDIDATE] provider=hierarchical stage=content_outline status=started")
    try:
        content_outline = await extract_page_labeled_content_outline(page_texts, model)
    except Exception as exc:
        print(
            "[TOC-CANDIDATE] provider=hierarchical "
            f"stage=content_outline status=error error={type(exc).__name__}"
        )
        content_outline = None
    if content_outline:
        return content_outline

    print("[TOC-CANDIDATE] provider=hierarchical stage=framework status=started")

    # stage=framework
    chapters = await extract_framework(page_texts, model)
    if not chapters:
        print("[TOC-CANDIDATE] provider=hierarchical stage=framework status=error action=abort")
        return None

    print(f"[TOC-CANDIDATE] provider=hierarchical stage=framework status=done chapters={len(chapters)}")

    # stage=expand
    print("[TOC-CANDIDATE] provider=hierarchical stage=expand status=started")
    sub_chapters_map = await expand_all_chapters(chapters, page_texts, model)

    total_subs = sum(len(subs) for subs in sub_chapters_map.values())
    expanded_count = sum(1 for subs in sub_chapters_map.values() if subs)
    print(f"[TOC-CANDIDATE] provider=hierarchical stage=expand status=done expanded={expanded_count}/{len(chapters)} sub_chapters={total_subs}")

    # stage=merge
    print("[TOC-CANDIDATE] provider=hierarchical stage=merge status=started")
    tree = merge_results(chapters, sub_chapters_map)

    # 计算置信度
    confidence = 0.5
    if len(chapters) >= 3:
        confidence += 0.2
    if expanded_count >= len(chapters) * 0.5:
        confidence += 0.2
    if total_subs >= len(chapters):
        confidence += 0.1

    return {
        "items": tree,
        "structure": "hierarchical",
        "source": "hierarchical",
        "confidence": min(confidence, 1.0),
        "stages": {
            "framework_chapters": len(chapters),
            "expanded_chapters": expanded_count,
            "total_sub_chapters": total_subs,
        },
    }
