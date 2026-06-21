"""TOC draft and mapping contracts used between S4 and S5.

This module intentionally returns plain dictionaries so the current pipeline can
adopt the contract incrementally without a large type migration.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

SECTION_KINDS = {"main_toc", "figure_toc", "table_toc", "other_toc"}
AUXILIARY_SECTION_KINDS = {"figure_toc", "table_toc"}

_SECTION_KIND_ALIASES = {
    "main": "main_toc",
    "toc": "main_toc",
    "contents": "main_toc",
    "main_toc": "main_toc",
    "figure": "figure_toc",
    "figures": "figure_toc",
    "figure_toc": "figure_toc",
    "list_of_figures": "figure_toc",
    "table": "table_toc",
    "tables": "table_toc",
    "table_toc": "table_toc",
    "list_of_tables": "table_toc",
    "other": "other_toc",
    "other_toc": "other_toc",
}


def normalize_section_kind(kind: Any, default: str = "main_toc") -> str:
    """Normalize a raw catalog kind into the stable TOC section kind set."""
    default_kind = _SECTION_KIND_ALIASES.get(str(default or "").strip().lower(), "main_toc")
    raw = str(kind or "").strip().lower()
    if not raw:
        return default_kind
    return _SECTION_KIND_ALIASES.get(raw, "other_toc")


def is_auxiliary_section_kind(kind: Any) -> bool:
    return normalize_section_kind(kind, default="other_toc") in AUXILIARY_SECTION_KINDS


def normalize_toc_draft_item(
    raw: Dict[str, Any],
    default_section_kind: str,
    source_page: Optional[int] = None,
) -> Dict[str, Any]:
    """Normalize one extracted TOC item without deciding physical pages."""
    if not isinstance(raw, dict):
        raise TypeError("raw TOC item must be a dict")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("TOC draft item title is required")

    section_kind = normalize_section_kind(
        raw.get("section_kind") or raw.get("toc_section_kind") or raw.get("kind"),
        default_section_kind,
    )
    normalized: Dict[str, Any] = {
        "title": title,
        "level": _positive_int(raw.get("level")) or _level_from_structure(raw.get("structure")) or 1,
        "section_kind": section_kind,
    }

    raw_page_label = _first_present(
        raw,
        ("raw_page_label", "page_label", "printed_page", "logical_page", "page", "physical_index"),
    )
    if raw_page_label is not None:
        normalized["raw_page_label"] = raw_page_label

    item_source_page = _positive_int(raw.get("source_page")) or _positive_int(source_page)
    if item_source_page is not None:
        normalized["source_page"] = item_source_page

    if raw.get("structure") not in (None, ""):
        normalized["structure"] = str(raw.get("structure")).strip()
    if raw.get("confidence") is not None:
        normalized["confidence"] = _safe_float(raw.get("confidence"), default=0.0)
    if isinstance(raw.get("metadata"), dict):
        normalized["metadata"] = dict(raw["metadata"])

    children = raw.get("children")
    if isinstance(children, list) and children:
        normalized["children"] = [
            normalize_toc_draft_item(child, section_kind, source_page=item_source_page)
            for child in children
            if isinstance(child, dict) and str(child.get("title") or "").strip()
        ]

    return normalized


def normalize_toc_draft(
    items: Iterable[Dict[str, Any]],
    section_kind: str,
    source: str,
    *,
    title: Optional[str] = None,
    source_pages: Optional[List[int]] = None,
    confidence: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap extracted TOC items as an S4 draft."""
    normalized_kind = normalize_section_kind(section_kind)
    normalized_items = [
        normalize_toc_draft_item(item, normalized_kind)
        for item in list(items or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    return {
        "type": "toc_draft",
        "source": _require_source(source),
        "section_kind": normalized_kind,
        "title": title or _default_section_title(normalized_kind),
        "items": normalized_items,
        "source_pages": list(source_pages or []),
        "confidence": float(confidence or 0.0),
        "metadata": dict(metadata or {}),
    }


def _first_present(raw: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in raw and raw.get(key) not in (None, ""):
            return raw.get(key)
    return None


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _level_from_structure(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    if "." in text:
        parts = [part for part in text.split(".") if part]
        if parts and all(part.isdigit() for part in parts):
            return len(parts)
    return 1


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _require_source(source: str) -> str:
    normalized = str(source or "").strip()
    if not normalized:
        raise ValueError("source is required")
    return normalized


def _default_section_title(section_kind: str) -> str:
    return {
        "main_toc": "目录",
        "figure_toc": "图目录",
        "table_toc": "表目录",
        "other_toc": "其他目录",
    }.get(section_kind, "目录")
