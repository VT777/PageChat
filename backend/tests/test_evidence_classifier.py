from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.evidence_classifier import (
    classify_bookmarks,
    classify_page_text,
    classify_pages,
)


def test_classifies_formal_toc_with_page_numbers():
    text = """
    Contents
    1 Market overview ........ 3
    2 Model landscape ........ 12
    3 Application opportunities ........ 25
    """

    evidence = classify_page_text(text, page_number=2)

    assert evidence["evidence_type"] == "formal_toc"
    assert evidence["primary_role"] == "toc_page"
    assert "toc_item" in [span["role"] for span in evidence["evidence_spans"]]
    assert evidence["has_page_numbers"] is True
    assert evidence["granularity"] == "catalog"


def test_classifies_no_page_toc_as_usable_skeleton():
    text = """
    Contents
    1 Market overview
    2 Model landscape
    3 Application opportunities
    4 Investment suggestions
    """

    evidence = classify_page_text(text, page_number=2)

    assert evidence["evidence_type"] == "no_page_toc"
    assert evidence["primary_role"] == "toc_page"
    assert evidence["has_page_numbers"] is False
    assert evidence["usable_as_skeleton"] is True


def test_classifies_agenda_as_outline_not_divider():
    text = """
    Agenda
    01 Market overview
    02 Model landscape
    03 Application opportunities
    """

    evidence = classify_page_text(text, page_number=5)

    assert evidence["evidence_type"] == "agenda_outline"
    assert evidence["primary_role"] == "agenda_page"
    assert evidence["granularity"] == "chapter"
    assert evidence["is_divider"] is False


def test_classifies_sparse_chapter_page_as_section_marker():
    text = """
    03
    Application opportunities
    """

    evidence = classify_page_text(text, page_number=21)

    assert evidence["evidence_type"] == "section_marker"
    assert evidence["primary_role"] == "chapter_cover"
    assert evidence["is_divider"] is True


def test_classifies_auxiliary_catalogs_separately():
    figure_evidence = classify_page_text(
        "List of Figures\nFigure 1 Model architecture 12\nFigure 2 Training pipeline 19",
        page_number=8,
    )
    table_evidence = classify_page_text(
        "List of Tables\nTable 1 Benchmark results 23\nTable 2 Cost comparison 31",
        page_number=9,
    )

    assert figure_evidence["evidence_type"] == "aux_figure_catalog"
    assert table_evidence["evidence_type"] == "aux_table_catalog"
    assert figure_evidence["primary_role"] == "auxiliary_catalog"
    assert table_evidence["primary_role"] == "auxiliary_catalog"
    assert figure_evidence["role"] == "auxiliary"
    assert table_evidence["role"] == "auxiliary"


def test_classifies_toc_page_with_auxiliary_catalog_secondary_role():
    evidence = classify_page_text(
        """
        Contents
        1 Market overview
        2 Model landscape
        3 Application opportunities
        图目录
        图1 模型架构 12
        图2 训练流程 19
        """,
        page_number=2,
    )

    assert evidence["primary_role"] == "toc_page"
    assert "auxiliary_catalog" in evidence["secondary_roles"]
    assert "figure_catalog" in evidence["signals"]
    assert any(span["role"] == "figure_catalog" for span in evidence["evidence_spans"])


def test_classifies_agenda_page_with_current_section_secondary_evidence():
    evidence = classify_page_text(
        """
        Agenda
        01 Market overview
        02 Model landscape
        第三章 应用机会
        """,
        page_number=5,
    )

    assert evidence["primary_role"] == "agenda_page"
    assert "page_title" in evidence["secondary_roles"]
    assert any(span["role"] == "page_title" for span in evidence["evidence_spans"])


def test_classifies_reliable_bookmarks_as_toc_skeleton():
    evidence = classify_bookmarks(
        [
            {"title": "1 Market overview", "page": 3, "level": 1},
            {"title": "1.1 Demand", "page": 5, "level": 2},
            {"title": "2 Model landscape", "page": 12, "level": 1},
            {"title": "3 Application opportunities", "page": 25, "level": 1},
        ]
    )

    assert evidence["evidence_type"] == "bookmark_toc"
    assert evidence["primary_role"] == "toc_page"
    assert evidence["usable_as_skeleton"] is True
    assert evidence["has_page_numbers"] is True


def test_classifies_pages_returns_all_non_content_evidence():
    evidences = classify_pages(
        [
            "Cover",
            "Contents\n1 Market overview\n2 Model landscape\n3 Application opportunities",
            "01\nMarket overview",
        ]
    )

    assert [e["evidence_type"] for e in evidences] == [
        "no_page_toc",
        "section_marker",
    ]
