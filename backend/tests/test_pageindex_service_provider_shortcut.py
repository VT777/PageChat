from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_balanced_provider_shortcut_maps_no_page_toc_and_freezes_skeleton():
    analysis = {
        "toc_pages": [2],
        "page_texts": [
            "Cover",
            "Contents\n1 Market overview\n2 Model landscape\n3 Application opportunities",
            "Market overview\nBody",
            "More market",
            "Model landscape\nBody",
            "More models",
            "Application opportunities\nBody",
        ],
    }

    result = PageIndexService._try_balanced_provider_shortcut(analysis, page_count=7)

    assert result["source"] == "toc_page_text"
    assert result["prevalidated"] is True
    assert result["mapped"] is True
    assert result["mapping_strategy"] == "title_search"
    assert analysis["build_state"]["top_level_frozen"] is True
    assert analysis["top_level_frozen"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_frozen"] is True
    assert analysis["toc_frozen_source"] == "toc_page_text"
    assert [item["physical_index"] for item in result["items"]] == [3, 5, 7]


def test_balanced_provider_shortcut_returns_slide_candidate(monkeypatch):
    from pageindex import slide_outline_extractor

    def fake_build_slide_outline(analysis):
        return {
            "source": "slide_outline",
            "toc_items": [{"title": "Slide topic", "start_index": 3}],
            "mapped": True,
            "semi_frozen": True,
        }

    monkeypatch.setattr(slide_outline_extractor, "build_slide_outline", fake_build_slide_outline)
    analysis = {
        "slide_outline_candidate": True,
        "page_texts": ["Cover", "Slide topic"],
    }

    result = PageIndexService._try_balanced_provider_shortcut(analysis, page_count=2)

    assert result["source"] == "slide_outline"
    assert result["prevalidated"] is True
    assert result["mapped"] is True
    assert analysis["build_state"]["top_level_frozen"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_frozen_source"] == "slide_outline"


def test_apply_balanced_quality_gate_updates_completeness_for_long_flat_chapter():
    analysis = {
        "build_state": {"top_level_frozen": True, "allow_child_expansion": True},
        "toc_skeleton": {"items": [{"title": "Chapter 2", "level": 1}]},
    }
    tree = [
        {
            "title": "Chapter 2",
            "level": 1,
            "start_index": 11,
            "end_index": 27,
            "nodes": [],
        }
    ]
    completeness = {"quality": "good", "needs_repair": False}

    fixed, updated = PageIndexService._apply_balanced_quality_gate(
        tree,
        analysis,
        completeness,
        page_count=43,
    )

    assert fixed == tree
    assert updated["needs_repair"] is True
    assert updated["balanced_quality_gate"]["long_chapter_completeness"] is False


def test_index_diagnostics_preserves_balanced_quality_gate_facts():
    diagnostics = PageIndexService._index_diagnostics_from_analysis(
        {
            "balanced_quality_gate": {
                "child_expansion_attempted": True,
                "child_expansion_required_count": 1,
                "unexpanded_long_leaf_hard_count": 1,
                "unexpanded_long_leaf_sample": [
                    {"title": "Chapter 2", "start": 11, "end": 27, "span": 17}
                ],
            }
        }
    )

    gate = diagnostics["balanced_quality_gate"]
    assert gate["child_expansion_attempted"] is True
    assert gate["unexpanded_long_leaf_hard_count"] == 1
    assert gate["unexpanded_long_leaf_sample"][0]["title"] == "Chapter 2"


def test_expand_page_outline_uses_llm_snippets_for_catalog_children(monkeypatch):
    tree = [
        {
            "title": "Contents",
            "structure": "main",
            "toc_section_kind": "main_toc",
            "catalog_type": "main",
            "start_index": 3,
            "end_index": 20,
            "nodes": [
                {
                    "title": "Part 1 Market analysis",
                    "structure": "1",
                    "start_index": 3,
                    "end_index": 10,
                    "nodes": [],
                },
                {
                    "title": "Part 2 Execution playbook",
                    "structure": "2",
                    "start_index": 11,
                    "end_index": 20,
                    "nodes": [],
                },
            ],
        }
    ]
    long_page = "A" * 260 + "\nThis tail must not be sent to the LLM snippet expander"
    page_list = [[f"Page {page} {long_page}"] for page in range(1, 21)]
    calls = []

    async def fake_expand_chapter(chapter_title, start_page, end_page, page_texts, model=None):
        calls.append((chapter_title, start_page, end_page, page_texts, model))
        assert all(len(text) <= 200 for text in page_texts)
        if chapter_title.startswith("Part 1"):
            return [
                {"title": "Consumer pressure", "level": 2, "page": 4},
                {"title": "Channel response", "level": 2, "page": 6},
            ]
        return [{"title": "Operating model", "level": 2, "page": 12}]

    monkeypatch.setattr("pageindex.hierarchical_extractor.expand_chapter", fake_expand_chapter)
    added = asyncio.run(
        PageIndexService._expand_page_outline(
            toc_tree=tree,
            analysis={
                "top_level_frozen": True,
                "allow_child_expansion": True,
                "route_decision": {"selected_path": "visible_toc_no_pages"},
            },
            page_count=20,
            toc_source="toc_page_text_rule",
            page_list=page_list,
            model="qwen3.6-flash",
        )
    )

    assert added == 3
    assert len(calls) == 2
    assert tree[0]["nodes"][0]["nodes"][0]["title"] == "Consumer pressure"
    assert tree[0]["nodes"][0]["nodes"][1]["start_index"] == 6
    assert tree[0]["nodes"][0]["nodes"][0]["end_index"] == 5
    assert tree[0]["nodes"][0]["nodes"][1]["end_index"] == 10
    assert tree[0]["nodes"][1]["nodes"][0]["title"] == "Operating model"
    assert tree[0]["nodes"][1]["nodes"][0]["end_index"] == 20


def test_llm_outline_child_tree_filters_body_text_leakage():
    parent = {
        "title": "Part02：AI心智占位：预测式社交生态实战指南",
        "structure": "2",
    }
    leaked_body = (
        "营销打法革新：从“流量式”进化为“耦合式”体验价值关系耦合全域旅程"
        "耦合内容标签耦合内容是“商品-用户”的交互界面构建可交互、可个性化组装的内容模块"
    )

    children = PageIndexService._build_llm_outline_child_tree(
        parent,
        [
            {"title": "商业逻辑变革：从响应式到预测式营销", "level": 2, "page": 15},
            {"title": leaked_body, "level": 2, "page": 17},
            {
                "title": "/新品前置种草前置种草 2个月把握测试黄金期 •AI拆解高互动笔记→抽取信任公式→规模化生产万级素材",
                "level": 2,
                "page": 18,
            },
        ],
        parent_start=13,
        parent_end=24,
    )

    assert [child["title"] for child in children] == [
        "商业逻辑变革：从响应式到预测式营销"
    ]


def test_llm_outline_child_tree_keeps_long_structured_step_heading():
    parent = {
        "title": "Part03: Content operations",
        "structure": "3",
    }

    children = PageIndexService._build_llm_outline_child_tree(
        parent,
        [
            {
                "title": "Step1——小额测试，找出“商品标签X用户标签”的有效组合爆款是结果，资产是能力；冷启动期严禁考核ROI，只看标签有效性",
                "level": 3,
                "page": 30,
            },
            {"title": "Step2——规模放量", "level": 3, "page": 31},
        ],
        parent_start=25,
        parent_end=34,
    )

    assert [child["title"] for child in children] == [
        "Step1——小额测试，找出“商品标签X用户标签”的有效组合爆款是结果，资产是能力；冷启动期严禁考核ROI，只看标签有效性",
        "Step2——规模放量",
    ]


def test_llm_outline_child_tree_keeps_multiple_clean_children_on_same_page():
    parent = {
        "title": "二 百花齐放的大模型时代",
        "structure": "2",
    }

    children = PageIndexService._build_llm_outline_child_tree(
        parent,
        [
            {"title": "2.1 大模型发展历程", "level": 2, "page": 15},
            {"title": "2.1 DeepSeek系列大模型", "level": 2, "page": 15},
            {"title": "2.2 智能体", "level": 2, "page": 22},
            {"title": "2.2 多智能体协作", "level": 2, "page": 22},
            {"title": "2.3 智能体实例", "level": 2, "page": 27},
        ],
        parent_start=13,
        parent_end=34,
    )

    assert [(child["title"], child["start_index"]) for child in children] == [
        ("2.1 大模型发展历程", 15),
        ("2.1 DeepSeek系列大模型", 15),
        ("2.2 智能体", 22),
        ("2.2 多智能体协作", 22),
        ("2.3 智能体实例", 27),
    ]


def test_llm_outline_expandable_parents_require_fact_based_minimum_span():
    parents = PageIndexService._llm_outline_expandable_parents(
        [
            {"title": "Two-page category", "start_index": 10, "end_index": 11, "nodes": []},
            {"title": "Eight-page category", "start_index": 12, "end_index": 19, "nodes": []},
        ],
        page_count=20,
    )

    assert [parent["title"] for parent in parents] == ["Eight-page category"]


def test_shallow_toc_expansion_ignores_noisy_levels_without_children():
    analysis = {}
    toc_items = [
        {"title": "One AI research paradigm", "level": 2, "physical_index": 4},
        {"title": "Two model landscape", "level": 4, "physical_index": 17},
        {"title": "Three hypothesis generation", "level": 4, "physical_index": 30},
        {"title": "Four papers and projects", "level": 4, "physical_index": 43},
        {"title": "Five outlook", "level": 4, "physical_index": 56},
    ]

    enabled = PageIndexService._enable_child_outline_expansion_for_shallow_toc(
        analysis,
        toc_items,
        page_count=68,
        toc_source="llm_toc_page",
    )

    assert enabled is True
    assert analysis["top_level_frozen"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_semi_frozen"] is True


def test_shallow_unpaged_rule_toc_enables_child_expansion():
    analysis = {
        "route_decision": {"selected_path": "visible_toc_no_pages"},
    }
    toc_items = [
        {"title": "国外大厂AI应用落地", "level": 1, "physical_index": 3, "nodes": []},
        {"title": "国内大厂AI应用落地", "level": 1, "physical_index": 9, "nodes": []},
        {"title": "产业链梳理", "level": 1, "physical_index": 16, "nodes": []},
        {"title": "风险提示", "level": 1, "physical_index": 18, "nodes": []},
    ]

    enabled = PageIndexService._enable_child_outline_expansion_for_shallow_toc(
        analysis,
        toc_items,
        page_count=21,
        toc_source="toc_page_text_rule",
    )

    assert enabled is True
    assert PageIndexService._llm_outline_expansion_min_span(analysis) == 6
    assert analysis["top_level_frozen"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_semi_frozen"] is True


def test_shallow_unpaged_rule_toc_enables_child_expansion_inside_catalog_root():
    analysis = {
        "route_decision": {"selected_path": "visible_toc_no_pages"},
    }
    toc_items = [
        {
            "title": "目录",
            "level": 1,
            "physical_index": 5,
            "start_index": 5,
            "end_index": 62,
            "nodes": [
                {
                    "title": "Part01: Market analysis",
                    "level": 1,
                    "physical_index": 5,
                    "start_index": 5,
                    "end_index": 12,
                    "nodes": [],
                },
                {
                    "title": "Part02: AI playbook",
                    "level": 1,
                    "physical_index": 13,
                    "start_index": 13,
                    "end_index": 24,
                    "nodes": [],
                },
                {
                    "title": "Part03: Content operations",
                    "level": 1,
                    "physical_index": 25,
                    "start_index": 25,
                    "end_index": 34,
                    "nodes": [],
                },
                {
                    "title": "Part04: Data foundation",
                    "level": 1,
                    "physical_index": 35,
                    "start_index": 35,
                    "end_index": 40,
                    "nodes": [],
                },
                {
                    "title": "Part05: Case studies",
                    "level": 1,
                    "physical_index": 41,
                    "start_index": 41,
                    "end_index": 62,
                    "nodes": [],
                },
            ],
        }
    ]

    enabled = PageIndexService._enable_child_outline_expansion_for_shallow_toc(
        analysis,
        toc_items,
        page_count=62,
        toc_source="toc_page_text_rule",
    )

    assert enabled is True
    assert analysis["top_level_frozen"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_semi_frozen"] is True


def test_content_ocr_stage_name_distinguishes_content_fill_from_structure_ocr():
    assert PageIndexService._content_ocr_stage_name() == "content_ocr"
