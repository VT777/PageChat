from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.balanced_quality_gate import run_balanced_quality_gate


def test_quality_gate_accepts_matching_top_level_and_children():
    skeleton = {
        "items": [
            {"title": "第一章", "level": 1},
            {"title": "第二章", "level": 1},
        ]
    }
    tree = [
        {"title": "第一章", "level": 1, "start_index": 1, "end_index": 5, "nodes": [{"title": "A", "start_index": 2, "end_index": 3}]},
        {"title": "第二章", "level": 1, "start_index": 6, "end_index": 10, "nodes": [{"title": "B", "start_index": 7, "end_index": 8}]},
    ]

    fixed, result = run_balanced_quality_gate(
        tree,
        {"top_level_frozen": True},
        skeleton,
        page_count=10,
    )

    assert result["top_level_exact_match"] is True
    assert result["needs_repair"] is False
    assert len(fixed) == 2


def test_quality_gate_removes_extra_top_level_but_keeps_children():
    skeleton = {"items": [{"title": "第一章", "level": 1}]}
    tree = [
        {"title": "第一章", "level": 1, "start_index": 1, "end_index": 10, "nodes": [{"title": "子项", "start_index": 2, "end_index": 3}]},
        {"title": "多余章节", "level": 1, "start_index": 11, "end_index": 12, "nodes": []},
    ]

    fixed, result = run_balanced_quality_gate(
        tree,
        {"top_level_frozen": True},
        skeleton,
        page_count=12,
    )

    assert [node["title"] for node in fixed] == ["第一章"]
    assert fixed[0]["nodes"][0]["title"] == "子项"
    assert "remove_extra_top_level" in result["repair_actions"]


def test_quality_gate_flags_long_chapter_without_children():
    skeleton = {"items": [{"title": "第二章", "level": 1}]}
    tree = [
        {"title": "第二章", "level": 1, "start_index": 11, "end_index": 24, "nodes": []},
    ]

    _, result = run_balanced_quality_gate(
        tree,
        {"top_level_frozen": True, "allow_child_expansion": True},
        skeleton,
        page_count=43,
    )

    assert result["long_chapter_completeness"] is False
    assert result["needs_repair"] is True
    assert "long_chapter_without_children" in result["repair_actions"]


def test_quality_gate_ignores_auxiliary_catalogs_for_top_level_match():
    skeleton = {"items": [{"title": "正文目录", "level": 1}]}
    tree = [
        {"title": "正文目录", "level": 1, "start_index": 3, "end_index": 20, "nodes": [{"title": "小节", "start_index": 4, "end_index": 5}]},
        {"title": "图目录", "level": 1, "start_index": 2, "end_index": 2, "is_auxiliary": True, "nodes": []},
    ]

    fixed, result = run_balanced_quality_gate(
        tree,
        {"top_level_frozen": True},
        skeleton,
        page_count=20,
    )

    assert result["top_level_exact_match"] is True
    assert result["auxiliary_catalog_isolation"] is True
    assert len(fixed) == 2
