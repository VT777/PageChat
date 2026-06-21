from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.toc_mapping import map_toc_draft_to_physical


def test_map_toc_draft_keeps_physical_page_labels_when_titles_match() -> None:
    page_texts = [
        "Cover",
        "Contents\n1.3 Valuation ........ 7\n4 Risk warning ........ 25",
        "Preface",
        "Body",
        "Body",
        "Body",
        "1.3 Valuation: Latest valuation reaches 750B USD\nBody",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "4 Risk warning\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {"title": "1.3 Valuation", "level": 2, "raw_page_label": 7},
            {"title": "4 Risk warning", "level": 1, "raw_page_label": 25},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert [item["physical_index"] for item in mapped] == [7, 25]
    assert [item["mapping_source"] for item in mapped] == ["physical_identity", "physical_identity"]
    assert report["status"] == "ok"
    assert report["strategy"] == "physical_identity"


def test_map_toc_draft_uses_printed_page_offset_only_with_content_anchors() -> None:
    page_texts = [
        "Cover",
        "Contents\nAlpha ........ 1\nBeta ........ 3",
        "Intro",
        "Alpha\nBody",
        "Alpha details",
        "Beta\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_toc_page",
        "section_kind": "main_toc",
        "items": [
            {"title": "Alpha", "level": 1, "raw_page_label": 1},
            {"title": "Beta", "level": 1, "raw_page_label": 3},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert [item["physical_index"] for item in mapped] == [4, 6]
    assert report["status"] == "ok"
    assert report["strategy"] == "printed_page_offset"
    assert report["strong_anchor_count"] >= 2


def test_map_toc_draft_locates_unpaged_toc_by_title_search() -> None:
    page_texts = [
        "Cover",
        "Contents\nAlpha\nBeta",
        "Intro",
        "Alpha\nBody",
        "Alpha details",
        "More alpha",
        "More alpha",
        "Beta\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_toc_page",
        "section_kind": "main_toc",
        "items": [
            {"title": "Alpha", "level": 1},
            {"title": "Beta", "level": 1},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
    )

    assert [item["physical_index"] for item in mapped] == [4, 8]
    assert report["status"] == "ok"
    assert report["strategy"] == "content_title_search"


def test_map_toc_draft_maps_auxiliary_catalogs_independently() -> None:
    page_texts = [
        "Cover",
        "Contents\nChapter A ........ 4\nList of Figures\nFigure 1 Model flow ........ 5",
        "Preface",
        "Chapter A\nBody",
        "Figure 1 Model flow\nBody",
        "Chapter B\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "toc_sections": [
            {
                "kind": "main_toc",
                "items": [{"title": "Chapter A", "level": 1, "raw_page_label": 4}],
            },
            {
                "kind": "figure_toc",
                "items": [{"title": "Figure 1 Model flow", "level": 1, "raw_page_label": 5}],
            },
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert [(item["section_kind"], item["physical_index"]) for item in mapped] == [
        ("main_toc", 4),
        ("figure_toc", 5),
    ]
    assert [section["kind"] for section in report["sections"]] == ["main_toc", "figure_toc"]
    assert report["sections"][0]["strategy"] == "physical_identity"
    assert report["sections"][1]["strategy"] == "physical_identity"
