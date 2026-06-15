"""Normalize unified OCR engine outputs into DocumentLayout."""

from __future__ import annotations

from typing import Iterable, List

from app.services.ocr_engines.contracts import OCRDocumentResult, OCRPageResult
from pageindex.layout.document_layout import (
    DocumentLayout,
    OCRLayoutLine,
    OCRLayoutPage,
    PPOCRPageResult,
    _page_features,
)


def normalize_ocr_document(
    ocr_result: OCRDocumentResult | Iterable[PPOCRPageResult],
    *,
    doc_id: str,
    page_count: int,
) -> DocumentLayout:
    if isinstance(ocr_result, OCRDocumentResult):
        pages = [_normalize_contract_page(page) for page in ocr_result.pages]
    else:
        pages = [_normalize_ppocr_page(page) for page in ocr_result]
    return DocumentLayout(
        doc_id=doc_id,
        page_count=page_count,
        source_type="ocr",
        pages=sorted(pages, key=lambda page: page.page),
    )


def _normalize_contract_page(page: OCRPageResult) -> OCRLayoutPage:
    lines = [_line_from_contract(line) for line in page.lines]
    markdown = page.markdown.strip()
    plain_text = page.plain_text
    if not lines and markdown:
        lines = _synthesize_low_confidence_lines(markdown)
    if not plain_text and page.structured_items:
        plain_text = _structured_plain_text(page.structured_items)
    return OCRLayoutPage(
        page=page.page_num,
        width=page.width,
        height=page.height,
        plain_text=plain_text,
        lines=sorted(lines, key=lambda line: (line.y0, line.x0)),
        features=_page_features(page.width, page.height, lines),
        source="ocr",
        markdown=markdown,
        structured_items=[dict(item) for item in page.structured_items],
        source_type="ocr",
        evidence_level=page.evidence_level,
    )


def _normalize_ppocr_page(page: PPOCRPageResult) -> OCRLayoutPage:
    lines = sorted(page.lines, key=lambda line: (line.y0, line.x0))
    return OCRLayoutPage(
        page=page.page_num,
        width=page.width,
        height=page.height,
        plain_text=page.plain_text,
        lines=lines,
        features=_page_features(page.width, page.height, lines),
        source="ocr",
        source_type="ocr",
        evidence_level="line_box",
    )


def _line_from_contract(line) -> OCRLayoutLine:
    return OCRLayoutLine(
        text=line.text,
        score=line.score,
        box=list(line.box),
        poly=[list(point) for point in line.poly],
    )


def _synthesize_low_confidence_lines(text: str) -> List[OCRLayoutLine]:
    lines: List[OCRLayoutLine] = []
    for index, raw_line in enumerate(str(text or "").splitlines()):
        if not raw_line.strip():
            continue
        y0 = index * 20
        lines.append(
            OCRLayoutLine(
                text=raw_line.strip(),
                score=0.35,
                box=[0, y0, 0, y0 + 16],
            )
        )
    return lines


def _structured_plain_text(items: list[dict]) -> str:
    parts: List[str] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        page = item.get("page")
        if title and page is not None:
            parts.append(f"{title} {page}")
        elif title:
            parts.append(title)
    return "\n".join(parts).strip()

