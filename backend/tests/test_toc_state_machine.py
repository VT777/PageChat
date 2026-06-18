import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _plan(analysis: dict, requested_mode: str = "smart") -> dict:
    from pageindex.pipeline.toc_state_machine import TocStateMachine

    return TocStateMachine().plan(analysis, requested_mode=requested_mode).to_dict()


def test_state_machine_accepts_high_quality_embedded_toc() -> None:
    plan = _plan(
        {
            "page_count": 20,
            "content_type": "text",
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": f"Chapter {idx}", "physical_index": idx}
                    for idx in range(1, 17)
                ],
            },
        }
    )

    assert plan["selected_path"] == "embedded_toc"
    assert plan["execution_mode"] == "fast"
    assert plan["states"] == ["S0", "S1", "S2", "S5", "S6"]
    assert plan["fallbacks"] == []


def test_state_machine_rejects_sparse_bookmark_outline_when_visible_toc_exists() -> None:
    plan = _plan(
        {
            "page_count": 50,
            "content_type": "text",
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": f"Section {idx}", "physical_index": idx + 3}
                    for idx in range(1, 20)
                ],
            },
            "toc_page_detection": {
                "status": "detected",
                "pages": [5],
                "has_page_numbers": True,
            },
        }
    )

    assert plan["selected_path"] == "visible_toc_with_pages"
    assert plan["fallbacks"][0]["reason"] == "embedded_toc_rejected"


def test_state_machine_falls_back_from_failed_s2_to_visible_toc_with_pages() -> None:
    plan = _plan(
        {
            "page_count": 40,
            "content_type": "text",
            "code_toc": {
                "source": "regex",
                "items": [
                    {"title": "2024", "physical_index": 2024},
                    {"title": "2025", "physical_index": 2025},
                    {"title": "2026", "physical_index": 2026},
                ],
            },
            "toc_page_detection": {
                "status": "detected",
                "pages": [2, 3],
                "has_page_numbers": True,
            },
        }
    )

    assert plan["selected_path"] == "visible_toc_with_pages"
    assert "S3" in plan["states"]
    assert plan["fallbacks"]
    assert plan["fallbacks"][0]["from"] == "S2"
    assert plan["fallbacks"][0]["to"] == "S3"


def test_state_machine_routes_no_page_number_toc_separately() -> None:
    plan = _plan(
        {
            "page_count": 62,
            "content_type": "hybrid",
            "toc_page_detection": {
                "status": "detected",
                "pages": [4],
                "has_page_numbers": False,
            },
        }
    )

    assert plan["content_type"] == "hybrid"
    assert plan["preprocess_strategy"] == "ocr_selected_pages"
    assert plan["selected_path"] == "visible_toc_no_pages"


def test_state_machine_routes_missing_toc_to_content_outline() -> None:
    plan = _plan(
        {
            "page_count": 28,
            "content_type": "text",
            "toc_page_detection": {"status": "not_found", "pages": []},
        }
    )

    assert plan["selected_path"] == "content_outline"
    assert plan["states"] == ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]


def test_state_machine_keeps_enrich_out_of_toc_route() -> None:
    plan = _plan(
        {
            "page_count": 44,
            "content_type": "ocr",
            "toc_page_detection": {
                "status": "detected",
                "pages": [2],
                "has_page_numbers": True,
            },
        }
    )

    assert plan["preprocess_strategy"] == "ocr_full_document"
    assert plan["selected_path"] == "visible_toc_with_pages"
    assert "S8" not in plan["states"]
    assert plan["post_route_states"] == ["S7", "S8"]
