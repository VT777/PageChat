from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
from pageindex.post_processing import normalize_tree_page_ranges


def test_normalize_catalog_groups_marks_figure_and_table_as_auxiliary() -> None:
    tree = [
        {
            "title": "Contents",
            "page_type": "catalog_group",
            "start_index": 1,
            "end_index": 20,
            "nodes": [{"title": "Chapter 1", "start_index": 3, "end_index": 9}],
        },
        {
            "title": "Figure Catalog",
            "page_type": "catalog_group",
            "start_index": 1,
            "end_index": 20,
            "text": "should be removed",
            "summary": "should be removed",
            "nodes": [{"title": "Figure 1 AI glasses", "start_index": 8, "end_index": 8}],
        },
        {
            "title": "Table Catalog",
            "node_type": "catalog_group",
            "start_index": 1,
            "end_index": 20,
            "text": "should be removed",
            "nodes": [{"title": "Table 1 AI glasses classes", "start_index": 9, "end_index": 9}],
        },
    ]

    normalized = PageIndexService._normalize_auxiliary_catalog_nodes(tree)

    assert normalized[0].get("page_type") != "catalog_group"
    assert normalized[0].get("node_type") != "auxiliary_catalog"
    assert normalized[1]["node_type"] == "auxiliary_catalog"
    assert normalized[1]["catalog_type"] == "figure"
    assert normalized[1]["exclude_from_text"] is True
    assert normalized[1].get("text", "") == ""
    assert normalized[1].get("summary", "") == ""
    assert normalized[1]["nodes"][0]["node_type"] == "auxiliary_catalog_item"
    assert normalized[1]["nodes"][0]["catalog_type"] == "figure"
    assert normalized[2]["node_type"] == "auxiliary_catalog"
    assert normalized[2]["catalog_type"] == "table"


def test_normalize_catalog_groups_recognizes_chinese_figure_and_table_titles() -> None:
    tree = [
        {
            "title": "\u56fe\u76ee\u5f55",
            "page_type": "catalog_group",
            "nodes": [{"title": "\u56fe1 AI\u773c\u955c\u67b6\u6784", "start_index": 8}],
        },
        {
            "title": "\u8868\u683c\u76ee\u5f55",
            "node_type": "catalog_group",
            "nodes": [{"title": "\u88681 \u4ea7\u4e1a\u94fe", "start_index": 9}],
        },
    ]

    normalized = PageIndexService._normalize_auxiliary_catalog_nodes(tree)

    assert [node["node_type"] for node in normalized] == [
        "auxiliary_catalog",
        "auxiliary_catalog",
    ]
    assert [node["catalog_type"] for node in normalized] == ["figure", "table"]
    assert normalized[0]["nodes"][0]["node_type"] == "auxiliary_catalog_item"
    assert normalized[1]["nodes"][0]["catalog_type"] == "table"


def test_final_tree_schema_preserves_auxiliary_catalog_semantics() -> None:
    tree = [
        {"title": "Main Chapter", "start_index": 1, "end_index": 8},
        {
            "title": "List of Figures",
            "node_type": "catalog_group",
            "nodes": [{"title": "Figure 1 Model stack", "start_index": 3}],
        },
    ]

    normalized = PageIndexService._normalize_auxiliary_catalog_nodes(tree)
    final_tree = PageIndexService._normalize_final_tree_schema(
        normalized,
        doc_id="doc-x",
        page_count=8,
    )

    assert final_tree[1]["node_type"] == "auxiliary_catalog"
    assert final_tree[1]["catalog_type"] == "figure"
    assert final_tree[1]["is_auxiliary"] is True
    assert final_tree[1]["exclude_from_coverage"] is True
    assert final_tree[1]["nodes"][0]["node_type"] == "auxiliary_catalog_item"
    assert final_tree[1]["nodes"][0]["is_auxiliary"] is True


def test_normalize_auxiliary_catalogs_merges_duplicate_sources() -> None:
    tree = [
        {
            "title": "图目录",
            "node_type": "catalog_group",
            "nodes": [
                {"title": "图 1 AI 眼镜概念", "start_index": 8, "end_index": 9},
                {"title": "图 2 AI 眼镜发展历程", "start_index": 10, "end_index": 29},
            ],
        },
        {
            "title": "图目录",
            "node_type": "auxiliary_catalog",
            "catalog_type": "figure",
            "nodes": [
                {"title": "图 1 AI 眼镜概念", "start_index": 1, "end_index": 1},
                {"title": "图 3 全球智能眼镜市场预测", "start_index": 30, "end_index": 30},
            ],
        },
        {
            "title": "表目录",
            "page_type": "catalog_group",
            "nodes": [{"title": "表1 AI 眼镜分类", "start_index": 9, "end_index": 25}],
        },
    ]

    normalized = PageIndexService._normalize_auxiliary_catalog_nodes(tree)

    figure_catalogs = [
        node for node in normalized
        if node.get("node_type") == "auxiliary_catalog" and node.get("catalog_type") == "figure"
    ]
    table_catalogs = [
        node for node in normalized
        if node.get("node_type") == "auxiliary_catalog" and node.get("catalog_type") == "table"
    ]

    assert len(figure_catalogs) == 1
    assert len(table_catalogs) == 1
    assert [child["title"] for child in figure_catalogs[0]["nodes"]] == [
        "图 1 AI 眼镜概念",
        "图 2 AI 眼镜发展历程",
        "图 3 全球智能眼镜市场预测",
    ]
    assert figure_catalogs[0]["nodes"][0]["start_index"] == 8
    assert figure_catalogs[0]["nodes"][0]["end_index"] == 9


def test_final_range_normalization_keeps_auxiliary_items_point_like() -> None:
    tree = [
        {
            "title": "Contents",
            "node_type": "catalog_group",
            "start_index": 4,
            "end_index": 20,
            "nodes": [
                {"title": "Chapter 1", "start_index": 4},
                {"title": "Chapter 2", "start_index": 10},
            ],
        },
        {
            "title": "List of Figures",
            "node_type": "auxiliary_catalog",
            "catalog_type": "figure",
            "is_auxiliary": True,
            "nodes": [
                {
                    "title": "Figure 1",
                    "start_index": 5,
                    "end_index": 5,
                    "node_type": "auxiliary_catalog_item",
                    "is_auxiliary": True,
                },
                {
                    "title": "Figure 2",
                    "start_index": 12,
                    "end_index": 12,
                    "node_type": "auxiliary_catalog_item",
                    "is_auxiliary": True,
                },
            ],
        },
    ]

    ranged = normalize_tree_page_ranges(tree, page_count=20)
    normalized = PageIndexService._normalize_auxiliary_catalog_nodes(ranged)

    figure_catalog = next(node for node in normalized if node.get("catalog_type") == "figure")
    assert [(child["start_index"], child["end_index"]) for child in figure_catalog["nodes"]] == [
        (5, 5),
        (12, 12),
    ]
