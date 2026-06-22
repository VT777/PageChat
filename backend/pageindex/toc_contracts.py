"""TOC draft and mapping contracts used between S4 and S5.

This module intentionally returns plain dictionaries so the current pipeline can
adopt the contract incrementally without a large type migration.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

SECTION_KINDS = {"main_toc", "figure_toc", "table_toc", "other_toc"}
AUXILIARY_SECTION_KINDS = {"figure_toc", "table_toc"}
FINAL_PAGE_FIELDS = {"physical_index", "start_index", "end_index"}


class TocContractError(ValueError):
    """Raised when a TOC payload violates the stage contract."""

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
        ("raw_page_label", "page_label", "printed_page", "logical_page", "page"),
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
    for field in FINAL_PAGE_FIELDS:
        if field in raw:
            normalized[field] = raw[field]

    children = raw.get("children")
    if isinstance(children, list) and children:
        normalized["children"] = [
            normalize_toc_draft_item(child, section_kind, source_page=item_source_page)
            for child in children
            if isinstance(child, dict) and str(child.get("title") or "").strip()
        ]

    return normalized


def normalize_toc_draft(
    items: Any,
    section_kind: Optional[str] = None,
    source: Optional[str] = None,
    *,
    title: Optional[str] = None,
    source_pages: Optional[List[int]] = None,
    confidence: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap extracted TOC items as an S4 draft."""
    if isinstance(items, Mapping):
        return _normalize_toc_draft_payload(items)

    normalized_kind = normalize_section_kind(section_kind)
    normalized_items = [
        normalize_toc_draft_item(item, normalized_kind)
        for item in list(items or [])
        if isinstance(item, dict) and str(item.get("title") or "").strip()
    ]
    section = {
        "kind": normalized_kind,
        "title": title or _default_section_title(normalized_kind),
        "items": normalized_items,
    }
    return {
        "type": "toc_draft",
        "source": _require_source(source or ""),
        "section_kind": normalized_kind,
        "title": section["title"],
        "items": normalized_items,
        "toc_sections": [section],
        "source_pages": list(source_pages or []),
        "confidence": float(confidence or 0.0),
        "metadata": dict(metadata or {}),
    }


def assert_s4_draft_contract(draft: Mapping[str, Any]) -> None:
    """Ensure an S4 draft contains structure only, never final physical pages."""
    if not isinstance(draft, Mapping):
        raise TocContractError("TOC draft must be a mapping")
    if draft.get("type") not in (None, "toc_draft"):
        raise TocContractError("TOC draft type must be 'toc_draft'")
    for path, item in _walk_items(draft):
        forbidden = sorted(field for field in FINAL_PAGE_FIELDS if field in item)
        if forbidden:
            raise TocContractError(
                f"S4 draft item at {path} contains final page fields: {', '.join(forbidden)}"
            )


def normalize_mapped_toc(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize and validate an S5 mapped TOC payload."""
    if not isinstance(payload, Mapping):
        raise TocContractError("Mapped TOC must be a mapping")
    result = dict(payload)
    result["type"] = "mapped_toc"
    items = list(result.get("items") or [])
    sections = result.get("toc_sections")
    if not items and isinstance(sections, list):
        for section in sections:
            if isinstance(section, Mapping):
                items.extend(item for item in section.get("items") or [] if isinstance(item, Mapping))
    result["items"] = [dict(item) for item in items if isinstance(item, Mapping)]
    _assert_mapped_items(result)
    return result


def _normalize_toc_draft_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    source = _require_source(str(payload.get("source") or payload.get("provider") or "unknown"))
    raw_sections = payload.get("toc_sections")
    sections: List[Dict[str, Any]] = []

    if isinstance(raw_sections, list) and raw_sections:
        for raw_section in raw_sections:
            if not isinstance(raw_section, Mapping):
                continue
            kind = normalize_section_kind(raw_section.get("kind") or raw_section.get("section_kind"))
            section_items = [
                normalize_toc_draft_item(dict(item), kind, source_page=_positive_int(raw_section.get("source_page")))
                for item in raw_section.get("items") or []
                if isinstance(item, Mapping) and str(item.get("title") or "").strip()
            ]
            sections.append(
                {
                    "kind": kind,
                    "title": str(raw_section.get("title") or _default_section_title(kind)),
                    "items": section_items,
                }
            )
    else:
        kind = normalize_section_kind(payload.get("section_kind") or payload.get("kind"))
        section_items = [
            normalize_toc_draft_item(dict(item), kind)
            for item in payload.get("items") or []
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
        sections.append(
            {
                "kind": kind,
                "title": str(payload.get("title") or _default_section_title(kind)),
                "items": section_items,
            }
        )

    main_section = next((section for section in sections if section.get("kind") == "main_toc"), sections[0] if sections else None)
    result: Dict[str, Any] = {
        "type": "toc_draft",
        "source": source,
        "toc_sections": sections,
        "items": list(main_section.get("items") or []) if isinstance(main_section, dict) else [],
        "source_pages": list(payload.get("source_pages") or []),
        "confidence": _safe_float(payload.get("confidence"), default=0.0),
        "metadata": dict(payload.get("metadata") or {}),
    }
    if isinstance(main_section, dict):
        result["section_kind"] = main_section.get("kind", "main_toc")
        result["title"] = main_section.get("title") or _default_section_title(result["section_kind"])
    return result


def _assert_mapped_items(mapped: Mapping[str, Any]) -> None:
    items = list(_walk_items(mapped))
    if not items:
        raise TocContractError("Mapped TOC must contain at least one mapped item")
    for path, item in items:
        missing = sorted(field for field in FINAL_PAGE_FIELDS if field not in item)
        if missing:
            raise TocContractError(
                f"Mapped TOC item at {path} missing final page fields: {', '.join(missing)}"
            )


def _walk_items(payload: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    def walk_list(items: Any, prefix: str) -> Iterable[tuple[str, Mapping[str, Any]]]:
        for index, item in enumerate(items or []):
            if not isinstance(item, Mapping):
                continue
            path = f"{prefix}[{index}]"
            yield path, item
            yield from walk_list(item.get("children"), f"{path}.children")

    yield from walk_list(payload.get("items"), "items")
    for section_index, section in enumerate(payload.get("toc_sections") or []):
        if not isinstance(section, Mapping):
            continue
        yield from walk_list(section.get("items"), f"toc_sections[{section_index}].items")


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
