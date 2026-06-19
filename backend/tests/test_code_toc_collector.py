from pathlib import Path
import json
import sys

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fixture_pdf(name: str) -> Path:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "toc" / "ai_knowledge_expected_routes.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    return Path(fixture["input_dir"]) / name


def test_collects_bookmarks_and_links_for_compliance_guide() -> None:
    from pageindex.code_toc_collector import collect_code_toc

    pdf_path = _fixture_pdf("生成式人工智能服务合规备案指南（2026年）.pdf")
    with pymupdf.open(pdf_path) as doc:
        report = collect_code_toc(doc, page_texts=[page.get_text() or "" for page in doc])

    assert report["source"] == "bookmarks+links"
    assert report["sources"]["bookmarks"]["count"] >= 150
    assert report["sources"]["links"]["count"] >= 100
    assert report["sources"]["links"]["toc_pages"] == [7, 8, 9]
    assert [section["kind"] for section in report["toc_sections"]] == [
        "main_toc",
        "table_toc",
        "figure_toc",
    ]
    assert report["toc_sections"][1]["items"], "table catalog must come from links"
    assert report["toc_sections"][2]["items"], "figure catalog must come from links"


def test_collects_link_only_toc_for_ai_agent_report() -> None:
    from pageindex.code_toc_collector import collect_code_toc

    pdf_path = _fixture_pdf("2026年AI Agent智能体技术发展报告.pdf")
    with pymupdf.open(pdf_path) as doc:
        report = collect_code_toc(doc, page_texts=[page.get_text() or "" for page in doc])

    assert report["source"] == "links"
    assert report["sources"]["bookmarks"]["count"] == 0
    assert report["sources"]["links"]["toc_pages"] == [3, 4, 5, 6, 7, 8]
    assert len(report["items"]) >= 100
    assert [section["kind"] for section in report["toc_sections"]] == ["main_toc"]


def test_collects_slide_outline_but_marks_weak_slide_noise() -> None:
    from pageindex.code_toc_collector import collect_code_toc

    pdf_path = _fixture_pdf("2025全球人工智能技术应用洞察报告.pdf")
    with pymupdf.open(pdf_path) as doc:
        report = collect_code_toc(doc, page_texts=[page.get_text() or "" for page in doc])

    assert report["source"] == "bookmarks"
    assert report["sources"]["bookmarks"]["slide_export_noise_count"] >= 3
    assert "weak_slide_export_outline" in report["quality_flags"]
    assert len(report["items"]) >= 30


def test_pdf_analyzer_preserves_multi_source_code_toc() -> None:
    from pageindex.pdf_analyzer import analyze_pdf_structure

    pdf_path = _fixture_pdf("生成式人工智能服务合规备案指南（2026年）.pdf")
    analysis = analyze_pdf_structure(str(pdf_path))
    code_toc = analysis["code_toc"]

    assert code_toc["source"] == "bookmarks+links"
    assert code_toc["sources"]["bookmarks"]["count"] >= 150
    assert code_toc["sources"]["links"]["toc_pages"] == [7, 8, 9]
    assert [section["kind"] for section in code_toc["toc_sections"]] == [
        "main_toc",
        "table_toc",
        "figure_toc",
    ]
