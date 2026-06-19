"""Provider adapter for code-extracted TOC sources."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pageindex.code_toc_quality import evaluate_code_toc
from pageindex.contracts import make_toc_skeleton_context
from pageindex.evidence_classifier import classify_bookmarks
from pageindex.index_quality import TocQualityChecker


class CodeTocProvider:
    name = "code_toc"
    priority = 10

    def can_run(self, analysis: Dict[str, Any]) -> bool:
        code_toc = analysis.get("code_toc") or {}
        return bool(code_toc.get("items"))

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        code_toc = analysis.get("code_toc") or {}
        source = code_toc.get("source")
        quality_report = evaluate_code_toc(analysis)
        items = list(quality_report.get("items") or [])
        if not items or not quality_report.get("accepted"):
            if quality_report.get("reasons"):
                analysis["code_toc_reject_reason"] = ",".join(quality_report.get("reasons") or [])
            return None

        quality = TocQualityChecker().check(items, toc_pages=[])
        if not quality.get("skeleton_valid"):
            analysis["code_toc_reject_reason"] = "invalid_skeleton"
            return None

        bookmark_evidence = classify_bookmarks(items)
        source_parts = set(str(source or "").split("+"))
        confidence = 0.9 if source_parts.intersection({"bookmarks", "links"}) else 0.72
        if source_parts.intersection({"bookmarks", "links"}) and not bookmark_evidence.get("usable_as_skeleton"):
            confidence = 0.65

        return make_toc_skeleton_context(
            source=source,
            items=items,
            skeleton_valid=bool(quality.get("skeleton_valid")),
            page_mapping_valid=bool(quality.get("page_mapping_valid")),
            hierarchy_valid=bool(quality.get("hierarchy_valid")),
            has_page_numbers=bool(quality.get("valid_page_count")),
            authoritative_top_level=True,
            confidence=confidence,
            debug={
                "quality": quality,
                "code_toc_quality": quality_report,
                "toc_sections": code_toc.get("toc_sections") or [],
                "evidence": bookmark_evidence,
            },
        )
