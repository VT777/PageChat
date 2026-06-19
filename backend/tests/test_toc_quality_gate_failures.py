from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.quality_validation import build_index_quality_report


def _node(title, start, end, *, summary="summary", **extra):
    payload = {
        "title": title,
        "start_index": start,
        "end_index": end,
        "summary": summary,
        "nodes": [],
    }
    payload.update(extra)
    return payload


def test_quality_gate_hard_fails_page_out_of_range() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Overview", 1, 4),
                _node("Appendix", 11, 12),
            ],
            "route_decision": {"selected_path": "visible_toc_with_pages"},
        },
        page_count=10,
    )

    assert report["status"] == "failed:toc_quality"
    assert "page_out_of_range" in report["hard_fail_reasons"]
    assert report["page_out_of_range_count"] == 1


def test_quality_gate_hard_fails_many_body_nodes_on_toc_pages() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Case 01", 2, 3),
                _node("Case 02", 2, 4),
                _node("Case 03", 2, 5),
                _node("Case 04", 6, 8),
            ],
            "diagnostics": {
                "toc_page_detection": {"pages": [2]},
            },
            "route_decision": {"selected_path": "visible_toc_with_pages"},
        },
        page_count=20,
    )

    assert report["status"] == "failed:toc_quality"
    assert "toc_page_leakage" in report["hard_fail_reasons"]
    assert report["toc_page_leakage_count"] == 3


def test_quality_gate_hard_fails_failed_mapping_report() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Part 1", 5, 12),
                _node("Part 2", 13, 20),
            ],
            "diagnostics": {
                "toc_content_mapping": {
                    "status": "failed",
                    "reasons": ["title_match_rate_below_threshold"],
                },
            },
        },
        page_count=20,
    )

    assert report["status"] == "failed:toc_quality"
    assert "toc_content_mapping_failed" in report["hard_fail_reasons"]


def test_quality_gate_hard_fails_unusable_node_content_from_page_text_map() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Chapter 1", 1, 5, text=""),
                _node("Chapter 2", 6, 10, text="   "),
                _node("Chapter 3", 11, 15, text="real content"),
            ],
            "diagnostics": {
                "page_text_map_diagnostics": {
                    "page_count": 15,
                    "qualities": {"reliable": 15},
                },
            },
        },
        page_count=15,
    )

    assert report["status"] == "failed:toc_quality"
    assert "node_content_unusable" in report["hard_fail_reasons"]
    assert report["empty_node_text_ratio"] >= 0.6


def test_quality_gate_accepts_flat_toc_when_ranges_are_usable() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Case 01", 3, 5, text="case one"),
                _node("Case 02", 6, 8, text="case two"),
                _node("Case 03", 9, 12, text="case three"),
                _node("Case 04", 13, 20, text="case four"),
            ],
            "diagnostics": {
                "toc_page_detection": {"pages": [2]},
                "page_text_map_diagnostics": {
                    "page_count": 20,
                    "qualities": {"reliable": 20},
                },
            },
        },
        page_count=20,
    )

    assert not report["status"].startswith("failed")
    assert report["detected_style"] == "flat"
    assert report["style_fit"] == "acceptable"


def test_quality_gate_accepts_auxiliary_catalog_nodes_on_toc_pages() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("目录", 2, 20, nodes=[_node("Main", 4, 20)]),
                _node(
                    "图目录",
                    2,
                    2,
                    node_type="auxiliary_catalog",
                    is_auxiliary=True,
                    exclude_from_coverage=True,
                    exclude_from_text=True,
                ),
                _node(
                    "表目录",
                    2,
                    2,
                    node_type="auxiliary_catalog",
                    is_auxiliary=True,
                    exclude_from_coverage=True,
                    exclude_from_text=True,
                ),
            ],
            "diagnostics": {
                "toc_page_detection": {"pages": [2]},
            },
        },
        page_count=20,
    )

    assert "toc_page_leakage" not in report["hard_fail_reasons"]
    assert report["toc_page_leakage_count"] == 0


def test_quality_gate_accepts_adjacent_boundary_overlap() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Chapter 1", 3, 10),
                _node("Chapter 2", 10, 15),
                _node("Chapter 3", 15, 20),
            ],
        },
        page_count=20,
    )

    assert "page_out_of_range" not in report["hard_fail_reasons"]
    assert "invalid_page_range" not in report["hard_fail_reasons"]
    assert not report["status"].startswith("failed")
