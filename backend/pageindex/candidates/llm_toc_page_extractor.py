"""LLM-based TOC extraction from confirmed TOC pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class LLMTOCExtractionResult:
    items: List[Dict[str, Any]]
    toc_sections: List[Dict[str, Any]]
    has_printed_page_numbers: bool
    raw_numeric_labels: List[int]
    missing_numeric_labels: List[int]
    numeric_label_gap_count: int
    diagnostics: Dict[str, Any]


def build_llm_toc_prompt(page_blocks: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for block in page_blocks:
        page = _positive_int(block.get("page")) or 0
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f"[PDF page {page}]\n{text[:6000]}")
    combined = "\n\n".join(blocks).strip()
    return f"""Extract the complete table of contents from the provided TOC page text.

TOC page text:
{combined[:12000]}

Requirements:
1. Use only TOC entries.
2. Preserve original entry order, titles, hierarchy levels, and visible printed page numbers.
3. Put visible printed page numbers in "page". Use null if absent.
4. Do not infer page offsets or physical PDF pages.
5. Return JSON only with this shape:
{{"toc_sections":[{{"kind":"main_toc","title":"Contents","items":[{{"title":"Chapter title","level":1,"page":1}}]}}]}}
Use kind values: main_toc, figure_toc, table_toc, other_toc.
If no reliable TOC exists, return {{"toc_sections":[]}}."""


def normalize_llm_toc_payload(payload: Dict[str, Any]) -> LLMTOCExtractionResult:
    toc_sections = _normalize_typed_sections(payload)
    if not toc_sections:
        raw_items = payload.get("toc_items") or payload.get("items") or []
        items = _normalize_items(raw_items, "main_toc")
        items = _merge_standalone_markers_with_adjacent_titles(items)
        if items:
            toc_sections = [{"kind": "main_toc", "title": "Contents", "items": items}]

    items = [
        dict(item)
        for section in toc_sections
        for item in (section.get("items") or [])
        if isinstance(item, dict)
    ]

    labels = [label for label in (_leading_label_order(item) for item in items) if label is not None]
    missing: List[int] = []
    if len(labels) >= 2:
        unique = sorted(set(labels))
        missing = [value for value in range(unique[0], unique[-1] + 1) if value not in set(unique)]
    pages = [_positive_int(item.get("page")) for item in items]
    has_page_numbers = any(page is not None for page in pages)
    level_distribution: Dict[int, int] = {}
    for item in items:
        level = _positive_int(item.get("level")) or 1
        level_distribution[level] = level_distribution.get(level, 0) + 1
    diagnostics = {
        "item_count": len(items),
        "has_printed_page_numbers": has_page_numbers,
        "raw_numeric_labels": labels,
        "missing_numeric_labels": missing,
        "numeric_label_gap_count": len(missing),
        "marker_normalized_count": sum(1 for item in items if item.get("marker_normalized")),
        "max_level": max(level_distribution.keys(), default=1),
        "level_distribution": dict(sorted(level_distribution.items())),
        "section_kinds": [section.get("kind") for section in toc_sections],
    }
    return LLMTOCExtractionResult(
        items=items,
        toc_sections=toc_sections,
        has_printed_page_numbers=has_page_numbers,
        raw_numeric_labels=labels,
        missing_numeric_labels=missing,
        numeric_label_gap_count=len(missing),
        diagnostics=diagnostics,
    )


def build_llm_toc_candidate(
    extraction: LLMTOCExtractionResult,
    *,
    toc_pages: List[int],
) -> Optional[Dict[str, Any]]:
    if not extraction.items:
        return None
    return {
        "candidate_id": "llm_toc_page_001",
        "source": "llm_toc_page",
        "cost_level": "high",
        "items": [dict(item) for item in extraction.items],
        "toc_sections": [
            {
                **section,
                "items": [dict(item) for item in (section.get("items") or [])],
            }
            for section in extraction.toc_sections
        ],
        "raw_confidence": 0.72 if not extraction.missing_numeric_labels else 0.58,
        "reasons": ["llm_structured_from_confirmed_toc_pages"],
        "evidence": {
            "toc_pages": list(toc_pages),
            "evidence_level": "text_only",
            "llm_structured": True,
            "has_printed_page_numbers": extraction.has_printed_page_numbers,
            "raw_numeric_labels": list(extraction.raw_numeric_labels),
            "missing_numeric_labels": list(extraction.missing_numeric_labels),
            "numeric_label_gap_count": extraction.numeric_label_gap_count,
        },
    }


def _clean_title(value: Any) -> str:
    title = re.sub(r"^#+\s*", "", str(value or "").strip())
    title = re.sub(r"^[-*+]\s+", "", title)
    return re.sub(r"[\s.…]+$", "", title).strip()


def _is_plain_catalog_heading(value: Any) -> bool:
    compact = re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)
    if compact in {
        "目录",
        "目次",
        "提纲",
        "汇报提纲",
        "报告提纲",
        "大纲",
        "contents",
        "tableofcontents",
        "outline",
        "agenda",
        "reportoutline",
        "presentationoutline",
    }:
        return True
    return compact in {
        "目录",
        "目次",
        "contents",
        "tableofcontents",
        "目录contents",
        "目次contents",
    }


def _merge_standalone_markers_with_adjacent_titles(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(items) < 2:
        return items

    marker_infos = [_standalone_marker_info(item.get("title")) for item in items]
    title_to_marker: Dict[int, Tuple[int, Dict[str, Any]]] = {}
    used_markers: set[int] = set()

    for index, marker in enumerate(marker_infos):
        if marker is None:
            continue
        previous_index = index - 1
        next_index = index + 1
        if (
            previous_index >= 0
            and marker_infos[previous_index] is None
            and previous_index not in title_to_marker
            and previous_index not in used_markers
        ):
            title_to_marker[previous_index] = (index, marker)
            used_markers.add(index)
            continue
        if (
            next_index < len(items)
            and marker_infos[next_index] is None
            and next_index not in title_to_marker
            and next_index not in used_markers
        ):
            title_to_marker[next_index] = (index, marker)
            used_markers.add(index)

    merged: List[Tuple[Dict[str, Any], Optional[int]]] = []
    for index, item in enumerate(items):
        if index in used_markers:
            continue
        updated = dict(item)
        marker_pair = title_to_marker.get(index)
        marker_order: Optional[int] = None
        if marker_pair is not None:
            marker_index, marker = marker_pair
            marker_item = items[marker_index]
            marker_order = int(marker["order"])
            display = str(marker["display"])
            title = str(updated.get("title") or "").strip()
            if not _title_starts_with_marker(title, display):
                updated["title"] = f"{display} {title}".strip()
            updated.setdefault("structure", display)
            if updated.get("page") is None and marker_item.get("page") is not None:
                updated["page"] = marker_item.get("page")
            if updated.get("physical_index") is None and marker_item.get("physical_index") is not None:
                updated["physical_index"] = marker_item.get("physical_index")
            updated["marker_normalized"] = True
        else:
            marker_order = _leading_label_order(updated)
        merged.append((updated, marker_order))

    merged = _dedupe_marker_merged_items(merged)
    merged = _drop_interstitial_unlabeled_fragments(merged)
    if _should_sort_by_marker_sequence(merged):
        merged = sorted(merged, key=lambda pair: int(pair[1] or 0))
    return [item for item, _order in merged]


def _drop_interstitial_unlabeled_fragments(
    items: List[Tuple[Dict[str, Any], Optional[int]]]
) -> List[Tuple[Dict[str, Any], Optional[int]]]:
    ordered_count = sum(1 for _item, order in items if order is not None)
    if ordered_count < 3:
        return items

    result: List[Tuple[Dict[str, Any], Optional[int]]] = []
    for index, (item, order) in enumerate(items):
        if order is not None:
            result.append((item, order))
            continue
        previous_order = next(
            (
                candidate_order
                for _candidate_item, candidate_order in reversed(items[:index])
                if candidate_order is not None
            ),
            None,
        )
        next_order = next(
            (
                candidate_order
                for _candidate_item, candidate_order in items[index + 1 :]
                if candidate_order is not None
            ),
            None,
        )
        if (
            previous_order is not None
            and next_order is not None
            and _is_short_unlabeled_fragment(item)
        ):
            continue
        result.append((item, order))
    return result


def _is_short_unlabeled_fragment(item: Dict[str, Any]) -> bool:
    if _positive_int(item.get("page")) is not None:
        return False
    title = str(item.get("title") or "").strip()
    if not title or len(title) > 24:
        return False
    if _leading_label_order(item) is not None:
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", title))


def _dedupe_marker_merged_items(
    items: List[Tuple[Dict[str, Any], Optional[int]]]
) -> List[Tuple[Dict[str, Any], Optional[int]]]:
    deduped: List[Tuple[Dict[str, Any], Optional[int]]] = []
    seen: set[Tuple[str, str, int]] = set()
    for item, order in items:
        structure = str(item.get("structure") or "").strip()
        title_key = _normalize_title_key(item.get("title"))
        page = _positive_int(item.get("page")) or 0
        key = (structure, title_key, page)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((item, order))
    return deduped


def _normalize_title_key(value: Any) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)


def _should_sort_by_marker_sequence(items: List[Tuple[Dict[str, Any], Optional[int]]]) -> bool:
    if len(items) < 3:
        return False
    orders = [order for _item, order in items]
    if any(order is None for order in orders):
        return False
    numeric_orders = [int(order) for order in orders if order is not None]
    if len(set(numeric_orders)) != len(numeric_orders):
        return False
    sorted_orders = sorted(numeric_orders)
    if numeric_orders == sorted_orders:
        return False
    return sorted_orders[-1] - sorted_orders[0] <= len(sorted_orders)


def _standalone_marker_info(value: Any) -> Optional[Dict[str, Any]]:
    text = str(value or "").strip()
    text = re.sub(r"^[\[(（【]\s*|\s*[\])）】]$", "", text).strip()
    text = text.strip(".、:：")
    if not text:
        return None

    numeric = re.fullmatch(r"(?:0?)(\d{1,2})", text)
    if numeric:
        order = int(numeric.group(1))
        if 1 <= order <= 99:
            return {"display": text, "order": order}

    part = re.fullmatch(r"(part|chapter|section)\s*0?(\d{1,2})", text, flags=re.I)
    if part:
        order = int(part.group(2))
        if 1 <= order <= 99:
            return {"display": text, "order": order}

    chinese = re.fullmatch(r"第?([一二三四五六七八九十百零〇两]+)(?:章|节|篇|部分|部)?", text)
    if chinese:
        order = _parse_chinese_number(chinese.group(1))
        if order is not None and 1 <= order <= 99:
            return {"display": text, "order": order}
    return None


def _title_starts_with_marker(title: str, marker: str) -> bool:
    compact_title = re.sub(r"[\s.、:：]+", "", title).lower()
    compact_marker = re.sub(r"[\s.、:：]+", "", marker).lower()
    return bool(compact_marker and compact_title.startswith(compact_marker))


def _leading_label_order(item: Dict[str, Any]) -> Optional[int]:
    structure = str(item.get("structure") or "").strip()
    marker = _standalone_marker_info(structure)
    if marker is not None:
        return int(marker["order"])
    numeric = _leading_numeric_label(item.get("title"))
    if numeric is not None:
        return numeric
    title = str(item.get("title") or "").strip()
    part = re.match(r"^(?:part|chapter|section)\s*0?(\d{1,2})(?:\b|[\s:：.、-])", title, re.I)
    if part:
        return _positive_int(part.group(1))
    match = re.match(r"^([一二三四五六七八九十百零〇两]+)(?:[\s、.：:]|\b)", title)
    if match:
        return _parse_chinese_number(match.group(1))
    return None


def _parse_chinese_number(value: str) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    digits = {
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
    if text in digits and digits[text] > 0:
        return digits[text]
    if text == "十":
        return 10
    if "百" in text:
        return None
    if "十" in text:
        left, right = text.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    if all(char in digits for char in text):
        number_text = "".join(str(digits[char]) for char in text)
        try:
            parsed = int(number_text)
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _normalize_typed_sections(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_sections = payload.get("toc_sections")
    if not isinstance(raw_sections, list):
        return []

    sections: List[Dict[str, Any]] = []
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            continue
        kind = _normalize_section_kind(raw_section.get("kind") or raw_section.get("section_kind"))
        section_items = _normalize_items(raw_section.get("items") or [], kind)
        if kind == "main_toc":
            section_items = _merge_standalone_markers_with_adjacent_titles(section_items)
        if not section_items:
            continue
        sections.append(
            {
                "kind": kind,
                "title": str(raw_section.get("title") or _default_section_title(kind)).strip(),
                "items": section_items,
            }
        )
    return sections


def _normalize_items(raw_items: Any, section_kind: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        title = _clean_title(raw.get("title"))
        if not title or _is_plain_catalog_heading(title):
            continue
        page = _positive_int(raw.get("page"))
        level = _positive_int(raw.get("level")) or 1
        item: Dict[str, Any] = {
            "title": title,
            "level": max(1, min(6, level)),
            "page": page,
            "section_kind": section_kind,
            "physical_index": None,
            "nodes": [],
        }
        if raw.get("structure") not in (None, ""):
            item["structure"] = str(raw.get("structure") or "").strip()
        items.append(item)
    return items


def _normalize_section_kind(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "main": "main_toc",
        "toc": "main_toc",
        "contents": "main_toc",
        "main_toc": "main_toc",
        "figure": "figure_toc",
        "figures": "figure_toc",
        "list_of_figures": "figure_toc",
        "figure_toc": "figure_toc",
        "table": "table_toc",
        "tables": "table_toc",
        "list_of_tables": "table_toc",
        "table_toc": "table_toc",
        "other": "other_toc",
        "other_toc": "other_toc",
    }
    return aliases.get(raw, "other_toc")


def _default_section_title(kind: str) -> str:
    return {
        "main_toc": "Contents",
        "figure_toc": "List of Figures",
        "table_toc": "List of Tables",
        "other_toc": "Other TOC",
    }.get(kind, "Contents")


def _leading_numeric_label(value: Any) -> Optional[int]:
    title = str(value or "").strip()
    match = re.match(r"^(\d{1,3})(?:[.)、．]\s*|\s+)(\S.*)$", title)
    if not match:
        return None
    return _positive_int(match.group(1))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
