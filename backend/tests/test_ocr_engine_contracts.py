from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_engines.contracts import (  # noqa: E402
    OCRDocumentResult,
    OCRLine,
    OCRPageResult,
)


def test_line_box_result_serializes_coordinates_and_text() -> None:
    result = OCRDocumentResult(
        task="toc_page",
        engine_type="paddleocr_job",
        model="PP-OCRv6",
        pages=[
            OCRPageResult(
                page_num=3,
                width=1200,
                height=1600,
                evidence_level="line_box",
                lines=[
                    OCRLine(
                        text="1. Introduction 7",
                        score=0.98,
                        box=[100, 200, 900, 238],
                        poly=[[100, 200], [900, 200], [900, 238], [100, 238]],
                    )
                ],
                raw={"source": "fixture"},
            )
        ],
        profile_version="profile-a",
        raw={"job_id": "job-1"},
    )

    payload = result.to_dict()

    assert payload["task"] == "toc_page"
    assert payload["pages"][0]["plain_text"] == "1. Introduction 7"
    assert payload["pages"][0]["lines"][0]["x0"] == 100.0
    assert payload["pages"][0]["lines"][0]["width"] == 800.0
    assert payload["pages"][0]["evidence_level"] == "line_box"
    assert payload["profile_version"] == "profile-a"


def test_text_only_result_serializes_markdown_without_lines() -> None:
    result = OCRDocumentResult(
        task="page_text",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        pages=[
            OCRPageResult(
                page_num=1,
                evidence_level="text_only",
                markdown="# Chapter 1\n\nReadable body text",
            )
        ],
    )

    payload = result.to_dict()

    assert payload["pages"][0]["plain_text"] == "# Chapter 1\n\nReadable body text"
    assert payload["pages"][0]["markdown"] == "# Chapter 1\n\nReadable body text"
    assert payload["pages"][0]["lines"] == []
    assert payload["pages"][0]["evidence_level"] == "text_only"


def test_model_inferred_result_serializes_structured_items() -> None:
    result = OCRDocumentResult(
        task="toc_page",
        engine_type="openai_compatible_ocr",
        model="qwen-vl-ocr-2025-11-20",
        pages=[
            OCRPageResult(
                page_num=2,
                evidence_level="model_inferred",
                structured_items=[
                    {"title": "Overview", "page": 5, "level": 1},
                    {"title": "Details", "page": 9, "level": 2},
                ],
            )
        ],
    )

    payload = result.to_dict()

    assert payload["pages"][0]["structured_items"] == [
        {"title": "Overview", "page": 5, "level": 1},
        {"title": "Details", "page": 9, "level": 2},
    ]
    assert payload["pages"][0]["evidence_level"] == "model_inferred"
