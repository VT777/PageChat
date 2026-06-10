"""Central page mapping helpers for balanced TOC skeletons."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

from pageindex.contracts import make_mapped_outline


def map_skeleton_pages(
    skeleton: Dict[str, Any],
    page_texts: List[str],
    page_count: int,
) -> Dict[str, Any]:
    items = deepcopy(skeleton.get("items") or [])
    source = skeleton.get("source") or "toc_skeleton"

    if skeleton.get("page_mapping_valid") and _has_monotonic_pages(items, page_count):
        _assign_ranges(items, page_count)
        return make_mapped_outline(
            source=source,
            items=items,
            mapping_strategy="existing",
            mapping_quality=1.0,
        )

    matched = _map_by_title_search(items, page_texts, page_count, skeleton.get("toc_pages") or [])
    if matched:
        quality = matched / max(1, len(items))
        if quality >= 0.5:
            _fill_missing_pages(items, page_count, skeleton.get("toc_pages") or [])
            _assign_ranges(items, page_count)
            return make_mapped_outline(
                source=source,
                items=items,
                mapping_strategy="title_search",
                mapping_quality=quality,
            )

    _map_uniform_after_toc(items, page_count, skeleton.get("toc_pages") or [])
    _assign_ranges(items, page_count)
    return make_mapped_outline(
        source=source,
        items=items,
        mapping_strategy="uniform_after_toc",
        mapping_quality=0.35 if items else 0.0,
    )


def _has_monotonic_pages(items: List[Dict[str, Any]], page_count: int) -> bool:
    pages = [_page_value(item) for item in items]
    if not pages or any(page is None for page in pages):
        return False
    clean_pages = [page for page in pages if page is not None]
    return all(1 <= page <= page_count for page in clean_pages) and all(
        clean_pages[i] <= clean_pages[i + 1]
        for i in range(len(clean_pages) - 1)
    )


def _map_by_title_search(
    items: List[Dict[str, Any]],
    page_texts: List[str],
    page_count: int,
    toc_pages: List[int],
) -> int:
    start_page = max(toc_pages or [0]) + 1
    matched = 0
    cursor = max(1, start_page)
    normalized_pages = [
        _normalize_text(text)
        for text in page_texts[:page_count]
    ]

    for item in items:
        title = _normalize_text(str(item.get("title", "")))
        if len(title) < 4:
            continue
        found = _find_title_page(title, normalized_pages, cursor, page_count)
        if found is None:
            continue
        item["physical_index"] = found
        cursor = found
        matched += 1
    return matched


def _find_title_page(
    normalized_title: str,
    normalized_pages: List[str],
    start_page: int,
    page_count: int,
) -> Optional[int]:
    title_head = normalized_title[:80]
    for page in range(max(1, start_page), page_count + 1):
        page_text = normalized_pages[page - 1] if page - 1 < len(normalized_pages) else ""
        if title_head and title_head in page_text:
            return page
    return None


def _fill_missing_pages(items: List[Dict[str, Any]], page_count: int, toc_pages: List[int]) -> None:
    if not items:
        return
    _map_uniform_after_toc(
        [item for item in items if _page_value(item) is None],
        page_count,
        toc_pages,
    )
    last_page = max(toc_pages or [0]) + 1
    for item in items:
        page = _page_value(item)
        if page is None or page < last_page:
            item["physical_index"] = last_page
        last_page = item["physical_index"]


def _map_uniform_after_toc(items: List[Dict[str, Any]], page_count: int, toc_pages: List[int]) -> None:
    if not items:
        return
    start = max(toc_pages or [0]) + 1
    start = max(1, min(start, page_count))
    span = max(1, page_count - start + 1)
    step = max(1, span // len(items))
    for index, item in enumerate(items):
        item["physical_index"] = min(page_count, start + index * step)


def _assign_ranges(items: List[Dict[str, Any]], page_count: int) -> None:
    sorted_items = sorted(
        items,
        key=lambda item: (_page_value(item) or page_count + 1, item.get("level", 1)),
    )
    for index, item in enumerate(sorted_items):
        start = _page_value(item) or 1
        item["start_index"] = start
        next_page = None
        for later in sorted_items[index + 1:]:
            later_page = _page_value(later)
            if later_page and later_page >= start:
                next_page = later_page
                break
        item["end_index"] = max(start, (next_page - 1) if next_page else page_count)


def _page_value(item: Dict[str, Any]) -> Optional[int]:
    value = item.get("physical_index") or item.get("start_index") or item.get("page")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())
