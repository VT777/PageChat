import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.child_expansion_policy import (
    analyze_child_expansion,
    collect_child_expansion_parents,
)


def test_long_appendix_leaf_is_expandable_but_not_hard_failure() -> None:
    tree = [
        {
            "title": "Appendix A: The bare Interpreter",
            "start_index": 44,
            "end_index": 52,
            "nodes": [],
        }
    ]

    parents = collect_child_expansion_parents(tree, page_count=53)
    report = analyze_child_expansion(tree, page_count=53)

    assert [node["title"] for node in parents] == ["Appendix A: The bare Interpreter"]
    assert report["required_count"] == 1
    assert report["hard_count"] == 0


def test_references_and_index_remain_relaxed_back_matter() -> None:
    tree = [
        {"title": "References", "start_index": 10, "end_index": 40, "nodes": []},
        {"title": "Index", "start_index": 41, "end_index": 53, "nodes": []},
    ]

    parents = collect_child_expansion_parents(tree, page_count=53)
    report = analyze_child_expansion(tree, page_count=53)

    assert parents == []
    assert report["required_count"] == 0
