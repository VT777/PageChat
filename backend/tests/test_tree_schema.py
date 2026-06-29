from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.tree_schema import normalize_tree_node, normalize_title


def test_normalize_tree_node_uses_one_based_inclusive_physical_range():
    node = {
        "title": " 第一章  全球人工智能技术发展洞察 ",
        "level": 1,
        "start_index": 0,
        "end_index": 99,
        "source": "toc_page_visual",
    }

    normalized = normalize_tree_node(node, doc_id="doc-a", page_count=43)

    assert normalized["start_index"] == 1
    assert normalized["end_index"] == 43
    assert normalized["title"] == "第一章 全球人工智能技术发展洞察"
    assert normalized["normalized_title"] == "第一章全球人工智能技术发展洞察"
    assert normalized["id"] == normalize_tree_node(node, doc_id="doc-a", page_count=43)["id"]


def test_normalize_tree_node_keeps_logical_page_separate_from_physical_range():
    node = {
        "title": "案例条目",
        "level": 2,
        "logical_page": 81,
        "printed_page": "77",
        "start_index": 42,
        "end_index": 43,
    }

    normalized = normalize_tree_node(node, doc_id="doc-b", page_count=43)

    assert normalized["start_index"] == 42
    assert normalized["end_index"] == 43
    assert normalized["logical_page"] == 81
    assert normalized["printed_page"] == "77"


def test_normalize_tree_node_marks_child_outside_parent_as_repair_needed():
    parent = {"title": "第二章", "start_index": 11, "end_index": 23, "level": 1}
    child = {"title": "越界子项", "start_index": 24, "end_index": 25, "level": 2}

    normalized = normalize_tree_node(child, doc_id="doc-c", page_count=43, parent=parent)

    assert normalized["start_index"] == 23
    assert normalized["end_index"] == 23
    assert normalized["needs_repair"] is True
    assert "range_outside_parent" in normalized["repair_reasons"]


def test_normalize_tree_node_marks_auxiliary_excluded_from_coverage():
    node = {
        "title": "图目录",
        "level": 1,
        "start_index": 2,
        "end_index": 2,
        "is_auxiliary": True,
    }

    normalized = normalize_tree_node(node, doc_id="doc-d", page_count=10)

    assert normalized["is_auxiliary"] is True
    assert normalized["exclude_from_coverage"] is True
    assert normalized["exclude_from_llm_qc"] is True


def test_normalize_tree_node_syncs_page_source_anchor_to_final_range():
    node = {
        "title": "（五）我国加速扩大全球影响力",
        "level": 2,
        "start_index": 34,
        "end_index": 34,
        "source_anchor": {
            "format": "pdf",
            "unit_type": "page",
            "start_page": 34,
            "end_page": 33,
        },
    }

    normalized = normalize_tree_node(node, doc_id="doc-e", page_count=49)

    assert normalized["start_index"] == 34
    assert normalized["end_index"] == 34
    assert normalized["source_anchor"] == {
        "format": "pdf",
        "unit_type": "page",
        "start_page": 34,
        "end_page": 34,
    }


def test_normalize_title_removes_spacing_but_preserves_letters():
    assert normalize_title("AI 十大行业 技术应用") == "ai十大行业技术应用"
