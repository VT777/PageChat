"""Verified low-cost TOC path for PDF outline/bookmark/link metadata."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


TRUSTED_SOURCES = {"bookmarks", "pdf_outline", "outline", "links"}


class CodeTOCFastPath:
    """Build a deterministic TOC candidate from pre-extracted code_toc data."""

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        code_toc = analysis.get("code_toc") or {}
        items = list(code_toc.get("items") or [])
        source = str(code_toc.get("source") or "").strip()
        if not items or not source:
            return None
        if source == "regex" and not _is_verified_regex(code_toc):
            return None

        evidence = self._evaluate(analysis, items, source)
        reasons = list(evidence.pop("reasons"))
        early_return = self._can_early_return(source, evidence, reasons)

        return {
            "candidate_id": f"code_toc_{source}",
            "source": "code_toc",
            "code_toc_source": source,
            "cost_level": "low",
            "items": items,
            "raw_confidence": 0.92 if early_return else 0.62,
            "score": 0.92 if early_return else 0.62,
            "early_return_allowed": early_return,
            "evidence": {
                **evidence,
                "early_return_allowed": early_return,
                "code_toc_source": source,
            },
            "reasons": reasons,
        }

    def _can_early_return(
        self,
        source: str,
        evidence: Dict[str, Any],
        reasons: List[str],
    ) -> bool:
        if source == "regex":
            return False
        if source not in TRUSTED_SOURCES:
            return False
        return (
            evidence["item_count"] >= 2
            and evidence["pages_valid"]
            and evidence["pages_monotonic"]
            and _bookmark_density_ok(
                source,
                evidence["item_count"],
                evidence.get("page_count"),
                garbled_or_ocr=bool(evidence.get("garbled_or_ocr")),
            )
            and evidence["title_noise_ratio"] <= 0.20
            and evidence["range_coverage"] >= 0.70
            and not reasons
        )

    def _evaluate(
        self,
        analysis: Dict[str, Any],
        items: List[Dict[str, Any]],
        source: str,
    ) -> Dict[str, Any]:
        page_count = int(analysis.get("page_count") or 0)
        pages = [_as_positive_int(item.get("physical_index") or item.get("page")) for item in items]
        pages = [page for page in pages if page is not None]
        reasons: List[str] = []

        pages_valid = bool(pages) and all(1 <= page <= page_count for page in pages) if page_count else bool(pages)
        pages_monotonic = all(left <= right for left, right in zip(pages, pages[1:]))
        range_coverage = (max(pages) / page_count) if pages and page_count else 0.0
        title_noise_ratio = _title_noise_ratio(items)

        if source == "regex":
            year_like_ratio = (
                sum(1 for page in pages if 1900 <= page <= 2100) / len(pages)
                if pages
                else 1.0
            )
            unique_ratio = len(set(pages)) / len(pages) if pages else 0.0
            if not pages_valid or year_like_ratio >= 0.3 or unique_ratio < 0.6:
                reasons.append("weak_regex")

        if not pages_valid:
            reasons.append("invalid_pages")
        if not pages_monotonic:
            reasons.append("non_monotonic_pages")
        if title_noise_ratio > 0.20:
            reasons.append("title_noise_high")

        return {
            "item_count": len(items),
            "page_count": page_count,
            "garbled_or_ocr": bool(
                analysis.get("is_garbled_pdf")
                or str(analysis.get("text_layer_quality") or "").lower() == "garbled"
                or str(analysis.get("content_type") or "").lower() == "ocr"
            ),
            "pages_valid": pages_valid,
            "pages_monotonic": pages_monotonic,
            "range_coverage": round(range_coverage, 4),
            "sampled_title_page_match": 0.0,
            "title_noise_ratio": round(title_noise_ratio, 4),
            "reasons": reasons,
        }


def _as_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _title_noise_ratio(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 1.0
    noisy = 0
    for item in items:
        title = str(item.get("title") or "").strip()
        if len(title) < 2 or len(title) > 120 or title.isdigit():
            noisy += 1
    return noisy / len(items)


def _bookmark_density_ok(
    source: str,
    item_count: int,
    page_count: Optional[int],
    *,
    garbled_or_ocr: bool = False,
) -> bool:
    if source != "bookmarks":
        return True
    if garbled_or_ocr:
        return True
    if not page_count or page_count <= 0:
        return True
    return item_count / page_count >= 0.75 or item_count >= 50


def _is_verified_regex(code_toc: Dict[str, Any]) -> bool:
    quality = code_toc.get("quality") or {}
    evidence = code_toc.get("evidence") or {}
    if quality.get("verified") is True or evidence.get("verified") is True:
        return True
    try:
        score = float(quality.get("score", evidence.get("score", 0.0)) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return score >= 0.85 and bool(
        quality.get("title_match_verified")
        or evidence.get("title_match_verified")
        or quality.get("offset_verified")
        or evidence.get("offset_verified")
    )
