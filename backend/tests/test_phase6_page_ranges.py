from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.post_processing import normalize_tree_page_ranges


def test_normalize_tree_page_ranges_allows_adjacent_boundary_overlap_recursively() -> None:
    tree = [
        {
            "title": "Chapter 1",
            "start_index": 5,
            "end_index": 12,
            "nodes": [
                {"title": "Section 1.1", "start_index": 5, "end_index": 7},
                {"title": "Section 1.2", "start_index": 7, "end_index": 10},
                {"title": "Section 1.3", "start_index": 10, "end_index": 12},
            ],
        },
        {
            "title": "Chapter 2",
            "start_index": 12,
            "end_index": 20,
            "nodes": [
                {"title": "Section 2.1", "start_index": 12, "end_index": 14},
                {"title": "Section 2.2", "start_index": 16, "end_index": 20},
            ],
        },
    ]

    normalized = normalize_tree_page_ranges(tree, page_count=20)

    assert normalized[0]["end_index"] == 12
    assert normalized[1]["end_index"] == 20
    assert [child["end_index"] for child in normalized[0]["nodes"]] == [7, 10, 12]
    assert [child["end_index"] for child in normalized[1]["nodes"]] == [15, 20]


def test_normalize_tree_page_ranges_clamps_invalid_pages_and_children_to_parent() -> None:
    tree = [
        {
            "title": "Chapter",
            "start_index": 0,
            "end_index": 99,
            "nodes": [
                {"title": "Inside", "start_index": 3, "end_index": 99},
                {"title": "Next", "start_index": 8, "end_index": 99},
            ],
        }
    ]

    normalized = normalize_tree_page_ranges(tree, page_count=10)

    assert normalized[0]["start_index"] == 1
    assert normalized[0]["end_index"] == 10
    assert normalized[0]["nodes"][0]["start_index"] == 3
    assert normalized[0]["nodes"][0]["end_index"] == 7
    assert normalized[0]["nodes"][1]["start_index"] == 8
    assert normalized[0]["nodes"][1]["end_index"] == 10
