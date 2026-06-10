from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.post_processing import (
    promote_single_catalog_root,
    repair_case_continuation_roots,
    repair_placeholder_chapter_titles,
)


def test_promote_single_catalog_root_when_it_wraps_real_chapters() -> None:
    tree = [
        {
            "title": "目录",
            "start_index": 1,
            "end_index": 43,
            "nodes": [
                {"title": "第一章", "start_index": 4, "end_index": 10},
                {"title": "第二章", "start_index": 11, "end_index": 20},
            ],
        }
    ]

    promoted = promote_single_catalog_root(tree, page_count=43)

    assert [node["title"] for node in promoted] == ["第一章", "第二章"]


def test_does_not_promote_non_covering_catalog_root() -> None:
    tree = [
        {
            "title": "目录",
            "start_index": 10,
            "end_index": 20,
            "nodes": [
                {"title": "子项一", "start_index": 11, "end_index": 12},
                {"title": "子项二", "start_index": 13, "end_index": 14},
            ],
        }
    ]

    assert promote_single_catalog_root(tree, page_count=43) == tree


def test_demotes_case_continuation_root_under_previous_award_chapter() -> None:
    tree = [
        {
            "title": "全球人工智能技术应用突破奖介绍",
            "start_index": 25,
            "end_index": 34,
            "nodes": [
                {"title": "金融AI：蚂蚁数科", "start_index": 34, "end_index": 34}
            ],
        },
        {
            "title": "出行AI：萝卜快跑——保持0重大事故记录",
            "start_index": 35,
            "end_index": 37,
            "nodes": [
                {"title": "消费AI：京东零售 Oxygen 架构", "start_index": 36, "end_index": 36},
                {"title": "医疗AI：深睿医疗", "start_index": 37, "end_index": 37},
            ],
        },
        {
            "title": "第四章 Chapter 4",
            "start_index": 38,
            "end_index": 40,
            "nodes": [
                {"title": "技术趋势：Agent智能体普及", "start_index": 39, "end_index": 39}
            ],
        },
    ]

    repaired = repair_case_continuation_roots(tree)

    assert [node["title"] for node in repaired] == [
        "全球人工智能技术应用突破奖介绍",
        "第四章 Chapter 4",
    ]
    award_children = repaired[0]["nodes"]
    assert [child["title"] for child in award_children] == [
        "金融AI：蚂蚁数科",
        "出行AI：萝卜快跑——保持0重大事故记录",
        "消费AI：京东零售 Oxygen 架构",
        "医疗AI：深睿医疗",
    ]
    assert repaired[0]["end_index"] == 37


def test_repairs_placeholder_chapter_title_from_children() -> None:
    tree = [
        {
            "title": "第四章 Chapter 4",
            "start_index": 38,
            "end_index": 40,
            "nodes": [
                {"title": "技术趋势：Agent智能体普及", "start_index": 39, "end_index": 39},
                {"title": "市场趋势：行业化竞争加剧", "start_index": 40, "end_index": 40},
            ],
        }
    ]

    repaired = repair_placeholder_chapter_titles(tree)

    assert repaired[0]["title"] == "技术趋势与市场趋势"
    assert repaired[0]["original_title"] == "第四章 Chapter 4"
