"""Incremental controller for the new multi-candidate TOC pipeline."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pageindex.candidates.ocr_toc_page_extractor import OCRTOCPageExtractor
from pageindex.fast_path.code_toc_fast_path import CodeTOCFastPath
from pageindex.judge.page_mapping_verifier import PageMappingVerifier
from pageindex.judge.toc_judge import TOCJudge
from pageindex.layout.document_layout import DocumentLayout


class TOCPipelineController:
    def __init__(
        self,
        *,
        code_toc_fast_path: Optional[CodeTOCFastPath] = None,
        judge: Optional[TOCJudge] = None,
        ocr_toc_extractor: Optional[OCRTOCPageExtractor] = None,
        page_mapping_verifier: Optional[PageMappingVerifier] = None,
    ) -> None:
        self.code_toc_fast_path = code_toc_fast_path or CodeTOCFastPath()
        self.judge = judge or TOCJudge()
        self.ocr_toc_extractor = ocr_toc_extractor or OCRTOCPageExtractor()
        self.page_mapping_verifier = page_mapping_verifier or PageMappingVerifier()

    def generate(
        self,
        *,
        pdf_path: str,
        mode: str = "smart",
        analysis: Optional[Dict[str, Any]] = None,
        layout: Optional[DocumentLayout] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
        budget: Optional[Dict[str, Any]] = None,
        page_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        analysis = analysis if analysis is not None else {}
        if page_count is None:
            try:
                page_count = int(analysis.get("page_count") or 0) or None
            except (TypeError, ValueError):
                page_count = None
        if page_count is None and layout is not None:
            try:
                page_count = int(getattr(layout, "page_count", 0) or 0) or None
            except (TypeError, ValueError):
                page_count = None
        candidate_set: List[Dict[str, Any]] = list(candidates or [])
        budget = budget or {}
        allow_code_toc = bool(budget.get("allow_code_toc", True))
        print(
            f"[TOC-PIPELINE] stage=controller action=start "
            f"mode={mode} initial_candidates={len(candidate_set)} layout={bool(layout)}"
        )

        if not allow_code_toc:
            print("[TOC-CANDIDATE] provider=code_toc action=skipped reason=disabled_by_budget")
        code_toc_candidate = self.code_toc_fast_path.run(analysis) if allow_code_toc else None
        if code_toc_candidate:
            code_toc_candidate = self._verify_candidate(code_toc_candidate, page_count, analysis=analysis)
            candidate_set.append(code_toc_candidate)
            print(
                f"[TOC-CANDIDATE] provider=code_toc action=accepted "
                f"items={len(code_toc_candidate.get('items') or [])} "
                f"early_return={bool(code_toc_candidate.get('early_return_allowed'))}"
            )
            if code_toc_candidate.get("early_return_allowed"):
                print(
                    f"[TOC-JUDGE] decision=early_return source=code_toc "
                    f"confidence={code_toc_candidate['raw_confidence']}"
                )
                return {
                    "status": "ok",
                    "source": "code_toc",
                    "items": code_toc_candidate["items"],
                    "confidence": code_toc_candidate["raw_confidence"],
                    "evidence": code_toc_candidate["evidence"],
                    "rejected_candidates": [],
                    "diagnostics": {"mode": mode, "pdf_path": pdf_path},
                }

        allow_layout_toc_extractor = bool(budget.get("allow_layout_toc_extractor", False))
        if layout and allow_layout_toc_extractor:
            ocr_candidate = self.ocr_toc_extractor.extract(layout)
            if ocr_candidate:
                candidate_set.append(self._verify_candidate(ocr_candidate, page_count, analysis=analysis))
                print(
                    f"[TOC-CANDIDATE] provider=ocr_toc_page action=accepted "
                    f"items={len(ocr_candidate.get('items') or [])}"
                )
        elif layout:
            print("[TOC-CANDIDATE] provider=ocr_toc_page action=skipped reason=disabled_by_budget")

        verified_candidates = [
            self._verify_candidate(candidate, page_count, analysis=analysis)
            for candidate in candidate_set
        ]
        print(
            f"[TOC-JUDGE] action=select candidates={len(verified_candidates)} "
            f"page_count={page_count or 0}"
        )
        judged = self.judge.select(verified_candidates, budget=budget)
        print(
            f"[TOC-JUDGE] decision={judged.get('status')} source={judged.get('source')} "
            f"confidence={judged.get('confidence')} "
            f"rejected={len(judged.get('rejected_candidates') or [])}"
        )
        judged.setdefault("diagnostics", {})
        judged["diagnostics"].update({"mode": mode, "pdf_path": pdf_path})
        if isinstance(analysis.get("ocr_route"), dict):
            judged["diagnostics"]["ocr_route"] = _sanitize_ocr_route(analysis["ocr_route"])
        return judged

    def _verify_candidate(
        self,
        candidate: Dict[str, Any],
        page_count: Optional[int],
        *,
        analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not candidate or not candidate.get("items"):
            return candidate
        verified = dict(candidate)
        verified["items"] = [dict(item) for item in verified.get("items") or []]
        evidence = dict(verified.get("evidence") or {})
        _map_printed_pages_if_needed(verified, evidence, analysis or {}, page_count)
        mapping = self.page_mapping_verifier.verify(verified, page_count)
        evidence.update(mapping)
        verified["evidence"] = evidence
        reasons = list(verified.get("reasons") or [])
        if mapping.get("page_monotonic") is False:
            reasons.append("page_mapping_non_monotonic")
        if mapping.get("pages_in_range") is False:
            reasons.append("page_mapping_out_of_range")
        if float(mapping.get("page_mapping_score") or 0.0) < 0.5:
            if evidence.get("mapping_pending"):
                reasons.append("mapping_pending")
            else:
                reasons.append("page_mapping_low")
        verified["reasons"] = sorted(set(reasons))
        try:
            raw_confidence = float(verified.get("raw_confidence") or 0.0)
        except (TypeError, ValueError):
            raw_confidence = 0.0
        mapping_score = float(mapping.get("page_mapping_score") or 0.0)
        if mapping_score:
            verified["raw_confidence"] = round(min(1.0, raw_confidence * (0.75 + 0.25 * mapping_score)), 4)
        return verified


def _sanitize_ocr_route(route: Dict[str, Any]) -> Dict[str, Any]:
    allowed = (
        "task",
        "source",
        "engine_type",
        "model",
        "profile_id",
        "profile_version",
        "evidence_level",
        "prompt_name",
        "prompt_version",
        "prompt_chars",
        "input_type",
        "elapsed_ms",
        "result_pages",
        "job_id",
        "requested_pages",
        "rendered_pages",
        "fallback_reason",
        "fallback_error_type",
    )
    return {key: route[key] for key in allowed if route.get(key) is not None}


def _map_printed_pages_if_needed(
    candidate: Dict[str, Any],
    evidence: Dict[str, Any],
    analysis: Dict[str, Any],
    page_count: Optional[int],
) -> None:
    if not page_count:
        return
    source = str(candidate.get("source") or "")
    if source not in {"ocr_toc_page", "toc_page_layout", "llm_toc_page"}:
        return

    items = candidate.get("items") or []
    if not items:
        return

    logical_pages = [
        int(item.get("page"))
        for item in items
        if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool)
    ]
    physical_pages = [
        int(item.get("physical_index"))
        for item in items
        if isinstance(item.get("physical_index"), int) and not isinstance(item.get("physical_index"), bool)
    ]
    if not logical_pages:
        return
    if physical_pages and max(physical_pages) <= page_count and max(logical_pages) <= page_count:
        return

    has_content_evidence = isinstance(analysis.get("ocr_text_map"), dict) and bool(analysis.get("ocr_text_map"))
    if not has_content_evidence and isinstance(analysis.get("page_list"), list):
        has_content_evidence = any(
            isinstance(page, (list, tuple))
            and len(page) >= 1
            and str(page[0] or "").strip()
            for page in analysis.get("page_list") or []
        )
    if not has_content_evidence:
        for item in items:
            value = item.get("physical_index")
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and not isinstance(item.get("page"), int)
            ):
                item["page"] = value
                item["logical_page"] = value
                item.pop("physical_index", None)
            elif isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool):
                item["logical_page"] = item.get("page")
                if item.get("physical_index") is None:
                    item.pop("physical_index", None)
        evidence["mapping_pending"] = True
        evidence["logical_overflow"] = max(logical_pages) > page_count
        evidence["page_mapping_score"] = min(float(evidence.get("page_mapping_score") or 0.45), 0.45)
        return

    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    toc_pages = _positive_pages(analysis.get("toc_pages"))
    if not toc_pages:
        toc_pages = _positive_pages(evidence.get("toc_pages"))
    if not toc_pages:
        toc_pages = _positive_pages((analysis.get("toc_page") or {}).get("pages"))
    page_texts = analysis.get("ocr_text_map")
    if not isinstance(page_texts, (dict, list)):
        page_texts = analysis.get("page_list")
    mapped_items, report = map_toc_items_to_physical_pages(
        items,
        page_texts=page_texts or {},
        page_count=int(page_count),
        toc_pages=toc_pages,
    )
    candidate["items"] = mapped_items
    evidence["content_mapping"] = report
    evidence["page_mapping_score"] = float(report.get("page_mapping_score") or evidence.get("page_mapping_score") or 0.0)
    evidence["mapping_pending"] = False
    evidence["logical_overflow"] = bool(report.get("logical_overflow"))
    evidence["mapping_source"] = report.get("strategy")
    if report.get("status") == "failed":
        evidence["mapping_failed"] = True


def _positive_pages(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    pages: List[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        try:
            page = int(item)
        except (TypeError, ValueError):
            continue
        if page > 0:
            pages.append(page)
    return pages


def _last_source_page(items: List[Dict[str, Any]]) -> int:
    pages = _positive_pages([item.get("source_page") for item in items])
    return max(pages) if pages else 0

