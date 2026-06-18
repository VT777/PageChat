from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
from pageindex.router import (
    PATH_HIERARCHICAL,
    PATH_TOC_PAGE,
    decide_extraction_path,
    normalize_confidence,
)


def test_route_smart_escalates_when_unparseable_pages_reach_threshold() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "smart",
        {
            "page_count": 60,
            "content_type": "ocr",
            "toc_page_detection": {
                "status": "detected",
                "pages": [2],
                "has_page_numbers": True,
            },
        },
    )
    assert route["execution_mode"] == "balanced"
    assert route["selected_path"] == "visible_toc_with_pages"


def test_route_smart_escalates_when_unparseable_ratio_exceeds_threshold() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "smart",
        {
            "page_count": 80,
            "content_type": "hybrid",
            "toc_page_detection": {
                "status": "detected",
                "pages": [4],
                "has_page_numbers": False,
            },
        },
    )
    assert route["preprocess_strategy"] == "ocr_selected_pages"
    assert route["selected_path"] == "visible_toc_no_pages"


def test_route_fast_does_not_auto_escalate_when_ratio_high() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "fast",
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
        },
    )
    assert route["execution_mode"] == "fast"
    assert route["selected_path"] == "embedded_toc"


def test_route_smart_keeps_fast_when_unparseable_ratio_equals_threshold() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "smart",
        {
            "page_count": 28,
            "content_type": "text",
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": f"Section {idx}", "physical_index": idx}
                    for idx in range(1, 23)
                ],
            },
        },
    )
    assert route["execution_mode"] == "fast"
    assert route["selected_path"] == "embedded_toc"


def test_route_keeps_fast_for_good_pre_analysis() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "fast",
        {
            "page_count": 30,
            "content_type": "text",
            "toc_page_detection": {"status": "not_found", "pages": []},
        },
    )
    assert route["execution_mode"] == "fast"
    assert route["selected_path"] == "content_outline"


def test_route_keeps_balanced_when_requested_balanced() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "balanced",
        {
            "page_count": 70,
            "content_type": "text",
            "toc_page_detection": {"status": "not_found", "pages": []},
        },
    )
    assert route["execution_mode"] == "balanced"
    assert route["selected_path"] == "content_outline"


def test_route_smart_defaults_to_fast_execution() -> None:
    route = PageIndexService._build_state_machine_route_decision(
        "smart",
        {
            "page_count": 70,
            "content_type": "text",
            "toc_page_detection": {"status": "not_found", "pages": []},
        },
    )
    assert route["requested_mode"] == "smart"
    assert route["execution_mode"] == "balanced"
    assert route["selected_path"] == "content_outline"


def test_router_normalizes_string_toc_confidence() -> None:
    assert normalize_confidence("anchor") == 0.7
    assert normalize_confidence("detected") == 0.7
    assert normalize_confidence("high") == 0.9
    assert normalize_confidence(0.62) == 0.62


def test_router_accepts_anchor_confidence_without_type_error() -> None:
    decision = decide_extraction_path(
        {
            "page_count": 201,
            "text_coverage": 1.0,
            "is_image_only_pdf": False,
            "is_garbled_pdf": False,
            "text_quality": {"meaningful_ratio": 1.0},
            "chapter_dividers": list(range(5, 105, 5)),
            "toc_page": {
                "has_toc_page": True,
                "pages": [2],
                "confidence": "anchor",
            },
        },
        mode="smart",
    )

    assert decision["path"] == PATH_TOC_PAGE


def test_router_does_not_choose_batch_for_slide_outline_candidate() -> None:
    decision = decide_extraction_path(
        {
            "page_count": 68,
            "text_coverage": 0.97,
            "is_image_only_pdf": False,
            "is_garbled_pdf": False,
            "text_quality": {"meaningful_ratio": 1.0},
            "chapter_dividers": [2, 3, 13, 35, 49, 61],
            "toc_page": {"has_toc_page": False, "confidence": 0},
            "slide_outline_candidate": True,
        },
        mode="smart",
    )

    assert decision["path"] == PATH_HIERARCHICAL


def test_router_does_not_choose_batch_for_agenda_outline_candidate() -> None:
    decision = decide_extraction_path(
        {
            "page_count": 21,
            "text_coverage": 1.0,
            "is_image_only_pdf": False,
            "is_garbled_pdf": False,
            "text_quality": {"meaningful_ratio": 1.0},
            "chapter_dividers": [3, 9, 16, 18, 20],
            "toc_page": {"has_toc_page": False, "confidence": 0},
            "agenda_outline_candidate": True,
        },
        mode="smart",
    )

    assert decision["path"] == PATH_HIERARCHICAL
