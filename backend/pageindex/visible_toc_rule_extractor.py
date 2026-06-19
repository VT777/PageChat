"""High-confidence visible TOC extraction from already prepared page text.

The extractor is intentionally conservative: it only accepts standard catalog
lines with an explicit trailing number, then lets content mapping validate
whether that number can be used as a printed page number.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pageindex.catalog_classifier import (
    CATALOG_FIGURE,
    CATALOG_MAIN,
    CATALOG_TABLE,
    catalog_group_title,
)
from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages


SECTION_TO_CATALOG = {
    "main_toc": CATALOG_MAIN,
    "figure_toc": CATALOG_FIGURE,
    "table_toc": CATALOG_TABLE,
}

CATALOG_TO_SECTION = {value: key for key, value in SECTION_TO_CATALOG.items()}

_LINE_WITH_PAGE_RE = re.compile(
    r"^(?P<title>.+?)(?:\.{2,}|…{1,}|·{2,}|\s{2,}|\s+)(?P<page>\d{1,4})$"
)
_LINE_WITH_LEADER_NO_PAGE_RE = re.compile(
    r"^(?P<title>.+?)(?:\.{3,}|…{2,}|·{3,})\s*$"
)

_MAIN_HEADING_RE = re.compile(r"^(?:目录|目次|contents|table of contents)$", re.I)
_FIGURE_HEADING_RE = re.compile(
    r"^(?:图目录|插图目录|图表目录|list of figures|figure catalog|figures)$",
    re.I,
)
_TABLE_HEADING_RE = re.compile(
    r"^(?:表目录|表格目录|list of tables|table catalog|tables)$",
    re.I,
)
_FIGURE_ITEM_RE = re.compile(r"^(?:图|figure|fig\.?)\s*[\dIVXivx一二三四五六七八九十]+")
_TABLE_ITEM_RE = re.compile(r"^(?:表|table|tab\.?)\s*[\dIVXivx一二三四五六七八九十]+")
_MAIN_ITEM_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百\d]+[章节篇部分]"
    r"|[一二三四五六七八九十]+[、.]"
    r"|(?:part|chapter|section)\s*\d+"
    r"|\d+(?:\.\d+){0,3}"
    r")",
    re.I,
)


def extract_visible_toc_with_pages(
    page_texts: List[str],
    *,
    toc_pages: List[int],
    page_count: int,
    min_items: int = 3,
) -> Optional[Dict[str, Any]]:
    """Extract a typed, mapped TOC from standard visible TOC pages.

    Returns ``None`` when the text is not a high-confidence paged TOC. Callers
    should then fall back to LLM extraction.
    """
    raw_items = _parse_toc_pages(page_texts, toc_pages)
    if len(raw_items) < min_items:
        return None

    if not _looks_like_real_printed_pages(raw_items, page_count=page_count, toc_pages=toc_pages):
        return None

    mapped_items, mapping_report = map_toc_items_to_physical_pages(
        raw_items,
        page_texts=page_texts,
        page_count=page_count,
        toc_pages=toc_pages,
        min_title_match_rate=0.0,
        prefer_printed_page_numbers=True,
    )
    if mapping_report.get("status") != "ok":
        return None

    sections = _group_items_by_catalog(mapped_items)
    if not sections:
        return None

    roots = [_section_to_root(section) for section in sections]
    return {
        "items": roots,
        "toc_items": roots,
        "toc_sections": sections,
        "source": "toc_page_text_rule",
        "confidence": _confidence(raw_items, mapping_report),
        "extraction_method": "rule",
        "mapped": True,
        "prevalidated": True,
        "top_level_frozen": True,
        "allow_child_expansion": False,
        "mapping_report": mapping_report,
    }


def extract_visible_toc_no_pages(
    page_texts: List[str],
    *,
    toc_pages: List[int],
    page_count: int,
    min_items: int = 3,
) -> Optional[Dict[str, Any]]:
    """Extract a main TOC skeleton from visible TOC pages without page numbers."""
    raw_items = _parse_unpaged_toc_pages(page_texts, toc_pages)
    if len(raw_items) < min_items:
        return None

    repeated_catalog_pages = _detect_repeated_catalog_pages(
        page_texts,
        raw_items,
        toc_pages=toc_pages,
    )
    divider_mapping = _map_unpaged_items_by_divider_sequence(
        raw_items,
        toc_pages=toc_pages,
        repeated_catalog_pages=repeated_catalog_pages,
        page_count=page_count,
    )
    if divider_mapping is not None:
        mapped_items, mapping_report = divider_mapping
    else:
        excluded_pages = sorted(set(toc_pages or []) | set(repeated_catalog_pages))
        mapped_items, mapping_report = map_toc_items_to_physical_pages(
            raw_items,
            page_texts=page_texts,
            page_count=page_count,
            toc_pages=toc_pages,
            excluded_pages=excluded_pages,
            min_title_match_rate=0.0,
            prefer_printed_page_numbers=False,
        )
    if mapping_report.get("status") != "ok":
        return None

    section = {
        "kind": "main_toc",
        "title": catalog_group_title(CATALOG_MAIN),
        "items": _build_catalog_tree(mapped_items),
    }
    return {
        "items": [_section_to_root(section)],
        "toc_items": [_section_to_root(section)],
        "toc_sections": [section],
        "source": "toc_page_text_rule",
        "confidence": _confidence(raw_items, mapping_report),
        "extraction_method": "rule",
        "mapped": True,
        "prevalidated": True,
        "top_level_frozen": True,
        "allow_child_expansion": True,
        "semi_frozen": True,
        "mapping_report": mapping_report,
    }


def _detect_repeated_catalog_pages(
    page_texts: List[str],
    items: List[Dict[str, Any]],
    *,
    toc_pages: Iterable[int],
) -> List[int]:
    toc_page_set = {
        int(page)
        for page in (toc_pages or [])
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
    }
    title_keys = [
        _normalize_key(item.get("title"))
        for item in items
        if _normalize_key(item.get("title"))
    ]
    if len(title_keys) < 3:
        return []
    marker_keys = {
        str(item.get("structure") or "").strip().lower()
        for item in items
        if str(item.get("structure") or "").strip()
    }
    marker_keys = {
        marker
        for marker in marker_keys
        if re.fullmatch(r"\d{2,3}|[a-z]{1,4}", marker)
    }
    title_threshold = min(len(title_keys), max(3, len(title_keys) // 2 + 1))
    max_lines = max(24, len(title_keys) * 6)
    detected: List[int] = []
    first_scan_page = max(toc_page_set or {0}) + 1

    for page in range(first_scan_page, len(page_texts) + 1):
        if page in toc_page_set:
            continue
        lines = [_clean_line(line) for line in str(page_texts[page - 1] or "").splitlines()]
        lines = [line for line in lines if line]
        if not lines or len(lines) > max_lines:
            continue
        normalized_text = _normalize_key("\n".join(lines))
        title_hits = sum(1 for title in title_keys if title and title in normalized_text)
        if title_hits < title_threshold:
            continue
        normalized_lines = {re.sub(r"\s+", "", line).lower() for line in lines}
        marker_hits = sum(1 for marker in marker_keys if marker in normalized_lines)
        has_catalog_heading = any(_catalog_from_heading(line) for line in lines)
        if has_catalog_heading or marker_hits >= 2:
            detected.append(page)
    return detected


def _map_unpaged_items_by_divider_sequence(
    raw_items: List[Dict[str, Any]],
    *,
    toc_pages: Iterable[int],
    repeated_catalog_pages: List[int],
    page_count: int,
) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    if len(raw_items) < 2 or len(repeated_catalog_pages) < len(raw_items) - 1:
        return None
    toc_page_set = {
        int(page)
        for page in (toc_pages or [])
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
    }
    divider_pages = sorted(
        page
        for page in repeated_catalog_pages
        if isinstance(page, int) and not isinstance(page, bool) and page > 0
    )
    start_pages = [max(toc_page_set or {0}) + 1]
    start_pages.extend(page + 1 for page in divider_pages[: len(raw_items) - 1])
    excluded_pages = set(toc_page_set) | set(divider_pages)
    if len(start_pages) != len(raw_items):
        return None
    if any(page < 1 or page > page_count or page in excluded_pages for page in start_pages):
        return None
    if not all(left < right for left, right in zip(start_pages, start_pages[1:])):
        return None

    mapped_items: List[Dict[str, Any]] = []
    for item, page in zip(raw_items, start_pages):
        mapped = dict(item)
        mapped["physical_index"] = page
        mapped["start_index"] = page
        mapped["mapping_source"] = "section_divider_sequence"
        mapped["mapping_confidence"] = 0.76
        mapped["mapping_evidence"] = {
            "matched_page": page,
            "divider_pages": divider_pages[: len(raw_items) - 1],
        }
        mapped_items.append(mapped)

    return mapped_items, _build_divider_mapping_report(
        mapped_items,
        toc_pages=sorted(toc_page_set),
        repeated_catalog_pages=divider_pages,
        page_count=page_count,
    )


def _build_divider_mapping_report(
    items: List[Dict[str, Any]],
    *,
    toc_pages: List[int],
    repeated_catalog_pages: List[int],
    page_count: int,
) -> Dict[str, Any]:
    mapped_pages = [_positive_int(item.get("physical_index")) for item in items]
    mapped_pages = [page for page in mapped_pages if page is not None]
    mapping_monotonic = all(left <= right for left, right in zip(mapped_pages, mapped_pages[1:]))
    pages_in_range = all(1 <= page <= page_count for page in mapped_pages)
    status = "ok" if items and mapping_monotonic and pages_in_range else "failed"
    reasons: List[str] = []
    if not mapping_monotonic:
        reasons.append("mapping_non_monotonic")
    if not pages_in_range:
        reasons.append("mapped_pages_out_of_range")
    item_count = len(items)
    mapped_ratio = len(mapped_pages) / item_count if item_count else 0.0
    return {
        "status": status,
        "strategy": "section_divider_sequence",
        "excluded_pages": sorted(set(toc_pages or []) | set(repeated_catalog_pages or [])),
        "logical_overflow": False,
        "regular_step": None,
        "regular_step_ratio": 0.0,
        "multi_logical_per_physical_suspected": False,
        "strong_anchor_count": 0,
        "boundary_anchor_count": item_count if status == "ok" else 0,
        "item_count": item_count,
        "total_item_count": item_count,
        "auxiliary_item_count": 0,
        "title_match_rate": 0.0,
        "sample_match_rate": 0.0,
        "anchor_coverage": {"front": True, "middle": item_count >= 3, "back": item_count >= 2},
        "mapping_monotonic": mapping_monotonic,
        "estimated_ratio": round(1.0 - mapped_ratio, 4) if item_count else 1.0,
        "tail_collapse": False,
        "front_collapse": False,
        "toc_page_leakage_count": 0,
        "page_mapping_score": 0.76 if status == "ok" else 0.0,
        "reasons": reasons,
    }


def _parse_toc_pages(page_texts: List[str], toc_pages: Iterable[int]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    current_catalog = CATALOG_MAIN

    for page in toc_pages or []:
        if not isinstance(page, int) or isinstance(page, bool):
            continue
        index = page - 1
        if index < 0 or index >= len(page_texts):
            continue

        for raw_line in str(page_texts[index] or "").splitlines():
            line = _clean_line(raw_line)
            if not line:
                continue
            heading = _catalog_from_heading(line)
            if heading:
                current_catalog = heading
                continue

            parsed = _parse_catalog_line(line)
            parsed_missing_page = False
            if parsed is None and current_catalog == CATALOG_MAIN:
                parsed = _parse_catalog_line_without_page(line)
                parsed_missing_page = parsed is not None
            if parsed is None:
                continue
            title, printed_page = parsed
            catalog = _catalog_for_title(title, current_catalog)
            if not _line_matches_catalog(title, catalog):
                continue
            item = {
                "title": title,
                "level": _infer_level(title, catalog),
                "structure": _infer_structure(title, catalog, len(items) + 1),
                "source_page": page,
                "catalog_type": catalog,
                "source": "toc_page_text_rule",
            }
            if not parsed_missing_page:
                item["page"] = printed_page
                item["logical_page"] = printed_page
            items.append(item)

    return _dedupe_items(items)


def _parse_unpaged_toc_pages(page_texts: List[str], toc_pages: Iterable[int]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for page in toc_pages or []:
        if not isinstance(page, int) or isinstance(page, bool):
            continue
        index = page - 1
        if index < 0 or index >= len(page_texts):
            continue
        lines = [_clean_line(line) for line in str(page_texts[index] or "").splitlines()]
        lines = [line for line in lines if line]
        cursor = 0
        while cursor < len(lines):
            line = lines[cursor]
            if _is_unpaged_noise_line(line):
                cursor += 1
                continue
            if _catalog_from_heading(line):
                cursor += 1
                continue

            section_number = ""
            title = ""
            if _looks_like_section_marker(line):
                if cursor + 1 < len(lines) and _is_unpaged_title(lines[cursor + 1]):
                    section_number = _normalize_section_marker(line)
                    title = lines[cursor + 1]
                    cursor += 2
                else:
                    cursor += 1
                    continue
            elif _is_unpaged_title(line):
                title = line
                if cursor + 1 < len(lines) and _looks_like_section_marker(lines[cursor + 1]):
                    section_number = _normalize_section_marker(lines[cursor + 1])
                    cursor += 2
                else:
                    cursor += 1
            else:
                cursor += 1
                continue

            title = _clean_title(title)
            if not title or _is_heading_like(title):
                continue
            structure = section_number or _infer_structure(title, CATALOG_MAIN, len(items) + 1)
            items.append(
                {
                    "title": title,
                    "page": None,
                    "logical_page": None,
                    "level": _infer_level(title, CATALOG_MAIN),
                    "structure": structure,
                    "source_page": page,
                    "catalog_type": CATALOG_MAIN,
                    "source": "toc_page_text_rule",
                }
            )
    return _dedupe_items(items)


def _parse_catalog_line(line: str) -> Optional[Tuple[str, int]]:
    match = _LINE_WITH_PAGE_RE.match(line)
    if not match:
        return None
    title = _clean_title(match.group("title"))
    if not title or _is_heading_like(title):
        return None
    try:
        page = int(match.group("page"))
    except (TypeError, ValueError):
        return None
    if page <= 0:
        return None
    return title, page


def _parse_catalog_line_without_page(line: str) -> Optional[Tuple[str, int]]:
    match = _LINE_WITH_LEADER_NO_PAGE_RE.match(line)
    if not match:
        return None
    title = _clean_title(match.group("title"))
    if not title or _is_heading_like(title) or not _MAIN_ITEM_RE.match(title):
        return None
    return title, 0


def _looks_like_real_printed_pages(
    items: List[Dict[str, Any]],
    *,
    page_count: int,
    toc_pages: List[int],
) -> bool:
    pages = [
        int(item["page"])
        for item in items
        if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool)
    ]
    if len(pages) < 3:
        return False
    if max(pages) <= max(toc_pages or [0]) + 2 and page_count > max(toc_pages or [0]) + 8:
        return False
    if len(set(pages)) == len(pages) and pages == sorted(pages) and max(pages) <= max(4, len(pages)):
        return False
    by_catalog: Dict[str, List[int]] = {}
    for item in items:
        if not isinstance(item.get("page"), int) or isinstance(item.get("page"), bool):
            continue
        by_catalog.setdefault(str(item.get("catalog_type") or CATALOG_MAIN), []).append(int(item["page"]))
    return all(all(left <= right for left, right in zip(values, values[1:])) for values in by_catalog.values())


def _group_items_by_catalog(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {CATALOG_MAIN: [], CATALOG_FIGURE: [], CATALOG_TABLE: []}
    for item in items:
        catalog = str(item.get("catalog_type") or CATALOG_MAIN)
        if catalog not in grouped:
            catalog = CATALOG_MAIN
        grouped[catalog].append(dict(item))

    sections: List[Dict[str, Any]] = []
    for catalog in (CATALOG_MAIN, CATALOG_FIGURE, CATALOG_TABLE):
        catalog_items = grouped.get(catalog) or []
        if not catalog_items:
            continue
        section_kind = CATALOG_TO_SECTION[catalog]
        sections.append(
            {
                "kind": section_kind,
                "title": catalog_group_title(catalog),
                "items": _build_catalog_tree(catalog_items),
            }
        )
    return sections


def _section_to_root(section: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(section.get("kind") or "main_toc")
    title = str(section.get("title") or catalog_group_title(SECTION_TO_CATALOG.get(kind, CATALOG_MAIN)))
    catalog = SECTION_TO_CATALOG.get(kind, CATALOG_MAIN)
    children = deepcopy(section.get("items") or [])
    start_pages = [_positive_int(child.get("physical_index")) for child in _flatten(children)]
    start_pages = [page for page in start_pages if page is not None]
    start = min(start_pages) if start_pages else None
    end = max(start_pages) if start_pages else start
    root: Dict[str, Any] = {
        "title": title,
        "structure": catalog,
        "nodes": children,
        "source": "toc_page_text_rule",
        "catalog_type": catalog,
        "toc_section_kind": kind,
    }
    if catalog != CATALOG_MAIN:
        root.update(
            {
                "node_type": "auxiliary_catalog",
                "is_auxiliary": True,
                "exclude_from_coverage": True,
                "exclude_from_llm_qc": True,
                "exclude_from_text": True,
            }
        )
    if start is not None:
        root["physical_index"] = start
        root["start_index"] = start
        root["end_index"] = end
    return root


def _build_catalog_tree(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    roots: List[Dict[str, Any]] = []
    stack: List[Dict[str, Any]] = []
    for raw_item in items:
        item = dict(raw_item)
        level = max(1, int(item.get("level") or 1))
        item["level"] = level
        item.setdefault("nodes", [])
        if item.get("catalog_type") != CATALOG_MAIN:
            item["node_type"] = "auxiliary_catalog_item"
            item["is_auxiliary"] = True
            item["exclude_from_coverage"] = True
            item["exclude_from_llm_qc"] = True
            item["exclude_from_text"] = True
            item["start_index"] = item.get("physical_index")
            item["end_index"] = item.get("physical_index")
        while stack and int(stack[-1].get("level") or 1) >= level:
            stack.pop()
        if stack:
            stack[-1].setdefault("nodes", []).append(item)
        else:
            roots.append(item)
        stack.append(item)
    return roots


def _catalog_from_heading(line: str) -> str:
    compact = re.sub(r"\s+", "", line).lower()
    if _FIGURE_HEADING_RE.match(line) or compact in {"图目录", "插图目录", "图表目录"}:
        return CATALOG_FIGURE
    if _TABLE_HEADING_RE.match(line) or compact in {"表目录", "表格目录"}:
        return CATALOG_TABLE
    if _MAIN_HEADING_RE.match(line) or compact in {"目录", "目次"}:
        return CATALOG_MAIN
    return ""


def _catalog_for_title(title: str, current_catalog: str) -> str:
    if _FIGURE_ITEM_RE.match(title):
        return CATALOG_FIGURE
    if _TABLE_ITEM_RE.match(title):
        return CATALOG_TABLE
    return current_catalog or CATALOG_MAIN


def _line_matches_catalog(title: str, catalog: str) -> bool:
    if catalog == CATALOG_FIGURE:
        return bool(_FIGURE_ITEM_RE.match(title))
    if catalog == CATALOG_TABLE:
        return bool(_TABLE_ITEM_RE.match(title))
    return bool(_MAIN_ITEM_RE.match(title))


def _is_unpaged_title(line: str) -> bool:
    if not line or _is_unpaged_noise_line(line) or _catalog_from_heading(line):
        return False
    if _looks_like_section_marker(line):
        return False
    if _parse_catalog_line(line) is not None:
        return False
    if len(line) < 2 or len(line) > 90:
        return False
    if re.search(r"[。；;，,]", line) and len(line) > 24:
        return False
    return bool(
        _MAIN_ITEM_RE.match(line)
        or re.match(r"^序[言章]|^前言$|^引言$", line)
        or re.match(r"^(?:preface|foreword|introduction|abstract|summary)$", line, re.I)
        or re.search(r"AI|人工智能|应用|治理|产业|风险|范式|营销|教育|模型", line, re.I)
    )


def _looks_like_section_marker(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return bool(
        re.fullmatch(r"\d{1,2}", compact)
        or re.fullmatch(r"[一二三四五六七八九十]", compact)
        or re.fullmatch(r"part\s*0?\d{1,3}", compact, re.I)
    )


def _normalize_section_marker(line: str) -> str:
    compact = re.sub(r"\s+", "", line)
    if re.fullmatch(r"\d{1,2}", compact):
        return compact.zfill(2)
    return compact


def _is_unpaged_noise_line(line: str) -> bool:
    lowered = line.lower()
    if not lowered:
        return True
    if lowered.startswith(("http://", "https://")):
        return True
    if re.match(r"^(?:page\s*)?\d+\s*/\s*\d+$", lowered):
        return True
    if "请务必阅读" in line or "免责声明" in line:
        return True
    return False


def _infer_level(title: str, catalog: str) -> int:
    if catalog != CATALOG_MAIN:
        return 1
    number = re.match(r"^\s*(\d+(?:\.\d+){1,3})", title)
    if number:
        return min(4, number.group(1).count(".") + 1)
    if re.match(r"^\s*[一二三四五六七八九十]+[、.]", title):
        return 2
    return 1


def _infer_structure(title: str, catalog: str, fallback_index: int) -> str:
    number = re.match(r"^\s*(\d+(?:\.\d+){0,3})", title)
    if number:
        return number.group(1)
    if catalog == CATALOG_FIGURE:
        return f"figure.{fallback_index}"
    if catalog == CATALOG_TABLE:
        return f"table.{fallback_index}"
    return str(fallback_index)


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, int]] = set()
    for item in items:
        key = (
            str(item.get("catalog_type") or ""),
            _normalize_key(item.get("title")),
            int(item.get("page") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip())


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "").strip())
    return title.strip(".·… \t")


def _is_heading_like(title: str) -> bool:
    return bool(_catalog_from_heading(title))


def _normalize_key(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def _flatten(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node.get("nodes") or []))
    return result


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _confidence(items: List[Dict[str, Any]], mapping_report: Dict[str, Any]) -> float:
    base = 0.78
    if len(items) >= 10:
        base += 0.08
    title_match = float(mapping_report.get("title_match_rate") or 0.0)
    if title_match:
        base += min(0.1, title_match * 0.1)
    return round(max(0.0, min(0.96, base)), 4)
