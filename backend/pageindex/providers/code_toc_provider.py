"""Provider adapter for code-extracted TOC sources."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pageindex.contracts import make_toc_skeleton_context
from pageindex.evidence_classifier import classify_bookmarks
from pageindex.quality_validation import TocQualityChecker


class CodeTocProvider:
    name = "code_toc"
    priority = 10

    def can_run(self, analysis: Dict[str, Any]) -> bool:
        code_toc = analysis.get("code_toc") or {}
        return bool(code_toc.get("items"))

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        code_toc = analysis.get("code_toc") or {}
        items = list(code_toc.get("items") or [])
        source = code_toc.get("source")
        if not items or source not in {"bookmarks", "links", "regex"}:
            return None

        if source == "bookmarks" and _is_weak_slide_bookmark_toc(analysis, items):
            analysis["code_toc_reject_reason"] = "weak_slide_bookmarks"
            return None

        if source == "regex" and not _is_reliable_regex_toc(analysis, items):
            analysis.setdefault("code_toc_reject_reason", "weak_regex_toc")
            return None

        quality = TocQualityChecker().check(items, toc_pages=[])
        if not quality.get("skeleton_valid"):
            analysis["code_toc_reject_reason"] = "invalid_skeleton"
            return None

        bookmark_evidence = classify_bookmarks(items)
        confidence = 0.9 if source in {"bookmarks", "links"} else 0.72
        if source in {"bookmarks", "links"} and not bookmark_evidence.get("usable_as_skeleton"):
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
                "evidence": bookmark_evidence,
            },
        )


def _is_weak_slide_bookmark_toc(analysis: Dict[str, Any], items: List[Dict[str, Any]]) -> bool:
    if not items:
        return False
    weak_titles = 0
    for item in items:
        title = str(item.get("title", "")).strip().lower()
        if (
            title.startswith("slide ")
            or title.startswith("幻灯片")
            or title.startswith("page ")
            or title.startswith("第") and "页" in title
        ):
            weak_titles += 1
    weak_ratio = weak_titles / len(items)
    page_count = int(analysis.get("page_count") or 0)
    garbled_ratio = (
        len(analysis.get("garbled_pages") or []) / page_count
        if page_count > 0 else 0.0
    )
    low_text_quality = (
        float(analysis.get("text_coverage") or 0.0) <= 0.35
        or garbled_ratio >= 0.3
        or float(analysis.get("image_coverage") or 0.0) >= 0.8
    )
    return weak_ratio >= 0.3 and low_text_quality


def _is_reliable_regex_toc(analysis: Dict[str, Any], items: List[Dict[str, Any]]) -> bool:
    page_count = int(analysis.get("page_count") or 0)
    if page_count <= 0 or analysis.get("agenda_outline_candidate"):
        analysis["code_toc_reject_reason"] = (
            "agenda_outline_candidate" if analysis.get("agenda_outline_candidate") else "missing_page_count"
        )
        return False

    physical_pages = [
        item.get("physical_index")
        for item in items
        if isinstance(item.get("physical_index"), int)
    ]
    if len(physical_pages) < 3:
        analysis["code_toc_reject_reason"] = "too_few_page_values"
        return False

    out_of_range_ratio = sum(1 for page in physical_pages if page > page_count) / len(physical_pages)
    year_like_ratio = sum(1 for page in physical_pages if 1900 <= page <= 2100) / len(physical_pages)
    if out_of_range_ratio >= 0.3 or year_like_ratio >= 0.3:
        analysis["code_toc_reject_reason"] = "weak_regex_page_values"
        return False

    compressed_ratio = max(physical_pages) / page_count if physical_pages else 1.0
    if page_count > 15 and compressed_ratio <= 0.35:
        analysis["code_toc_reject_reason"] = "compressed_regex_pages"
        return False

    in_range_pages = [page for page in physical_pages if 1 <= page <= page_count]
    unique_ratio = len(set(in_range_pages)) / len(in_range_pages) if in_range_pages else 0.0
    if len(in_range_pages) < 3 or unique_ratio < 0.6:
        analysis["code_toc_reject_reason"] = "low_unique_page_ratio"
        return False

    return True
