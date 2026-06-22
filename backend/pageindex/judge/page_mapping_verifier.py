"""Lightweight page mapping checks for TOC candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from pageindex.catalog_classifier import CATALOG_MAIN, detect_catalog_type


OCR_LOGICAL_PAGE_SOURCES = {
    "llm_toc_page",
}


class PageMappingVerifier:
    def verify(self, candidate: Dict[str, Any], page_count: int | None = None) -> Dict[str, Any]:
        all_items = candidate.get("items") or []
        items = _main_items_for_verification(all_items)
        evidence = candidate.get("evidence") or {}
        source = str(candidate.get("source") or "")
        physical_pages = [
            item.get("physical_index")
            for item in items
            if isinstance(item.get("physical_index"), int)
            and not isinstance(item.get("physical_index"), bool)
        ]
        logical_pages = [
            item.get("logical_page") or item.get("page")
            for item in items
            if isinstance(item.get("logical_page") or item.get("page"), int)
            and not isinstance(item.get("logical_page") or item.get("page"), bool)
        ]
        has_explicit_physical = bool(physical_pages)
        mapping_pending = bool(evidence.get("mapping_pending")) and not has_explicit_physical
        logical_only_ocr = source in OCR_LOGICAL_PAGE_SOURCES and not has_explicit_physical
        if mapping_pending or logical_only_ocr:
            monotonic = all(left <= right for left, right in zip(logical_pages, logical_pages[1:]))
            score = min(_bounded_score(evidence.get("page_mapping_score"), default=0.45), 0.45)
            return {
                "page_monotonic": monotonic,
                "pages_in_range": True,
                "mapped_ratio": 0.0,
                "has_explicit_physical": False,
                "page_mapping_score": round(score, 4),
            }

        pages = physical_pages or logical_pages
        monotonic = all(left <= right for left, right in zip(pages, pages[1:]))
        in_range = True
        if page_count:
            in_range = all(1 <= page <= page_count for page in pages)
        mapped_ratio = len(pages) / len(items) if items else 0.0
        score = mapped_ratio
        if not monotonic:
            score *= 0.6
        if not in_range:
            score *= 0.6
        unique_pages = len(set(pages))
        page_collapse = bool(len(pages) >= 8 and unique_pages <= max(1, len(pages) // 4))
        if page_collapse:
            score = min(score, 0.35)
        return {
            "page_monotonic": monotonic,
            "pages_in_range": in_range,
            "mapped_ratio": mapped_ratio,
            "verified_item_count": len(items),
            "total_item_count": len(all_items),
            "has_explicit_physical": has_explicit_physical,
            "page_collapse": page_collapse,
            "page_mapping_score": round(score, 4),
        }


def _bounded_score(value: Any, *, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return max(0.0, min(1.0, score))


def _main_items_for_verification(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    main_items = [
        item
        for item in items
        if isinstance(item, dict) and detect_catalog_type(item) == CATALOG_MAIN
    ]
    return main_items or [item for item in items if isinstance(item, dict)]


def map_toc_physical_pages(
    toc_items: List[Dict[str, Any]],
    page_count: int,
    first_content_page: Optional[int],
    last_toc_page: int,
    ocr_text_map: Optional[Dict[int, str]] = None,
    dividers: Optional[List[int]] = None,
) -> None:
    """Map TOC logical page numbers to PDF physical pages.

    It keeps logical TOC page values in ``page`` and writes verified/estimated
    PDF pages to ``physical_index``.
    """
    if not toc_items or page_count <= 0:
        return

    _normalize_mislabeled_logical_pages(toc_items, page_count)
    items_with_page = [
        item
        for item in toc_items
        if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool)
    ]
    effective_first = first_content_page or (last_toc_page + 1) or 1
    effective_first = max(1, min(page_count, effective_first))

    if not items_with_page:
        if dividers:
            top_items = [
                item
                for item in toc_items
                if "." not in str(item.get("structure", ""))
            ]
            if len(top_items) == len(dividers):
                for item, page in zip(top_items, dividers):
                    item["physical_index"] = max(1, min(page_count, int(page)))
                _inherit_missing_physical_pages(toc_items, page_count, effective_first)
                return
        _map_uniformly(toc_items, page_count, effective_first)
        _inherit_missing_physical_pages(toc_items, page_count, effective_first)
        _ensure_monotonic_physical(toc_items, page_count)
        return

    first_logical = int(items_with_page[0]["page"])
    last_logical = max(int(item["page"]) for item in items_with_page)
    offset = effective_first - first_logical

    if ocr_text_map:
        first_title = str(items_with_page[0].get("title") or "")[:15]
        if len(first_title) >= 3:
            for phys_page in sorted(ocr_text_map.keys()):
                if phys_page <= last_toc_page:
                    continue
                if first_title in str(ocr_text_map.get(phys_page) or ""):
                    offset = phys_page - first_logical
                    break

    estimated_last = last_logical + offset
    if estimated_last <= page_count * 1.2:
        for item in items_with_page:
            item["physical_index"] = max(1, min(page_count, int(item["page"]) + offset))
    else:
        logical_pages = [int(item["page"]) for item in items_with_page]
        diffs = [
            logical_pages[index + 1] - logical_pages[index]
            for index in range(len(logical_pages) - 1)
        ]
        most_common_diff = 0
        diff_ratio = 0.0
        if diffs:
            most_common_diff, count = Counter(diffs).most_common(1)[0]
            diff_ratio = count / len(diffs)

        if most_common_diff > 1 and diff_ratio >= 0.8 and len(diffs) >= 3:
            for index, item in enumerate(items_with_page):
                item["physical_index"] = min(page_count, effective_first + index)
        else:
            logical_range = max(1, last_logical - first_logical)
            physical_range = max(1, page_count - effective_first + 1)
            scale = physical_range / logical_range
            for item in items_with_page:
                physical = effective_first + (int(item["page"]) - first_logical) * scale
                item["physical_index"] = max(1, min(page_count, round(physical)))

    _inherit_missing_physical_pages(toc_items, page_count, effective_first)
    _ensure_monotonic_physical(toc_items, page_count)


def _normalize_mislabeled_logical_pages(
    toc_items: List[Dict[str, Any]],
    page_count: int,
) -> None:
    physical_values = [
        item.get("physical_index")
        for item in toc_items
        if isinstance(item.get("physical_index"), int)
        and not isinstance(item.get("physical_index"), bool)
    ]
    if not physical_values:
        return
    page_values = [
        item.get("page")
        for item in toc_items
        if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool)
    ]
    if page_values:
        return
    diffs = [
        physical_values[index + 1] - physical_values[index]
        for index in range(len(physical_values) - 1)
    ]
    likely_logical = max(physical_values) > page_count
    if diffs:
        step, count = Counter(diffs).most_common(1)[0]
        likely_logical = likely_logical or (step > 1 and count / len(diffs) >= 0.6)
    if not likely_logical:
        return
    for item in toc_items:
        value = item.get("physical_index")
        if isinstance(value, int) and not isinstance(value, bool):
            item["page"] = value
            item.pop("physical_index", None)


def _inherit_missing_physical_pages(
    toc_items: List[Dict[str, Any]],
    page_count: int,
    default_page: int,
) -> None:
    previous_page: Optional[int] = None
    for index, item in enumerate(toc_items):
        current = item.get("physical_index")
        if isinstance(current, int) and not isinstance(current, bool) and current > 0:
            item["physical_index"] = max(1, min(page_count, current))
            previous_page = item["physical_index"]
            continue

        next_page = None
        for following in toc_items[index + 1:]:
            candidate = following.get("physical_index")
            if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                next_page = max(1, min(page_count, candidate))
                break
        inherited = next_page or previous_page or default_page
        item["physical_index"] = max(1, min(page_count, inherited))
        previous_page = item["physical_index"]


def _map_uniformly(
    toc_items: List[Dict[str, Any]],
    page_count: int,
    first_content_page: int,
) -> None:
    available = max(1, page_count - first_content_page + 1)
    count = len(toc_items)
    if count <= 0:
        return
    for index, item in enumerate(toc_items):
        if item.get("physical_index") is not None:
            continue
        physical = first_content_page + index * available / count
        item["physical_index"] = max(1, min(page_count, round(physical)))


def _ensure_monotonic_physical(
    toc_items: List[Dict[str, Any]],
    page_count: int,
) -> None:
    last_page = 1
    for item in toc_items:
        current = item.get("physical_index")
        if not isinstance(current, int) or isinstance(current, bool):
            current = last_page
        current = max(last_page, min(page_count, current))
        item["physical_index"] = current
        last_page = current
