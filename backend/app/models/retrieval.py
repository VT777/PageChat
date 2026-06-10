import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class RetrievalScope:
    user_id: str
    allowed_doc_ids: Optional[tuple[str, ...]] = None

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if self.allowed_doc_ids is not None:
            object.__setattr__(self, "allowed_doc_ids", tuple(self.allowed_doc_ids))

    @property
    def cache_key(self) -> str:
        doc_ids = None
        if self.allowed_doc_ids is not None:
            doc_ids = sorted(self.allowed_doc_ids)
        return json.dumps(
            {"user_id": self.user_id, "allowed_doc_ids": doc_ids},
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass(frozen=True)
class SourceAnchor:
    format: str
    unit_type: str
    values: Mapping[str, Any]


@dataclass(frozen=True)
class RetrievalTrace:
    retrieval_source: str
    confidence: float
    why_selected: str = ""
    source_anchor: Optional[Mapping[str, Any]] = None
    display_label: Optional[str] = None


def _range_label(start: Any, end: Any, singular: str, plural: str) -> Optional[str]:
    if start is None:
        return None
    if end is None or end == start:
        return f"{singular} {start}"
    return f"{plural} {start}-{end}"


def build_source_display_label(
    document_name: str, anchor: Mapping[str, Any] | None
) -> str:
    fallback = f"{document_name} source unavailable"
    if not anchor:
        return fallback

    unit_type = anchor.get("unit_type")
    if unit_type == "page":
        start_page = anchor.get("start_page")
        end_page = anchor.get("end_page")
        if start_page is None:
            return fallback
        label = (
            f"p.{start_page}"
            if end_page is None or end_page == start_page
            else f"p.{start_page}-{end_page}"
        )
        return f"{document_name} {label}" if label else fallback

    if unit_type == "line":
        label = _range_label(
            anchor.get("start_line"), anchor.get("end_line"), "line", "lines"
        )
        return f"{document_name} {label}" if label else fallback

    if unit_type == "paragraph":
        label = _range_label(
            anchor.get("start_paragraph"),
            anchor.get("end_paragraph"),
            "paragraph",
            "paragraphs",
        )
        return f"{document_name} {label}" if label else fallback

    if unit_type == "row_range":
        sheet = anchor.get("sheet")
        label = _range_label(anchor.get("start_row"), anchor.get("end_row"), "row", "rows")
        if sheet and label:
            return f"{document_name} {sheet} {label}"
        return fallback

    if unit_type == "slide":
        label = _range_label(
            anchor.get("start_slide"), anchor.get("end_slide"), "slide", "slides"
        )
        return f"{document_name} {label}" if label else fallback

    return fallback
