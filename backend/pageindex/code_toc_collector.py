"""Collect low-cost PDF TOC signals without choosing a final route."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import pymupdf

from pageindex.catalog_classifier import (
    CATALOG_FIGURE,
    CATALOG_MAIN,
    CATALOG_TABLE,
    catalog_group_title,
    detect_catalog_type,
)


SECTION_KIND_BY_CATALOG = {
    CATALOG_MAIN: "main_toc",
    CATALOG_TABLE: "table_toc",
    CATALOG_FIGURE: "figure_toc",
}


def collect_code_toc(
    doc: pymupdf.Document,
    *,
    page_texts: Optional[List[str]] = None,
    max_scan_pages: int = 30,
) -> Dict[str, Any]:
    """Collect bookmarks, TOC links, and regex evidence into one report."""

    bookmarks = _collect_bookmarks(doc)
    links = _collect_links(doc, page_texts=page_texts, max_scan_pages=max_scan_pages)
    regex = _empty_source("regex")

    sections = _merge_sections(bookmarks["items"], links["items"])
    main_section = next((section for section in sections if section.get("kind") == "main_toc"), None)
    merged_items: List[Dict[str, Any]] = list((main_section or {}).get("items") or [])

    source_parts = []
    if bookmarks["items"]:
        source_parts.append("bookmarks")
    if links["items"]:
        source_parts.append("links")
    if regex["items"]:
        source_parts.append("regex")
    source = "+".join(source_parts) if source_parts else None

    quality_flags: List[str] = []
    if bookmarks.get("weak_slide_export_outline"):
        quality_flags.append("weak_slide_export_outline")

    return {
        "source": source,
        "items": merged_items,
        "toc_sections": sections,
        "sources": {
            "bookmarks": bookmarks,
            "links": links,
            "regex": regex,
        },
        "quality_flags": quality_flags,
    }


def _collect_bookmarks(doc: pymupdf.Document) -> Dict[str, Any]:
    raw = doc.get_toc(simple=True) or []
    raw_items = []
    cleaned_items = []
    for row in raw:
        if len(row) < 3:
            continue
        level, title, page = row[:3]
        clean = _clean_title(title)
        if not clean:
            continue
        raw_item = {
            "level": _positive_int(level) or 1,
            "title": clean,
            "physical_index": max(1, _positive_int(page) or 1),
            "source": "bookmarks",
        }
        raw_items.append(raw_item)
        normalized_title = _clean_slide_export_title(clean)
        if not normalized_title:
            continue
        cleaned_items.append(
            {
                "level": _positive_int(level) or 1,
                "title": normalized_title,
                "physical_index": max(1, _positive_int(page) or 1),
                "source": "bookmarks",
            }
        )

    slide_noise = sum(1 for item in raw_items if _is_slide_export_title(item["title"]))
    items = _levels_to_structure(cleaned_items)
    weak_slide = bool(slide_noise >= 3 or (raw_items and slide_noise / len(raw_items) >= 0.35))
    return {
        "source": "bookmarks",
        "status": "found" if items else "not_found",
        "count": len(items),
        "raw_count": len(raw),
        "slide_export_noise_count": slide_noise,
        "weak_slide_export_outline": weak_slide,
        "sample_titles": [item["title"] for item in items[:8]],
        "items": items,
    }


def _collect_links(
    doc: pymupdf.Document,
    *,
    page_texts: Optional[List[str]],
    max_scan_pages: int,
) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    toc_pages: List[int] = []
    found_toc_page = False

    for page_index in range(min(max_scan_pages, len(doc))):
        page = doc[page_index]
        internal_links = [
            link
            for link in page.get_links()
            if link.get("kind") == pymupdf.LINK_GOTO and _positive_int(link.get("page")) is not None
        ]
        if len(internal_links) < 5:
            if found_toc_page:
                break
            continue

        found_toc_page = True
        physical_toc_page = page_index + 1
        toc_pages.append(physical_toc_page)
        page_catalog = _page_catalog_type(
            page_texts[page_index] if page_texts and page_index < len(page_texts) else page.get_text() or ""
        )
        internal_links.sort(key=lambda link: (link["from"].y0, link["from"].x0))

        for link in internal_links:
            rect = pymupdf.Rect(link["from"])
            title = page.get_text("text", clip=rect).strip().replace("\n", " ")
            clean = _clean_link_title(title)
            dest_page = int(link.get("page") or 0) + 1
            if not clean or _is_bare_page_number(clean) or dest_page <= 0:
                continue
            catalog_type = detect_catalog_type({"title": clean, "catalog_type": page_catalog})
            entries.append(
                {
                    "title": clean,
                    "physical_index": dest_page,
                    "source": "links",
                    "source_toc_page": physical_toc_page,
                    "catalog_type": catalog_type,
                }
            )

    deduped = _dedupe_adjacent(entries)
    structured = _infer_structure_from_titles(deduped)
    return {
        "source": "links",
        "status": "found" if structured else "not_found",
        "count": len(structured),
        "toc_pages": toc_pages,
        "sample_titles": [item["title"] for item in structured[:8]],
        "items": structured,
    }


def _merge_sections(bookmark_items: List[Dict[str, Any]], link_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {
        CATALOG_MAIN: [],
        CATALOG_TABLE: [],
        CATALOG_FIGURE: [],
    }

    for item in bookmark_items:
        catalog_type = detect_catalog_type(item)
        if catalog_type == CATALOG_MAIN:
            grouped[CATALOG_MAIN].append(dict(item, catalog_type=CATALOG_MAIN))

    link_groups: Dict[str, List[Dict[str, Any]]] = {
        CATALOG_MAIN: [],
        CATALOG_TABLE: [],
        CATALOG_FIGURE: [],
    }
    for item in link_items:
        catalog_type = detect_catalog_type(item)
        link_groups.setdefault(catalog_type, []).append(dict(item, catalog_type=catalog_type))

    if grouped[CATALOG_MAIN] and link_groups[CATALOG_MAIN]:
        bookmark_noise = _section_noise_ratio(grouped[CATALOG_MAIN])
        link_noise = _section_noise_ratio(link_groups[CATALOG_MAIN])
        if bookmark_noise > 0.20 and link_noise <= 0.05 and len(link_groups[CATALOG_MAIN]) >= 3:
            grouped[CATALOG_MAIN] = link_groups[CATALOG_MAIN]
    elif not grouped[CATALOG_MAIN] and link_groups[CATALOG_MAIN]:
        grouped[CATALOG_MAIN] = link_groups[CATALOG_MAIN]
    grouped[CATALOG_TABLE] = link_groups[CATALOG_TABLE]
    grouped[CATALOG_FIGURE] = link_groups[CATALOG_FIGURE]

    sections = []
    for catalog_type in (CATALOG_MAIN, CATALOG_TABLE, CATALOG_FIGURE):
        items = grouped.get(catalog_type) or []
        if not items:
            continue
        sections.append(
            {
                "kind": SECTION_KIND_BY_CATALOG[catalog_type],
                "title": catalog_group_title(catalog_type),
                "source": _section_source(items),
                "items": items,
            }
        )
    return sections


def _section_source(items: List[Dict[str, Any]]) -> str:
    parts = []
    for item in items:
        source = str(item.get("source") or "").strip()
        if source and source not in parts:
            parts.append(source)
    return "+".join(parts) if parts else "code_toc"


def _empty_source(source: str) -> Dict[str, Any]:
    return {
        "source": source,
        "status": "not_found",
        "count": 0,
        "items": [],
        "sample_titles": [],
    }


def _page_catalog_type(text: str) -> str:
    compact = re.sub(r"\s+", "", str(text or "").lower())
    if any(marker in compact for marker in ("图目录", "插图目录", "listoffigures", "figurecatalog")):
        return CATALOG_FIGURE
    if any(marker in compact for marker in ("表目录", "表格目录", "listoftables", "tablecatalog")):
        return CATALOG_TABLE
    return CATALOG_MAIN


def _clean_title(title: Any) -> str:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    text = re.sub(r"[\s:：.…·\u00b7\u2026]+$", "", text)
    return text.strip()


def _clean_link_title(title: Any) -> str:
    text = _clean_title(title)
    text = re.sub(r"[.…·\s\u00b7\u2026]+\d{1,4}\s*$", "", text)
    return _clean_title(text)


def _is_bare_page_number(title: str) -> bool:
    return bool(re.fullmatch(r"\d{1,4}", re.sub(r"\s+", "", str(title or ""))))


def _section_noise_ratio(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 1.0
    noisy = 0
    for item in items:
        title = str(item.get("title") or "").strip()
        compact = re.sub(r"\s+", "", title)
        if (
            not title
            or _is_bare_page_number(title)
            or re.fullmatch(r"\d{4}(?:[./年-]\d{1,2})?(?:月)?", compact)
            or compact in {"序号", "发布时间", "发布主体", "政策名称", "标准名称", "文件名称"}
        ):
            noisy += 1
    return noisy / len(items)


def _is_slide_export_title(title: str) -> bool:
    value = str(title or "").strip().lower()
    return bool(
        value == "默认节"
        or value == "default section"
        or value.startswith("幻灯片")
        or value.startswith("slide ")
        or value.startswith("page ")
    )


def _clean_slide_export_title(title: str) -> str:
    value = _clean_title(title)
    lowered = value.lower()
    if lowered in {"默认节", "default section"}:
        return ""
    cleaned = re.sub(r"^\s*幻灯片\s*\d+\s*[:：-]?\s*", "", value)
    cleaned = re.sub(r"^\s*slide\s*\d+\s*[:：-]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*page\s*\d+\s*[:：-]?\s*", "", cleaned, flags=re.IGNORECASE)
    return _clean_title(cleaned)


def _levels_to_structure(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counters: Dict[int, int] = {}
    result = []
    for item in items:
        level = _positive_int(item.get("level")) or 1
        for key in list(counters.keys()):
            if key > level:
                del counters[key]
        counters[level] = counters.get(level, 0) + 1
        parts = [str(counters[key]) for key in sorted(counters) if key <= level]
        result.append(
            {
                "structure": ".".join(parts),
                "level": level,
                "title": item["title"],
                "physical_index": item["physical_index"],
                "source": item.get("source") or "bookmarks",
                "catalog_type": detect_catalog_type(item),
            }
        )
    return result


def _infer_structure_from_titles(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counters: Dict[str, int] = {}
    result = []
    current_main_structure: Optional[str] = None
    current_main_allows_chinese_children = False
    child_counters: Dict[str, int] = {}
    for item in items:
        title = str(item.get("title") or "").strip()
        catalog_type = detect_catalog_type(item)
        number = _leading_structure(title)
        chapter_number = _leading_chapter_number(title) if catalog_type == CATALOG_MAIN else None
        section_marker = _leading_chinese_section_marker(title) if catalog_type == CATALOG_MAIN else None
        if number:
            structure = number
            clean_title = re.sub(rf"^\s*{re.escape(number)}(?:[.．、\s]+)?", "", title).strip() or title
            if "." not in structure:
                current_main_structure = structure
                current_main_allows_chinese_children = True
                child_counters.setdefault(current_main_structure, 0)
            else:
                current_main_structure = structure.split(".", 1)[0]
                current_main_allows_chinese_children = True
        elif chapter_number is not None:
            structure = str(chapter_number)
            current_main_structure = structure
            current_main_allows_chinese_children = True
            child_counters[current_main_structure] = 0
            clean_title = title
        elif section_marker and current_main_structure and current_main_allows_chinese_children:
            child_counters[current_main_structure] = child_counters.get(current_main_structure, 0) + 1
            structure = f"{current_main_structure}.{child_counters[current_main_structure]}"
            clean_title = title
        elif catalog_type in {CATALOG_FIGURE, CATALOG_TABLE}:
            key = catalog_type
            counters[key] = counters.get(key, 0) + 1
            structure = str(counters[key])
            clean_title = title
        else:
            counters[CATALOG_MAIN] = counters.get(CATALOG_MAIN, 0) + 1
            structure = str(counters[CATALOG_MAIN])
            current_main_structure = structure if catalog_type == CATALOG_MAIN else current_main_structure
            if catalog_type == CATALOG_MAIN:
                current_main_allows_chinese_children = False
                child_counters.setdefault(current_main_structure, 0)
            clean_title = title
        result.append({**item, "structure": structure, "title": clean_title, "catalog_type": catalog_type})
    return result


def _leading_structure(title: str) -> Optional[str]:
    match = re.match(r"^\s*(\d+(?:\.\d+){0,4})(?:\s+|[.．、])", title)
    if match:
        return match.group(1)
    return None


def _leading_chapter_number(title: str) -> Optional[int]:
    match = re.match(r"^\s*第\s*([一二三四五六七八九十百零〇两\d]+)\s*[章节篇部分部]", title)
    if not match:
        return None
    return _parse_chinese_or_int(match.group(1))


def _leading_chinese_section_marker(title: str) -> Optional[int]:
    match = re.match(r"^\s*([一二三四五六七八九十百零〇两\d]{1,4})\s*[、.．]\s*\S+", title)
    if not match:
        return None
    return _parse_chinese_or_int(match.group(1))


def _parse_chinese_or_int(value: str) -> Optional[int]:
    text = re.sub(r"\s+", "", str(value or ""))
    if not text:
        return None
    if text.isdigit():
        parsed = int(text)
        return parsed if parsed > 0 else None
    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if text == "十":
        return 10
    if "百" in text:
        left, _, right = text.partition("百")
        hundreds = digit_map.get(left, 1 if not left else 0)
        tail = _parse_chinese_or_int(right) if right else 0
        return hundreds * 100 + (tail or 0)
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digit_map.get(left, 1 if not left else 0)
        ones = digit_map.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(text) == 1:
        return digit_map.get(text)
    return None


def _dedupe_adjacent(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    for item in items:
        if deduped and item.get("title") == deduped[-1].get("title") and item.get("physical_index") == deduped[-1].get("physical_index"):
            continue
        deduped.append(item)
    return deduped


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
