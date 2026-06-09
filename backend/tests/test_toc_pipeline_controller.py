import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import balanced_toc as balanced_toc_module
from pageindex import post_processing as post_processing_module
from pageindex import toc_detector as toc_detector_module
from pageindex.quality_validator import validate_toc
from pageindex.visual_extractor import extract_visual_toc
from app.services.pageindex_service import PageIndexService


def _flatten_titles(nodes):
    titles = []
    for node in nodes:
        titles.append(node.get("title"))
        titles.extend(_flatten_titles(node.get("nodes") or []))
    return titles


def test_flat_toc_normalizer_merges_visual_label_titles_into_part_items():
    toc_items = [
        {"title": "Part01：市场分析：“M型”消费趋势与获客挑战", "level": 1},
        {"title": "增长引擎一·AI心智占位：预测式社交生态实战指南", "level": 1},
        {"title": "Part02：AI心智占位：预测式社交生态实战指南", "level": 1},
        {"title": "增长引擎二·内容营销工业化：标签思维驱动工业化增长", "level": 1},
        {"title": "Part03：内容营销工业化：标签思维驱动工业化增长", "level": 1},
        {"title": "增长引擎三·数据基建：驱动端到端进化的数字底座", "level": 1},
        {"title": "Part04：数据基建：驱动端到端进化的数字底座", "level": 1},
        {"title": "Part05：AI变革落地：快消品牌AI营销案例", "level": 1},
    ]

    merged = balanced_toc_module._merge_flat_toc_subtitle_labels(toc_items)

    assert [item["title"] for item in merged] == [
        "Part01：市场分析：“M型”消费趋势与获客挑战",
        "Part02：增长引擎一：AI心智占位：预测式社交生态实战指南",
        "Part03：增长引擎二：内容营销工业化：标签思维驱动工业化增长",
        "Part04：增长引擎三：数据基建：驱动端到端进化的数字底座",
        "Part05：AI变革落地：快消品牌AI营销案例",
    ]


def test_visual_extractor_preserves_balanced_toc_items(monkeypatch):
    async def fake_build_balanced_toc_visual(**_kwargs):
        return {
            "toc_items": [
                {"title": "01 case", "level": 2, "physical_index": 3},
                {"title": "02 case", "level": 2, "physical_index": 4},
            ],
            "source": "vlm_toc",
        }

    monkeypatch.setattr(
        balanced_toc_module,
        "build_balanced_toc_visual",
        fake_build_balanced_toc_visual,
    )

    result = asyncio.run(
        extract_visual_toc(
            "dummy.pdf",
            {"page_count": 44},
            model=None,
            anchors={"toc_pages": [2], "chapter_dividers": []},
        )
    )

    assert result is not None
    assert result["items"][0]["physical_index"] == 3
    assert result["source"] == "vlm_toc"
    assert result["mapped"] is True


def test_visual_extractor_preserves_prevalidated_visual_skeleton(monkeypatch):
    async def fake_build_balanced_toc_visual(**_kwargs):
        return {
            "toc_items": [{"title": "A", "level": 1, "physical_index": 5}],
            "source": "vlm_toc_skeleton",
            "mapped": True,
            "prevalidated": True,
        }

    monkeypatch.setattr(
        balanced_toc_module,
        "build_balanced_toc_visual",
        fake_build_balanced_toc_visual,
    )

    result = asyncio.run(
        extract_visual_toc(
            "dummy.pdf",
            {"page_count": 43},
            model=None,
            anchors={"toc_pages": [2], "chapter_dividers": [5]},
        )
    )

    assert result is not None
    assert result["source"] == "vlm_toc_skeleton"
    assert result["prevalidated"] is True


def test_visual_extractor_preserves_semi_frozen_visual_skeleton(monkeypatch):
    async def fake_build_balanced_toc_visual(**_kwargs):
        return {
            "toc_items": [{"title": "A", "level": 1, "physical_index": 4}],
            "source": "vlm_toc_skeleton",
            "mapped": True,
            "semi_frozen": True,
            "prevalidated": True,
        }

    monkeypatch.setattr(
        balanced_toc_module,
        "build_balanced_toc_visual",
        fake_build_balanced_toc_visual,
    )

    result = asyncio.run(
        extract_visual_toc(
            "dummy.pdf",
            {"page_count": 43},
            model=None,
            anchors={"toc_pages": [2], "chapter_dividers": []},
        )
    )

    assert result is not None
    assert result["semi_frozen"] is True


def test_visual_extractor_passes_full_analysis_to_balanced_visual(monkeypatch):
    async def fake_build_balanced_toc_visual(**kwargs):
        assert kwargs["analysis"].get("page_texts") == ["toc", "chapter"]
        return {
            "toc_items": [{"title": "A", "level": 1, "physical_index": 2}],
            "source": "vlm_toc_skeleton",
            "mapped": True,
            "prevalidated": True,
        }

    monkeypatch.setattr(
        balanced_toc_module,
        "build_balanced_toc_visual",
        fake_build_balanced_toc_visual,
    )

    result = asyncio.run(
        extract_visual_toc(
            "dummy.pdf",
            {"page_count": 43, "page_texts": ["toc", "chapter"]},
            model=None,
            anchors={"toc_pages": [1], "chapter_dividers": []},
        )
    )

    assert result is not None


def test_balanced_visual_reuses_provided_toc_pages(monkeypatch):
    async def fail_if_detecting_again(*_args, **_kwargs):
        raise AssertionError("toc_pages should be reused, not detected again")

    async def fake_quick_extract_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "category one", "level": 1, "page": 1},
                {"title": "01 case", "level": 2, "page": 1},
                {"title": "category two", "level": 1, "page": 3},
                {"title": "02 case", "level": 2, "page": 3},
            ]
        }

    async def fake_branch_a(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "01 case", "level": 2, "physical_index": 3},
                {"title": "02 case", "level": 2, "physical_index": 4},
            ],
            "source": "vlm_toc",
        }

    monkeypatch.setattr(toc_detector_module, "find_toc_pages", fail_if_detecting_again)
    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fake_branch_a)

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 44},
            model=None,
            anchors={
                "toc_pages": [2],
                "chapter_dividers": [],
                "first_content_page": 3,
            },
        )
    )

    assert result["source"] == "vlm_toc"
    assert len(result["toc_items"]) == 2


def test_balanced_visual_preserves_flat_toc_skeleton_over_dividers(monkeypatch):
    async def fail_if_detecting_again(*_args, **_kwargs):
        raise AssertionError("toc_pages should be reused, not detected again")

    async def fake_quick_extract_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Global AI capabilities and market scale", "level": 1, "page": 1},
                {"title": "AI penetration by key industries", "level": 1, "page": 1},
                {"title": "AI application breakthrough awards", "level": 1, "page": 1},
                {"title": "Technology trends and risks", "level": 1, "page": 1},
            ]
        }

    async def fake_branch_a(*_args, **_kwargs):
        return {
            "toc_items": [
                {
                    "title": "Global AI capabilities and market scale",
                    "level": 1,
                    "physical_index": 5,
                },
                {
                    "title": "AI penetration by key industries",
                    "level": 1,
                    "physical_index": 13,
                },
                {
                    "title": "AI application breakthrough awards",
                    "level": 1,
                    "physical_index": 25,
                },
                {
                    "title": "Technology trends and risks",
                    "level": 1,
                    "physical_index": 38,
                },
            ],
            "source": "vlm_toc",
        }

    async def fail_branch_b(*_args, **_kwargs):
        raise AssertionError("flat but valid TOC skeleton should not let dividers own top-level")

    monkeypatch.setattr(toc_detector_module, "find_toc_pages", fail_if_detecting_again)
    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fake_branch_a)
    monkeypatch.setattr(balanced_toc_module, "_branch_b_normal_dividers", fail_branch_b)

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 43},
            model=None,
            anchors={
                "toc_pages": [2],
                "chapter_dividers": [5, 13, 25, 35, 41],
                "first_content_page": 5,
            },
        )
    )

    assert result["source"] == "vlm_toc_skeleton"
    assert [item["title"] for item in result["toc_items"]] == [
        "Global AI capabilities and market scale",
        "AI penetration by key industries",
        "AI application breakthrough awards",
        "Technology trends and risks",
    ]


def test_balanced_visual_merges_toc_subtitle_labels_into_part_items(monkeypatch):
    async def fake_quick_extract_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Part01：市场分析：“M型”消费趋势与获客挑战", "level": 1},
                {"title": "增长引擎一：", "level": 1},
                {"title": "Part02：AI心智占位：预测式社交生态实战指南", "level": 1},
                {"title": "增长引擎二：", "level": 1},
                {"title": "Part03：内容营销工业化：标签思维驱动工业化增长", "level": 1},
                {"title": "增长引擎三：", "level": 1},
                {"title": "Part04：数据基建：驱动端到端进化的数字底座", "level": 1},
                {"title": "Part05：AI变革落地：快消品牌AI营销案例", "level": 1},
            ]
        }

    async def fail_branch_a(*_args, **_kwargs):
        raise AssertionError("valid flat TOC skeleton should be preserved after subtitle merge")

    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fail_branch_a)

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 62},
            model=None,
            anchors={
                "toc_pages": [4],
                "chapter_dividers": [5, 13, 25, 35, 41],
                "first_content_page": 5,
            },
        )
    )

    assert result["source"] == "vlm_toc_skeleton"
    assert [item["title"] for item in result["toc_items"]] == [
        "Part01：市场分析：“M型”消费趋势与获客挑战",
        "Part02：增长引擎一：AI心智占位：预测式社交生态实战指南",
        "Part03：增长引擎二：内容营销工业化：标签思维驱动工业化增长",
        "Part04：增长引擎三：数据基建：驱动端到端进化的数字底座",
        "Part05：AI变革落地：快消品牌AI营销案例",
    ]
    assert [item["physical_index"] for item in result["toc_items"]] == [5, 13, 25, 35, 41]


def test_balanced_visual_does_not_reextract_valid_flat_toc_skeleton(monkeypatch):
    async def fake_quick_extract_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Global AI technology development insight", "level": 1, "page": 1},
                {"title": "Top industry AI application demand insight", "level": 1, "page": 2},
                {"title": "Global AI technology application awards", "level": 1, "page": 3},
                {"title": "Global AI technology application future trends", "level": 1, "page": 4},
            ]
        }

    async def fail_branch_a(*_args, **_kwargs):
        raise AssertionError("valid flat TOC skeleton should be preserved, not re-extracted")

    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fail_branch_a)

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 43},
            model=None,
            anchors={
                "toc_pages": [2],
                "chapter_dividers": [5, 13, 25, 35, 41],
                "first_content_page": 5,
            },
        )
    )

    assert result["source"] == "vlm_toc_skeleton"
    assert result["mapped"] is True
    assert result["prevalidated"] is True
    assert [item["title"] for item in result["toc_items"]] == [
        "Global AI technology development insight",
        "Top industry AI application demand insight",
        "Global AI technology application awards",
        "Global AI technology application future trends",
    ]
    assert [item["physical_index"] for item in result["toc_items"]] == [5, 13, 25, 35]


def test_balanced_visual_maps_flat_skeleton_with_text_chapter_anchors(monkeypatch):
    async def fake_quick_extract_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Global AI technology development insight", "level": 1, "page": 1},
                {"title": "Top industry AI application demand insight", "level": 1, "page": 1},
                {"title": "Global AI technology application awards", "level": 1, "page": 1},
                {"title": "Global AI technology application future trends", "level": 1, "page": 1},
            ]
        }

    async def fail_branch_a(*_args, **_kwargs):
        raise AssertionError("valid flat TOC skeleton should be preserved")

    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fail_branch_a)

    page_texts = [""] * 43
    page_texts[4] = "Chapter 1 Global AI technology development insight"
    page_texts[11] = "Chapter 2 Top industry AI application demand insight"
    page_texts[24] = "Chapter 3 Global AI technology application awards"
    page_texts[38] = "Chapter 4 Global AI technology application future trends"

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 43, "page_texts": page_texts},
            model=None,
            anchors={
                "toc_pages": [2],
                "chapter_dividers": [5, 13, 25, 35, 41],
                "first_content_page": 5,
            },
        )
    )

    assert [item["physical_index"] for item in result["toc_items"]] == [5, 12, 25, 39]


def test_balanced_visual_maps_chapter_cover_before_first_content(monkeypatch):
    async def fake_quick_extract_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Global AI technology development insight", "level": 1, "page": 1},
                {"title": "Top industry AI application demand insight", "level": 1, "page": 2},
                {"title": "Global AI technology application awards", "level": 1, "page": 3},
                {"title": "Global AI technology application future trends", "level": 1, "page": 4},
            ]
        }

    async def fail_branch_a(*_args, **_kwargs):
        raise AssertionError("valid flat TOC skeleton should be preserved")

    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fail_branch_a)

    page_texts = [""] * 43
    page_texts[3] = "Chapter 1 ◆ ◆ ◆"
    page_texts[10] = "Chapter 2 AI industry demand insight"
    page_texts[23] = "Chapter 3 AI application breakthrough awards"
    page_texts[37] = "Chapter 4 future trends"

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 43, "page_texts": page_texts},
            model=None,
            anchors={
                "toc_pages": [2],
                "chapter_dividers": [],
                "first_content_page": 5,
            },
        )
    )

    assert [item["physical_index"] for item in result["toc_items"]] == [4, 11, 24, 38]


def test_balanced_visual_accepts_document_title_wrapped_toc(monkeypatch):
    async def fail_if_detecting_again(*_args, **_kwargs):
        raise AssertionError("toc_pages should be reused, not detected again")

    async def fake_quick_extract_toc(*_args, **_kwargs):
        items = [
            {
                "title": "2025年度重庆市人工智能应用场景典型案例集",
                "level": 1,
            }
        ]
        groups = [
            ("AI+industry", 1),
            ("AI+governance", 15),
            ("AI+livelihood", 26),
            ("AI+science", 34),
            ("AI+consumption", 38),
            ("AI+cooperation", 41),
        ]
        group_iter = iter(groups)
        next_group, next_case = next(group_iter)

        for case_no, logical_page in zip(range(1, 42), range(1, 82, 2)):
            if case_no == next_case:
                items.append({"title": next_group, "level": 2})
                try:
                    next_group, next_case = next(group_iter)
                except StopIteration:
                    next_group, next_case = None, None
            items.append(
                {
                    "title": f"{case_no:02d} case",
                    "level": 3,
                    "page": logical_page,
                }
            )
        return {"toc_items": items}

    async def fake_branch_a(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "AI+industry", "level": 1, "physical_index": 3},
                {"title": "01 case", "level": 2, "physical_index": 3},
            ],
            "source": "vlm_toc",
        }

    async def fail_branch_c(*_args, **_kwargs):
        raise AssertionError("high-quality TOC should use Branch A, not Branch C")

    monkeypatch.setattr(toc_detector_module, "find_toc_pages", fail_if_detecting_again)
    monkeypatch.setattr(balanced_toc_module, "_quick_extract_toc", fake_quick_extract_toc)
    monkeypatch.setattr(balanced_toc_module, "_branch_a_toc_page", fake_branch_a)
    monkeypatch.setattr(balanced_toc_module, "_branch_c_fulltext", fail_branch_c)

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_visual(
            "dummy.pdf",
            {"page_count": 44},
            model=None,
            anchors={
                "toc_pages": [2],
                "chapter_dividers": [],
                "first_content_page": 3,
            },
        )
    )

    assert result["source"] == "vlm_toc"
    assert result["toc_items"][0]["title"] == "AI+industry"


def test_balanced_text_uses_heading_rules_for_chapter_skeleton(monkeypatch):
    async def fail_meta_processor(*_args, **_kwargs):
        raise AssertionError("chapter skeleton text docs should not call LLM text extraction")

    monkeypatch.setattr(
        balanced_toc_module,
        "meta_processor",
        fail_meta_processor,
        raising=False,
    )

    page_texts = [
        "封面",
        "目录\n序言\n第一章：发展学生智能素养\n第二章：发展教师智能教学素养\n第七章：强化人工智能应用体制机制与支撑保障\n第八章：人工智能重塑职业教育生态：困境与展望",
        "序言：研究背景\n正文",
        "第一章 发展学生人工智能素养\nn 本章概览",
        "1.1 紧跟技能人才需求的变化\n正文",
        "1.2 精准评估学生人工智能素养水平\n正文",
        "1.3 提升学生的AI应用体验\n正文",
        "1.4 优化学生智能素养发展路径\n正文",
        "7.1 人工智能应用规划和政策制定\n正文",
        "8.1 发展师生智能素养\n正文",
        "8.2 融合AI技术与教育\n正文",
    ]
    analysis = {
        "page_count": len(page_texts),
        "page_texts": page_texts,
        "page_list": [(text, len(text)) for text in page_texts],
        "toc_pages": [2],
        "toc_page": {"has_toc_page": True, "pages": [2], "confidence": "anchor"},
        "text_coverage": 1.0,
    }

    result = asyncio.run(
        balanced_toc_module.build_balanced_toc_text(
            analysis,
            model=None,
            dividers=[4, 8],
        )
    )

    by_structure = {item["structure"]: item for item in result["toc_items"]}

    assert result["source"] == "text_heading"
    assert result["mapped"] is True
    assert by_structure["1.3"]["physical_index"] == 7
    assert by_structure["1.4"]["physical_index"] == 8
    assert by_structure["7.1"]["physical_index"] == 9
    assert by_structure["8.2"]["physical_index"] == 11


def test_service_uses_text_heading_shortcut_for_text_balanced_docs() -> None:
    rule_result = {
        "toc_items": [
            {"structure": "1", "title": "第一章", "physical_index": 5},
            {"structure": "1.1", "title": "1.1 小节", "physical_index": 6},
        ],
        "source": "text_heading",
        "mapped": True,
        "semi_frozen": True,
    }
    analysis = {
        "text_coverage": 1.0,
        "toc_pages": [2],
        "toc_page": {"has_toc_page": True, "pages": [2], "confidence": "anchor"},
    }

    result = PageIndexService._try_text_heading_shortcut(analysis, rule_result)

    assert result == {
        "items": rule_result["toc_items"],
        "source": "text_heading",
        "mapped": True,
        "semi_frozen": True,
        "prevalidated": True,
    }
    assert PageIndexService._is_prevalidated_text_heading_result(result) is True


def test_service_accepts_slide_outline_shortcut_as_prevalidated() -> None:
    rule_result = {
        "toc_items": [
            {"structure": "1", "title": "AI驱动的第五科研范式", "physical_index": 4},
            {"structure": "1.1", "title": "1.1 第五范式", "physical_index": 4},
        ],
        "source": "slide_outline",
        "mapped": True,
        "semi_frozen": True,
    }
    analysis = {"text_coverage": 0.97}

    result = PageIndexService._try_prevalidated_outline_shortcut(analysis, rule_result)

    assert result == {
        "items": rule_result["toc_items"],
        "source": "slide_outline",
        "mapped": True,
        "semi_frozen": True,
        "prevalidated": True,
    }
    assert PageIndexService._is_prevalidated_outline_result(result) is True
    assert analysis["toc_frozen"] is True
    assert analysis["toc_frozen_source"] == "slide_outline"


def test_service_accepts_agenda_outline_shortcut_as_prevalidated() -> None:
    rule_result = {
        "toc_items": [
            {"structure": "1", "title": "国外大厂AI应用落地", "physical_index": 4},
            {"structure": "1.1", "title": "Open AI发布 ChatGPT Health 健康应用", "physical_index": 4},
        ],
        "source": "agenda_outline",
        "mapped": True,
        "semi_frozen": True,
    }
    analysis = {"text_coverage": 1.0}

    result = PageIndexService._try_prevalidated_outline_shortcut(analysis, rule_result)

    assert result == {
        "items": rule_result["toc_items"],
        "source": "agenda_outline",
        "mapped": True,
        "semi_frozen": True,
        "prevalidated": True,
    }
    assert PageIndexService._is_prevalidated_outline_result(result) is True
    assert analysis["toc_frozen"] is True
    assert analysis["toc_frozen_source"] == "agenda_outline"


def test_service_rejects_regex_code_toc_when_pages_look_like_years() -> None:
    analysis = {
        "page_count": 68,
        "code_toc": {
            "source": "regex",
            "items": [
                {"title": "ENIAC", "physical_index": 1945},
                {"title": "Transformer", "physical_index": 2017},
                {"title": "ChatGPT", "physical_index": 2022},
                {"title": "DeepSeek", "physical_index": 2023},
                {"title": "2025", "physical_index": 2014},
            ],
        },
    }

    assert PageIndexService._has_reliable_code_toc(analysis) is False


def test_service_rejects_regex_code_toc_when_pages_look_like_section_numbers() -> None:
    analysis = {
        "page_count": 21,
        "agenda_outline_candidate": True,
        "code_toc": {
            "source": "regex",
            "items": [
                {"title": "国外大厂AI应用落地", "physical_index": 1},
                {"title": "国内大厂AI应用落地", "physical_index": 2},
                {"title": "产业链梳理", "physical_index": 3},
                {"title": "风险提示", "physical_index": 4},
                {"title": "图：DLSS 4", "physical_index": 5},
            ],
        },
    }

    assert PageIndexService._has_reliable_code_toc(analysis) is False


def test_service_accepts_bookmark_code_toc_as_reliable() -> None:
    analysis = {
        "page_count": 68,
        "code_toc": {
            "source": "bookmarks",
            "items": [{"title": "A", "physical_index": 4}],
        },
    }

    assert PageIndexService._has_reliable_code_toc(analysis) is True


def test_service_smart_uses_balanced_when_regex_code_toc_is_weak() -> None:
    analysis = {
        "page_count": 68,
        "code_toc": {
            "source": "regex",
            "items": [
                {"title": "ENIAC", "physical_index": 1945},
                {"title": "Transformer", "physical_index": 2017},
                {"title": "ChatGPT", "physical_index": 2022},
            ],
        },
    }

    assert PageIndexService._select_initial_execution_mode("smart", analysis) == "balanced"


def test_service_smart_keeps_fast_for_reliable_code_toc() -> None:
    analysis = {
        "page_count": 68,
        "code_toc": {
            "source": "links",
            "items": [{"title": "A", "physical_index": 4}],
        },
    }

    assert PageIndexService._select_initial_execution_mode("smart", analysis) == "fast"


def test_service_does_not_treat_text_rich_pdf_as_image_doc() -> None:
    assert (
        PageIndexService._is_effectively_image_doc(
            {
                "is_image_only_pdf": False,
                "text_coverage": 1.0,
                "image_coverage": 0.9,
            }
        )
        is False
    )
    assert (
        PageIndexService._is_effectively_image_doc(
            {
                "is_image_only_pdf": False,
                "text_coverage": 0.0,
                "image_coverage": 0.9,
            }
        )
        is True
    )


def test_prevalidated_text_heading_result_skips_generic_validation(monkeypatch) -> None:
    def fail_validation(*_args, **_kwargs):
        raise AssertionError("prevalidated text_heading should skip generic validation")

    from pageindex import quality_validator as quality_validator_module

    monkeypatch.setattr(quality_validator_module, "validate_toc", fail_validation)

    result = PageIndexService._try_text_heading_shortcut(
        {},
        {
            "toc_items": [
                {"structure": "1", "title": "第一章", "physical_index": 5},
            ],
            "source": "text_heading",
            "mapped": True,
            "semi_frozen": True,
        },
    )

    assert PageIndexService._is_prevalidated_text_heading_result(result) is True


def test_prevalidated_skip_validation_message_uses_actual_source() -> None:
    assert (
        PageIndexService._prevalidated_skip_validation_message({"source": "slide_outline"})
        == "[INDEX-V3-NEW] slide_outline shortcut prevalidated, skipping generic validation"
    )
    assert (
        PageIndexService._prevalidated_skip_validation_message({"source": "text_heading"})
        == "[INDEX-V3-NEW] text_heading shortcut prevalidated, skipping generic validation"
    )


def test_service_accepts_visual_toc_skeleton_as_prevalidated() -> None:
    result = {
        "source": "vlm_toc_skeleton",
        "items": [{"title": "A", "physical_index": 5}],
        "prevalidated": True,
    }

    assert PageIndexService._is_prevalidated_outline_result(result) is True


def test_service_expands_semi_frozen_visual_skeleton_with_page_titles() -> None:
    analysis = {
        "toc_semi_frozen": True,
        "toc_frozen_source": "vlm_toc_skeleton",
    }
    page_list = [
        ("", 1),
        ("", 1),
        ("", 1),
        ("Chapter 1\n第一章 全球人工智能技术发展洞察", 10),
        ("全球人工智能基础能力与市场规模", 10),
        ("核心技术演进与融合发展趋势", 10),
    ]
    tree = [
        {
            "structure": "1",
            "title": "第一章 全球人工智能技术发展洞察",
            "start_index": 4,
            "end_index": 6,
            "nodes": [],
        }
    ]

    added = PageIndexService._expand_visual_page_outline_if_needed(
        toc_tree=tree,
        analysis=analysis,
        page_count=6,
        toc_source="vlm_toc_skeleton",
        page_list=page_list,
    )

    assert added == 2
    assert [child["title"] for child in tree[0]["nodes"]] == [
        "全球人工智能基础能力与市场规模",
        "核心技术演进与融合发展趋势",
    ]


def test_service_visual_page_outline_requires_page_list_text() -> None:
    analysis = {
        "toc_semi_frozen": True,
        "toc_frozen_source": "vlm_toc_skeleton",
        "page_texts": ["低质量分析文本不应直接用于展开"],
    }
    tree = [
        {
            "structure": "1",
            "title": "第一章",
            "start_index": 1,
            "end_index": 1,
            "nodes": [],
        }
    ]

    added = PageIndexService._expand_visual_page_outline_if_needed(
        toc_tree=tree,
        analysis=analysis,
        page_count=1,
        toc_source="vlm_toc_skeleton",
        page_list=None,
    )

    assert added == 0
    assert tree[0]["nodes"] == []


def test_toc_quality_checker_is_not_imported_inside_generate_index() -> None:
    source = Path(PageIndexService.__module__.replace(".", "/") + ".py")
    service_path = Path(__file__).resolve().parents[1] / source
    text = service_path.read_text(encoding="utf-8")
    function_body = text.split("async def _generate_index_v2", 1)[1]

    assert "from pageindex.quality_validation import TocQualityChecker" not in function_body


def test_text_heading_quality_check_is_local_and_respects_children(monkeypatch):
    async def fail_llm_call(*_args, **_kwargs):
        raise AssertionError("text_heading QC should not call LLM")

    import pageindex.utils as utils_module

    monkeypatch.setattr(utils_module, "ChatGPT_API_async", fail_llm_call)

    tree = [
        {
            "title": "序言",
            "start_index": 1,
            "end_index": 4,
            "nodes": [],
        },
        {
            "title": "第一章 发展学生人工智能素养",
            "start_index": 5,
            "end_index": 33,
            "nodes": [
                {"title": "1.1 紧跟技能人才需求的变化", "start_index": 6, "end_index": 6, "nodes": []},
                {"title": "1.2 精准评估学生人工智能素养水平", "start_index": 7, "end_index": 11, "nodes": []},
            ],
        }
    ]

    result = asyncio.run(
        post_processing_module.llm_quality_check(
            tree=tree,
            toc_items=[],
            page_count=33,
            source="text_heading",
        )
    )

    assert result["needs_repair"] is False
    assert result["large_nodes"] == []
    assert result["overall_score"] >= 85


def test_slide_outline_quality_check_is_local(monkeypatch):
    async def fail_llm_call(*_args, **_kwargs):
        raise AssertionError("slide_outline QC should not call LLM")

    import pageindex.utils as utils_module

    monkeypatch.setattr(utils_module, "ChatGPT_API_async", fail_llm_call)

    tree = [
        {"title": "Preface", "start_index": 1, "end_index": 3, "nodes": []},
        {
            "title": "AI驱动的第五科研范式",
            "start_index": 4,
            "end_index": 13,
            "nodes": [
                {"title": "1.1 第五范式", "start_index": 4, "end_index": 4, "nodes": []},
                {"title": "1.2 典型案例", "start_index": 7, "end_index": 7, "nodes": []},
            ],
        },
        {
            "title": "未来科研范式展望",
            "start_index": 14,
            "end_index": 20,
            "nodes": [
                {"title": "5.1 AI研究新范式", "start_index": 14, "end_index": 14, "nodes": []},
            ],
        },
    ]

    result = asyncio.run(
        post_processing_module.llm_quality_check(
            tree=tree,
            toc_items=[],
            page_count=20,
            source="slide_outline",
        )
    )

    assert result["needs_repair"] is False
    assert result["overall_score"] >= 85


def test_agenda_outline_quality_check_is_local(monkeypatch):
    async def fail_llm_call(*_args, **_kwargs):
        raise AssertionError("agenda_outline QC should not call LLM")

    import pageindex.utils as utils_module

    monkeypatch.setattr(utils_module, "ChatGPT_API_async", fail_llm_call)

    tree = [
        {"title": "Preface", "start_index": 1, "end_index": 3, "nodes": []},
        {
            "title": "国外大厂AI应用落地",
            "start_index": 4,
            "end_index": 9,
            "nodes": [
                {"title": "Open AI发布 ChatGPT Health 健康应用", "start_index": 4, "end_index": 4, "nodes": []},
                {"title": "Anthropic：Claude for Healthcare", "start_index": 5, "end_index": 5, "nodes": []},
            ],
        },
        {
            "title": "国内大厂AI应用落地",
            "start_index": 10,
            "end_index": 16,
            "nodes": [
                {"title": "阿里巴巴：千问APP公测上线", "start_index": 11, "end_index": 11, "nodes": []},
            ],
        },
        {"title": "产业链梳理", "start_index": 17, "end_index": 18, "nodes": []},
        {"title": "风险提示", "start_index": 19, "end_index": 19, "nodes": []},
        {"title": "Appendix", "start_index": 20, "end_index": 21, "nodes": []},
    ]

    result = asyncio.run(
        post_processing_module.llm_quality_check(
            tree=tree,
            toc_items=[],
            page_count=21,
            source="agenda_outline",
        )
    )

    assert result["needs_repair"] is False
    assert result["overall_score"] >= 85


def test_service_visual_fallback_maps_mislabeled_logical_pages():
    items = [
        {"title": f"{case_no:02d} case", "level": 2, "physical_index": logical_page}
        for case_no, logical_page in zip(range(1, 42), range(1, 82, 2))
    ]
    fallback_result = {"toc_items": items}

    PageIndexService._normalize_and_map_fallback_toc(
        fallback_result,
        page_count=44,
        toc_pages=[2],
    )

    assert [(item["page"], item["physical_index"]) for item in items[:3]] == [
        (1, 3),
        (3, 4),
        (5, 5),
    ]
    assert [(item["page"], item["physical_index"]) for item in items[-3:]] == [
        (77, 41),
        (79, 42),
        (81, 43),
    ]


def test_mapped_visual_toc_passes_new_architecture_validation():
    items = [
        {"title": f"{case_no:02d} case", "level": 2, "physical_index": physical_page}
        for case_no, physical_page in zip(range(1, 42), range(3, 44))
    ]

    validation = validate_toc(items, page_count=44, page_texts=[], source="vlm_toc")

    assert validation["is_valid"] is True
    assert validation["score"] >= 0.7


def test_mapped_visual_toc_with_groups_passes_new_architecture_validation():
    items = [{"title": "目录", "level": 1, "physical_index": 1}]
    groups = [
        ("AI+产业发展", 3),
        ("AI+超大城市现代化治理", 17),
        ("AI+民生福祉", 28),
        ("AI+科学技术", 36),
        ("AI+消费提质", 40),
        ("AI+开放合作", 43),
    ]
    group_iter = iter(groups)
    next_group, next_page = next(group_iter)

    for case_no, physical_page in zip(range(1, 42), range(3, 44)):
        if physical_page == next_page:
            items.append({"title": next_group, "level": 2, "physical_index": physical_page})
            try:
                next_group, next_page = next(group_iter)
            except StopIteration:
                next_group, next_page = None, None
        items.append(
            {
                "title": f"{case_no:02d} case",
                "level": 3,
                "physical_index": physical_page,
            }
        )

    validation = validate_toc(items, page_count=44, page_texts=[], source="vlm_toc")

    assert validation["is_valid"] is True
    assert validation["score"] >= 0.7


def test_service_syncs_detected_toc_pages_for_post_processing():
    analysis = {}

    PageIndexService._sync_toc_context(
        analysis,
        toc_pages=[2],
        confidence="high",
    )

    assert analysis["toc_pages"] == [2]
    assert analysis["toc_page"]["has_toc_page"] is True
    assert analysis["toc_page"]["pages"] == [2]
    assert analysis["toc_page"]["confidence"] == "high"


def test_post_processing_rejects_destructive_grouping_for_frozen_toc(monkeypatch):
    toc_items = [
        {
            "title": f"{case_no:02d} case",
            "structure": f"{case_no:02d}",
            "physical_index": physical_page,
        }
        for case_no, physical_page in zip(range(1, 42), range(3, 44))
    ]

    def destructive_grouping(_tree, _analysis, _page_count, _model):
        return [
            {
                "title": "目录",
                "node_type": "catalog_group",
                "physical_index": 1,
                "start_index": 1,
                "end_index": 44,
                "nodes": [
                    {
                        "title": "01 case",
                        "structure": "01",
                        "physical_index": 3,
                        "start_index": 3,
                        "end_index": 3,
                        "nodes": [],
                    },
                    {
                        "title": "01 case",
                        "structure": "01",
                        "physical_index": 3,
                        "start_index": 3,
                        "end_index": 3,
                        "nodes": [],
                    },
                ],
            }
        ]

    monkeypatch.setattr(
        post_processing_module,
        "_llm_group_catalogs",
        destructive_grouping,
    )

    tree, _ = post_processing_module.post_process_toc(
        toc_items,
        page_count=44,
        analysis={
            "toc_page": {"has_toc_page": True},
            "toc_frozen": True,
        },
        use_llm_grouping=True,
        model=None,
    )

    titles = _flatten_titles(tree)

    assert titles.count("01 case") == 1
    assert "41 case" in titles
    assert len([title for title in titles if title and title.endswith(" case")]) == 41


def test_post_processing_keeps_frozen_visual_skeleton_over_dividers(monkeypatch):
    def fail_grouping(*_args, **_kwargs):
        raise AssertionError("frozen visual skeleton should not call LLM grouping")

    monkeypatch.setattr(
        post_processing_module,
        "_llm_group_catalogs",
        fail_grouping,
    )

    toc_items = [
        {
            "title": "Global AI technology development insight",
            "level": 1,
            "physical_index": 5,
        },
        {
            "title": "Top industry AI application demand insight",
            "level": 1,
            "physical_index": 13,
        },
        {
            "title": "Global AI technology application awards",
            "level": 1,
            "physical_index": 25,
        },
        {
            "title": "Global AI technology application future trends",
            "level": 1,
            "physical_index": 35,
        },
    ]

    tree, completeness = post_processing_module.post_process_toc(
        toc_items,
        page_count=43,
        dividers=[5, 13, 25, 35, 41],
        analysis={
            "toc_page": {"has_toc_page": True},
            "toc_frozen": True,
            "toc_frozen_source": "vlm_toc_skeleton",
        },
        use_llm_grouping=True,
        model=None,
    )

    titles = _flatten_titles(tree)

    assert "Chapter at page 41" not in titles
    assert "Global AI technology application future trends" in titles
    assert tree[-1]["end_index"] == 43
    assert completeness["coverage"] == 1.0


def test_post_processing_keeps_semi_frozen_visual_skeleton_over_dividers(monkeypatch):
    def fail_grouping(*_args, **_kwargs):
        raise AssertionError("semi-frozen visual skeleton should not call LLM grouping")

    monkeypatch.setattr(
        post_processing_module,
        "_llm_group_catalogs",
        fail_grouping,
    )

    toc_items = [
        {"title": "Chapter 1", "level": 1, "physical_index": 5},
        {"title": "Chapter 2", "level": 1, "physical_index": 12},
        {"title": "Chapter 3", "level": 1, "physical_index": 25},
        {"title": "Chapter 4", "level": 1, "physical_index": 39},
    ]

    tree, completeness = post_processing_module.post_process_toc(
        toc_items,
        page_count=43,
        dividers=[5, 13, 25, 35, 41],
        analysis={
            "toc_page": {"has_toc_page": True},
            "toc_semi_frozen": True,
            "toc_frozen_source": "vlm_toc_skeleton",
        },
        use_llm_grouping=True,
        model=None,
    )

    assert [node["title"] for node in tree[1:]] == [
        "Chapter 1",
        "Chapter 2",
        "Chapter 3",
        "Chapter 4",
    ]
    assert [node["start_index"] for node in tree[1:]] == [5, 12, 25, 39]
    assert completeness["coverage"] == 1.0


def test_post_processing_uses_build_state_to_skip_grouping_for_child_expandable_skeleton(monkeypatch):
    def fail_grouping(*_args, **_kwargs):
        raise AssertionError("top-level-frozen build_state should not call LLM grouping")

    monkeypatch.setattr(
        post_processing_module,
        "_llm_group_catalogs",
        fail_grouping,
    )

    toc_items = [
        {"title": "Part01：市场分析", "level": 1, "physical_index": 5},
        {"title": "Part02：增长引擎一：AI心智占位", "level": 1, "physical_index": 13},
        {"title": "Part03：增长引擎二：内容营销工业化", "level": 1, "physical_index": 25},
        {"title": "Part04：增长引擎三：数据基建", "level": 1, "physical_index": 35},
        {"title": "Part05：AI变革落地", "level": 1, "physical_index": 41},
    ]

    tree, completeness = post_processing_module.post_process_toc(
        toc_items,
        page_count=62,
        dividers=[5, 13, 25, 35, 41],
        analysis={
            "toc_page": {"has_toc_page": True},
            "build_state": {
                "top_level_frozen": True,
                "allow_child_expansion": True,
                "children_locked": False,
            },
        },
        use_llm_grouping=True,
        model=None,
    )

    assert [node["title"] for node in tree[1:]] == [item["title"] for item in toc_items]
    assert [node["start_index"] for node in tree[1:]] == [5, 13, 25, 35, 41]
    assert completeness["coverage"] == 1.0


def test_post_processing_groups_frozen_case_catalog_deterministically(monkeypatch):
    toc_items = []
    groups = [
        ("AI+industry", 1),
        ("AI+governance", 15),
        ("AI+livelihood", 26),
        ("AI+science", 34),
        ("AI+consumption", 38),
        ("AI+cooperation", 41),
    ]
    group_iter = iter(groups)
    next_group, next_case = next(group_iter)

    for case_no, physical_page in zip(range(1, 42), range(3, 44)):
        if case_no == next_case:
            toc_items.append(
                {
                    "title": next_group,
                    "level": 1,
                    "physical_index": physical_page,
                }
            )
            try:
                next_group, next_case = next(group_iter)
            except StopIteration:
                next_group, next_case = None, None
        toc_items.append(
            {
                "title": f"{case_no:02d} case",
                "level": 2,
                "physical_index": physical_page,
            }
        )

    def fail_grouping(*_args, **_kwargs):
        raise AssertionError("frozen TOC should not call LLM grouping")

    monkeypatch.setattr(
        post_processing_module,
        "_llm_group_catalogs",
        fail_grouping,
    )

    tree, completeness = post_processing_module.post_process_toc(
        toc_items,
        page_count=44,
        analysis={
            "toc_page": {"has_toc_page": True},
            "toc_frozen": True,
        },
        use_llm_grouping=True,
        model=None,
    )

    assert completeness["coverage"] == 1.0
    assert tree[0]["title"] == "Preface"
    groups = tree[1:]
    assert [group["title"] for group in groups] == [
        "AI+industry",
        "AI+governance",
        "AI+livelihood",
        "AI+science",
        "AI+consumption",
        "AI+cooperation",
    ]
    assert [child["title"] for child in groups[0]["nodes"]] == [
        f"{case_no:02d} case" for case_no in range(1, 15)
    ]
    assert [child["title"] for child in groups[-1]["nodes"]] == ["41 case"]
    assert len([title for title in _flatten_titles(tree) if title and title.endswith(" case")]) == 41


def test_post_processing_rejects_incomplete_grouping_result(monkeypatch):
    toc_items = [
        {
            "title": f"{case_no:02d} case",
            "structure": f"{case_no:02d}",
            "physical_index": physical_page,
        }
        for case_no, physical_page in zip(range(1, 42), range(3, 44))
    ]

    def incomplete_grouping(_tree, _analysis, _page_count, _model):
        return [
            {
                "title": "目录",
                "node_type": "catalog_group",
                "physical_index": 1,
                "start_index": 1,
                "end_index": 44,
                "nodes": [
                    {
                        "title": f"{case_no:02d} case",
                        "structure": f"{case_no:02d}",
                        "physical_index": physical_page,
                        "start_index": physical_page,
                        "end_index": physical_page,
                        "nodes": [],
                    }
                    for case_no, physical_page in zip(range(1, 31), range(3, 33))
                ],
            }
        ]

    monkeypatch.setattr(
        post_processing_module,
        "_llm_group_catalogs",
        incomplete_grouping,
    )

    tree, _ = post_processing_module.post_process_toc(
        toc_items,
        page_count=44,
        analysis={"toc_page": {"has_toc_page": True}},
        use_llm_grouping=True,
        model=None,
    )

    titles = _flatten_titles(tree)

    assert "41 case" in titles
    assert len([title for title in titles if title and title.endswith(" case")]) == 41
