"""Explicit state planner for PDF TOC generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class TocFlowPath(str, Enum):
    FAST_CODE_TOC = "fast_code_toc"
    BALANCED_TEXT = "balanced_text"
    BALANCED_IMAGE = "balanced_image"
    BALANCED_HYBRID = "balanced_hybrid"


@dataclass(frozen=True)
class TocFlowPlan:
    path: TocFlowPath
    execution_mode: str
    document_kind: str
    reason: str
    diagnostics: Dict[str, Any]


class TocStateMachine:
    def plan(self, analysis: Dict[str, Any], *, requested_mode: str) -> TocFlowPlan:
        requested = str(requested_mode or "smart")
        kind = _document_kind(analysis)
        if requested == "smart" and _has_reliable_code_toc(analysis):
            return TocFlowPlan(
                path=TocFlowPath.FAST_CODE_TOC,
                execution_mode="fast",
                document_kind=kind,
                reason="high_quality_code_toc",
                diagnostics={"requested_mode": requested},
            )

        return TocFlowPlan(
            path=_balanced_path(kind),
            execution_mode="balanced" if requested == "smart" else requested,
            document_kind=kind,
            reason=f"balanced_{kind}",
            diagnostics={"requested_mode": requested},
        )


def _balanced_path(kind: str) -> TocFlowPath:
    if kind == "image_pdf":
        return TocFlowPath.BALANCED_IMAGE
    if kind == "hybrid_low_quality":
        return TocFlowPath.BALANCED_HYBRID
    return TocFlowPath.BALANCED_TEXT


def _document_kind(analysis: Dict[str, Any]) -> str:
    if analysis.get("is_image_only_pdf"):
        return "image_pdf"
    try:
        text_coverage = float(analysis.get("text_coverage") or 0.0)
    except (TypeError, ValueError):
        text_coverage = 0.0
    if analysis.get("is_garbled_pdf") or text_coverage < 0.3:
        return "hybrid_low_quality"
    return "native_text"


def _has_reliable_code_toc(analysis: Dict[str, Any]) -> bool:
    code_toc = analysis.get("code_toc") or {}
    source = str(code_toc.get("source") or "").strip()
    if source not in {"bookmarks", "pdf_outline", "outline", "links"}:
        return False
    items: List[Dict[str, Any]] = [item for item in code_toc.get("items") or [] if isinstance(item, dict)]
    if len(items) < 2:
        return False
    pages = [_positive_int(item.get("physical_index") or item.get("page")) for item in items]
    pages = [page for page in pages if page is not None]
    return len(pages) >= 2 and all(left <= right for left, right in zip(pages, pages[1:]))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
