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
    pre = {"unparseable_pages": 60, "unparseable_ratio": 0.05}
    route = PageIndexService._decide_pdf_route("smart", pre)
    assert route["execution_mode"] == "fast"
    assert route["escalated_from_pre_analysis"] is False


def test_route_smart_escalates_when_unparseable_ratio_exceeds_threshold() -> None:
    pre = {"unparseable_pages": 12, "unparseable_ratio": 0.18}
    route = PageIndexService._decide_pdf_route("smart", pre)
    assert route["execution_mode"] == "fast"
    assert route["escalated_from_pre_analysis"] is False


def test_route_fast_does_not_auto_escalate_when_ratio_high() -> None:
    pre = {"unparseable_pages": 80, "unparseable_ratio": 0.9}
    route = PageIndexService._decide_pdf_route("fast", pre)
    assert route["execution_mode"] == "fast"
    assert route["escalated_from_pre_analysis"] is False


def test_route_smart_keeps_fast_when_unparseable_ratio_equals_threshold() -> None:
    pre = {"unparseable_pages": 12, "unparseable_ratio": 0.15}
    route = PageIndexService._decide_pdf_route("smart", pre)
    assert route["execution_mode"] == "fast"
    assert route["escalated_from_pre_analysis"] is False


def test_route_keeps_fast_for_good_pre_analysis() -> None:
    pre = {"unparseable_pages": 8, "unparseable_ratio": 0.08}
    route = PageIndexService._decide_pdf_route("fast", pre)
    assert route["execution_mode"] == "fast"
    assert route["escalated_from_pre_analysis"] is False


def test_route_keeps_balanced_when_requested_balanced() -> None:
    pre = {"unparseable_pages": 0, "unparseable_ratio": 0.0}
    route = PageIndexService._decide_pdf_route("balanced", pre)
    assert route["execution_mode"] == "balanced"
    assert route["escalated_from_pre_analysis"] is False


def test_route_smart_defaults_to_fast_execution() -> None:
    pre = {"unparseable_pages": 2, "unparseable_ratio": 0.02}
    route = PageIndexService._decide_pdf_route("smart", pre)
    assert route["requested_mode"] == "smart"
    assert route["execution_mode"] == "fast"
    assert route["escalated_from_pre_analysis"] is False


def test_fast_quality_gate_helper() -> None:
    assert PageIndexService._should_escalate_fast_by_toc_quality(0.5) is True
    assert PageIndexService._should_escalate_fast_by_toc_quality(0.78) is False


def test_fast_toc_readiness_detects_missing_ranges() -> None:
    result = {
        "page_count": 20,
        "structure": [
            {"title": "A", "start_index": 1, "end_index": 10, "nodes": []},
            {"title": "B", "start_index": 11, "end_index": None, "nodes": []},
        ],
    }
    readiness = PageIndexService._evaluate_fast_toc_readiness(result)
    assert readiness["ok"] is False
    assert "missing_ranges" in readiness["reason"]


def test_fast_toc_readiness_detects_page_coverage_gap() -> None:
    result = {
        "page_count": 20,
        "structure": [
            {"title": "A", "start_index": 1, "end_index": 8, "nodes": []},
            {"title": "B", "start_index": 9, "end_index": 12, "nodes": []},
        ],
    }
    readiness = PageIndexService._evaluate_fast_toc_readiness(result)
    assert readiness["ok"] is False
    assert "coverage_end_lt_page_count" in readiness["reason"]


def test_vision_first_required_rules() -> None:
    assert (
        PageIndexService._vision_first_required(
            {"unparseable_pages": 44, "unparseable_ratio": 1.0}
        )
        is True
    )
    assert (
        PageIndexService._vision_first_required(
            {"unparseable_pages": 60, "unparseable_ratio": 0.3}
        )
        is True
    )
    assert (
        PageIndexService._vision_first_required(
            {"unparseable_pages": 10, "unparseable_ratio": 0.2}
        )
        is False
    )


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
