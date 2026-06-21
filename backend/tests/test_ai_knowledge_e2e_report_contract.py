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
            "--input",
            r"D:\docs",
            "--file",
            "sample.pdf",
            "--output",
            "artifacts/toc_e2e",
            "--stop-on-fail",
        ]
    )

    assert args.input == r"D:\docs"
    assert args.file == "sample.pdf"
    assert args.output == "artifacts/toc_e2e"
    assert args.stop_on_fail is True


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
    assert report["acceptance"]["ok"] is True


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
