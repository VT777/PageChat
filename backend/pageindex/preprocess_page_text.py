"""Build PageTextMap before TOC routing."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from pageindex.page_text_map import PageTextEntry, PageTextMap


PAGE_TEXT_OCR_PROMPT = "Recognize all readable text in natural reading order."


def infer_content_type(analysis: Mapping[str, Any]) -> str:
    page_count = max(1, int(analysis.get("page_count") or 0))
    text_coverage = float(analysis.get("text_coverage") or 0.0)
    image_coverage = float(analysis.get("image_coverage") or 0.0)
    image_only_pages = list(analysis.get("image_only_pages") or [])
    garbled_pages = list(analysis.get("garbled_pages") or [])
    image_only_ratio = len(image_only_pages) / page_count
    garbled_ratio = len(garbled_pages) / page_count
    text_quality = str(analysis.get("text_layer_quality") or "").lower()
    sparse_edge_images = (
        text_quality == "reliable"
        and text_coverage >= 0.95
        and not garbled_pages
        and len(image_only_pages) / page_count <= 0.05
        and all(page in {0, page_count - 1} for page in image_only_pages)
    )

    if (
        analysis.get("is_image_only_pdf")
        or analysis.get("is_garbled_pdf")
        or image_only_ratio >= 0.9
        or garbled_ratio >= 0.5
        or (text_coverage <= 0.05 and image_coverage >= 0.5)
        or text_quality == "garbled"
    ):
        return "ocr"
    if sparse_edge_images:
        return "text"
    if image_only_pages or garbled_pages or text_quality in {"partial", "noisy"}:
        return "hybrid"
    return "text"


async def preprocess_page_text_map(
    file_path: str | Path,
    analysis: Dict[str, Any],
    *,
    ocr_pages_fn=None,
    content_type: Optional[str] = None,
    prompt: str = PAGE_TEXT_OCR_PROMPT,
) -> PageTextMap:
    """Convert PDF analysis output into canonical per-page text.

    ``ocr_pages_fn`` is injected by the service layer. It receives 0-indexed page
    indices and must return OCR text keyed by 1-indexed physical page numbers.
    """

    page_count = int(analysis.get("page_count") or 0)
    page_list = list(analysis.get("page_list") or [])
    if page_count <= 0:
        page_count = len(page_list)
    content_type = content_type or infer_content_type(analysis)
    if content_type not in {"text", "ocr", "hybrid"}:
        raise ValueError(f"Unsupported content_type: {content_type}")

    if content_type == "text":
        page_map = _build_from_pdf_text(page_list, page_count=page_count)
        _attach_to_analysis(analysis, page_map, content_type=content_type)
        return page_map

    pages_to_ocr = _pages_to_ocr(analysis, content_type=content_type, page_count=page_count)
    if pages_to_ocr and ocr_pages_fn is None:
        raise ValueError("ocr_pages_fn is required for OCR-backed PageTextMap preprocessing")

    ocr_by_page = await _call_ocr_pages(
        ocr_pages_fn,
        file_path,
        pages_to_ocr,
        prompt=prompt,
        analysis=analysis,
    )
    entries = _merge_entries(
        page_list=page_list,
        page_count=page_count,
        content_type=content_type,
        pages_to_ocr=pages_to_ocr,
        ocr_by_page=ocr_by_page,
    )
    page_map = PageTextMap(entries)
    _attach_to_analysis(analysis, page_map, content_type=content_type)
    return page_map


def _build_from_pdf_text(page_list: List[Any], *, page_count: int) -> PageTextMap:
    entries = []
    for index in range(1, page_count + 1):
        original = _page_list_text(page_list, index)
        entries.append(
            PageTextEntry(
                physical_page=index,
                text=original,
                source="pdf_text",
                quality="reliable" if original.strip() else "low",
                ocr_used=False,
            )
        )
    return PageTextMap(entries)


def _pages_to_ocr(analysis: Mapping[str, Any], *, content_type: str, page_count: int) -> List[int]:
    if content_type == "ocr":
        return list(range(page_count))
    bad_pages = set()
    if content_type == "hybrid":
        for index in range(page_count):
            page_info = _page_info(analysis, index)
            if int(page_info.get("image_count") or 0) > 0:
                bad_pages.add(index)
    for key in ("image_only_pages", "garbled_pages"):
        for page in analysis.get(key) or []:
            try:
                page_idx = int(page)
            except Exception:
                continue
            if 0 <= page_idx < page_count:
                bad_pages.add(page_idx)
    page_list = list(analysis.get("page_list") or [])
    for index in range(page_count):
        if not _page_list_text(page_list, index + 1).strip():
            page_info = _page_info(analysis, index)
            if page_info.get("image_count", 0) or page_info.get("type") in {"image_only", "garbled", "empty"}:
                bad_pages.add(index)
    return sorted(bad_pages)


async def _call_ocr_pages(
    ocr_pages_fn,
    file_path: str | Path,
    page_indices: Iterable[int],
    *,
    prompt: str,
    analysis: Dict[str, Any],
) -> Dict[int, str]:
    page_indices = list(page_indices)
    if not page_indices:
        return {}
    result = ocr_pages_fn(file_path, page_indices, prompt=prompt, analysis=analysis)
    if inspect.isawaitable(result):
        result = await result
    return _normalize_ocr_result(result)


def _normalize_ocr_result(result: Any) -> Dict[int, str]:
    if isinstance(result, dict):
        if "ocr_pages" in result:
            return _normalize_ocr_result(result.get("ocr_pages") or [])
        normalized = {}
        for key, value in result.items():
            try:
                page_num = int(key)
            except Exception:
                continue
            if isinstance(value, dict):
                text = str(value.get("text") or value.get("plain_text") or "")
            else:
                text = str(value or "")
            normalized[page_num] = text
        return normalized

    normalized = {}
    for item in result or []:
        if not isinstance(item, dict):
            continue
        page_num = int(item.get("page_num") or 0)
        if page_num <= 0:
            continue
        normalized[page_num] = str(item.get("text") or item.get("plain_text") or "")
    return normalized


def _merge_entries(
    *,
    page_list: List[Any],
    page_count: int,
    content_type: str,
    pages_to_ocr: List[int],
    ocr_by_page: Mapping[int, str],
) -> List[PageTextEntry]:
    ocr_indices = set(pages_to_ocr)
    entries: List[PageTextEntry] = []
    for index in range(1, page_count + 1):
        original = _page_list_text(page_list, index)
        ocr_text = str(ocr_by_page.get(index) or "")
        if index - 1 in ocr_indices:
            if ocr_text.strip():
                text = ocr_text
                source = "ocr"
                quality = "reliable"
                ocr_used = True
                diagnostics = {
                    "ocr_requested": True,
                    "original_text_chars": len(original),
                    "ocr_text_chars": len(ocr_text),
                }
            elif content_type == "hybrid" and original.strip():
                text = original
                source = "pdf_text_fallback"
                quality = "partial"
                ocr_used = False
                diagnostics = {
                    "ocr_requested": True,
                    "ocr_fallback": "pdf_text",
                    "original_text_chars": len(original),
                    "ocr_text_chars": 0,
                }
            else:
                text = ""
                source = "ocr"
                quality = "low"
                ocr_used = True
                diagnostics = {
                    "ocr_requested": True,
                    "original_text_chars": len(original),
                    "ocr_text_chars": 0,
                }
            entries.append(
                PageTextEntry(
                    physical_page=index,
                    text=text,
                    source=source,
                    quality=quality,
                    ocr_used=ocr_used,
                    diagnostics=diagnostics,
                )
            )
            continue

        entries.append(
            PageTextEntry(
                physical_page=index,
                text=original,
                source="pdf_text",
                quality="reliable" if original.strip() else "low",
                ocr_used=False,
            )
        )
    return entries


def _attach_to_analysis(analysis: Dict[str, Any], page_map: PageTextMap, *, content_type: str) -> None:
    diagnostics = page_map.to_diagnostics()
    analysis["content_type"] = content_type
    analysis["page_text_map"] = page_map
    analysis["page_text_map_diagnostics"] = diagnostics
    analysis["page_text_map_ocr_pages"] = diagnostics["ocr_pages"]
    analysis["page_text_map_ocr_completed"] = bool(diagnostics["ocr_pages"])
    analysis["page_list"] = page_map.to_page_list()
    analysis["page_texts"] = page_map.page_texts()


def _page_list_text(page_list: List[Any], physical_page: int) -> str:
    index = physical_page - 1
    if index < 0 or index >= len(page_list):
        return ""
    page = page_list[index]
    if isinstance(page, (list, tuple)) and page:
        return str(page[0] or "")
    return str(page or "")


def _page_info(analysis: Mapping[str, Any], index: int) -> Dict[str, Any]:
    pages = analysis.get("pages") or []
    if 0 <= index < len(pages) and isinstance(pages[index], dict):
        return pages[index]
    return {}
