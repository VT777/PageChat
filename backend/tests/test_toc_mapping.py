from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.toc_mapping import map_toc_draft_to_physical


def test_map_toc_draft_keeps_physical_page_labels_when_titles_match() -> None:
    page_texts = [
        "Cover",
        "Contents\n1.3 Valuation ........ 7\n4 Risk warning ........ 25",
        "Preface",
        "Body",
        "Body",
        "Body",
        "1.3 Valuation: Latest valuation reaches 750B USD\nBody",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "Body",
        "4 Risk warning\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {"title": "1.3 Valuation", "level": 2, "raw_page_label": 7},
            {"title": "4 Risk warning", "level": 1, "raw_page_label": 25},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert [item["physical_index"] for item in mapped] == [7, 25]
    assert [item["mapping_source"] for item in mapped] == ["physical_identity", "physical_identity"]
    assert report["status"] == "ok"
    assert report["strategy"] == "physical_identity"


def test_map_toc_draft_uses_printed_page_offset_only_with_content_anchors() -> None:
    page_texts = [
        "Cover",
        "Contents\nAlpha ........ 1\nBeta ........ 3",
        "Intro",
        "Alpha\nBody",
        "Alpha details",
        "Beta\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_toc_page",
        "section_kind": "main_toc",
        "items": [
            {"title": "Alpha", "level": 1, "raw_page_label": 1},
            {"title": "Beta", "level": 1, "raw_page_label": 3},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert [item["physical_index"] for item in mapped] == [4, 6]
    assert report["status"] == "ok"
    assert report["strategy"] == "printed_page_offset"
    assert report["strong_anchor_count"] >= 2


def test_map_toc_draft_locates_unpaged_toc_by_title_search() -> None:
    page_texts = [
        "Cover",
        "Contents\nAlpha\nBeta",
        "Intro",
        "Alpha\nBody",
        "Alpha details",
        "More alpha",
        "More alpha",
        "Beta\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_toc_page",
        "section_kind": "main_toc",
        "items": [
            {"title": "Alpha", "level": 1},
            {"title": "Beta", "level": 1},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
    )

    assert [item["physical_index"] for item in mapped] == [4, 8]
    assert report["status"] == "ok"
    assert report["strategy"] == "content_title_search"


def test_map_toc_draft_uses_repeated_catalog_pages_as_unpaged_section_dividers() -> None:
    catalog_text = "\n".join(
        [
            "国外大厂AI应用落地",
            "01",
            "国内大厂AI应用落地",
            "02",
            "目录",
            "产业链梳理",
            "03",
            "风险提示",
            "04",
        ]
    )
    page_texts = [
        "Cover",
        "Summary",
        catalog_text,
        "Open AI发布 ChatGPT Health 健康应用",
        "Anthropic Claude for Healthcare",
        "亚马逊 推出AI退货看板",
        "谷歌 AI模型最新迭代及场景化落地",
        "英伟达 推出全新Rubin平台",
        catalog_text,
        "阿里巴巴 AQ健康品牌升级",
        "字节 官宣成为央视春晚独家AI伙伴",
        "DeepSeek 即将发布V4旗舰模型",
        "腾讯 云小程序成长计划",
        "智谱AI与MiniMax 登陆港股",
        "海外与国内应用小结",
        catalog_text,
        "AI产业链梳理",
        catalog_text,
        "风险提示",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {"title": "国外大厂AI应用落地", "level": 1, "structure": "01"},
            {"title": "国内大厂AI应用落地", "level": 1, "structure": "02"},
            {"title": "产业链梳理", "level": 1, "structure": "03"},
            {"title": "风险提示", "level": 1, "structure": "04"},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[3],
        selected_path="visible_toc_no_pages",
    )

    assert report["status"] == "ok"
    assert report["strategy"] == "section_divider_sequence"
    assert [item["physical_index"] for item in mapped] == [3, 9, 16, 18]


def test_unpaged_section_divider_sequence_reorders_by_explicit_markers() -> None:
    catalog_text = "\n".join(
        [
            "汇报提纲",
            "AI驱动的第五科研范式",
            "一",
            "百花齐放的大模型时代",
            "二",
            "大模型辅助的科学假设生成",
            "三",
            "未来科研范式展望",
            "五",
            "大模型辅助的论文与项目",
            "四",
        ]
    )
    page_texts = [
        "Cover",
        catalog_text,
        catalog_text,
    ] + ["第一章正文"] * 9 + [
        catalog_text,
    ] + ["第二章正文"] * 21 + [
        catalog_text,
    ] + ["第三章正文"] * 13 + [
        catalog_text,
    ] + ["第四章正文"] * 11 + [
        catalog_text,
        "第五章正文",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {"title": "AI驱动的第五科研范式", "level": 1, "structure": "一"},
            {"title": "百花齐放的大模型时代", "level": 1, "structure": "二"},
            {"title": "大模型辅助的科学假设生成", "level": 1, "structure": "三"},
            {"title": "未来科研范式展望", "level": 1, "structure": "五"},
            {"title": "大模型辅助的论文与项目", "level": 1, "structure": "四"},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2, 3],
        selected_path="visible_toc_no_pages",
    )

    assert report["status"] == "ok"
    assert report["strategy"] == "section_divider_sequence"
    assert [item["title"] for item in mapped] == [
        "AI驱动的第五科研范式",
        "百花齐放的大模型时代",
        "大模型辅助的科学假设生成",
        "大模型辅助的论文与项目",
        "未来科研范式展望",
    ]
    assert [item["physical_index"] for item in mapped] == [3, 13, 35, 49, 61]


def test_map_toc_draft_maps_auxiliary_catalogs_independently() -> None:
    page_texts = [
        "Cover",
        "Contents\nChapter A ........ 4\nList of Figures\nFigure 1 Model flow ........ 5",
        "Preface",
        "Chapter A\nBody",
        "Figure 1 Model flow\nBody",
        "Chapter B\nBody",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "toc_sections": [
            {
                "kind": "main_toc",
                "items": [{"title": "Chapter A", "level": 1, "raw_page_label": 4}],
            },
            {
                "kind": "figure_toc",
                "items": [{"title": "Figure 1 Model flow", "level": 1, "raw_page_label": 5}],
            },
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert [(item["section_kind"], item["physical_index"]) for item in mapped] == [
        ("main_toc", 4),
        ("figure_toc", 5),
    ]
    assert [section["kind"] for section in report["sections"]] == ["main_toc", "figure_toc"]
    assert report["sections"][0]["strategy"] == "physical_identity"
    assert report["sections"][1]["strategy"] == "physical_identity"


def test_mapping_report_preserves_main_title_match_when_auxiliary_catalogs_are_weaker() -> None:
    page_texts = [
        "Cover",
        "Contents\nChapter A ........ 4\nChapter B ........ 6\nList of Figures\nFigure 1 ........ 4\nFigure 2 ........ 5\nFigure 3 ........ 6\nFigure 4 ........ 7",
        "Preface",
        "Chapter A\nBody",
        "Body",
        "Chapter B\nBody",
        "Body",
    ]
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "toc_sections": [
            {
                "kind": "main_toc",
                "items": [
                    {"title": "Chapter A", "level": 1, "raw_page_label": 4},
                    {"title": "Chapter B", "level": 1, "raw_page_label": 6},
                ],
            },
            {
                "kind": "figure_toc",
                "items": [
                    {"title": "Figure 1 Architecture", "level": 1, "raw_page_label": 4},
                    {"title": "Figure 2 Pipeline", "level": 1, "raw_page_label": 5},
                    {"title": "Figure 3 Revenue", "level": 1, "raw_page_label": 6},
                    {"title": "Figure 4 Risk", "level": 1, "raw_page_label": 7},
                ],
            },
        ],
    }

    _mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_with_pages",
    )

    assert report["status"] == "ok"
    assert report["title_match_rate"] < 0.45
    assert report["main_title_match_rate"] == 1.0
    assert report["main_sample_checked_count"] == 2
