"""Low-cost TOC page detection for the new layout-first pipeline.

This module intentionally does not call image-model detection. Image-only,
garbled, and low-text-quality documents are routed to the PP-OCR layout path by
``pageindex.router``; this detector only reuses already available text/analysis
signals.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

MAX_SCAN_PAGES = 20


def _positive_pages(values: Any) -> List[int]:
    pages: List[int] = []
    for value in values or []:
        try:
            page = int(value)
        except Exception:
            continue
        if page > 0:
            pages.append(page)
    return pages


def detect_toc_pages_text_report(
    page_texts: List[str],
    max_scan_pages: int = MAX_SCAN_PAGES,
) -> Dict[str, Any]:
    """Detect TOC pages from extracted text and preserve route-critical facts."""
    empty_report = {
        "source": "text_detector",
        "status": "not_found",
        "pages": [],
        "has_page_numbers": False,
        "candidates": [],
        "reason": "no_text_toc_pages",
        "classification_complete": True,
    }
    if not page_texts:
        return empty_report

    from pageindex.pdf_analyzer import _detect_toc_pages

    has_toc, toc_indices, confidence, _ = _detect_toc_pages(
        page_texts,
        max_scan_pages,
    )
    if has_toc and confidence >= 0.5:
        pages = [idx + 1 for idx in toc_indices]
        has_page_numbers = _pages_have_trailing_page_numbers(page_texts, pages)
        return {
            "source": "text_detector",
            "status": "detected",
            "pages": pages,
            "has_page_numbers": has_page_numbers,
            "candidates": [
                {
                    "page": page,
                    "source": "text_detector",
                    "is_toc": True,
                    "score": float(confidence),
                    "has_page_numbers": has_page_numbers,
                }
                for page in pages
            ],
            "reason": "detected_by_text_toc_detector",
            "classification_complete": True,
        }

    unpaged = _detect_unpaged_toc_pages(page_texts, max_scan_pages=max_scan_pages)
    if unpaged:
        has_page_numbers = _pages_have_trailing_page_numbers(page_texts, unpaged)
        return {
            "source": "text_detector",
            "status": "detected",
            "pages": unpaged,
            "has_page_numbers": has_page_numbers,
            "candidates": [
                {
                    "page": page,
                    "source": "text_detector",
                    "is_toc": True,
                    "score": 0.72,
                    "has_page_numbers": has_page_numbers,
                }
                for page in unpaged
            ],
            "reason": "detected_unpaged_toc_by_text_signals",
            "classification_complete": True,
        }
    return empty_report


def detect_toc_pages_text(
    page_texts: List[str],
    max_scan_pages: int = MAX_SCAN_PAGES,
) -> Optional[List[int]]:
    """Detect TOC pages from extracted text only."""
    report = detect_toc_pages_text_report(page_texts, max_scan_pages)
    if report.get("status") == "detected":
        return list(report.get("pages") or [])
    return None


async def find_toc_pages(
    analysis: Dict[str, Any],
    file_path: str,
    model: Optional[str] = None,
) -> Optional[List[int]]:
    """Return detected TOC pages without invoking visual fallback."""
    direct_pages = _positive_pages(analysis.get("toc_pages"))
    if direct_pages:
        _store_toc_page_report(
            analysis,
            pages=direct_pages,
            has_page_numbers=_pages_have_trailing_page_numbers(
                analysis.get("page_texts") or [],
                direct_pages,
            ),
            reason="direct_toc_pages",
        )
        print(f"[TOC-PROBE] Using analysis toc_pages={direct_pages}")
        return direct_pages

    toc_page = analysis.get("toc_page") or {}
    nested_pages = _positive_pages(toc_page.get("pages"))
    if nested_pages:
        _store_toc_page_report(
            analysis,
            pages=nested_pages,
            has_page_numbers=_pages_have_trailing_page_numbers(
                analysis.get("page_texts") or [],
                nested_pages,
            ),
            reason="direct_toc_page_pages",
        )
        print(f"[TOC-PROBE] Using analysis toc_page.pages={nested_pages}")
        return nested_pages

    page_texts = analysis.get("page_texts") or []
    legacy_indices: List[int] = []
    for value in toc_page.get("page_indices") or []:
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            legacy_indices.append(index + 1)
    if legacy_indices:
        _store_toc_page_report(
            analysis,
            pages=sorted(set(legacy_indices)),
            has_page_numbers=_pages_have_trailing_page_numbers(
                page_texts,
                sorted(set(legacy_indices)),
            ),
            reason="legacy_toc_page_indices",
        )
        print(f"[TOC-PROBE] Using analysis toc_page.page_indices={legacy_indices}")
        return sorted(set(legacy_indices))

    text_pages = detect_toc_pages_text(page_texts)
    if text_pages:
        report = detect_toc_pages_text_report(page_texts)
        if report.get("status") != "detected" or list(report.get("pages") or []) != list(text_pages):
            report = _build_toc_page_report(
                pages=text_pages,
                has_page_numbers=_pages_have_trailing_page_numbers(page_texts, text_pages),
                reason="detected_by_text_toc_detector",
            )
        analysis["toc_page_detection"] = report
        analysis["toc_pages"] = list(text_pages)
        analysis["toc_page"] = {
            "has_toc_page": True,
            "pages": list(text_pages),
            "confidence": "detected",
        }
        page_type = "with_pages" if report.get("has_page_numbers") else "no_pages"
        print(f"[TOC-PROBE] Text detection found toc_pages={text_pages} type={page_type}")
        return text_pages

    print("[TOC-PROBE] No text TOC pages found; OCR/layout path owns image detection")
    return None


_TRAILING_PAGE_PATTERN = re.compile(r"(?:\.{2,}|…{1,}|[\s·]{3,})\s*\d{1,4}\s*$")
_CHAPTER_MARKER_PATTERN = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇两\d]+[章节部分篇]"
    r"|[一二三四五六七八九十]+[、.]"
    r"|(?:part|chapter)\s*\d+"
    r"|\d+(?:\.\d+){0,2}"
    r")",
    re.IGNORECASE,
)
_TOC_HEADING_PATTERN = re.compile(
    r"^(?:目录|目次|contents|table of contents|汇报提纲|提纲|agenda|outline)$",
    re.IGNORECASE,
)


def _detect_unpaged_toc_pages(
    page_texts: List[str],
    *,
    max_scan_pages: int,
) -> List[int]:
    pages: List[int] = []
    scan_limit = min(max_scan_pages, len(page_texts))
    for index in range(scan_limit):
        text = str(page_texts[index] or "")
        if _is_unpaged_toc_text(text):
            pages.append(index + 1)
            continue
        if pages:
            break
    return pages


def _is_unpaged_toc_text(text: str) -> bool:
    lines = [_normalize_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 4:
        return False
    trailing_page_lines = sum(1 for line in lines if _TRAILING_PAGE_PATTERN.search(line))
    if trailing_page_lines >= 3:
        return False

    heading_hits = sum(1 for line in lines[:8] if _TOC_HEADING_PATTERN.match(line))
    title_like = [_is_toc_title_line(line) for line in lines]
    title_count = sum(1 for value in title_like if value)
    marker_count = sum(1 for line in lines if _CHAPTER_MARKER_PATTERN.match(line))
    part_count = sum(1 for line in lines if re.match(r"^part\s*\d+", line, re.IGNORECASE))

    if heading_hits and title_count >= 3:
        return True
    if heading_hits and marker_count >= 2:
        return True
    if part_count >= 4 and title_count >= 4:
        return True
    return False


def _is_toc_title_line(line: str) -> bool:
    if len(line) < 2 or len(line) > 80:
        return False
    if line.isdigit():
        return False
    if re.match(r"^https?://", line, re.IGNORECASE):
        return False
    if re.match(r"^(page\s*)?\d+\s*/\s*\d+$", line, re.IGNORECASE):
        return False
    if _TOC_HEADING_PATTERN.match(line):
        return False
    return True


def _pages_have_trailing_page_numbers(page_texts: List[str], pages: List[int]) -> bool:
    trailing_count = 0
    standalone_number_count = 0
    dense_numbered_catalog_count = 0
    for page in pages:
        index = page - 1
        if index < 0 or index >= len(page_texts):
            continue
        lines = [_normalize_line(line) for line in str(page_texts[index] or "").splitlines()]
        trailing_count += sum(1 for line in lines if _TRAILING_PAGE_PATTERN.search(line))
        standalone_number_count += sum(1 for line in lines if re.fullmatch(r"\d{1,4}", line))
        dense_numbered_catalog_count += sum(
            1
            for line in lines
            if re.match(r"^\d{1,3}\s+\S.{2,}", line)
        )
    return (
        trailing_count >= 3
        or standalone_number_count >= 6
        or dense_numbered_catalog_count >= 10
    )


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "")).strip()


def _build_toc_page_report(
    *,
    pages: List[int],
    has_page_numbers: bool,
    reason: str,
) -> Dict[str, Any]:
    return {
        "source": "text_detector",
        "status": "detected" if pages else "not_found",
        "pages": list(pages),
        "has_page_numbers": bool(has_page_numbers),
        "candidates": [
            {
                "page": page,
                "source": "text_detector",
                "is_toc": True,
                "score": 1.0,
                "has_page_numbers": bool(has_page_numbers),
            }
            for page in pages
        ],
        "reason": reason if pages else "no_text_toc_pages",
        "classification_complete": True,
    }


def _store_toc_page_report(
    analysis: Dict[str, Any],
    *,
    pages: List[int],
    has_page_numbers: bool,
    reason: str,
) -> None:
    if not pages:
        return
    analysis["toc_page_detection"] = _build_toc_page_report(
        pages=pages,
        has_page_numbers=has_page_numbers,
        reason=reason,
    )
