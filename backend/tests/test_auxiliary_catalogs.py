from pathlib import Path
import sys
import asyncio
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
from pageindex.node_filler import fill_node_text
from pageindex import page_index


def test_extract_auxiliary_catalogs_from_regex_toc_items() -> None:
    analysis = {
        "code_toc": {
            "source": "regex",
            "items": [
                {"title": "1. 正文章节", "physical_index": 4, "structure": "1"},
                {"title": "图1、OpenAI 与微软公司的合作机制", "physical_index": 4, "structure": "2"},
                {"title": "图2、OpenAI 发起人及创始人", "physical_index": 4, "structure": "3"},
                {"title": "表1、OpenAI 核心员工离职后的创业情况", "physical_index": 6, "structure": "4"},
            ],
        }
    }

    catalogs = PageIndexService._build_auxiliary_catalog_nodes(analysis)

    assert [node["title"] for node in catalogs] == ["图目录", "表目录"]
    assert catalogs[0]["node_type"] == "auxiliary_catalog"
    assert catalogs[0]["exclude_from_coverage"] is True
    assert [child["title"] for child in catalogs[0]["nodes"]] == [
        "图1、OpenAI 与微软公司的合作机制",
        "图2、OpenAI 发起人及创始人",
    ]
    assert catalogs[1]["nodes"][0]["title"] == "表1、OpenAI 核心员工离职后的创业情况"


def test_merge_auxiliary_catalogs_appends_without_duplicates() -> None:
    tree = [{"title": "正文", "start_index": 1, "end_index": 5}]
    catalogs = [
        {"title": "图目录", "node_type": "auxiliary_catalog", "nodes": []},
        {"title": "表目录", "node_type": "auxiliary_catalog", "nodes": []},
    ]

    merged = PageIndexService._merge_auxiliary_catalog_nodes(tree, catalogs)
    merged_again = PageIndexService._merge_auxiliary_catalog_nodes(merged, catalogs)

    assert [node["title"] for node in merged_again] == ["正文", "图目录", "表目录"]


def test_fill_node_text_skips_auxiliary_catalog_nodes() -> None:
    tree = [
        {"title": "正文", "start_index": 1, "end_index": 1},
        {
            "title": "图目录",
            "node_type": "auxiliary_catalog",
            "exclude_from_text": True,
            "nodes": [
                {
                    "title": "图1、示例",
                    "node_type": "auxiliary_catalog_item",
                    "exclude_from_text": True,
                    "start_index": 1,
                    "end_index": 1,
                }
            ],
        },
    ]

    fill_node_text(tree, [("正文页面文本", 10)])

    assert tree[0]["text"] == "正文页面文本"
    assert tree[1].get("text", "") == ""
    assert tree[1]["nodes"][0].get("text", "") == ""


def test_large_node_processing_does_not_skip_regular_catalog_group(monkeypatch) -> None:
    calls = []

    async def fake_meta_processor(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    async def fake_check(items, *args, **kwargs):
        return items

    monkeypatch.setattr(page_index, "meta_processor", fake_meta_processor)
    monkeypatch.setattr(page_index, "check_title_appearance_in_start_concurrent", fake_check)

    node = {
        "title": "Contents",
        "node_type": "catalog_group",
        "start_index": 1,
        "end_index": 3,
        "nodes": [
            {
                "title": "Chapter 1",
                "start_index": 1,
                "end_index": 3,
                "nodes": [],
            }
        ],
    }
    opt = SimpleNamespace(
        max_page_num_each_node=1,
        max_token_num_each_node=1,
        model=None,
    )

    asyncio.run(page_index.process_large_node_recursively(node, [("text", 10)] * 3, opt))

    assert calls, "regular catalog groups should not block child processing"


def test_large_node_processing_skips_auxiliary_catalog_group(monkeypatch) -> None:
    async def fail_meta_processor(*args, **kwargs):
        raise AssertionError("auxiliary catalogs should not be expanded as正文 nodes")

    monkeypatch.setattr(page_index, "meta_processor", fail_meta_processor)

    node = {
        "title": "\u56fe\u76ee\u5f55",
        "node_type": "catalog_group",
        "start_index": 1,
        "end_index": 3,
        "nodes": [
            {
                "title": "\u56fe1 \u67b6\u6784",
                "start_index": 1,
                "end_index": 3,
                "nodes": [],
            }
        ],
    }
    opt = SimpleNamespace(
        max_page_num_each_node=1,
        max_token_num_each_node=1,
        model=None,
    )

    result = asyncio.run(page_index.process_large_node_recursively(node, [("text", 10)] * 3, opt))

    assert result is node
