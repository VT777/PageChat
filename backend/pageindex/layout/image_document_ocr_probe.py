"""Low-cost OCR layout probe for image/garbled documents."""

from __future__ import annotations

from typing import Any, Dict, List

from .document_layout import DocumentLayout


class ImageDocumentOCRProbe:
    def __init__(self, max_probe_pages: int = 10) -> None:
        self.max_probe_pages = max(1, int(max_probe_pages))

    def probe(self, layout: DocumentLayout) -> Dict[str, Any]:
        probe_pages = list(range(1, min(layout.page_count, self.max_probe_pages) + 1))
        possible_toc_pages: List[int] = []
        for page in layout.pages:
            if page.page not in probe_pages:
                continue
            if float(page.features.get("toc_score") or 0.0) >= 0.5:
                possible_toc_pages.append(page.page)
        return {
            "ocr_probe_pages": probe_pages,
            "possible_toc_pages": possible_toc_pages,
            "recommended_ocr_scope": "toc_pages" if possible_toc_pages else "batched_or_full",
        }
