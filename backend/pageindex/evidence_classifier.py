"""Lightweight evidence classification for balanced TOC extraction.

This module does not decide the final extraction path. It only labels document
signals so providers can consume them without duplicating page-type heuristics.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


_FORMAL_TOC_TITLES = (
    "contents",
    "table of contents",
    "目录",
    "目 录",
    "目次",
)
_AGENDA_TITLES = (
    "agenda",
    "outline",
    "提纲",
    "议程",
    "汇报提纲",
    "章节路线",
    "章节路线图",
)
_FIGURE_CATALOG_TITLES = (
    "list of figures",
    "图目录",
    "插图目录",
)
_TABLE_CATALOG_TITLES = (
    "list of tables",
    "表目录",
    "表格目录",
)

_NUMBERED_LINE_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百]+[章节篇部分]|[0-9]{1,2}(?:\.[0-9]{1,2})*|[一二三四五六七八九十]+[、.．])\s+\S+"
)
_PAGE_NUMBER_RE = re.compile(r"(?:\.{2,}|\s{2,}|[·•]{2,})\s*\d{1,4}\s*$")
_AUX_FIGURE_RE = re.compile(r"^\s*(?:图|figure|fig\.)\s*[\d一二三四五六七八九十]", re.I)
_AUX_TABLE_RE = re.compile(r"^\s*(?:表|table)\s*[\d一二三四五六七八九十]", re.I)


def classify_page_text(text: str, page_number: Optional[int] = None) -> Dict[str, Any]:
    lines = _meaningful_lines(text)
    lowered = "\n".join(lines).lower()
    numbered_lines = [line for line in lines if _NUMBERED_LINE_RE.match(line)]
    page_number_lines = [line for line in lines if _PAGE_NUMBER_RE.search(line)]

    base = {
        "page": page_number,
        "evidence_type": "content",
        "role": "content",
        "primary_role": "content_slide",
        "secondary_roles": [],
        "evidence_spans": [],
        "confidence": 0.0,
        "entry_count": len(numbered_lines),
        "has_page_numbers": bool(page_number_lines),
        "usable_as_skeleton": False,
        "is_divider": False,
        "granularity": "page",
        "signals": [],
    }

    figure_catalog = _contains_any(lowered, _FIGURE_CATALOG_TITLES) or _count_matches(lines, _AUX_FIGURE_RE) >= 2
    table_catalog = _contains_any(lowered, _TABLE_CATALOG_TITLES) or _count_matches(lines, _AUX_TABLE_RE) >= 2
    figure_spans = _spans_for_matches(lines, _AUX_FIGURE_RE, "figure_catalog")
    table_spans = _spans_for_matches(lines, _AUX_TABLE_RE, "table_catalog")

    if figure_catalog and not _contains_any(lowered, _FORMAL_TOC_TITLES):
        return _with_evidence_roles(
            base,
            evidence_type="aux_figure_catalog",
            role="auxiliary",
            primary_role="auxiliary_catalog",
            confidence=0.85,
            granularity="catalog",
            signals=["figure_catalog"],
            evidence_spans=figure_spans,
        )

    if table_catalog and not _contains_any(lowered, _FORMAL_TOC_TITLES):
        return _with_evidence_roles(
            base,
            evidence_type="aux_table_catalog",
            role="auxiliary",
            primary_role="auxiliary_catalog",
            confidence=0.85,
            granularity="catalog",
            signals=["table_catalog"],
            evidence_spans=table_spans,
        )

    has_formal_toc_title = _contains_any(lowered, _FORMAL_TOC_TITLES)
    has_agenda_title = _contains_any(lowered, _AGENDA_TITLES)

    if has_formal_toc_title and len(numbered_lines) >= 3:
        has_page_numbers = bool(page_number_lines)
        secondary_roles = []
        spans = _spans_for_numbered_lines(numbered_lines, "toc_item")
        signals = ["toc_title", "numbered_entries"] + (["page_numbers"] if has_page_numbers else [])
        if figure_catalog or table_catalog:
            secondary_roles.append("auxiliary_catalog")
            spans.extend(figure_spans)
            spans.extend(table_spans)
            if figure_catalog:
                signals.append("figure_catalog")
            if table_catalog:
                signals.append("table_catalog")
        return _with_evidence_roles(
            base,
            evidence_type="formal_toc" if has_page_numbers else "no_page_toc",
            role="primary",
            primary_role="toc_page",
            secondary_roles=secondary_roles,
            confidence=0.9 if has_page_numbers else 0.78,
            has_page_numbers=has_page_numbers,
            usable_as_skeleton=True,
            granularity="catalog",
            signals=signals,
            evidence_spans=spans,
        )

    if has_agenda_title and len(numbered_lines) >= 2:
        secondary_roles = []
        spans = _spans_for_numbered_lines(numbered_lines, "agenda_item")
        page_title_spans = _spans_for_current_section(lines)
        if page_title_spans:
            secondary_roles.append("page_title")
            spans.extend(page_title_spans)
        return _with_evidence_roles(
            base,
            evidence_type="agenda_outline",
            role="primary",
            primary_role="agenda_page",
            secondary_roles=secondary_roles,
            confidence=0.76,
            usable_as_skeleton=True,
            granularity="chapter",
            signals=["agenda_title", "numbered_entries"],
            evidence_spans=spans,
        )

    if _looks_like_section_marker(lines):
        return _with_evidence_roles(
            base,
            evidence_type="section_marker",
            role="supporting",
            primary_role="chapter_cover",
            confidence=0.72,
            is_divider=True,
            granularity="chapter",
            signals=["sparse_page", "large_section_marker"],
            evidence_spans=_spans_for_current_section(lines) or _spans_for_numbered_lines(lines, "page_title"),
        )

    return base


def classify_pages(page_texts: Iterable[str]) -> List[Dict[str, Any]]:
    evidences: List[Dict[str, Any]] = []
    for index, text in enumerate(page_texts, start=1):
        evidence = classify_page_text(text, page_number=index)
        if evidence["evidence_type"] != "content":
            evidences.append(evidence)
    return evidences


def classify_bookmarks(bookmarks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    items = [item for item in bookmarks if str(item.get("title", "")).strip()]
    if not items:
        return _bookmark_evidence("weak_bookmark", items, 0.0, False, False)

    page_count = sum(1 for item in items if _positive_int(item.get("page")) is not None)
    level_count = sum(1 for item in items if _positive_int(item.get("level")) is not None)
    numbered_count = sum(1 for item in items if _NUMBERED_LINE_RE.match(str(item.get("title", ""))))

    has_pages = page_count >= max(2, len(items) * 0.5)
    has_structure = level_count >= max(2, len(items) * 0.5) or numbered_count >= max(2, len(items) * 0.5)
    reliable = len(items) >= 3 and has_pages and has_structure

    return _bookmark_evidence(
        "bookmark_toc" if reliable else "weak_bookmark",
        items,
        0.85 if reliable else 0.35,
        reliable,
        has_pages,
    )


def _bookmark_evidence(
    evidence_type: str,
    items: List[Dict[str, Any]],
    confidence: float,
    usable_as_skeleton: bool,
    has_page_numbers: bool,
) -> Dict[str, Any]:
    return {
        "page": None,
        "evidence_type": evidence_type,
        "role": "primary" if evidence_type == "bookmark_toc" else "supporting",
        "primary_role": "toc_page" if evidence_type == "bookmark_toc" else "bookmark",
        "secondary_roles": [],
        "evidence_spans": [
            {
                "role": "bookmark_item",
                "text": str(item.get("title", "")).strip(),
                "confidence": confidence,
            }
            for item in items
        ],
        "confidence": confidence,
        "entry_count": len(items),
        "has_page_numbers": has_page_numbers,
        "usable_as_skeleton": usable_as_skeleton,
        "is_divider": False,
        "granularity": "catalog",
        "signals": ["bookmarks"],
    }


def _meaningful_lines(text: str) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle.lower() in text for needle in needles)


def _count_matches(lines: Iterable[str], pattern: re.Pattern[str]) -> int:
    return sum(1 for line in lines if pattern.search(line))


def _with_evidence_roles(base: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    secondary_roles = list(kwargs.pop("secondary_roles", []) or [])
    evidence_spans = list(kwargs.pop("evidence_spans", []) or [])
    result = dict(base)
    result.update(kwargs)
    result["secondary_roles"] = secondary_roles
    result["evidence_spans"] = evidence_spans
    return result


def _spans_for_matches(lines: Iterable[str], pattern: re.Pattern[str], role: str) -> List[Dict[str, Any]]:
    return [
        {"role": role, "text": line, "confidence": 0.8}
        for line in lines
        if pattern.search(line)
    ]


def _spans_for_numbered_lines(lines: Iterable[str], role: str) -> List[Dict[str, Any]]:
    return [
        {"role": role, "text": line, "confidence": 0.78}
        for line in lines
        if _NUMBERED_LINE_RE.match(line)
    ]


def _spans_for_current_section(lines: Iterable[str]) -> List[Dict[str, Any]]:
    spans = []
    for line in lines:
        if re.match(r"^\s*第[一二三四五六七八九十百]+[章节篇部分]\s+\S+", line):
            spans.append({"role": "page_title", "text": line, "confidence": 0.76})
    return spans


def _looks_like_section_marker(lines: List[str]) -> bool:
    if not lines or len(lines) > 4:
        return False
    joined = " ".join(lines)
    if len(joined) > 80:
        return False
    if re.match(r"^\s*(?:[0-9]{1,2}|[一二三四五六七八九十]+|第[一二三四五六七八九十百]+[章节篇部分])\b", joined):
        return True
    return False


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
