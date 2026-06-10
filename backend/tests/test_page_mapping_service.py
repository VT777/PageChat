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
