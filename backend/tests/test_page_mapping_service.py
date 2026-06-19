from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.page_mapping_service import map_skeleton_pages


def test_maps_no_page_skeleton_by_title_search():
    skeleton = {
        "items": [
            {"title": "Market overview", "level": 1},
            {"title": "Model landscape", "level": 1},
            {"title": "Application opportunities", "level": 1},
        ],
        "toc_pages": [2],
    }
    page_texts = [
        "Cover",
        "Contents",
        "Market overview\nBody",
        "More market",
        "Model landscape\nBody",
        "More models",
        "Application opportunities\nBody",
    ]

    mapped = map_skeleton_pages(skeleton, page_texts, page_count=7)

    assert mapped["range_mapped"] is True
    assert mapped["mapping_strategy"] == "title_search"
    assert mapped["mapping_quality"] >= 0.9
    assert [item["physical_index"] for item in mapped["items"]] == [3, 5, 7]


def test_preserves_valid_existing_page_mapping():
    skeleton = {
        "items": [
            {"title": "A", "level": 1, "physical_index": 2},
            {"title": "B", "level": 1, "physical_index": 6},
        ],
        "page_mapping_valid": True,
    }

    mapped = map_skeleton_pages(skeleton, ["A", "B"], page_count=8)

    assert mapped["mapping_strategy"] == "existing"
    assert [item["physical_index"] for item in mapped["items"]] == [2, 6]


def test_uniform_fallback_keeps_monotonic_ranges_when_titles_not_found():
    skeleton = {
        "items": [
            {"title": "A", "level": 1},
            {"title": "B", "level": 1},
            {"title": "C", "level": 1},
        ],
        "toc_pages": [2],
    }

    mapped = map_skeleton_pages(skeleton, ["Cover", "Contents", "Body"] * 4, page_count=12)

    assert mapped["mapping_strategy"] == "uniform_after_toc"
    assert mapped["range_mapped"] is True
    assert [item["physical_index"] for item in mapped["items"]] == [3, 6, 9]


def test_mapping_report_exposes_phase6_anchor_match_and_leakage_status():
    skeleton = {
        "items": [
            {"title": "Intro", "level": 1},
            {"title": "Method", "level": 1},
            {"title": "Risk", "level": 1},
        ],
        "toc_pages": [2],
    }
    page_texts = [
        "Cover",
        "Contents",
        "Intro\nBody",
        "Method\nBody",
        "Risk\nBody",
    ]

    mapped = map_skeleton_pages(skeleton, page_texts, page_count=5)

    report = mapped["mapping_report"]
    assert report["status"] == "ok"
    assert report["strategy"] == "title_search"
    assert report["anchor_match"] == "3/3"
    assert report["toc_page_leakage_count"] == 0


def test_unpaged_skeleton_never_uses_toc_page_numbers_as_physical_pages():
    skeleton = {
        "items": [
            {"title": "Part One", "level": 1, "page": 1},
            {"title": "Part Two", "level": 1, "page": 2},
        ],
        "toc_pages": [2],
    }
    page_texts = [
        "Cover",
        "Contents\nPart One 01\nPart Two 02",
        "Preface",
        "Part One\nBody",
        "Part Two\nBody",
    ]

    mapped = map_skeleton_pages(skeleton, page_texts, page_count=5)

    assert mapped["mapping_strategy"] == "title_search"
    assert [item["physical_index"] for item in mapped["items"]] == [4, 5]
    assert mapped["mapping_report"]["toc_page_leakage_count"] == 0
