"""Low-cost TOC page detection for the new layout-first pipeline.

This module intentionally does not call image-model detection. Image-only,
garbled, and low-text-quality documents are routed to the PP-OCR layout path by
``pageindex.router``; this detector only reuses already available text/analysis
signals.
"""

from __future__ import annotations

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


def detect_toc_pages_text(
    page_texts: List[str],
    max_scan_pages: int = MAX_SCAN_PAGES,
) -> Optional[List[int]]:
    """Detect TOC pages from extracted text only."""
    if not page_texts:
        return None

    from pageindex.pdf_analyzer import _detect_toc_pages

    has_toc, toc_indices, confidence, _ = _detect_toc_pages(
        page_texts,
        max_scan_pages,
    )
    if has_toc and confidence >= 0.5:
        return [idx + 1 for idx in toc_indices]
    return None


async def find_toc_pages(
    analysis: Dict[str, Any],
    file_path: str,
    model: Optional[str] = None,
) -> Optional[List[int]]:
    """Return detected TOC pages without invoking visual fallback."""
    direct_pages = _positive_pages(analysis.get("toc_pages"))
    if direct_pages:
        print(f"[TOC-PROBE] Using analysis toc_pages={direct_pages}")
        return direct_pages

    toc_page = analysis.get("toc_page") or {}
    nested_pages = _positive_pages(toc_page.get("pages"))
    if nested_pages:
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
        print(f"[TOC-PROBE] Using analysis toc_page.page_indices={legacy_indices}")
        return sorted(set(legacy_indices))

    text_pages = detect_toc_pages_text(page_texts)
    if text_pages:
        print(f"[TOC-PROBE] Text detection found toc_pages={text_pages}")
        return text_pages

    print("[TOC-PROBE] No text TOC pages found; OCR/layout path owns image detection")
    return None
