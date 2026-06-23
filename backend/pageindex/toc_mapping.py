"""Unified S5 TOC-to-physical-page mapping entrypoint."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pageindex.catalog_classifier import CATALOG_FIGURE, CATALOG_MAIN, CATALOG_TABLE
from pageindex.judge.content_page_mapper import (
    map_toc_items_to_physical_pages,
    page_texts_to_map,
    score_title_on_page,
)
from pageindex.toc_contracts import normalize_section_kind, normalize_toc_draft_item

SECTION_TO_CATALOG = {
    "main_toc": CATALOG_MAIN,
    "figure_toc": CATALOG_FIGURE,
    "table_toc": CATALOG_TABLE,
    "other_toc": CATALOG_MAIN,
}


def map_toc_draft_to_physical(
    draft: Dict[str, Any],
    *,
    page_texts: List[str],
    page_count: int,
    toc_pages: Optional[List[int]] = None,
    selected_path: str,
    allowed_page_range: Optional[Tuple[int, int]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Map an S4 TOC draft to final physical pages.

    S4 is allowed to provide raw page labels, but this function is the only S5
    place that decides ``physical_index``.
    """
    sections = _draft_sections(draft)
    mapped_all: List[Dict[str, Any]] = []
    section_reports: List[Dict[str, Any]] = []

    for section in sections:
        section_kind = normalize_section_kind(section.get("kind"), draft.get("section_kind") or "main_toc")
        raw_items = section.get("items") or []
        items = [
            _prepare_mapper_item(item, section_kind)
            for item in raw_items
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ]
        mapped_items, report = _map_section_items(
            items,
            page_texts=page_texts,
            page_count=page_count,
            toc_pages=toc_pages or [],
            selected_path=selected_path,
            allowed_page_range=allowed_page_range,
        )
        for item in mapped_items:
            item["section_kind"] = section_kind
            metadata = dict(item.get("metadata") or {})
            metadata["toc_section_kind"] = section_kind
            item["metadata"] = metadata
        mapped_all.extend(mapped_items)
        section_reports.append(
            {
                "kind": section_kind,
                "item_count": len(mapped_items),
                "status": report.get("status"),
                "strategy": report.get("strategy"),
                "title_match_rate": report.get("title_match_rate"),
                "sample_checked_count": report.get("sample_checked_count") or report.get("item_count"),
                "main_title_match_rate": report.get("main_title_match_rate"),
                "main_sample_checked_count": report.get("main_sample_checked_count"),
                "main_strong_anchor_count": report.get("main_strong_anchor_count"),
                "strong_anchor_count": report.get("strong_anchor_count"),
                "boundary_anchor_count": report.get("boundary_anchor_count"),
                "evidence_mode": report.get("evidence_mode"),
                "page_mapping_score": report.get("page_mapping_score"),
                "toc_pages": list(report.get("toc_pages") or []),
                "excluded_pages": list(report.get("excluded_pages") or []),
                "section_divider_pages": list(report.get("section_divider_pages") or []),
                "reasons": list(report.get("reasons") or []),
                "warnings": list(report.get("warnings") or []),
            }
        )

    report = _merge_section_reports(
        section_reports,
        mapped_all,
        selected_path=selected_path,
        page_count=page_count,
    )
    return mapped_all, report


def derive_toc_ranges(
    nodes: List[Dict[str, Any]],
    *,
    page_count: int,
    parent_start: Optional[int] = None,
    parent_end: Optional[int] = None,
    copy_nodes: bool = True,
) -> List[Dict[str, Any]]:
    """Derive inclusive physical page ranges from mapped starts.

    This is deterministic S5 logic: callers may provide mapped ``start_index``
    or ``physical_index`` values, and this function owns final ``end_index``
    derivation. Auxiliary figure/table entries remain point-like because they
    do not represent body text spans.
    """
    derived = deepcopy(nodes) if copy_nodes else nodes
    if not derived:
        return derived

    max_page = max(1, int(page_count or 1))
    lower = _clamp_page(parent_start or 1, max_page)
    upper = _clamp_page(parent_end or max_page, max_page)
    if upper < lower:
        upper = lower

    if all(_is_catalog_container(node) for node in derived):
        for node in derived:
            _derive_catalog_container_range(node, page_count=max_page, lower=lower, upper=upper)
        return derived

    starts: List[int] = []
    for node in derived:
        start = _node_start_page(node) or lower
        start = max(lower, min(_clamp_page(start, max_page), upper))
        node["start_index"] = start
        if not _positive_int(node.get("physical_index")):
            node["physical_index"] = start
        starts.append(start)

    for index, node in enumerate(derived):
        start = int(node["start_index"])
        if _is_auxiliary_catalog_item(node):
            end = start
            node["range_boundary"] = "point"
        elif index < len(derived) - 1:
            next_start = starts[index + 1]
            end, boundary = _derive_sibling_end_from_next_start(
                start=start,
                next_start=next_start,
                next_node=derived[index + 1],
                upper=upper,
            )
            node["range_boundary"] = boundary
        else:
            end = max(start, upper)
            node["range_boundary"] = "document_end"
        node["end_index"] = end

        children = node.get("nodes") or []
        if children:
            node["nodes"] = derive_toc_ranges(
                children,
                page_count=max_page,
                parent_start=start,
                parent_end=end,
                copy_nodes=False,
            )
    return derived


def _derive_sibling_end_from_next_start(
    *,
    start: int,
    next_start: int,
    next_node: Dict[str, Any],
    upper: int,
) -> Tuple[int, str]:
    if _next_title_is_known_not_near_page_top(next_node):
        return max(start, min(next_start, upper)), "overlap_with_next_start"
    return max(start, min(next_start - 1, upper)), "exclusive_before_next_start"


def _next_title_is_known_not_near_page_top(next_node: Dict[str, Any]) -> bool:
    evidence = next_node.get("mapping_evidence") if isinstance(next_node, dict) else None
    if not isinstance(evidence, dict):
        return False
    return evidence.get("near_page_top") is False


def _draft_sections(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(draft.get("toc_sections"), list) and draft["toc_sections"]:
        return [
            {
                "kind": section.get("kind") or section.get("section_kind") or draft.get("section_kind"),
                "items": list(section.get("items") or []),
            }
            for section in draft["toc_sections"]
            if isinstance(section, dict)
        ]
    return [
        {
            "kind": draft.get("section_kind") or "main_toc",
            "items": list(draft.get("items") or []),
        }
    ]


def _prepare_mapper_item(raw: Dict[str, Any], section_kind: str) -> Dict[str, Any]:
    normalized = normalize_toc_draft_item(raw, section_kind)
    item = {
        "title": normalized["title"],
        "level": normalized.get("level") or 1,
        "section_kind": normalized.get("section_kind") or section_kind,
        "catalog_type": SECTION_TO_CATALOG.get(section_kind, CATALOG_MAIN),
    }
    for key in ("structure", "source_page", "confidence", "metadata"):
        if key in normalized:
            item[key] = deepcopy(normalized[key])
    raw_page = normalized.get("raw_page_label")
    if raw_page is not None:
        item["raw_page_label"] = raw_page
        logical_page = _positive_int(raw_page)
        if logical_page is not None:
            item["page"] = logical_page
            item["logical_page"] = logical_page
    return item


def _map_section_items(
    items: List[Dict[str, Any]],
    *,
    page_texts: List[str],
    page_count: int,
    toc_pages: List[int],
    selected_path: str,
    allowed_page_range: Optional[Tuple[int, int]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    if not items:
        return [], _with_explicit_toc_pages({
            "status": "failed",
            "strategy": "empty",
            "item_count": 0,
            "strong_anchor_count": 0,
            "title_match_rate": 0.0,
            "reasons": ["empty_items"],
        }, toc_pages)

    identity = _map_by_physical_identity(
        items,
        page_texts=page_texts,
        page_count=page_count,
        toc_pages=toc_pages,
        allowed_page_range=allowed_page_range,
    )
    if identity is not None:
        mapped, report = identity
        return mapped, _with_explicit_toc_pages(report, toc_pages)

    has_raw_page_numbers = any(_positive_int(item.get("raw_page_label")) is not None for item in items)
    if selected_path == "visible_toc_no_pages" and not has_raw_page_numbers and allowed_page_range is None:
        divider_sequence = _map_unpaged_items_by_repeated_catalog_sequence(
            items,
            page_texts=page_texts,
            page_count=page_count,
            toc_pages=toc_pages,
        )
        if divider_sequence is not None:
            mapped, report = divider_sequence
            return mapped, _with_explicit_toc_pages(report, toc_pages)

    mapped, report = map_toc_items_to_physical_pages(
        items,
        page_texts=page_texts,
        page_count=page_count,
        toc_pages=toc_pages,
        excluded_pages=_excluded_pages_outside_allowed_range(page_count, allowed_page_range),
        prefer_printed_page_numbers=bool(
            has_raw_page_numbers and selected_path in {"visible_toc_with_pages", "embedded_toc"}
        ),
        allow_neighbor_inference=not (selected_path == "visible_toc_no_pages" and not has_raw_page_numbers),
        require_all_mapped=bool(selected_path == "visible_toc_no_pages" and not has_raw_page_numbers),
    )
    return mapped, _with_explicit_toc_pages(report, toc_pages)


def _with_explicit_toc_pages(report: Dict[str, Any], toc_pages: Iterable[int]) -> Dict[str, Any]:
    normalized_toc_pages = sorted(
        {
            page
            for page in (_positive_int(value) for value in (toc_pages or []))
            if page is not None
        }
    )
    normalized = dict(report)
    normalized["toc_pages"] = normalized_toc_pages
    if "excluded_pages" not in normalized:
        normalized["excluded_pages"] = normalized_toc_pages
    return normalized


def _map_unpaged_items_by_repeated_catalog_sequence(
    items: List[Dict[str, Any]],
    *,
    page_texts: List[str],
    page_count: int,
    toc_pages: List[int],
) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    if len(items) < 2:
        return None
    ordered_items = _order_items_by_explicit_structure(items)
    repeated_pages = _detect_repeated_catalog_pages(
        page_texts,
        ordered_items,
        toc_pages=toc_pages,
    )
    if len(repeated_pages) < len(ordered_items) - 1:
        return None

    first_start = max(toc_pages) if toc_pages else 1
    start_pages = [first_start] + repeated_pages[: len(ordered_items) - 1]
    if len(start_pages) != len(ordered_items):
        return None
    if any(page < 1 or page > page_count for page in start_pages):
        return None
    if not all(left < right for left, right in zip(start_pages, start_pages[1:])):
        return None

    mapped_items: List[Dict[str, Any]] = []
    for item, page in zip(deepcopy(ordered_items), start_pages):
        item["physical_index"] = page
        item["start_index"] = page
        item["mapping_source"] = "section_divider_sequence"
        item["mapping_confidence"] = 0.76
        item["mapping_evidence"] = {
            "matched_page": page,
            "divider_pages": repeated_pages[: len(items) - 1],
        }
        mapped_items.append(item)

    return mapped_items, _build_divider_sequence_report(
        mapped_items,
        toc_pages=toc_pages,
        repeated_pages=repeated_pages,
        page_count=page_count,
    )


def _detect_repeated_catalog_pages(
    page_texts: List[str],
    items: List[Dict[str, Any]],
    *,
    toc_pages: Iterable[int],
) -> List[int]:
    toc_page_set = {
        page
        for page in (_positive_int(value) for value in (toc_pages or []))
        if page is not None
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
        if re.fullmatch(r"\d{1,3}|[a-z]{1,4}", marker)
    }
    title_threshold = min(len(title_keys), max(3, len(title_keys) // 2 + 1))
    max_lines = max(24, len(title_keys) * 6)
    first_scan_page = max(toc_page_set or {0}) + 1
    detected: List[int] = []

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
        has_catalog_heading = any(_is_catalog_heading(line) for line in lines)
        if has_catalog_heading or marker_hits >= 2:
            detected.append(page)
    return detected


def _order_items_by_explicit_structure(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keyed: List[Tuple[int, int, Dict[str, Any]]] = []
    for index, item in enumerate(items):
        marker = _structure_order_value(item.get("structure"))
        if marker is None:
            return items
        keyed.append((marker, index, item))
    values = [marker for marker, _index, _item in keyed]
    if len(set(values)) != len(values):
        return items
    sorted_values = sorted(values)
    if sorted_values != list(range(min(sorted_values), max(sorted_values) + 1)):
        return items
    keyed.sort(key=lambda part: (part[0], part[1]))
    return [item for _marker, _index, item in keyed]


def _structure_order_value(value: Any) -> Optional[int]:
    text = re.sub(r"\s+", "", str(value or "").strip())
    if not text:
        return None
    numeric = _positive_int(text)
    if numeric is not None:
        return numeric
    chinese = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return chinese.get(text)


def _build_divider_sequence_report(
    items: List[Dict[str, Any]],
    *,
    toc_pages: List[int],
    repeated_pages: List[int],
    page_count: int,
) -> Dict[str, Any]:
    mapped_pages = [
        page
        for page in (_positive_int(item.get("physical_index")) for item in items)
        if page is not None
    ]
    mapping_monotonic = all(left <= right for left, right in zip(mapped_pages, mapped_pages[1:]))
    pages_in_range = all(1 <= page <= page_count for page in mapped_pages)
    status = "ok" if items and mapping_monotonic and pages_in_range else "failed"
    reasons: List[str] = []
    if not mapping_monotonic:
        reasons.append("mapping_non_monotonic")
    if not pages_in_range:
        reasons.append("mapped_pages_out_of_range")
    item_count = len(items)
    return {
        "status": status,
        "strategy": "section_divider_sequence",
        "toc_pages": sorted(set(toc_pages or [])),
        "excluded_pages": sorted(set(toc_pages or [])),
        "section_divider_pages": sorted(set(repeated_pages or [])),
        "logical_overflow": False,
        "regular_step": None,
        "regular_step_ratio": 0.0,
        "multi_logical_per_physical_suspected": False,
        "strong_anchor_count": 0,
        "boundary_anchor_count": item_count if status == "ok" else 0,
        "evidence_mode": "boundary_sequence",
        "item_count": item_count,
        "total_item_count": item_count,
        "auxiliary_item_count": 0,
        "title_match_rate": 0.0,
        "sample_match_rate": 0.0,
        "anchor_coverage": {"front": True, "middle": item_count >= 3, "back": item_count >= 2},
        "mapping_monotonic": mapping_monotonic,
        "estimated_ratio": 0.0 if item_count else 1.0,
        "tail_collapse": False,
        "front_collapse": False,
        "toc_page_leakage_count": 0,
        "page_mapping_score": 0.76 if status == "ok" else 0.0,
        "reasons": reasons,
    }


def _map_by_physical_identity(
    items: List[Dict[str, Any]],
    *,
    page_texts: List[str],
    page_count: int,
    toc_pages: Iterable[int],
    allowed_page_range: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    indexed_pages = [
        (index, _positive_int(item.get("raw_page_label")))
        for index, item in enumerate(items)
    ]
    indexed_pages = [(index, page) for index, page in indexed_pages if page is not None]
    if not indexed_pages:
        return None
    if len(indexed_pages) != len(items):
        return None
    if len(indexed_pages) < max(1, len(items) // 2):
        return None
    if any(page < 1 or page > page_count for _, page in indexed_pages):
        return None
    allowed_range = _normalized_allowed_page_range(page_count, allowed_page_range)
    if any(not _page_in_allowed_range(page, allowed_range) for _, page in indexed_pages):
        return None

    toc_page_set = {page for page in (_positive_int(value) for value in (toc_pages or [])) if page is not None}
    if any(page in toc_page_set for _, page in indexed_pages):
        return None

    page_text_map = page_texts_to_map(page_texts, page_count=page_count)
    anchors = []
    for index, page in indexed_pages:
        title = str(items[index].get("title") or "").strip()
        score = float(score_title_on_page(title, page_text_map.get(page, "")).get("score") or 0.0)
        if score >= 0.58:
            anchors.append((index, page, score))

    required_anchors = min(2, len(indexed_pages))
    if len(anchors) < required_anchors:
        return None
    if len(anchors) / max(1, len(indexed_pages)) < 0.5:
        return None

    mapped = [dict(item) for item in deepcopy(items)]
    anchor_scores = {index: score for index, _page, score in anchors}
    for index, page in indexed_pages:
        mapped[index]["physical_index"] = page
        mapped[index]["start_index"] = page
        mapped[index]["mapping_source"] = "physical_identity"
        mapped[index]["mapping_confidence"] = round(float(anchor_scores.get(index, 0.78)), 4)
        mapped[index]["mapping_evidence"] = {
            "matched_page": page,
            "source": "raw_page_label",
        }

    return mapped, {
        "status": "ok",
        "strategy": "physical_identity",
        "excluded_pages": sorted(toc_page_set),
        "logical_overflow": False,
        "strong_anchor_count": len(anchors),
        "item_count": len(items),
        "title_match_rate": round(len(anchors) / max(1, len(indexed_pages)), 4),
        "sample_match_rate": round(len(anchors) / max(1, len(indexed_pages)), 4),
        "mapping_monotonic": _pages_monotonic([page for _, page in indexed_pages]),
        "estimated_ratio": round(1.0 - len(indexed_pages) / max(1, len(items)), 4),
        "toc_page_leakage_count": 0,
        "page_mapping_score": 0.95,
        "reasons": [],
    }


def _merge_section_reports(
    section_reports: List[Dict[str, Any]],
    mapped_items: List[Dict[str, Any]],
    *,
    selected_path: str,
    page_count: int,
) -> Dict[str, Any]:
    statuses = [str(report.get("status") or "") for report in section_reports]
    reasons: List[str] = []
    warnings: List[str] = []
    for report in section_reports:
        reasons.extend(str(reason) for reason in report.get("reasons") or [])
        warnings.extend(str(warning) for warning in report.get("warnings") or [])
    strategies = [str(report.get("strategy") or "") for report in section_reports if report.get("strategy")]
    strategy = strategies[0] if len(set(strategies)) == 1 else "section_isolated"
    toc_pages = _merge_report_pages(section_reports, "toc_pages")
    excluded_pages = _merge_report_pages(section_reports, "excluded_pages")
    section_divider_pages = _merge_report_pages(section_reports, "section_divider_pages")
    return {
        "status": "ok" if statuses and all(status == "ok" for status in statuses) else "failed",
        "strategy": strategy,
        "selected_path": selected_path,
        "page_count": page_count,
        "sections": section_reports,
        "section_kinds": [report["kind"] for report in section_reports],
        "toc_pages": toc_pages,
        "excluded_pages": excluded_pages,
        "section_divider_pages": section_divider_pages,
        "item_count": len(mapped_items),
        "strong_anchor_count": sum(int(report.get("strong_anchor_count") or 0) for report in section_reports),
        "boundary_anchor_count": sum(int(report.get("boundary_anchor_count") or 0) for report in section_reports),
        "evidence_modes": sorted(
            {
                str(report.get("evidence_mode"))
                for report in section_reports
                if str(report.get("evidence_mode") or "").strip()
            }
        ),
        "title_match_rate": _weighted_title_match_rate(section_reports),
        "page_mapping_score": _weighted_page_mapping_score(section_reports),
        "main_title_match_rate": _main_title_match_rate(section_reports),
        "main_sample_checked_count": _main_sample_checked_count(section_reports),
        "main_strong_anchor_count": _main_strong_anchor_count(section_reports),
        "reasons": sorted(set(reasons)),
        "warnings": sorted(set(warnings)),
    }


def _merge_report_pages(section_reports: List[Dict[str, Any]], key: str) -> List[int]:
    pages: set[int] = set()
    for report in section_reports:
        for value in report.get(key) or []:
            page = _positive_int(value)
            if page is not None:
                pages.add(page)
    return sorted(pages)


def _excluded_pages_outside_allowed_range(
    page_count: int,
    allowed_page_range: Optional[Tuple[int, int]],
) -> List[int]:
    allowed = _normalized_allowed_page_range(page_count, allowed_page_range)
    if allowed is None:
        return []
    start, end = allowed
    return [page for page in range(1, max(1, int(page_count or 1)) + 1) if page < start or page > end]


def _normalized_allowed_page_range(
    page_count: int,
    allowed_page_range: Optional[Tuple[int, int]],
) -> Optional[Tuple[int, int]]:
    if not allowed_page_range:
        return None
    start = _positive_int(allowed_page_range[0])
    end = _positive_int(allowed_page_range[1])
    if start is None or end is None:
        return None
    max_page = max(1, int(page_count or 1))
    start = max(1, min(start, max_page))
    end = max(1, min(end, max_page))
    if end < start:
        end = start
    return start, end


def _page_in_allowed_range(page: int, allowed_range: Optional[Tuple[int, int]]) -> bool:
    if allowed_range is None:
        return True
    return allowed_range[0] <= page <= allowed_range[1]


def _weighted_title_match_rate(section_reports: List[Dict[str, Any]]) -> float:
    total = sum(int(report.get("item_count") or 0) for report in section_reports)
    if total <= 0:
        return 0.0
    weighted = sum(
        int(report.get("item_count") or 0) * float(report.get("title_match_rate") or 0.0)
        for report in section_reports
    )
    return round(weighted / total, 4)


def _weighted_page_mapping_score(section_reports: List[Dict[str, Any]]) -> float:
    total = sum(
        int(report.get("item_count") or 0)
        for report in section_reports
        if report.get("page_mapping_score") is not None
    )
    if total <= 0:
        return 0.0
    weighted = sum(
        int(report.get("item_count") or 0) * float(report.get("page_mapping_score") or 0.0)
        for report in section_reports
        if report.get("page_mapping_score") is not None
    )
    return round(weighted / total, 4)


def _main_title_match_rate(section_reports: List[Dict[str, Any]]) -> float:
    main_reports = [report for report in section_reports if report.get("kind") == "main_toc"]
    total = _main_sample_checked_count(main_reports)
    if total <= 0:
        return 0.0
    weighted = 0.0
    for report in main_reports:
        sample_count = int(
            report.get("main_sample_checked_count")
            or report.get("sample_checked_count")
            or report.get("item_count")
            or 0
        )
        rate = report.get("main_title_match_rate")
        if rate is None:
            rate = report.get("title_match_rate")
        weighted += sample_count * float(rate or 0.0)
    return round(weighted / total, 4)


def _main_sample_checked_count(section_reports: List[Dict[str, Any]]) -> int:
    total = 0
    for report in section_reports:
        if report.get("kind") != "main_toc":
            continue
        total += int(
            report.get("main_sample_checked_count")
            or report.get("sample_checked_count")
            or report.get("item_count")
            or 0
        )
    return total


def _main_strong_anchor_count(section_reports: List[Dict[str, Any]]) -> int:
    total = 0
    for report in section_reports:
        if report.get("kind") != "main_toc":
            continue
        total += int(
            report.get("main_strong_anchor_count")
            or report.get("strong_anchor_count")
            or 0
        )
    return total


def _derive_catalog_container_range(
    node: Dict[str, Any],
    *,
    page_count: int,
    lower: int,
    upper: int,
) -> None:
    children = node.get("nodes") or []
    if children:
        node["nodes"] = derive_toc_ranges(
            children,
            page_count=page_count,
            parent_start=lower,
            parent_end=upper,
            copy_nodes=False,
        )
        child_starts = [
            _positive_int(child.get("start_index"))
            for child in node["nodes"]
            if isinstance(child, dict)
        ]
        child_ends = [
            _positive_int(child.get("end_index"))
            for child in node["nodes"]
            if isinstance(child, dict)
        ]
        child_starts = [page for page in child_starts if page is not None]
        child_ends = [page for page in child_ends if page is not None]
        if child_starts:
            node["start_index"] = min(child_starts)
            node["physical_index"] = node.get("physical_index") or node["start_index"]
        else:
            start = max(lower, min(_clamp_page(_node_start_page(node) or lower, page_count), upper))
            node["start_index"] = start
            node["physical_index"] = node.get("physical_index") or start
        node["end_index"] = max(child_ends) if child_ends else node["start_index"]
        return

    start = max(lower, min(_clamp_page(_node_start_page(node) or lower, page_count), upper))
    node["start_index"] = start
    node["physical_index"] = node.get("physical_index") or start
    node["end_index"] = max(start, upper)


def _node_start_page(node: Dict[str, Any]) -> Optional[int]:
    return (
        _positive_int(node.get("start_index"))
        or _positive_int(node.get("physical_index"))
        or _positive_int(node.get("page"))
    )


def _is_catalog_container(node: Dict[str, Any]) -> bool:
    if node.get("page_type") == "catalog_group" or node.get("node_type") == "catalog_group":
        return True
    title = re.sub(r"\s+", "", str(node.get("title") or "")).casefold()
    return title in {
        "目录",
        "目次",
        "contents",
        "tableofcontents",
        "图目录",
        "插图目录",
        "listoffigures",
        "figurecatalog",
        "表目录",
        "表格目录",
        "listoftables",
        "tablecatalog",
    }


def _is_auxiliary_catalog_item(node: Dict[str, Any]) -> bool:
    if bool(node.get("is_auxiliary")):
        return True
    if node.get("node_type") == "auxiliary_catalog_item":
        return True
    catalog = str(node.get("catalog_type") or "").strip().lower()
    return catalog in {CATALOG_FIGURE, CATALOG_TABLE}


def _clamp_page(value: Any, page_count: int) -> int:
    parsed = _positive_int(value) or 1
    upper = max(1, int(page_count or 1))
    return max(1, min(int(parsed), upper))


def _pages_monotonic(pages: List[int]) -> bool:
    return all(left <= right for left, right in zip(pages, pages[1:]))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _clean_line(line: Any) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip())


def _is_catalog_heading(line: Any) -> bool:
    compact = re.sub(r"\s+", "", str(line or "").strip().lower())
    return compact in {
        "目录",
        "目次",
        "contents",
        "tableofcontents",
        "汇报提纲",
        "提纲",
        "agenda",
        "outline",
        "图目录",
        "插图目录",
        "listoffigures",
        "表目录",
        "表格目录",
        "listoftables",
    }


def _normalize_key(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)
