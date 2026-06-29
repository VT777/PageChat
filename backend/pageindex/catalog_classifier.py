"""Shared helpers for classifying TOC entries by catalog type."""

from __future__ import annotations

import re
from typing import Any, Dict


CATALOG_MAIN = "main"
CATALOG_FIGURE = "figure"
CATALOG_TABLE = "table"
AUXILIARY_CATALOG_TYPES = {CATALOG_FIGURE, CATALOG_TABLE}

CATALOG_GROUP_TITLES = {
    CATALOG_MAIN: "目录",
    CATALOG_FIGURE: "图目录",
    CATALOG_TABLE: "表目录",
}


def catalog_group_title(catalog_type: str) -> str:
    return CATALOG_GROUP_TITLES.get(catalog_type, CATALOG_GROUP_TITLES[CATALOG_MAIN])


def detect_catalog_type(item: Dict[str, Any] | str | None) -> str:
    """Classify a TOC item as main, figure, or table catalog content.

    The classifier intentionally uses only strong generic signals: explicit
    metadata, dedicated catalog headings, and figure/table entry prefixes.
    """
    if isinstance(item, dict):
        explicit = _normalize_explicit_catalog_type(item)
        if explicit:
            return explicit
        title = str(item.get("title") or "")
    else:
        title = str(item or "")

    stripped = re.sub(r"\s+", " ", title).strip()
    lowered = stripped.lower()
    compact = re.sub(r"\s+", "", lowered)

    if _looks_like_figure_catalog_heading(lowered, compact) or _looks_like_figure_item(stripped):
        return CATALOG_FIGURE
    if _looks_like_table_catalog_heading(lowered, compact) or _looks_like_table_item(stripped):
        return CATALOG_TABLE
    return CATALOG_MAIN


def is_auxiliary_catalog_item(item: Dict[str, Any] | str | None) -> bool:
    return detect_catalog_type(item) in AUXILIARY_CATALOG_TYPES


def _normalize_explicit_catalog_type(item: Dict[str, Any]) -> str:
    values = [
        item.get("catalog_type"),
        item.get("catalog"),
        item.get("catalog_kind"),
        item.get("page_type"),
        item.get("type"),
        item.get("node_type"),
    ]
    for value in values:
        text = str(value or "").strip().lower()
        if text in {"figure", "figures", "figure_catalog", "aux_figure_catalog"}:
            return CATALOG_FIGURE
        if text in {"table", "tables", "table_catalog", "aux_table_catalog"}:
            return CATALOG_TABLE
        if text in {"main", "chapter", "chapter_catalog", "toc", "contents"}:
            return CATALOG_MAIN
    return ""


def _looks_like_figure_catalog_heading(lowered: str, compact: str) -> bool:
    return any(
        marker in lowered or marker in compact
        for marker in (
            "list of figures",
            "figure catalog",
            "figures catalog",
            "图目录",
            "插图目录",
            "图表目录",
        )
    )


def _looks_like_table_catalog_heading(lowered: str, compact: str) -> bool:
    return any(
        marker in lowered or marker in compact
        for marker in (
            "list of tables",
            "table catalog",
            "tables catalog",
            "表目录",
            "表格目录",
        )
    )


def _looks_like_figure_item(title: str) -> bool:
    return bool(
        re.match(r"^\s*(?:figure|fig\.)\s*[0-9ivxlcdm]+(?:[.\-\s:]|$)", title, re.I)
        or re.match(r"^\s*图\s*[0-9一二三四五六七八九十]+(?:[.．、\-\s:]|$)", title)
    )


def _looks_like_table_item(title: str) -> bool:
    return bool(
        re.match(r"^\s*(?:table|tab\.)\s*[0-9ivxlcdm]+(?:[.\-\s:]|$)", title, re.I)
        or re.match(r"^\s*表\s*[0-9一二三四五六七八九十]+(?:[.．、\-\s:]|$)", title)
    )
