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
