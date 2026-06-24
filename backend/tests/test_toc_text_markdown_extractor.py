from pathlib import Path
import sys
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.skip(
    "legacy TOCTextMarkdownExtractor removed in unified TOC architecture",
    allow_module_level=True,
)

from pageindex.candidates.toc_text_markdown_extractor import (  # noqa: E402
    TOCTextMarkdownExtractor,
)
from pageindex.layout.document_layout import DocumentLayout, OCRLayoutPage  # noqa: E402


def _layout_page(
    *,
    page: int = 2,
    plain_text: str = "",
    markdown: str = "",
    structured_items=None,
    evidence_level: str = "text_only",
) -> DocumentLayout:
    text = plain_text or markdown
    return DocumentLayout(
        doc_id="doc-1",
        page_count=20,
        source_type="ocr",
        pages=[
            OCRLayoutPage(
                page=page,
                width=0,
                height=0,
                plain_text=text,
                lines=[],
                features={"toc_score": 0.7},
                source="ocr",
                markdown=markdown,
                structured_items=list(structured_items or []),
                source_type="ocr",
                evidence_level=evidence_level,
            )
        ],
    )


def test_extracts_markdown_heading_toc_items() -> None:
    layout = _layout_page(
        markdown="# Contents\n\n## Part I Strategy 3\n### 1.1 Scope 7\n## Part II Execution 11"
    )

    candidate = TOCTextMarkdownExtractor().extract(layout)

    assert candidate is not None
    assert candidate["source"] == "ocr_text_markdown"
    assert [item["title"] for item in candidate["items"]] == [
        "Part I Strategy",
        "1.1 Scope",
        "Part II Execution",
    ]
    assert [item["level"] for item in candidate["items"]] == [1, 2, 1]
    assert [item["page"] for item in candidate["items"]] == [3, 7, 11]
    assert candidate["evidence"]["evidence_level"] == "text_only"


def test_extracts_plain_title_page_lines() -> None:
    layout = _layout_page(
        plain_text="Contents\n1 Introduction ........ 1\n1.1 Background 4\nAppendix A 18"
    )

    candidate = TOCTextMarkdownExtractor().extract(layout)

    assert candidate is not None
    assert [item["title"] for item in candidate["items"]] == [
        "1 Introduction",
        "1.1 Background",
        "Appendix A",
    ]
    assert candidate["items"][1]["level"] == 2


def test_extracts_structured_json_items() -> None:
    layout = _layout_page(
        evidence_level="model_inferred",
        structured_items=[
            {"title": "Overview", "page": 5, "level": 1},
            {"title": "Details", "page": 8, "level": 2},
        ],
    )

    candidate = TOCTextMarkdownExtractor().extract(layout)

    assert candidate is not None
    assert candidate["items"][0]["title"] == "Overview"
    assert candidate["items"][0]["physical_index"] == 5
    assert candidate["evidence"]["evidence_level"] == "model_inferred"


def test_rejects_hallucinated_structured_title_not_present_in_source_text() -> None:
    layout = _layout_page(
        plain_text="Contents\nOverview 5",
        evidence_level="model_inferred",
        structured_items=[{"title": "Completely Invented", "page": 9, "level": 1}],
    )

    candidate = TOCTextMarkdownExtractor().extract(layout)

    assert candidate is None


def test_returns_low_confidence_reason_for_weak_text_without_page_numbers() -> None:
    layout = _layout_page(plain_text="Contents\nOverview\nDetails")

    candidate = TOCTextMarkdownExtractor().extract(layout)

    assert candidate is not None
    assert candidate["items"] == []
    assert candidate["raw_confidence"] < 0.5
    assert "no_page_numbers" in candidate["reasons"]
