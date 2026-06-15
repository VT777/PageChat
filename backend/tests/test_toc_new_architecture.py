from pathlib import Path
import inspect
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.fast_path.code_toc_fast_path import CodeTOCFastPath
from pageindex.judge.toc_judge import TOCJudge
from pageindex.layout.document_layout import (
    DocumentLayoutBuilder,
    OCRLayoutLine,
    PPOCRPageResult,
)
from pageindex.layout.image_document_ocr_probe import ImageDocumentOCRProbe
from pageindex.layout.ppocr_client import PPOCRClient
from pageindex.candidates.ocr_toc_page_extractor import OCRTOCPageExtractor
from pageindex.pipeline.toc_pipeline_controller import TOCPipelineController
from pageindex.router import PATH_PPOCR_LAYOUT, decide_extraction_path
from app.services.pageindex_service import PageIndexService
import app.services.pageindex_service as pageindex_service_module


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


class FakeHTTPSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(payload={"data": {"jobId": "job-1"}})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if url.endswith("/job-1"):
            return FakeResponse(
                payload={
                    "data": {
                        "state": "done",
                        "extractProgress": {"extractedPages": 1},
                        "resultUrl": {"jsonUrl": "https://example.test/result.jsonl"},
                    }
                }
            )
        return FakeResponse(
            text='{"result":{"ocrResults":[{"prunedResult":{"rec_texts":["目录","第一章 绪论 1"],"rec_scores":[0.99,0.98],"rec_boxes":[[80,80,180,120],[100,160,680,200]]}}]}}'
        )


def test_router_uses_ppocr_layout_for_image_only_documents() -> None:
    decision = decide_extraction_path(
        {
            "page_count": 80,
            "text_coverage": 0.0,
            "is_image_only_pdf": True,
            "is_garbled_pdf": False,
            "text_quality": {"meaningful_ratio": 0.0},
        },
        mode="smart",
    )

    assert decision["path"] == PATH_PPOCR_LAYOUT
    assert "visual" not in decision["alternatives"]


def test_router_uses_ppocr_layout_for_image_only_documents_even_in_fast_mode() -> None:
    decision = decide_extraction_path(
        {
            "page_count": 6,
            "text_coverage": 0.0,
            "is_image_only_pdf": True,
            "is_garbled_pdf": False,
            "text_quality": {"meaningful_ratio": 0.0},
        },
        mode="fast",
    )

    assert decision["path"] == PATH_PPOCR_LAYOUT


def test_router_uses_ppocr_layout_for_garbled_documents() -> None:
    decision = decide_extraction_path(
        {
            "page_count": 30,
            "text_coverage": 0.2,
            "is_image_only_pdf": False,
            "is_garbled_pdf": True,
            "text_quality": {"meaningful_ratio": 0.05},
        },
        mode="smart",
    )

    assert decision["path"] == PATH_PPOCR_LAYOUT


def test_new_architecture_service_path_has_no_visual_fallback() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService._generate_index_v2)

    assert "extract_visual_toc" not in source
    assert "falling back to targeted visual/legacy" not in source
    assert "build_balanced_toc_visual" not in source
    assert "_vlm_detect_anchors" not in source
    assert "balanced_toc" not in source


def test_code_toc_fast_path_allows_verified_bookmark_early_return() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 20,
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": "第一章 绪论", "level": 1, "physical_index": 3},
                    {"title": "第二章 方法", "level": 1, "physical_index": 8},
                    {"title": "第三章 结论", "level": 1, "physical_index": 14},
                ],
            },
        }
    )

    assert result is not None
    assert result["source"] == "code_toc"
    assert result["early_return_allowed"] is True
    assert result["evidence"]["pages_monotonic"] is True


def test_code_toc_fast_path_never_early_returns_weak_regex() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 100,
            "code_toc": {
                "source": "regex",
                "items": [
                    {"title": "2024", "level": 1, "physical_index": 2024},
                    {"title": "2025", "level": 1, "physical_index": 2025},
                    {"title": "2026", "level": 1, "physical_index": 2026},
                ],
            },
        }
    )

    assert result is None


def test_code_toc_fast_path_rejects_unverified_regex_candidate() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 20,
            "code_toc": {
                "source": "regex",
                "items": [
                    {"title": "1 Introduction", "level": 1, "physical_index": 3},
                    {"title": "2 Method", "level": 1, "physical_index": 8},
                ],
                "quality": {"verified": False, "score": 0.2},
            },
        }
    )

    assert result is None


def test_ppocr_client_submits_local_file_and_parses_jsonl(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    session = FakeHTTPSession()

    results = PPOCRClient(
        token="token-1",
        session=session,
        poll_interval_seconds=0,
    ).recognize_pages(str(pdf_path))

    assert session.posts[0][0].endswith("/api/v2/ocr/jobs")
    assert session.posts[0][1]["data"]["model"] == "PP-OCRv6"
    assert results[0].page_num == 1
    assert "第一章 绪论" in results[0].plain_text


def test_document_layout_builder_derives_page_features() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=1,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=1,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="目录", score=0.99, box=[350, 60, 450, 100]),
                    OCRLayoutLine(text="第一章 绪论", score=0.98, box=[100, 160, 420, 200]),
                    OCRLayoutLine(text="1", score=0.98, box=[720, 160, 750, 200]),
                ],
            )
        ],
    )

    page = layout.pages[0]
    assert page.source == "ocr"
    assert page.features["toc_score"] > 0.5
    assert page.features["right_aligned_number_count"] == 1


def test_image_document_ocr_probe_limits_pages_and_detects_toc() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=20,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=3,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="目录", score=0.99, box=[350, 60, 450, 100]),
                    OCRLayoutLine(text="第一章 绪论", score=0.98, box=[100, 160, 420, 200]),
                    OCRLayoutLine(text="1", score=0.98, box=[720, 160, 750, 200]),
                ],
            )
        ],
    )

    probe = ImageDocumentOCRProbe(max_probe_pages=5).probe(layout)

    assert probe["ocr_probe_pages"] == [1, 2, 3, 4, 5]
    assert probe["possible_toc_pages"] == [3]
    assert probe["recommended_ocr_scope"] == "toc_pages"


def test_ocr_toc_page_extractor_extracts_right_aligned_page_numbers() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=30,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=2,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="目录", score=0.99, box=[350, 60, 450, 100]),
                    OCRLayoutLine(text="第一章 绪论", score=0.98, box=[100, 160, 420, 200]),
                    OCRLayoutLine(text="1", score=0.98, box=[720, 160, 750, 200]),
                    OCRLayoutLine(text="1.1 背景", score=0.98, box=[140, 220, 420, 260]),
                    OCRLayoutLine(text="3", score=0.98, box=[720, 220, 750, 260]),
                ],
            )
        ],
    )

    candidate = OCRTOCPageExtractor().extract(layout)

    assert candidate["source"] == "ocr_toc_page"
    assert [item["title"] for item in candidate["items"]] == ["第一章 绪论", "1.1 背景"]
    assert candidate["items"][0]["page"] == 1
    assert candidate["items"][0]["physical_index"] is None
    assert candidate["items"][1]["level"] == 2


def test_ocr_toc_page_extractor_accepts_dotted_page_number_lines() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=30,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=1,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="目录", score=0.99, box=[100, 60, 200, 100]),
                    OCRLayoutLine(text="第一章 绪论", score=0.98, box=[100, 160, 420, 200]),
                    OCRLayoutLine(text="..2", score=0.98, box=[620, 160, 680, 200]),
                    OCRLayoutLine(text="第二章 方法..", score=0.98, box=[100, 220, 420, 260]),
                    OCRLayoutLine(text="… 4", score=0.98, box=[620, 220, 680, 260]),
                ],
            )
        ],
    )

    candidate = OCRTOCPageExtractor().extract(layout)

    assert candidate is not None
    assert [item["page"] for item in candidate["items"]] == [2, 4]
    assert [item["title"] for item in candidate["items"]] == ["第一章 绪论", "第二章 方法"]


def test_ocr_toc_page_extractor_groups_visual_line_fragments() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=30,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=2,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="Contents", score=0.99, box=[320, 60, 450, 100]),
                    OCRLayoutLine(text="1", score=0.98, box=[100, 160, 120, 200]),
                    OCRLayoutLine(text="Introduction", score=0.98, box=[135, 162, 320, 198]),
                    OCRLayoutLine(text="5", score=0.98, box=[720, 161, 740, 199]),
                ],
            )
        ],
    )

    candidate = OCRTOCPageExtractor().extract(layout)

    assert candidate is not None
    assert candidate["items"][0]["title"] == "1 Introduction"
    assert candidate["items"][0]["page"] == 5


def test_ocr_toc_page_extractor_uses_stable_right_page_number_column() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=60,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=2,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="Contents", score=0.99, box=[320, 60, 450, 100]),
                    OCRLayoutLine(text="2024 Market Review", score=0.98, box=[100, 160, 420, 200]),
                    OCRLayoutLine(text="12", score=0.98, box=[720, 160, 750, 200]),
                    OCRLayoutLine(text="2025 Outlook", score=0.98, box=[100, 220, 420, 260]),
                    OCRLayoutLine(text="18", score=0.98, box=[720, 220, 750, 260]),
                ],
            )
        ],
    )

    candidate = OCRTOCPageExtractor().extract(layout)

    assert candidate is not None
    assert [item["title"] for item in candidate["items"]] == [
        "2024 Market Review",
        "2025 Outlook",
    ]
    assert [item["page"] for item in candidate["items"]] == [12, 18]


def test_ocr_toc_page_extractor_joins_cross_line_titles() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=80,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=3,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="Contents", score=0.99, box=[320, 60, 450, 100]),
                    OCRLayoutLine(text="2 Long title about", score=0.98, box=[100, 160, 420, 196]),
                    OCRLayoutLine(text="market structure", score=0.98, box=[128, 198, 420, 234]),
                    OCRLayoutLine(text="21", score=0.98, box=[720, 198, 750, 234]),
                ],
            )
        ],
    )

    candidate = OCRTOCPageExtractor().extract(layout)

    assert candidate is not None
    assert candidate["items"][0]["title"] == "2 Long title about market structure"
    assert candidate["items"][0]["page"] == 21


def test_ocr_toc_page_extractor_keeps_logical_and_physical_pages_separate() -> None:
    layout = DocumentLayoutBuilder().build(
        doc_id="doc-1",
        page_count=100,
        ppocr_pages=[
            PPOCRPageResult(
                page_num=4,
                width=800,
                height=1000,
                lines=[
                    OCRLayoutLine(text="Contents", score=0.99, box=[320, 60, 450, 100]),
                    OCRLayoutLine(text="Chapter One", score=0.98, box=[100, 160, 420, 200]),
                    OCRLayoutLine(text="1", score=0.98, box=[720, 160, 750, 200]),
                ],
            )
        ],
    )

    candidate = OCRTOCPageExtractor().extract(layout)

    assert candidate is not None
    assert candidate["items"][0]["page"] == 1
    assert candidate["items"][0]["physical_index"] is None
    assert candidate["items"][0]["source_page"] == 4


def test_toc_judge_prefers_verified_code_toc_over_ocr_candidate() -> None:
    judged = TOCJudge().select(
        [
            {
                "candidate_id": "ocr-1",
                "source": "ocr_toc_page",
                "cost_level": "medium",
                "raw_confidence": 0.95,
                "items": [{"title": "OCR", "physical_index": 5}],
                "evidence": {"page_monotonic": True},
            },
            {
                "candidate_id": "code-1",
                "source": "code_toc",
                "cost_level": "low",
                "raw_confidence": 0.9,
                "items": [{"title": "Bookmark", "physical_index": 3}],
                "evidence": {"early_return_allowed": True},
            },
        ]
    )

    assert judged["source"] == "code_toc"
    assert judged["items"][0]["title"] == "Bookmark"
    assert judged["rejected_candidates"][0]["source"] == "ocr_toc_page"


def test_pipeline_controller_returns_verified_code_toc_without_ocr_or_vlm() -> None:
    result = TOCPipelineController().generate(
        pdf_path="dummy.pdf",
        analysis={
            "page_count": 20,
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": "第一章 绪论", "level": 1, "physical_index": 3},
                    {"title": "第二章 方法", "level": 1, "physical_index": 8},
                    {"title": "第三章 结论", "level": 1, "physical_index": 14},
                ],
            },
        },
    )

    assert result["status"] == "ok"
    assert result["source"] == "code_toc"
    assert result["evidence"]["early_return_allowed"] is True


def test_service_accepts_ocr_toc_page_as_prevalidated_result() -> None:
    result = {
        "source": "ocr_toc_page",
        "prevalidated": True,
        "items": [{"title": "第一章 绪论", "physical_index": 3}],
    }

    assert PageIndexService._is_prevalidated_outline_result(result) is True
