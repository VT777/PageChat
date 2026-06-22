"""Explicit state planner for PDF TOC generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class TocFlowPath(str, Enum):
    EMBEDDED_TOC = "embedded_toc"
    VISIBLE_TOC_WITH_PAGES = "visible_toc_with_pages"
    VISIBLE_TOC_NO_PAGES = "visible_toc_no_pages"
    CONTENT_OUTLINE = "content_outline"


ROUTE_STATES_TO_EMBEDDED_TOC = ["S0", "S1", "S2", "S5", "S6"]
ROUTE_STATES_TO_BUILT_TOC = ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
POST_ROUTE_STATES = ["S7", "S8"]


@dataclass(frozen=True)
class TocFlowPlan:
    path: TocFlowPath
    execution_mode: str
    content_type: str
    preprocess_strategy: str
    states: List[str]
    post_route_states: List[str]
    fallbacks: List[Dict[str, Any]]
    attempts: List[Dict[str, Any]]
    reason: str
    diagnostics: Dict[str, Any]

    @property
    def selected_path(self) -> str:
        return self.path.value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requested_mode": self.diagnostics.get("requested_mode", "smart"),
            "execution_mode": self.execution_mode,
            "content_type": self.content_type,
            "preprocess_strategy": self.preprocess_strategy,
            "states": list(self.states),
            "post_route_states": list(self.post_route_states),
            "selected_path": self.selected_path,
            "path": self.selected_path,
            "fallbacks": [dict(item) for item in self.fallbacks],
            "attempts": [dict(item) for item in self.attempts],
            "attempt_chain": [dict(item) for item in self.attempts],
            "reason": self.reason,
            "diagnostics": dict(self.diagnostics),
        }


class TocStateMachine:
    def plan(self, analysis: Dict[str, Any], *, requested_mode: str) -> TocFlowPlan:
        analysis = analysis if isinstance(analysis, dict) else {}
        requested = str(requested_mode or "smart").strip() or "smart"
        content_type = _content_type(analysis)
        preprocess_strategy = _preprocess_strategy(content_type)
        fallbacks: List[Dict[str, Any]] = []
        toc_signal = _toc_page_signal(analysis)

        code_toc_disabled = bool(analysis.get("disable_code_toc_fast_path"))
        has_code_signal = _has_code_toc_signal(analysis)
        embedded_candidate = None if code_toc_disabled else _embedded_toc_candidate(analysis)
        if embedded_candidate:
            return TocFlowPlan(
                path=TocFlowPath.EMBEDDED_TOC,
                execution_mode=_execution_mode_for(requested, embedded=True),
                content_type=content_type,
                preprocess_strategy=preprocess_strategy,
                states=list(ROUTE_STATES_TO_EMBEDDED_TOC),
                post_route_states=list(POST_ROUTE_STATES),
                fallbacks=[],
                attempts=_attempt_chain(
                    TocFlowPath.EMBEDDED_TOC,
                    toc_signal,
                    include_embedded=True,
                ),
                reason="embedded_toc_accepted",
                diagnostics={
                    "requested_mode": requested,
                    "code_toc_source": embedded_candidate.get("code_toc_source"),
                    "code_toc_items": len(embedded_candidate.get("items") or []),
                },
            )

        if has_code_signal:
            fallbacks.append(
                {
                    "from": "S2",
                    "to": "S3",
                    "reason": "embedded_toc_disabled" if code_toc_disabled else "embedded_toc_rejected",
                    "code_toc_source": (analysis.get("code_toc") or {}).get("source"),
                }
            )

        if toc_signal["has_toc_page"]:
            selected_path = (
                TocFlowPath.VISIBLE_TOC_WITH_PAGES
                if toc_signal["has_page_numbers"]
                else TocFlowPath.VISIBLE_TOC_NO_PAGES
            )
            reason = "visible_toc_with_pages" if toc_signal["has_page_numbers"] else "visible_toc_no_pages"
        else:
            selected_path = TocFlowPath.CONTENT_OUTLINE
            reason = "no_visible_toc_page"

        return TocFlowPlan(
            path=selected_path,
            execution_mode=_execution_mode_for(requested, embedded=False),
            content_type=content_type,
            preprocess_strategy=preprocess_strategy,
            states=list(ROUTE_STATES_TO_BUILT_TOC),
            post_route_states=list(POST_ROUTE_STATES),
            fallbacks=fallbacks,
            attempts=_attempt_chain(
                selected_path,
                toc_signal,
                include_embedded=False,
            ),
            reason=reason,
            diagnostics={
                "requested_mode": requested,
                "toc_pages": list(toc_signal["pages"]),
                "has_page_numbers": bool(toc_signal["has_page_numbers"]),
            },
        )


def _attempt_chain(
    selected_path: TocFlowPath,
    toc_signal: Dict[str, Any],
    *,
    include_embedded: bool,
) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []

    def add(path: TocFlowPath, reason: str) -> None:
        if any(item.get("path") == path.value for item in attempts):
            return
        attempts.append({"path": path.value, "reason": reason})

    if include_embedded:
        add(TocFlowPath.EMBEDDED_TOC, "code_toc_signal")

    if selected_path == TocFlowPath.EMBEDDED_TOC:
        if toc_signal.get("has_toc_page"):
            if toc_signal.get("has_page_numbers"):
                add(TocFlowPath.VISIBLE_TOC_WITH_PAGES, "visible_toc_with_pages")
                add(TocFlowPath.VISIBLE_TOC_NO_PAGES, "mapping_fallback")
            else:
                add(TocFlowPath.VISIBLE_TOC_NO_PAGES, "visible_toc_no_pages")
        add(TocFlowPath.CONTENT_OUTLINE, "last_resort")
        return attempts

    if selected_path == TocFlowPath.VISIBLE_TOC_WITH_PAGES:
        add(TocFlowPath.VISIBLE_TOC_WITH_PAGES, "visible_toc_with_pages")
        add(TocFlowPath.VISIBLE_TOC_NO_PAGES, "mapping_fallback")
        add(TocFlowPath.CONTENT_OUTLINE, "last_resort")
        return attempts

    if selected_path == TocFlowPath.VISIBLE_TOC_NO_PAGES:
        add(TocFlowPath.VISIBLE_TOC_NO_PAGES, "visible_toc_no_pages")
        add(TocFlowPath.CONTENT_OUTLINE, "last_resort")
        return attempts

    add(TocFlowPath.CONTENT_OUTLINE, "last_resort")
    return attempts


def _execution_mode_for(requested: str, *, embedded: bool) -> str:
    if requested == "smart":
        return "fast" if embedded else "balanced"
    return requested


def _content_type(analysis: Dict[str, Any]) -> str:
    value = str(analysis.get("content_type") or "").strip().lower()
    if value in {"text", "ocr", "hybrid"}:
        return value
    try:
        from pageindex.preprocess_page_text import infer_content_type

        inferred = infer_content_type(analysis)
        if inferred in {"text", "ocr", "hybrid"}:
            return inferred
    except Exception:
        pass
    if analysis.get("is_image_only_pdf") or analysis.get("is_garbled_pdf"):
        return "ocr"
    if analysis.get("image_only_pages") or analysis.get("garbled_pages"):
        return "hybrid"
    return "text"


def _preprocess_strategy(content_type: str) -> str:
    if content_type == "ocr":
        return "ocr_full_document"
    if content_type == "hybrid":
        return "ocr_selected_pages"
    return "pdf_text"


def _embedded_toc_candidate(analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from pageindex.code_toc_quality import evaluate_code_toc

    try:
        from pageindex.fast_path.code_toc_fast_path import CodeTOCFastPath

        candidate = CodeTOCFastPath().run(analysis)
    except Exception:
        candidate = None
    if candidate and candidate.get("early_return_allowed") and candidate.get("items"):
        return candidate
    quality = evaluate_code_toc(analysis)
    if quality.get("accepted"):
        code_toc = analysis.get("code_toc") or {}
        return {
            "code_toc_source": code_toc.get("source"),
            "items": quality.get("items") or [],
        }
    return None


def _has_code_toc_signal(analysis: Dict[str, Any]) -> bool:
    code_toc = analysis.get("code_toc") or {}
    return bool(code_toc.get("source") or code_toc.get("items"))


def _has_reliable_code_toc(analysis: Dict[str, Any]) -> bool:
    from pageindex.code_toc_quality import evaluate_code_toc

    return bool(evaluate_code_toc(analysis).get("accepted"))


def _toc_page_signal(analysis: Dict[str, Any]) -> Dict[str, Any]:
    detection = analysis.get("toc_page_detection") if isinstance(analysis.get("toc_page_detection"), dict) else {}
    toc_page = analysis.get("toc_page") if isinstance(analysis.get("toc_page"), dict) else {}
    pages = _positive_pages(detection.get("pages"))
    if not pages:
        pages = _positive_pages(analysis.get("toc_pages"))
    if not pages:
        pages = _positive_pages(toc_page.get("pages"))

    status = str(detection.get("status") or "").strip().lower()
    has_toc = bool(pages) and status != "not_found"
    if not has_toc:
        has_toc = bool(toc_page.get("has_toc_page")) and bool(pages or toc_page.get("pages"))

    explicit = _explicit_has_page_numbers(detection, toc_page)
    if explicit is not None:
        has_page_numbers = explicit
    else:
        has_page_numbers = _infer_has_page_numbers(detection, toc_page)

    return {
        "has_toc_page": has_toc,
        "pages": pages,
        "has_page_numbers": bool(has_page_numbers),
    }


def _explicit_has_page_numbers(*sources: Dict[str, Any]) -> Optional[bool]:
    keys = (
        "has_page_numbers",
        "has_printed_page_numbers",
        "page_numbers_present",
        "contains_page_numbers",
    )
    for source in sources:
        for key in keys:
            if key in source:
                return bool(source.get(key))
    return None


def _infer_has_page_numbers(*sources: Dict[str, Any]) -> bool:
    for source in sources:
        preview_items = source.get("preview_items") or source.get("items") or []
        if any(
            isinstance(item, dict)
            and (
                _positive_int(item.get("page")) is not None
                or _positive_int(item.get("logical_page")) is not None
                or _positive_int(item.get("physical_index")) is not None
            )
            for item in preview_items
        ):
            return True
        candidates = source.get("candidates") or []
        catalog_lines = sum(int(candidate.get("catalog_line_count") or 0) for candidate in candidates if isinstance(candidate, dict))
        unpaged_lines = sum(int(candidate.get("unpaged_catalog_line_count") or 0) for candidate in candidates if isinstance(candidate, dict))
        if catalog_lines or unpaged_lines:
            return catalog_lines >= unpaged_lines
    return False


def _positive_pages(values: Any) -> List[int]:
    pages: List[int] = []
    for value in values or []:
        page = _positive_int(value)
        if page is not None and page not in pages:
            pages.append(page)
    return pages


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
