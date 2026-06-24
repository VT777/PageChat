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


def test_quality_gate_hard_fails_body_ranges_overlapping_toc_pages() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Preface", 1, 5),
                _node("Chapter 1", 3, 5),
                _node("Chapter 2", 4, 5),
                _node("Chapter 3", 6, 10),
            ],
            "diagnostics": {
                "toc_page_detection": {"pages": [5]},
            },
            "route_decision": {"selected_path": "visible_toc_with_pages"},
        },
        page_count=10,
    )

    assert report["status"] == "failed:toc_quality"
    assert "toc_page_leakage" in report["hard_fail_reasons"]
    assert report["toc_page_leakage_count"] == 2
    assert report["toc_page_leakage_sample"][0]["page"] == 5


def test_quality_gate_allows_legal_front_matter_and_contents_overlap_with_toc_page() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Preface", 1, 4),
                _node("Contents", 3, 3),
                _node("Introduction", 3, 6),
                _node("Interpretation and Application", 6, 10),
            ],
            "diagnostics": {
                "toc_page_detection": {"pages": [3]},
            },
            "route_decision": {"selected_path": "embedded_toc", "toc_source": "code_toc"},
        },
        page_count=10,
    )

    assert "toc_page_leakage" not in report["hard_fail_reasons"]
    assert report["toc_page_leakage_count"] == 0


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


def test_quality_gate_hard_fails_low_evidence_content_outline_declared_pages() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Generated heading A", 1, 2),
                _node("Generated heading B", 3, 8),
            ],
            "diagnostics": {
                "toc_content_mapping": {
                    "status": "ok",
                    "strategy": "content_outline_declared_pages",
                    "title_match_rate": 0.0,
                    "warnings": ["low_title_validation"],
                },
            },
            "route_decision": {"selected_path": "content_outline"},
        },
        page_count=8,
    )

    assert report["status"] == "failed:toc_quality"
    assert "low_evidence_content_outline_mapping" in report["hard_fail_reasons"]


def test_quality_gate_hard_fails_low_evidence_section_divider_sequence() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Chapter A", 3, 8),
                _node("Chapter B", 9, 20),
            ],
            "diagnostics": {
                "toc_content_mapping": {
                    "status": "ok",
                    "strategy": "section_divider_sequence",
                    "item_count": 2,
                    "boundary_anchor_count": 0,
                    "page_mapping_score": 0.76,
                    "title_match_rate": 0.0,
                },
            },
            "route_decision": {"selected_path": "visible_toc_no_pages"},
        },
        page_count=20,
    )

    assert report["status"] == "failed:toc_quality"
    assert "low_evidence_section_divider_sequence" in report["hard_fail_reasons"]


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


def test_quality_gate_hard_fails_visible_toc_with_weak_title_anchors() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Chapter 1", 3, 8),
                _node("Chapter 2", 9, 15),
                _node("Chapter 3", 16, 22),
            ],
            "route_decision": {"selected_path": "visible_toc_with_pages"},
            "diagnostics": {
                "toc_content_mapping": {
                    "status": "ok",
                    "page_mapping_score": 0.72,
                    "title_match_rate": 0.2,
                },
            },
        },
        page_count=25,
    )

    assert report["status"] == "failed:toc_quality"
    assert "title_match_rate_below_route_threshold" in report["hard_fail_reasons"]


def test_quality_gate_uses_main_title_match_rate_when_auxiliary_catalogs_lower_overall_rate() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node(
                    "目录",
                    1,
                    20,
                    nodes=[
                        _node("1. Main", 4, 8, text="main"),
                        _node("2. Next", 9, 20, text="next"),
                    ],
                ),
                _node(
                    "图目录",
                    4,
                    20,
                    node_type="auxiliary_catalog",
                    is_auxiliary=True,
                    exclude_from_coverage=True,
                    nodes=[
                        _node("图1", 4, 4, is_auxiliary=True),
                        _node("图2", 5, 5, is_auxiliary=True),
                    ],
                ),
            ],
            "route_decision": {"selected_path": "visible_toc_with_pages"},
            "diagnostics": {
                "toc_content_mapping": {
                    "status": "ok",
                    "page_mapping_score": 0.75,
                    "title_match_rate": 0.25,
                    "main_title_match_rate": 1.0,
                    "main_strong_anchor_count": 2,
                    "main_sample_checked_count": 2,
                },
            },
        },
        page_count=20,
    )

    assert "title_match_rate_below_route_threshold" not in report["hard_fail_reasons"]
    assert not report["status"].startswith("failed")


def test_quality_gate_hard_fails_unexpanded_visible_no_page_chapters() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("第一章", 3, 18),
                _node("第二章", 19, 34),
            ],
            "route_decision": {"selected_path": "visible_toc_no_pages"},
        },
        page_count=40,
    )

    assert report["status"] == "failed:toc_quality"
    assert "visible_no_page_long_chapter_without_children" in report["hard_fail_reasons"]


def test_quality_gate_warns_medium_visible_no_page_leaf_without_hard_fail() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                {
                    "title": "目录",
                    "start_index": 5,
                    "end_index": 62,
                    "nodes": [
                        _node("Part01", 5, 12),
                        _node("Part02", 13, 24),
                        _node("Part03", 25, 34, nodes=[_node("Step1", 29, 29)]),
                    ],
                }
            ],
            "route_decision": {"selected_path": "visible_toc_no_pages"},
        },
        page_count=62,
    )

    assert report["status"] != "failed:toc_quality"
    assert "visible_no_page_long_chapter_without_children" not in report["hard_fail_reasons"]
    assert report["unexpanded_long_leaf_count"] == 2
    assert report["unexpanded_long_leaf_hard_count"] == 0


def test_quality_gate_warns_nested_visible_no_page_leaf_without_hard_fail() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                {
                    "title": "目录",
                    "start_index": 3,
                    "end_index": 80,
                    "nodes": [
                        _node(
                            "Chapter",
                            10,
                            40,
                            nodes=[_node("Deep section", 12, 32)],
                        ),
                    ],
                }
            ],
            "route_decision": {"selected_path": "visible_toc_no_pages"},
        },
        page_count=80,
    )

    assert report["status"] != "failed:toc_quality"
    assert "visible_no_page_long_chapter_without_children" not in report["hard_fail_reasons"]
    assert report["unexpanded_long_leaf_count"] == 1
    assert report["unexpanded_long_leaf_hard_count"] == 0


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


def test_quality_gate_uses_selected_candidate_for_evidence_title_preservation() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                {
                    "title": "目录",
                    "start_index": 7,
                    "end_index": 50,
                    "nodes": [
                        _node("1 Overview", 7, 8),
                        _node("2 Monetary Policy and Economic Developments", 9, 20),
                        _node("3 Financial Stability", 21, 30),
                        _node("4 Supervision and Regulation", 31, 50),
                    ],
                }
            ],
            "route_decision": {"selected_path": "visible_toc_with_pages"},
            "diagnostics": {
                "toc_candidates_summary": [
                    {
                        "candidate_id": "toc_page_text_rule_001",
                        "source": "toc_page_text_rule",
                        "item_count": 1,
                        "status": "selected",
                    },
                    {
                        "candidate_id": "code_toc_links",
                        "source": "code_toc",
                        "item_count": 49,
                        "status": "rejected",
                    },
                ],
                "balanced_quality_gate": {
                    "child_expansion_attempted": False,
                    "child_expansion_required_count": 0,
                    "unexpanded_long_leaf_count": 0,
                    "unexpanded_long_leaf_hard_count": 0,
                },
            },
        },
        page_count=50,
    )

    assert report["evidence_title_count"] == 1
    assert report["title_preservation_rate"] == 1.0
    assert "evidence_titles_lost_in_final_tree" not in report["hard_fail_reasons"]


def test_quality_gate_selected_candidate_without_source_does_not_crash() -> None:
    report = build_index_quality_report(
        {
            "structure": [_node("1 Overview", 1, 10)],
            "diagnostics": {
                "toc_candidates_summary": [
                    {
                        "candidate_id": "toc_page_text_rule_001",
                        "item_count": 1,
                        "status": "selected",
                    }
                ],
            },
        },
        page_count=10,
    )

    assert report["evidence_source"] == "toc_page_text_rule_001"


def test_quality_gate_reads_new_runner_selected_attempt_summary() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                {
                    "title": "Contents",
                    "start_index": 1,
                    "end_index": 30,
                    "nodes": [
                        _node("Only surviving title", 1, 30),
                    ],
                }
            ],
            "diagnostics": {
                "toc_candidates_summary": {
                    "attempt_chain": [
                        {
                            "path": "visible_toc_with_pages",
                            "status": "selected",
                            "item_count": 8,
                            "sample_titles": [
                                "Chapter A",
                                "Chapter B",
                                "Chapter C",
                                "Chapter D",
                                "Chapter E",
                                "Chapter F",
                            ],
                        }
                    ]
                }
            },
        },
        page_count=30,
    )

    assert report["evidence_title_count"] == 8
    assert report["title_preservation_rate"] < 0.35
    assert "evidence_titles_lost_in_final_tree" in report["hard_fail_reasons"]


def test_quality_gate_does_not_treat_section_divider_pages_as_toc_leakage() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Chapter 1", 3, 8),
                _node("Chapter 2", 9, 14),
                _node("Chapter 3", 15, 20),
            ],
            "diagnostics": {
                "toc_page_detection": {"pages": [2]},
                "mapping": {
                    "status": "ok",
                    "strategy": "section_divider_sequence",
                    "toc_pages": [2],
                    "excluded_pages": [2],
                    "section_divider_pages": [3, 9, 15],
                    "boundary_anchor_count": 3,
                    "item_count": 3,
                    "total_item_count": 3,
                },
            },
        },
        page_count=20,
    )

    assert report["toc_page_leakage_count"] == 0
    assert "toc_page_leakage" not in report["hard_fail_reasons"]


def test_quality_gate_hard_fails_auxiliary_catalog_mixed_into_main_tree() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                {
                    "title": "Contents",
                    "start_index": 3,
                    "end_index": 20,
                    "nodes": [
                        _node("Chapter 1", 4, 12),
                        _node(
                            "Figure 1 Model architecture",
                            5,
                            5,
                            catalog_type="figure",
                            node_type="auxiliary_catalog_item",
                            is_auxiliary=True,
                        ),
                    ],
                }
            ],
            "route_decision": {"selected_path": "visible_toc_with_pages"},
        },
        page_count=20,
    )

    assert report["status"] == "failed:toc_quality"
    assert report["auxiliary_catalog_isolation"] is False
    assert report["auxiliary_catalog_mixed_count"] == 1
    assert "auxiliary_catalog_mixed_into_main" in report["hard_fail_reasons"]


def test_quality_gate_hard_fails_unexpanded_long_leaf_after_expansion_attempt() -> None:
    report = build_index_quality_report(
        {
            "structure": [
                _node("Chapter 1", 3, 22),
                _node("Chapter 2", 23, 30, nodes=[_node("Section 2.1", 24, 25)]),
            ],
            "route_decision": {"selected_path": "visible_toc_with_pages"},
            "diagnostics": {
                "balanced_quality_gate": {
                    "child_expansion_attempted": True,
                    "child_expansion_required_count": 1,
                    "unexpanded_long_leaf_count": 1,
                    "unexpanded_long_leaf_hard_count": 1,
                    "unexpanded_long_leaf_sample": [
                        {"title": "Chapter 1", "start": 3, "end": 22, "span": 20}
                    ],
                },
            },
        },
        page_count=30,
    )

    assert report["status"] == "failed:toc_quality"
    assert report["child_expansion_attempted"] is True
    assert report["unexpanded_long_leaf_hard_count"] == 1
    assert "unexpanded_long_leaf_after_expansion" in report["hard_fail_reasons"]
