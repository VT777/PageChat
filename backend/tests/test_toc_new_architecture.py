from pathlib import Path
import inspect
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.fast_path.code_toc_fast_path import CodeTOCFastPath
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
            text='{"result":{"ocrResults":[{"prunedResult":{"rec_texts":["鐩綍","绗竴绔?缁 1"],"rec_scores":[0.99,0.98],"rec_boxes":[[80,80,180,120],[100,160,680,200]]}}]}}'
        )


def test_new_architecture_service_path_has_no_visual_fallback() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService._generate_pdf_index)

    assert "extract_visual_toc" not in source
    assert "falling back to targeted visual/legacy" not in source
    assert "build_balanced_toc_visual" not in source
    assert "_vlm_detect_anchors" not in source
    assert "_run_unified_toc_controller" not in source
    assert "segment_fallback" not in source
    assert "page_heading_outline" not in source


def test_new_architecture_service_uses_page_text_ocr_only() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService)

    assert '_resolve_ocr_engine("toc_page")' not in source
    assert 'task="toc_page"' not in source


def test_pageindex_service_does_not_keep_legacy_candidate_lifecycle() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService)

    forbidden = [
        "_collect_text_toc_candidates",
        "_run_unified_toc_controller",
        "_build_segment_fallback_toc",
        "_looks_like_segment_fallback_toc",
        "_is_segment_fallback_judgment",
        "_build_page_heading_outline_candidate_from_page_list",
        "segment_fallback",
        "page_heading_outline",
    ]
    for token in forbidden:
        assert token not in source


def test_code_toc_fast_path_allows_verified_bookmark_early_return() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 20,
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": "绗竴绔?缁", "level": 1, "physical_index": 3},
                    {"title": "绗簩绔?鏂规硶", "level": 1, "physical_index": 8},
                    {"title": "绗笁绔?缁撹", "level": 1, "physical_index": 14},
                ],
            },
        }
    )

    assert result is not None
    assert result["source"] == "code_toc"
    assert result["early_return_allowed"] is True
    assert result["evidence"]["pages_monotonic"] is True


def test_code_toc_fast_path_does_not_early_return_when_visible_auxiliary_catalog_is_missing() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 50,
            "toc_page_detection": {
                "status": "detected",
                "pages": [2],
                "has_page_numbers": True,
                "sections": [
                    {"kind": "main_toc", "pages": [2]},
                    {"kind": "figure_toc", "pages": [2]},
                ],
            },
            "code_toc": {
                "source": "bookmarks",
                "toc_sections": [
                    {
                        "kind": "main_toc",
                        "source": "bookmarks",
                        "items": [
                            {"title": "Overview", "level": 1, "physical_index": 7},
                            {"title": "Current State", "level": 1, "physical_index": 10},
                            {"title": "Challenges", "level": 1, "physical_index": 16},
                            {"title": "Framework", "level": 1, "physical_index": 25},
                            {"title": "Practice", "level": 1, "physical_index": 40},
                            {"title": "Outlook", "level": 1, "physical_index": 47},
                        ],
                    }
                ],
                "items": [
                    {"title": "Overview", "level": 1, "physical_index": 7},
                    {"title": "Current State", "level": 1, "physical_index": 10},
                    {"title": "Challenges", "level": 1, "physical_index": 16},
                    {"title": "Framework", "level": 1, "physical_index": 25},
                    {"title": "Practice", "level": 1, "physical_index": 40},
                    {"title": "Outlook", "level": 1, "physical_index": 47},
                ],
            },
        }
    )

    assert result is not None
    assert result["early_return_allowed"] is False
    assert "missing_visible_auxiliary_catalog:figure_toc" in result["reasons"]


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


def test_page_mapping_verifier_penalizes_many_items_collapsed_to_one_page() -> None:
    from pageindex.judge.page_mapping_verifier import PageMappingVerifier

    items = [
        {"title": f"Section {index}", "physical_index": 1}
        for index in range(12)
    ]

    report = PageMappingVerifier().verify({"source": "code_toc", "items": items}, page_count=50)

    assert report["page_collapse"] is True
    assert report["page_mapping_score"] < 0.5
