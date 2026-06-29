import asyncio
import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "backend" / "tests" / "fixtures" / "toc" / "ai_knowledge_expected_routes.json"
DIAGNOSTIC_SCRIPT = ROOT / "scripts" / "run_ai_knowledge_toc_diagnostics.py"


EXPECTED_FILES = {
    "2025全球人工智能技术应用洞察报告.pdf",
    "2025年AI治理报告：回归现实主义.pdf",
    "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf",
    "2025年第五范式-人工智能驱动的科技创新报告.pdf",
    "2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf",
    "2026年AI Agent智能体技术发展报告.pdf",
    "2026年快消行业AI营销增长白皮书.pdf",
    "AI眼镜关键技术与产业生态研究报告（2025年）.pdf",
    "OpenAI深度报告：大模型王者，引领AGI之路.pdf",
    "中国AI+营销趋势洞察2026.pdf",
    "人工智能安全治理研究报告（2025年）.pdf",
    "清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf",
    "生成式人工智能服务合规备案指南（2026年）.pdf",
}


def _load_fixture() -> dict:
    assert FIXTURE_PATH.exists(), "AI Knowledge baseline fixture is missing"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_diagnostic_module():
    assert DIAGNOSTIC_SCRIPT.exists(), "AI Knowledge diagnostic script is missing"
    spec = importlib.util.spec_from_file_location("ai_knowledge_toc_diagnostics", DIAGNOSTIC_SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_ai_knowledge_expected_routes_fixture_is_complete() -> None:
    fixture = _load_fixture()
    documents = fixture.get("documents")

    assert fixture["input_dir"].endswith(r"knowledge\AI Knowledge")
    assert isinstance(documents, list)
    assert {doc["file"] for doc in documents} == EXPECTED_FILES

    for doc in documents:
        assert doc["page_count"] > 0
        assert doc["expected_path"]
        assert doc.get("expected_route")
        has_assertion = any(
            doc.get(key)
            for key in (
                "must_have_sections",
                "known_pages",
                "expected_top_level",
                "key_assertions",
            )
        )
        assert has_assertion, f"{doc['file']} must have at least one acceptance check"


def test_ai_knowledge_fixture_references_real_files_when_available() -> None:
    fixture = _load_fixture()
    input_dir = Path(fixture["input_dir"])
    if not input_dir.exists():
        pytest.skip(f"AI Knowledge input directory is not available: {input_dir}")

    actual = {path.name for path in input_dir.glob("*.pdf")}
    missing = EXPECTED_FILES - actual

    assert not missing


def test_diagnostic_script_collects_raw_pdf_signals(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    module = _load_diagnostic_module()

    pdf_path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    for idx in range(4):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {idx + 1}")
    doc.set_toc([[1, "Intro", 2], [1, "Body", 3], [1, "End", 4]])
    first = doc[0]
    first.insert_link(
        {
            "kind": pymupdf.LINK_GOTO,
            "from": pymupdf.Rect(72, 90, 160, 110),
            "page": 2,
        }
    )
    doc.save(pdf_path)
    doc.close()

    result = module.collect_pdf_diagnostics(pdf_path)

    assert result["page_count"] == 4
    assert result["text_coverage"] == pytest.approx(1.0)
    assert result["raw_bookmarks"]["count"] == 3
    assert result["raw_links"]["pages"] == [1]
    assert result["raw_links"]["total_internal_links"] == 1
    assert result["current_analyzer"]["code_toc_source"] == "bookmarks"
    assert result["current_analyzer"]["code_toc_items"] >= 3
    assert result["weak_slide_export_outline"] is False


def test_diagnostic_script_parses_explicit_route_all_flag() -> None:
    module = _load_diagnostic_module()

    args = module._parse_args(["--phase", "route", "--all"])

    assert args.phase == "route"
    assert args.all is True


def test_diagnostic_script_parses_embedded_phase() -> None:
    module = _load_diagnostic_module()

    args = module._parse_args(["--phase", "embedded", "--all"])

    assert args.phase == "embedded"
    assert args.all is True


def test_diagnostic_script_parses_detect_phase() -> None:
    module = _load_diagnostic_module()

    args = module._parse_args(["--phase", "detect", "--all"])

    assert args.phase == "detect"
    assert args.all is True


def test_diagnostic_script_parses_quality_phase() -> None:
    module = _load_diagnostic_module()

    args = module._parse_args(["--phase", "quality", "--all"])

    assert args.phase == "quality"
    assert args.all is True


def test_diagnostic_script_parses_logs_phase() -> None:
    module = _load_diagnostic_module()

    args = module._parse_args(["--phase", "logs", "--file", "logs.pdf"])

    assert args.phase == "logs"
    assert args.file == "logs.pdf"


def test_logs_diagnostic_reports_ocr_log_boundaries(monkeypatch, tmp_path: Path) -> None:
    module = _load_diagnostic_module()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf_path = input_dir / "logs.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    async def fake_collect_preprocess(path, **_kwargs):
        assert Path(path).name == "logs.pdf"
        return {
            "file": "logs.pdf",
            "status": "ok",
            "content_type": "ocr",
            "page_count": 44,
            "ocr_calls_summary": {
                "page_text": {
                    "primary_model": "qwen-vl-ocr",
                    "pages": 44,
                    "success": 44,
                    "missing": 0,
                    "concurrency": 20,
                    "diagnostics_dir": "backend/data/ocr_diagnostics/logs",
                }
            },
        }

    monkeypatch.setattr(module, "collect_preprocess_diagnostics", fake_collect_preprocess)

    result = asyncio.run(module.run_logs_diagnostics(input_dir, selected_file="logs.pdf"))

    assert result["phase"] == "logs"
    assert result["summary"]["ok"] == 1
    document = result["documents"][0]
    assert document["main_log_checks"]["compact_ocr_summary"] is True
    assert document["ocr_diagnostics"]["diagnostics_dir"].endswith("ocr_diagnostics/logs")


def test_quality_diagnostic_reports_quality_gate(monkeypatch, tmp_path: Path) -> None:
    module = _load_diagnostic_module()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    pdf_path = input_dir / "quality.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    async def fake_collect_map(path, **_kwargs):
        assert Path(path).name == "quality.pdf"
        return {
            "file": "quality.pdf",
            "status": "ok",
            "page_count": 6,
            "content_type": "text",
            "route_decision": {"selected_path": "visible_toc_with_pages"},
            "toc_page_detection": {"pages": [2]},
            "mapping_report": {
                "status": "ok",
                "page_mapping_score": 1.0,
                "title_match_rate": 1.0,
                "main_title_match_rate": 1.0,
                "main_sample_checked_count": 2,
                "item_count": 2,
            },
            "items": [
                {
                    "title": "Preface",
                    "start_index": 1,
                    "end_index": 1,
                    "summary": "summary",
                    "text": "preface",
                    "nodes": [],
                },
                {
                    "title": "Chapter 1",
                    "start_index": 3,
                    "end_index": 6,
                    "summary": "summary",
                    "text": "body",
                    "nodes": [],
                },
            ],
            "key_checks": {"all_ranges_valid": True},
        }

    monkeypatch.setattr(module, "collect_map_diagnostics", fake_collect_map)

    result = asyncio.run(module.run_quality_diagnostics(input_dir, selected_file="quality.pdf"))

    assert result["summary"]["ok"] == 1
    assert result["summary"]["failed"] == 0
    assert result["documents"][0]["quality_report"]["status"] == "completed"
    assert result["documents"][0]["quality_report"]["mapping_status"] == "ok"


def test_embedded_diagnostic_reports_code_toc_quality(tmp_path: Path, monkeypatch) -> None:
    module = _load_diagnostic_module()
    pdf_path = tmp_path / "embedded.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    items = [
        {"title": f"Section {idx:02d}", "physical_index": idx + 1, "structure": str(idx)}
        for idx in range(1, 25)
    ]

    def fake_analyze(_path):
        return {
            "page_count": 30,
            "content_type": "text",
            "text_layer_quality": "reliable",
            "code_toc": {
                "source": "bookmarks",
                "items": items,
                "toc_sections": [{"kind": "main_toc", "items": items}],
                "sources": {"bookmarks": {"count": len(items)}},
            },
        }

    monkeypatch.setattr(module, "analyze_pdf_structure", fake_analyze)

    result = module.collect_embedded_diagnostics(pdf_path)

    assert result["status"] == "ok"
    assert result["code_toc_quality"]["accepted"] is True
    assert result["section_kinds"] == ["main_toc"]
    assert result["route_decision"]["selected_path"] == "embedded_toc"


def test_embedded_phase_match_accepts_rejected_code_toc_for_visible_expected_path() -> None:
    module = _load_diagnostic_module()
    result = {
        "code_toc_quality": {"accepted": False, "reasons": ["sparse_bookmarks"]},
        "route_decision": {"selected_path": "content_outline"},
    }
    expected = {"selected_path": "visible_toc_with_pages"}

    assert module._embedded_expected_matches(result, expected) is True


def test_route_diagnostic_reports_state_machine_path(tmp_path: Path, monkeypatch) -> None:
    module = _load_diagnostic_module()

    pdf_path = tmp_path / "route.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_analyze(_path):
        return {
            "page_count": 3,
            "page_list": [
                ("Cover page for route diagnostics", 10),
                (
                    "Contents\nPreface\nChapter 1 Student AI literacy\nChapter 2 Teacher AI literacy\nChapter 3 AI talent development",
                    20,
                ),
                ("Preface: research background and objectives", 10),
            ],
            "text_coverage": 1.0,
            "image_coverage": 0.0,
            "image_only_pages": [],
            "garbled_pages": [],
            "text_layer_quality": "reliable",
        }

    async def fake_preprocess(_path, analysis, **_kwargs):
        analysis["content_type"] = "text"
        analysis["page_texts"] = [page[0] for page in analysis["page_list"]]
        analysis["page_text_map_diagnostics"] = {"page_count": 3, "ocr_page_count": 0}
        return None

    monkeypatch.setattr(module, "analyze_pdf_structure", fake_analyze)
    monkeypatch.setattr(module, "preprocess_page_text_map", fake_preprocess)

    result = asyncio.run(module.collect_route_diagnostics(pdf_path, preprocess=True))

    assert result["status"] == "ok"
    assert result["content_type"] == "text"
    assert result["toc_page_detection"]["pages"] == [2]
    assert result["toc_page_detection"]["has_page_numbers"] is False
    assert result["route_decision"]["selected_path"] == "visible_toc_no_pages"


def test_detect_diagnostic_reports_typed_toc_sections(tmp_path: Path, monkeypatch) -> None:
    module = _load_diagnostic_module()

    pdf_path = tmp_path / "detect.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    def fake_analyze(_path):
        catalog_text = (
            "\u56fe\u76ee\u5f55\n"
            "\u56fe 1 AI \u773c\u955c\u7cfb\u7edf\u67b6\u6784 ........ 12\n"
            "\u56fe 2 \u5149\u5b66\u65b9\u6848\u5bf9\u6bd4 ........ 18\n"
            "\u8868\u76ee\u5f55\n"
            "\u8868 1 \u4f9b\u5e94\u94fe\u516c\u53f8\u6e05\u5355 ........ 28\n"
            "\u8868 2 \u5173\u952e\u53c2\u6570\u5bf9\u6bd4 ........ 35"
        )
        return {
            "page_count": 3,
            "page_list": [
                ("Cover page", 10),
                (catalog_text, 10),
                ("Body page", 10),
            ],
            "text_coverage": 1.0,
            "image_coverage": 0.0,
            "image_only_pages": [],
            "garbled_pages": [],
            "text_layer_quality": "reliable",
        }

    async def fake_preprocess(_path, analysis, **_kwargs):
        analysis["content_type"] = "text"
        analysis["page_texts"] = [page[0] for page in analysis["page_list"]]
        analysis["page_text_map_diagnostics"] = {"page_count": 3, "ocr_page_count": 0}
        return None

    monkeypatch.setattr(module, "analyze_pdf_structure", fake_analyze)
    monkeypatch.setattr(module, "preprocess_page_text_map", fake_preprocess)

    result = asyncio.run(module.collect_detect_diagnostics(pdf_path, preprocess=True))

    assert result["status"] == "ok"
    assert result["toc_page_detection"]["pages"] == [2]
    assert result["toc_page_detection"]["sections"] == [
        {"kind": "figure_toc", "pages": [2]},
        {"kind": "table_toc", "pages": [2]},
    ]
    assert result["toc_page_detection"]["has_page_numbers"] is True
