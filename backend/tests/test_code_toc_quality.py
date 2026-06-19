from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_quality_accepts_multi_source_using_main_section_items() -> None:
    from pageindex.code_toc_quality import evaluate_code_toc

    main_items = [
        {"title": f"Chapter {idx}", "physical_index": idx + 3, "structure": str(idx)}
        for idx in range(1, 61)
    ]
    report = evaluate_code_toc(
        {
            "page_count": 70,
            "text_layer_quality": "reliable",
            "code_toc": {
                "source": "bookmarks+links",
                "items": main_items,
                "toc_sections": [
                    {"kind": "main_toc", "items": main_items},
                    {"kind": "table_toc", "items": [{"title": "表 1", "physical_index": 20}]},
                    {"kind": "figure_toc", "items": [{"title": "图 1", "physical_index": 21}]},
                ],
            },
        }
    )

    assert report["accepted"] is True
    assert report["effective_source"] == "bookmarks+links"
    assert report["item_count"] == 60
    assert report["section_kinds"] == ["main_toc", "table_toc", "figure_toc"]


def test_quality_rejects_sparse_reliable_text_bookmarks() -> None:
    from pageindex.code_toc_quality import evaluate_code_toc

    report = evaluate_code_toc(
        {
            "page_count": 50,
            "text_layer_quality": "reliable",
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": f"Section {idx}", "physical_index": idx + 2}
                    for idx in range(1, 20)
                ],
            },
        }
    )

    assert report["accepted"] is False
    assert "sparse_bookmarks" in report["reasons"]


def test_quality_accepts_cleaned_slide_outline_for_ocr_document() -> None:
    from pageindex.code_toc_quality import evaluate_code_toc

    report = evaluate_code_toc(
        {
            "page_count": 43,
            "content_type": "ocr",
            "text_layer_quality": "garbled",
            "code_toc": {
                "source": "bookmarks",
                "quality_flags": ["weak_slide_export_outline"],
                "items": [
                    {"title": "第一章", "physical_index": 4},
                    {"title": "全球人工智能基础能力与市场规模", "physical_index": 5},
                    {"title": "第二章", "physical_index": 11},
                    {"title": "第三章", "physical_index": 24},
                    {"title": "第四章", "physical_index": 38},
                ],
            },
        }
    )

    assert report["accepted"] is True
    assert "weak_slide_export_outline" in report["warnings"]
