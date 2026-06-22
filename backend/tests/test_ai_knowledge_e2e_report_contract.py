import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "run_ai_knowledge_toc_e2e.py"


def _load_e2e_module():
    assert SCRIPT_PATH.exists(), "AI Knowledge E2E runner is missing"
    spec = importlib.util.spec_from_file_location("ai_knowledge_toc_e2e", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_e2e_script_parses_single_file_and_stop_on_fail() -> None:
    module = _load_e2e_module()

    args = module._parse_args(
        [
            "--fixture",
            r"D:\fixtures\official.json",
            "--input",
            r"D:\docs",
            "--file",
            "sample.pdf",
            "--output",
            "artifacts/toc_e2e",
            "--stop-on-fail",
        ]
    )

    assert args.fixture == r"D:\fixtures\official.json"
    assert args.input == r"D:\docs"
    assert args.file == "sample.pdf"
    assert args.output == "artifacts/toc_e2e"
    assert args.stop_on_fail is True


def test_iter_expected_docs_can_use_official_fixture() -> None:
    module = _load_e2e_module()
    fixture = {
        "documents": [
            {"id": "P01", "file": "annual.pdf", "expected_route": {"selected_path": "embedded_toc"}},
            {"id": "P02", "file": "paper.pdf", "expected_route": {"selected_path": "content_outline"}},
        ]
    }

    docs = module._iter_expected_docs(Path(r"D:\docs"), None, fixture=fixture)

    assert [doc["id"] for doc in docs] == ["P01", "P02"]


def test_build_report_applies_official_acceptance_constraints(tmp_path: Path) -> None:
    module = _load_e2e_module()
    expected = {
        "id": "P04",
        "file": "earthmover.pdf",
        "page_count": 12,
        "expected_route": {"content_type": "text", "selected_path": "content_outline"},
        "acceptance": {
            "must_succeed": True,
            "min_root_count": 3,
            "min_node_count": 4,
            "min_depth": 2,
            "required_root_titles": ["INTRODUCTION", "CONCLUSION"],
            "required_pages": {"INTRODUCTION": 1, "CONCLUSION": 12},
            "forbidden_patterns": {"no_generic_single_node": True},
        },
    }
    index_payload = {
        "doc_name": "earthmover.pdf",
        "page_count": 12,
        "route_decision": {"content_type": "text", "selected_path": "content_outline"},
        "structure": [
            {"title": "ABSTRACT", "start_index": 1, "end_index": 1, "nodes": []},
            {
                "title": "INTRODUCTION",
                "start_index": 1,
                "end_index": 2,
                "nodes": [{"title": "Problem", "start_index": 2, "end_index": 2, "nodes": []}],
            },
            {"title": "CONCLUSION", "start_index": 12, "end_index": 12, "nodes": []},
        ],
        "quality_report": {"status": "completed", "hard_fail_reasons": []},
    }

    report = module.build_report_from_index_payload(
        file_path=tmp_path / "earthmover.pdf",
        doc_id="e2e-p04",
        index_payload=index_payload,
        expected=expected,
        elapsed_ms=100,
    )

    assert report["acceptance"]["minimum_shape"] is True
    assert report["acceptance"]["required_root_titles"] is True
    assert report["acceptance"]["required_pages"] is True
    assert report["acceptance"]["forbidden_patterns"] is True
    assert report["acceptance"]["ok"] is True


def test_build_report_from_index_payload_matches_expected_contract(tmp_path: Path) -> None:
    module = _load_e2e_module()
    expected = {
        "id": "T09",
        "file": "sample.pdf",
        "page_count": 26,
        "expected_route": {"content_type": "text", "selected_path": "visible_toc_with_pages"},
        "must_have_sections": ["main_toc", "figure_toc", "table_toc"],
        "known_pages": {"Risk": 25},
    }
    index_payload = {
        "doc_name": "sample.pdf",
        "page_count": 26,
        "route_decision": {
            "content_type": "text",
            "selected_path": "visible_toc_with_pages",
            "states": ["S0", "S1", "S3", "S4", "S6", "S7", "S8"],
            "fallbacks": [],
        },
        "structure": [
            {
                "title": "目录",
                "metadata": {"toc_section_kind": "main_toc"},
                "start_index": 2,
                "end_index": 24,
                "nodes": [{"title": "Risk", "start_index": 25, "end_index": 26, "nodes": []}],
            },
            {
                "title": "图目录",
                "metadata": {"toc_section_kind": "figure_toc"},
                "start_index": 3,
                "end_index": 3,
                "nodes": [],
            },
            {
                "title": "表目录",
                "metadata": {"toc_section_kind": "table_toc"},
                "start_index": 3,
                "end_index": 3,
                "nodes": [],
            },
        ],
        "quality_report": {"status": "completed", "hard_fail_reasons": [], "warnings": []},
        "diagnostics": {
            "toc_page_detection": {"pages": [2, 3], "sections": [{"kind": "main_toc"}]},
            "toc_content_mapping": {"status": "ok", "strategy": "printed_page_offset"},
        },
    }

    report = module.build_report_from_index_payload(
        file_path=tmp_path / "sample.pdf",
        doc_id="e2e-sample",
        index_payload=index_payload,
        expected=expected,
        elapsed_ms=1234,
    )

    assert report["status"] == "ok"
    assert report["file"] == "sample.pdf"
    assert report["doc_id"] == "e2e-sample"
    assert report["elapsed_ms"] == 1234
    assert report["elapsed_seconds"] == pytest.approx(1.234)
    assert report["stages"] == ["S0", "S1", "S3", "S4", "S6", "S7", "S8"]
    assert report["route"]["matches_expected"] is True
    assert report["toc"]["root_count"] == 3
    assert report["toc"]["top_level_titles"] == ["目录", "图目录", "表目录"]
    assert report["toc"]["section_kinds"] == ["main_toc", "figure_toc", "table_toc"]
    assert report["quality"]["status"] == "completed"
    assert report["key_checks"]["known_pages"]["Risk"] == {
        "expected": 25,
        "actual": 25,
        "ok": True,
    }


def test_llm_quality_needs_repair_is_advisory_without_fact_hard_fail(tmp_path: Path) -> None:
    module = _load_e2e_module()
    expected = {
        "id": "T12",
        "file": "sample.pdf",
        "page_count": 30,
        "expected_route": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
    }
    index_payload = {
        "doc_name": "sample.pdf",
        "page_count": 30,
        "route_decision": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
        "structure": [
            {"title": "目录", "start_index": 4, "end_index": 30, "nodes": []},
        ],
        "quality_report": {
            "status": "needs_review",
            "hard_fail_reasons": [],
            "warnings": ["visible no-page TOC has long chapters without child expansion"],
        },
        "llm_quality_check": {
            "needs_repair": True,
            "overall_score": 0.8,
            "warnings": ["duplicate numbering but distinct titles"],
        },
    }

    report = module.build_report_from_index_payload(
        file_path=tmp_path / "sample.pdf",
        doc_id="e2e-sample",
        index_payload=index_payload,
        expected=expected,
        elapsed_ms=100,
    )

    assert report["quality"]["llm_needs_repair"] is True
    assert report["acceptance"]["quality"] is True
    assert report["status"] == "ok"
    assert report["acceptance"]["ok"] is True


def test_build_report_enforces_must_have_node_start_and_end_ranges(tmp_path: Path) -> None:
    module = _load_e2e_module()
    expected = {
        "id": "T-range",
        "file": "range.pdf",
        "page_count": 12,
        "expected_route": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
        "must_have_nodes": [
            {"title": "Part 1 Market", "start_index": 3, "end_index": 5},
            {"title": "Part 2 Growth", "start_index": 6, "end_index": 12},
        ],
    }
    index_payload = {
        "doc_name": "range.pdf",
        "page_count": 12,
        "route_decision": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
        "structure": [
            {"title": "Part 1 Market", "start_index": 3, "end_index": 4, "nodes": []},
            {"title": "Part 2 Growth", "start_index": 6, "end_index": 12, "nodes": []},
        ],
        "quality_report": {"status": "completed", "hard_fail_reasons": []},
    }

    report = module.build_report_from_index_payload(
        file_path=tmp_path / "range.pdf",
        doc_id="range",
        index_payload=index_payload,
        expected=expected,
        elapsed_ms=100,
    )

    assert report["key_checks"]["must_have_nodes"]["ok"] is False
    item = report["key_checks"]["must_have_nodes"]["items"]["Part 1 Market"]
    assert item["expected_start"] == 3
    assert item["expected_end"] == 5
    assert item["actual_start"] == 3
    assert item["actual_end"] == 4
    assert item["auxiliary_end_ignored"] is False
    assert item["ok"] is False
    assert report["acceptance"]["must_have_nodes"] is False
    assert report["acceptance"]["ok"] is False


def test_must_have_node_uses_expected_range_when_titles_repeat(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "repeat-title.pdf",
        doc_id="repeat-title",
        elapsed_ms=10,
        expected={
            "file": "repeat-title.pdf",
            "expected_route": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "must_have_nodes": [
                {"title": "风险提示", "start_index": 18, "end_index": 21},
            ],
        },
        index_payload={
            "doc_name": "repeat-title.pdf",
            "page_count": 21,
            "route_decision": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "structure": [
                {
                    "title": "产业链梳理",
                    "start_index": 16,
                    "end_index": 17,
                    "nodes": [
                        {"title": "风险提示", "start_index": 16, "end_index": 17, "nodes": []},
                    ],
                },
                {"title": "风险提示", "start_index": 18, "end_index": 21, "nodes": []},
            ],
            "quality_report": {"status": "completed", "hard_fail_reasons": []},
        },
    )

    item = report["key_checks"]["must_have_nodes"]["items"]["风险提示"]
    assert item["actual_start"] == 18
    assert item["actual_end"] == 21
    assert item["ok"] is True
    assert report["acceptance"]["must_have_nodes"] is True


def test_build_report_treats_llm_qc_needs_repair_as_advisory_without_hard_facts(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "needs-repair.pdf",
        doc_id="needs-repair",
        elapsed_ms=10,
        expected={
            "file": "needs-repair.pdf",
            "expected_route": {"content_type": "text", "selected_path": "visible_toc_with_pages"},
        },
        index_payload={
            "doc_name": "needs-repair.pdf",
            "page_count": 10,
            "route_decision": {"content_type": "text", "selected_path": "visible_toc_with_pages"},
            "structure": [{"title": "Chapter 1", "start_index": 2, "end_index": 10, "nodes": []}],
            "quality_report": {"status": "completed", "hard_fail_reasons": []},
            "llm_quality_check": {"needs_repair": True, "overall_score": 0.2},
        },
    )

    assert report["quality"]["llm_needs_repair"] is True
    assert report["acceptance"]["quality"] is True
    assert report["acceptance"]["ok"] is True


def test_build_report_requires_child_expansion_when_reference_demands_it(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "long-parts.pdf",
        doc_id="long-parts",
        elapsed_ms=10,
        expected={
            "file": "long-parts.pdf",
            "expected_route": {"content_type": "hybrid", "selected_path": "visible_toc_no_pages"},
            "required_checks": {"requires_child_expansion": True, "min_children_per_long_chapter": 1},
            "must_have_nodes": [
                {"title": "Part 1", "start_index": 5, "end_index": 12},
            ],
        },
        index_payload={
            "doc_name": "long-parts.pdf",
            "page_count": 20,
            "route_decision": {"content_type": "hybrid", "selected_path": "visible_toc_no_pages"},
            "structure": [{"title": "Part 1", "start_index": 5, "end_index": 12, "nodes": []}],
            "quality_report": {"status": "completed", "hard_fail_reasons": []},
        },
    )

    assert report["key_checks"]["required_checks"]["requires_child_expansion"]["ok"] is False
    assert report["acceptance"]["required_checks"] is False
    assert report["acceptance"]["ok"] is False


def test_build_report_treats_needs_child_expansion_status_as_required(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "short-slide-report.pdf",
        doc_id="short-slide-report",
        elapsed_ms=10,
        expected={
            "file": "short-slide-report.pdf",
            "reference_status": "needs_child_expansion",
            "expected_route": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "must_have_nodes": [
                {"title": "Part 1", "start_index": 3, "end_index": 8},
                {"title": "Part 2", "start_index": 9, "end_index": 15},
            ],
        },
        index_payload={
            "doc_name": "short-slide-report.pdf",
            "page_count": 21,
            "route_decision": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "structure": [
                {"title": "Part 1", "start_index": 3, "end_index": 8, "nodes": []},
                {"title": "Part 2", "start_index": 9, "end_index": 15, "nodes": []},
            ],
            "quality_report": {"status": "completed", "hard_fail_reasons": []},
        },
    )

    assert report["key_checks"]["required_checks"]["requires_child_expansion"]["ok"] is False
    assert report["acceptance"]["required_checks"] is False
    assert report["acceptance"]["ok"] is False


def test_forbidden_start_pages_only_apply_to_effective_roots(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "children.pdf",
        doc_id="children",
        elapsed_ms=10,
        expected={
            "file": "children.pdf",
            "expected_route": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "forbidden_patterns": {"forbidden_start_pages": [4]},
        },
        index_payload={
            "doc_name": "children.pdf",
            "page_count": 12,
            "route_decision": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "structure": [
                {
                    "title": "Part 1",
                    "start_index": 3,
                    "end_index": 8,
                    "nodes": [{"title": "1.1 Child", "start_index": 4, "end_index": 5}],
                }
            ],
            "quality_report": {"status": "completed", "hard_fail_reasons": []},
        },
    )

    assert report["key_checks"]["forbidden_patterns"]["forbidden_start_pages"]["ok"] is True
    assert report["acceptance"]["forbidden_patterns"] is True
    assert report["acceptance"]["ok"] is True


def test_must_have_node_allows_point_like_auxiliary_catalog_items(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "figures.pdf",
        doc_id="figures",
        elapsed_ms=10,
        expected={
            "file": "figures.pdf",
            "expected_route": {"content_type": "text", "selected_path": "visible_toc_with_pages"},
            "must_have_nodes": [
                {"title": "Figure 1 Model", "start_index": 8, "end_index": 12},
            ],
        },
        index_payload={
            "doc_name": "figures.pdf",
            "page_count": 20,
            "route_decision": {"content_type": "text", "selected_path": "visible_toc_with_pages"},
            "structure": [
                {
                    "title": "List of Figures",
                    "metadata": {"toc_section_kind": "figure_toc"},
                    "node_type": "auxiliary_catalog",
                    "catalog_type": "figure",
                    "is_auxiliary": True,
                    "start_index": 8,
                    "end_index": 8,
                    "nodes": [
                        {
                            "title": "Figure 1 Model",
                            "node_type": "auxiliary_catalog_item",
                            "catalog_type": "figure",
                            "is_auxiliary": True,
                            "start_index": 8,
                            "end_index": 8,
                            "nodes": [],
                        }
                    ],
                }
            ],
            "quality_report": {"status": "completed", "hard_fail_reasons": []},
        },
    )

    item = report["key_checks"]["must_have_nodes"]["items"]["Figure 1 Model"]
    assert item["auxiliary_end_ignored"] is True
    assert item["ok"] is True
    assert report["acceptance"]["must_have_nodes"] is True


def test_build_report_accepts_route_options_for_quality_fallback(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "fallback.pdf",
        doc_id="fallback",
        elapsed_ms=10,
        expected={
            "file": "fallback.pdf",
            "expected_route": {"content_type": "text", "selected_path": "embedded_toc"},
            "expected_route_options": [
                {"content_type": "text", "selected_path": "embedded_toc"},
                {"content_type": "text", "selected_path": "visible_toc_with_pages"},
            ],
        },
        index_payload={
            "doc_name": "fallback.pdf",
            "page_count": 10,
            "route_decision": {
                "content_type": "text",
                "selected_path": "visible_toc_with_pages",
                "fallbacks": [{"reason": "embedded_toc_disabled"}],
            },
            "structure": [{"title": "目录", "start_index": 2, "end_index": 10, "nodes": []}],
            "quality_report": {"status": "needs_review", "hard_fail_reasons": []},
        },
    )

    assert report["route"]["matches_expected"] is True
    assert report["acceptance"]["route"] is True
    assert report["acceptance"]["ok"] is True


def test_write_reports_creates_per_file_and_summary(tmp_path: Path) -> None:
    module = _load_e2e_module()
    reports = [
        {"id": "T01", "file": "one.pdf", "status": "ok", "elapsed_ms": 1000, "acceptance": {"ok": True}},
        {"id": "T02", "file": "two.pdf", "status": "failed", "elapsed_ms": 2500, "acceptance": {"ok": False}},
    ]

    summary_path = module.write_reports(reports, tmp_path)

    assert summary_path == tmp_path / "summary.json"
    assert (tmp_path / "T01-one.json").exists()
    assert (tmp_path / "T02-two.json").exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["summary"] == {"total": 2, "ok": 1, "failed": 1, "error": 0, "missing": 0}
    assert summary["durations"] == [
        {"id": "T01", "file": "one.pdf", "status": "ok", "elapsed_ms": 1000, "elapsed_seconds": 1.0},
        {"id": "T02", "file": "two.pdf", "status": "failed", "elapsed_ms": 2500, "elapsed_seconds": 2.5},
    ]


def test_expected_top_level_can_match_main_catalog_children(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "catalog.pdf",
        doc_id="catalog",
        elapsed_ms=10,
        expected={
            "file": "catalog.pdf",
            "expected_route": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "expected_top_level": ["Part01", "Part02"],
        },
        index_payload={
            "doc_name": "catalog.pdf",
            "page_count": 10,
            "route_decision": {"content_type": "text", "selected_path": "visible_toc_no_pages"},
            "structure": [
                {
                    "title": "目录",
                    "start_index": 2,
                    "end_index": 10,
                    "nodes": [
                        {"title": "Part01 市场洞察", "start_index": 3, "end_index": 5, "nodes": []},
                        {"title": "Part02 增长策略", "start_index": 6, "end_index": 10, "nodes": []},
                    ],
                }
            ],
            "quality_report": {"status": "needs_review", "hard_fail_reasons": []},
        },
    )

    assert report["toc"]["top_level_check"]["ok"] is True
    assert report["acceptance"]["ok"] is True


def test_known_page_checks_match_chapter_aliases(tmp_path: Path) -> None:
    module = _load_e2e_module()
    report = module.build_report_from_index_payload(
        file_path=tmp_path / "chapters.pdf",
        doc_id="chapters",
        elapsed_ms=10,
        expected={
            "file": "chapters.pdf",
            "expected_route": {"content_type": "ocr", "selected_path": "embedded_toc"},
            "known_pages": {"Chapter 1": 4, "Chapter 2": 11},
        },
        index_payload={
            "doc_name": "chapters.pdf",
            "page_count": 20,
            "route_decision": {"content_type": "ocr", "selected_path": "embedded_toc"},
            "structure": [
                {"title": "第一章", "start_index": 4, "end_index": 10, "nodes": []},
                {"title": "第二章", "start_index": 11, "end_index": 20, "nodes": []},
            ],
            "quality_report": {"status": "needs_review", "hard_fail_reasons": []},
        },
    )

    assert report["key_checks"]["known_pages"]["Chapter 1"]["ok"] is True
    assert report["key_checks"]["known_pages"]["Chapter 2"]["ok"] is True
    assert report["acceptance"]["ok"] is True
