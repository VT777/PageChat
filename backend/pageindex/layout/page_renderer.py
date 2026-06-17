"""PDF page rendering helpers for OCR/layout processing."""

from __future__ import annotations

import base64
import hashlib
from typing import Any, Dict, List


def render_pages_to_images(
    file_path: str,
    page_indices: List[int],
    *,
    dpi: int = 150,
) -> List[Dict[str, Any]]:
    import pymupdf

    doc = pymupdf.open(file_path)
    images: List[Dict[str, Any]] = []
    try:
        zoom = dpi / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)
        for page_index in page_indices:
            if page_index < 0 or page_index >= len(doc):
                continue
            page = doc[page_index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_bytes = pix.tobytes("jpeg")
            image_base64 = base64.b64encode(image_bytes).decode("ascii")
            images.append(
                {
                    "page_index": page_index,
                    "image_base64": image_base64,
                    "width": pix.width,
                    "height": pix.height,
                    "dpi": dpi,
                    "image_format": "jpeg",
                    "image_mime_type": "image/jpeg",
                    "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
                }
            )
    finally:
        doc.close()
    return images