from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_engines.contracts import (  # noqa: E402
    OCRDocumentResult,
    OCRLine,
    OCRPageResult,
)
from pageindex.layout.document_layout import OCRLayoutLine, PPOCRPageResult  # noqa: E402
from pageindex.layout.ocr_normalizer import normalize_ocr_document  # noqa: E402


def test_normalizes_line_box_ocr_to_document_layout() -> None:
    result = OCRDocumentResult(
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        pages=[
            OCRPageResult(
                page_num=2,
                width=800,
                height=1000,
                evidence_level="line_box",
                lines=[OCRLine(text="Contents", score=0.99, box=[100, 100, 300, 130])],
            )
        ],
    )

    layout = normalize_ocr_document(result, doc_id="doc-1", page_count=10)

    page = layout.pages[0]
    assert layout.source_type == "ocr"
    assert page.page == 2
    assert page.evidence_level == "line_box"
    assert page.source_type == "ocr"
    assert page.lines[0].text == "Contents"
    assert page.plain_text == "Contents"


def test_normalizes_markdown_ocr_without_synthesizing_high_quality_boxes() -> None:
    result = OCRDocumentResult(
        task="page_text",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        pages=[OCRPageResult(page_num=1, evidence_level="text_only", markdown="# Title\nBody")],
    )

    layout = normalize_ocr_document(result, doc_id="doc-1", page_count=1)

    page = layout.pages[0]
    assert page.markdown == "# Title\nBody"
    assert page.evidence_level == "text_only"
    assert [line.text for line in page.lines] == ["# Title", "Body"]
    assert all(line.score == 0.35 for line in page.lines)


def test_normalizes_structured_model_inferred_items() -> None:
    result = OCRDocumentResult(
        task="toc_page",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        pages=[
            OCRPageResult(
                page_num=3,
                evidence_level="model_inferred",
                structured_items=[{"title": "Intro", "page": 1, "level": 1}],
            )
        ],
    )

    layout = normalize_ocr_document(result, doc_id="doc-1", page_count=3)

    page = layout.pages[0]
    assert page.structured_items == [{"title": "Intro", "page": 1, "level": 1}]
    assert page.evidence_level == "model_inferred"
    assert page.plain_text == "Intro 1"


def test_normalizer_preserves_legacy_ppocr_page_result_compatibility() -> None:
    layout = normalize_ocr_document(
        [
            PPOCRPageResult(
                page_num=1,
                width=800,
                height=1000,
                lines=[OCRLayoutLine(text="Contents", box=[100, 100, 300, 130], score=0.99)],
            )
        ],
        doc_id="doc-1",
        page_count=1,
    )

    page = layout.pages[0]
    assert page.evidence_level == "line_box"
    assert page.source_type == "ocr"
    assert page.lines[0].text == "Contents"
