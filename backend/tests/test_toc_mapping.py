from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.toc_mapping import derive_toc_ranges, map_toc_draft_to_physical


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
    assert report["toc_pages"] == [2]
    assert report["excluded_pages"] == [2]


def test_map_toc_draft_fills_missing_page_labels_with_title_search() -> None:
    page_texts = [f"Body page {page}" for page in range(1, 27)]
    page_texts[0] = "Cover"
    page_texts[1] = "\n".join(
        [
            "目录",
            "1. Review ........................................ 4",
            "1.1 Overview ..................................... 4",
            "2. Outlook ....................................... 9",
            "3. Ecosystem ..................................... 20",
            "4. Risk warning ..................................",
        ]
    )
    page_texts[2] = "Figure catalog"
    page_texts[3] = "1. Review\n1.1 Overview\nbody"
    page_texts[8] = "2. Outlook\nbody"
    page_texts[19] = "3. Ecosystem\nbody"
    page_texts[24] = "4. Risk warning\nbody"
    draft = {
        "type": "toc_draft",
        "toc_sections": [
            {
                "kind": "main_toc",
                "items": [
                    {"title": "1. Review", "level": 1, "raw_page_label": 4},
                    {"title": "1.1 Overview", "level": 2, "raw_page_label": 4},
                    {"title": "2. Outlook", "level": 1, "raw_page_label": 9},
                    {"title": "3. Ecosystem", "level": 1, "raw_page_label": 20},
                    {"title": "4. Risk warning", "level": 1},
                ],
            }
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2, 3],
        selected_path="visible_toc_with_pages",
    )

    by_title = {item["title"]: item for item in mapped}
    assert by_title["4. Risk warning"]["physical_index"] == 25
    assert by_title["4. Risk warning"]["mapping_source"] == "title_search"
    assert report["status"] == "ok"
    assert report["toc_pages"] == [2, 3]
    assert report["excluded_pages"] == [2, 3]


def test_content_outline_declared_pages_do_not_bypass_title_evidence() -> None:
    page_texts = [
        "Cover",
        "Catalog",
        "OCR text whose heading is noisy",
        "More OCR text",
        "Another page",
    ]
    draft = {
        "type": "toc_draft",
        "source": "content_outline",
        "section_kind": "main_toc",
        "items": [
            {"title": "Clean LLM heading A", "level": 1, "raw_page_label": 3},
            {"title": "Clean LLM heading B", "level": 1, "raw_page_label": 5},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="content_outline",
    )

    assert report["status"] == "failed"
    assert report["strategy"] == "content_title_search"
    assert {item["mapping_source"] for item in mapped} == {"unmapped"}


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


def test_map_toc_draft_keeps_stable_offset_for_truncated_overflow_labels() -> None:
    page_texts = ["Cover", "Blank", "Contents"] + ["Body"] * 47
    page_texts[6] = "1 Overview\nBody"
    page_texts[8] = "2 Monetary Policy and Economic Developments\nBody"
    page_texts[20] = (
        "3 Financial Stability\n"
        "This chapter mentions Supervision and Regulation before that chapter starts."
    )
    page_texts[30] = "4 Supervision and Regulation\nBody"
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {"title": "1 Overview", "level": 1, "raw_page_label": 1},
            {"title": "2 Monetary Policy and Economic Developments", "level": 1, "raw_page_label": 3},
            {"title": "3 Financial Stability", "level": 1, "raw_page_label": 15},
            {"title": "4 Supervision and Regulation", "level": 1, "raw_page_label": 25},
            {"title": "5 Payment System and Reserve Bank Oversight", "level": 1, "raw_page_label": 53},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[3],
        selected_path="visible_toc_with_pages",
    )

    assert [item["physical_index"] for item in mapped[:4]] == [7, 9, 21, 31]
    assert mapped[4]["physical_index"] == 50
    assert report["status"] == "ok"
    assert report["strategy"] == "printed_page_offset"


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


def test_map_toc_draft_locates_part_title_across_split_heading_lines() -> None:
    page_texts = ["Cover", "Contents\nPart01\nPart02\nPart03", "Preface"]
    page_texts.extend([""] * 59)
    page_texts[4] = "Part01\nMarket analysis\nM-shaped consumer trends and acquisition challenges"
    page_texts[12] = (
        "122,344,45,87,90,Part02\n"
        "306,481,78,461,90,Growth Engine One: AI Mindshare\n"
        "306,583,78,461,90,Predictive Social Ecosystem Guide"
    )
    page_texts[24] = "Part03\nContent marketing industrialization\nTag-thinking driven growth"
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {
                "title": "Part01: Market analysis: M-shaped consumer trends and acquisition challenges",
                "level": 1,
            },
            {
                "title": "Part02: AI Mindshare: Predictive Social Ecosystem Guide",
                "level": 1,
            },
            {
                "title": "Part03: Content marketing industrialization: Tag-thinking driven growth",
                "level": 1,
            },
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
    )

    assert [item["physical_index"] for item in mapped] == [5, 13, 25]
    assert [item["mapping_source"] for item in mapped] == ["title_search", "title_search", "title_search"]
    assert report["status"] == "ok"
    assert report["title_match_rate"] == 1.0


def test_map_toc_draft_locates_chinese_part_title_across_split_heading_lines() -> None:
    page_texts = [
        "Cover",
        "Contents\nPart01\nPart02\nPart03",
        "Preface",
    ]
    page_texts.extend([""] * 59)
    page_texts[4] = "Part01\n\u5e02\u573a\u5206\u6790\nM\u578b\u6d88\u8d39\u8d8b\u52bf\u4e0e\u83b7\u5ba2\u6311\u6218"
    page_texts[12] = (
        "122,344,45,87,90,Part02\n"
        "306,481,78,461,90,\u589e\u957f\u5f15\u64ce\u4e00\uff1aAI\u5fc3\u667a\u5360\u4f4d\n"
        "306,583,78,461,90,\u9884\u6d4b\u5f0f\u793e\u4ea4\u751f\u6001\u5b9e\u6218\u6307\u5357"
    )
    page_texts[24] = "Part03\n\u5185\u5bb9\u8425\u9500\u5de5\u4e1a\u5316\n\u6807\u7b7e\u601d\u7ef4\u9a71\u52a8\u5de5\u4e1a\u5316\u589e\u957f"
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {
                "title": "Part01: \u5e02\u573a\u5206\u6790\uff1a\u201cM\u578b\u201d\u6d88\u8d39\u8d8b\u52bf\u4e0e\u83b7\u5ba2\u6311\u6218",
                "level": 1,
            },
            {
                "title": "Part02: AI\u5fc3\u667a\u5360\u4f4d\uff1a\u9884\u6d4b\u5f0f\u793e\u4ea4\u751f\u6001\u5b9e\u6218\u6307\u5357",
                "level": 1,
            },
            {
                "title": "Part03: \u5185\u5bb9\u8425\u9500\u5de5\u4e1a\u5316\uff1a\u6807\u7b7e\u601d\u7ef4\u9a71\u52a8\u5de5\u4e1a\u5316\u589e\u957f",
                "level": 1,
            },
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
    )

    assert [item["physical_index"] for item in mapped] == [5, 13, 25]
    assert [item["mapping_source"] for item in mapped] == ["title_search", "title_search", "title_search"]
    assert report["status"] == "ok"
    assert report["title_match_rate"] == 1.0


def test_unpaged_toc_mapping_fails_instead_of_collapsing_missing_anchor_to_previous_page() -> None:
    page_texts = ["Cover", "Contents\nAlpha\nBeta\nGamma", "Preface"]
    page_texts.extend([""] * 27)
    page_texts[4] = "Alpha\nOpening chapter"
    page_texts[19] = "Gamma\nFinal chapter"
    draft = {
        "type": "toc_draft",
        "source": "visible_toc_rule",
        "section_kind": "main_toc",
        "items": [
            {"title": "Alpha", "level": 1},
            {"title": "Beta title not present in content", "level": 1},
            {"title": "Gamma", "level": 1},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
    )

    assert mapped[0]["physical_index"] == 5
    assert "physical_index" not in mapped[1]
    assert mapped[1]["mapping_source"] == "unmapped"
    assert mapped[2]["physical_index"] == 20
    assert report["status"] == "failed"
    assert "unmapped_required_anchor" in report["reasons"]


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
    assert report["boundary_anchor_count"] == 4
    assert report["page_mapping_score"] == 0.76
    assert report["evidence_modes"] == ["boundary_sequence"]
    assert report["toc_pages"] == [3]
    assert report["excluded_pages"] == [3]
    assert report["section_divider_pages"] == [9, 16, 18]
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
    assert report["boundary_anchor_count"] == 5
    assert report["evidence_modes"] == ["boundary_sequence"]
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


def test_derive_toc_ranges_recursively_uses_sibling_boundaries() -> None:
    tree = [
        {
            "title": "Chapter 1",
            "start_index": 3,
            "nodes": [
                {"title": "1.1", "start_index": 4},
                {"title": "1.2", "start_index": 7},
            ],
        },
        {"title": "Chapter 2", "start_index": 10},
    ]

    derived = derive_toc_ranges(tree, page_count=20)

    assert derived[0]["end_index"] == 9
    assert derived[1]["end_index"] == 20
    assert [child["end_index"] for child in derived[0]["nodes"]] == [6, 9]


def test_derive_toc_ranges_allows_boundary_overlap_when_next_title_is_not_near_page_top() -> None:
    tree = [
        {
            "title": "Chapter 1",
            "start_index": 3,
            "mapping_evidence": {"matched_page": 3, "near_page_top": True},
        },
        {
            "title": "Chapter 2",
            "start_index": 10,
            "mapping_evidence": {"matched_page": 10, "near_page_top": False},
        },
        {
            "title": "Chapter 3",
            "start_index": 15,
            "mapping_evidence": {"matched_page": 15, "near_page_top": True},
        },
    ]

    derived = derive_toc_ranges(tree, page_count=20)

    assert derived[0]["end_index"] == 10
    assert derived[0]["range_boundary"] == "overlap_with_next_start"
    assert derived[1]["end_index"] == 14
    assert derived[1]["range_boundary"] == "exclusive_before_next_start"


def test_title_search_mapping_sets_near_page_top_evidence_for_boundary_ranges() -> None:
    page_texts = [
        "Cover",
        "Contents\nChapter 1\nChapter 2\nChapter 3",
        "Chapter 1\nopening body",
        "Chapter 1 continued",
        "Chapter 1 still running\n\n\n\n\n\nChapter 2\nstarts after prior chapter text",
        "Chapter 2 continued",
        "Chapter 3\nnew page heading",
        "Tail",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_toc_page",
        "section_kind": "main_toc",
        "items": [
            {"title": "Chapter 1", "level": 1},
            {"title": "Chapter 2", "level": 1},
            {"title": "Chapter 3", "level": 1},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
    )
    derived = derive_toc_ranges(mapped, page_count=len(page_texts))

    assert report["status"] == "ok"
    assert mapped[1]["physical_index"] == 5
    assert mapped[1]["mapping_evidence"]["near_page_top"] is False
    assert derived[0]["end_index"] == 5
    assert derived[0]["range_boundary"] == "overlap_with_next_start"


def test_mapping_can_be_restricted_to_parent_page_range() -> None:
    page_texts = [
        "Subsection A appears in unrelated front matter",
        "Contents",
        "Chapter parent",
        "Body before child",
        "Subsection A\nactual child heading",
        "Tail inside chapter",
        "Back matter",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_chapter_snippet",
        "section_kind": "main_toc",
        "items": [
            {
                "title": "Subsection A",
                "level": 2,
                "raw_page_label": 4,
            }
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        selected_path="visible_toc_no_pages",
        allowed_page_range=(3, 6),
    )

    assert report["status"] == "ok"
    assert mapped[0]["physical_index"] == 5
    assert mapped[0]["mapping_source"] == "title_search"


def test_parent_scoped_unpaged_mapping_skips_top_level_divider_sequence() -> None:
    page_texts = [
        "Cover",
        "Contents",
        "Parent chapter",
        "3.1 Alpha\n3.2 Beta\n3.3 Gamma",
        "Intro text",
        "3.1 Alpha\nActual alpha body",
        "3.2 Beta\nActual beta body",
        "3.3 Gamma\nActual gamma body",
    ]
    draft = {
        "type": "toc_draft",
        "source": "llm_chapter_snippet",
        "section_kind": "main_toc",
        "items": [
            {"title": "3.1 Alpha", "level": 2, "structure": "3.1"},
            {"title": "3.2 Beta", "level": 2, "structure": "3.2"},
            {"title": "3.3 Gamma", "level": 2, "structure": "3.3"},
        ],
    }

    mapped, report = map_toc_draft_to_physical(
        draft,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[4],
        selected_path="visible_toc_no_pages",
        allowed_page_range=(4, 8),
    )

    assert report["status"] == "ok"
    assert report["strategy"] == "content_title_search"
    assert [item["physical_index"] for item in mapped] == [6, 7, 8]


def test_derive_toc_ranges_clamps_invalid_child_ranges_to_parent() -> None:
    tree = [
        {
            "title": "Chapter 1",
            "start_index": 3,
            "end_index": 8,
            "nodes": [
                {"title": "Before parent", "start_index": 1, "end_index": 99},
                {"title": "After parent", "start_index": 20},
            ],
        }
    ]

    derived = derive_toc_ranges(tree, page_count=10)

    assert derived[0]["start_index"] == 3
    assert derived[0]["end_index"] == 10
    assert derived[0]["nodes"][0]["start_index"] == 3
    assert derived[0]["nodes"][0]["end_index"] == 9
    assert derived[0]["nodes"][1]["start_index"] == 10
    assert derived[0]["nodes"][1]["end_index"] == 10


def test_derive_toc_ranges_keeps_catalog_roots_independent() -> None:
    tree = [
        {
            "title": "目录",
            "node_type": "catalog_group",
            "nodes": [
                {"title": "Chapter 1", "start_index": 4},
                {"title": "Chapter 2", "start_index": 10},
            ],
        },
        {
            "title": "图目录",
            "node_type": "catalog_group",
            "is_auxiliary": True,
            "nodes": [
                {"title": "Figure 1", "start_index": 4, "node_type": "auxiliary_catalog_item"},
                {"title": "Figure 2", "start_index": 6, "node_type": "auxiliary_catalog_item"},
            ],
        },
    ]

    derived = derive_toc_ranges(tree, page_count=20)

    assert derived[0]["start_index"] == 4
    assert derived[0]["end_index"] == 20
    assert [child["end_index"] for child in derived[0]["nodes"]] == [9, 20]
    assert derived[1]["start_index"] == 4
    assert derived[1]["end_index"] == 6
    assert [child["end_index"] for child in derived[1]["nodes"]] == [4, 6]
