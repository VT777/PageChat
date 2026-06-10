from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.toc_page_extractor import (
    _build_tree_by_groups,
    _fallback_grouping,
    _normalize_group_ranges,
    _validate_groups,
)


def test_fallback_grouping_uses_entry_range_not_page_range():
    groups = _fallback_grouping([{"title": "A"}, {"title": "B"}])

    assert groups == [
        {
            "title": "目录",
            "type": "chapter_catalog",
            "entry_start": 1,
            "entry_end": 2,
        }
    ]


def test_validate_groups_accepts_entry_range_fields():
    groups = [{"title": "目录", "entry_start": 1, "entry_end": 2}]

    assert _validate_groups(groups, total_entries=2) is True


def test_normalize_group_ranges_converts_legacy_index_fields():
    groups = [{"title": "目录", "start_index": 1, "end_index": 3}]

    normalized = _normalize_group_ranges(groups)

    assert normalized[0]["entry_start"] == 1
    assert normalized[0]["entry_end"] == 3
    assert "start_index" not in normalized[0]
    assert "end_index" not in normalized[0]


def test_build_tree_by_groups_uses_entry_ranges_without_page_index_fields():
    entries = [
        {"title": "A", "level": 1, "physical_index": 3},
        {"title": "B", "level": 1, "physical_index": 5},
    ]
    groups = [{"title": "目录", "entry_start": 1, "entry_end": 2}]

    tree = _build_tree_by_groups(entries, groups)

    assert tree[0]["title"] == "目录"
    assert "start_index" not in tree[0]
    assert "end_index" not in tree[0]
    assert len(tree[0]["children"]) == 2
