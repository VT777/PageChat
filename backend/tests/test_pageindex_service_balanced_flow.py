from pathlib import Path
import sys
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_should_skip_legacy_toc_detection_when_anchor_toc_exists_and_provider_succeeded():
    analysis = {"toc_pages": [2], "toc_page": {"has_toc_page": True, "pages": [2]}}
    result = {"items": [{"title": "A"}], "prevalidated": True, "source": "toc_page_text"}

    assert PageIndexService._should_skip_legacy_toc_detection(analysis, result) is True


def test_should_not_skip_legacy_toc_detection_without_result():
    analysis = {"toc_pages": [2], "toc_page": {"has_toc_page": True, "pages": [2]}}

    assert PageIndexService._should_skip_legacy_toc_detection(analysis, None) is False


def test_service_builds_route_decision_from_state_machine():
    analysis = {
        "page_count": 62,
        "content_type": "hybrid",
        "toc_page_detection": {
            "status": "detected",
            "pages": [4],
            "has_page_numbers": False,
        },
    }

    route = PageIndexService._build_state_machine_route_decision("smart", analysis)

    assert route["requested_mode"] == "smart"
    assert route["content_type"] == "hybrid"
    assert route["selected_path"] == "visible_toc_no_pages"
    assert route["states"] == ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
    assert route["post_route_states"] == ["S7", "S8"]


def test_collect_candidates_respects_selected_visible_toc_path(monkeypatch, tmp_path):
    service = PageIndexService()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("selected visible TOC path must not run other complete TOC builders")

    async def fake_extract_toc_text(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "第一章", "page": 5, "physical_index": 5, "level": 1}
            ],
            "source": "llm_toc_page",
        }

    monkeypatch.setattr(service, "_try_balanced_provider_shortcut", forbidden)
    monkeypatch.setattr(service, "_try_text_heading_toc", forbidden)
    monkeypatch.setattr(service, "_extract_toc_text", fake_extract_toc_text)
    monkeypatch.setattr(
        service,
        "_build_text_toc_candidate",
        lambda *_args, **_kwargs: forbidden(),
    )

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": ["", "目录\n第一章 ........ 5", "正文"],
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "sample.pdf",
            page_count=10,
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert [candidate["source"] for candidate in candidates] == ["llm_toc_page"]
