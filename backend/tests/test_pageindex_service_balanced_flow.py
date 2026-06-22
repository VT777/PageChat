from pathlib import Path
import sys
import asyncio
import json
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_service_builds_route_decision_from_state_machine():
    analysis = {
        "page_count": 62,
        "content_type": "hybrid",
        "toc_page_detection": {
            "status": "detected",
            "pages": [4],
            "has_page_numbers": False,
        },
    }

    route = PageIndexService._build_state_machine_route_decision("smart", analysis)

    assert route["requested_mode"] == "smart"
    assert route["content_type"] == "hybrid"
    assert route["selected_path"] == "visible_toc_no_pages"
    assert route["states"] == ["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
    assert route["post_route_states"] == ["S7", "S8"]


def test_prepare_prebuilt_toc_tree_normalizes_invalid_child_ranges_before_qc():
    tree = [
        {
            "title": "目录",
            "start_index": 6,
            "end_index": 34,
            "nodes": [
                {"title": "（四）全球生态", "physical_index": 33},
                {
                    "title": "（五）我国加速扩大全球影响力",
                    "physical_index": 34,
                    "start_index": 34,
                    "end_index": 33,
                    "source_anchor": {
                        "format": "pdf",
                        "unit_type": "page",
                        "start_page": 34,
                        "end_page": 33,
                    },
                },
            ],
        }
    ]

    normalized = PageIndexService._prepare_prebuilt_toc_tree(tree, page_count=49)
    child = normalized[0]["nodes"][1]

    assert child["start_index"] == 34
    assert child["end_index"] == 49
    assert child["source_anchor"]["start_page"] == 34
    assert child["source_anchor"]["end_page"] == 49


def test_llm_outline_expandable_parents_use_fact_based_span_policy() -> None:
    tree = [
        {
            "title": "目录",
            "node_type": "catalog_group",
            "nodes": [
                {"title": "Short", "start_index": 3, "end_index": 6, "nodes": []},
                {"title": "Medium", "start_index": 7, "end_index": 14, "nodes": []},
                {"title": "Long", "start_index": 15, "end_index": 31, "nodes": []},
                {"title": "Has children", "start_index": 32, "end_index": 45, "nodes": [{"title": "Child"}]},
                {"title": "Appendix", "start_index": 46, "end_index": 60, "nodes": []},
                {
                    "title": "Figure catalog",
                    "start_index": 10,
                    "end_index": 30,
                    "is_auxiliary": True,
                    "nodes": [],
                },
            ],
        }
    ]

    parents = PageIndexService._llm_outline_expandable_parents(tree, page_count=60)

    assert [node["title"] for node in parents] == ["Medium", "Long", "Appendix"]


def test_llm_outline_expandable_parents_expand_short_slide_report_sections() -> None:
    tree = [
        {
            "title": "目录",
            "node_type": "catalog_group",
            "nodes": [
                {"title": "Part05: AI营销案例", "start_index": 41, "end_index": 44, "nodes": []},
                {"title": "Appendix", "start_index": 45, "end_index": 46, "nodes": []},
                {
                    "title": "Figure catalog",
                    "start_index": 2,
                    "end_index": 3,
                    "is_auxiliary": True,
                    "nodes": [],
                },
            ],
        }
    ]

    parents = PageIndexService._llm_outline_expandable_parents(
        tree,
        page_count=60,
        analysis={
            "route_decision": {"selected_path": "visible_toc_no_pages"},
            "toc_source": "slide_outline",
            "layout_type": "mixed_layout_report",
            "content_type": "hybrid",
            "image_coverage": 1.0,
        },
    )

    assert [node["title"] for node in parents] == ["Part05: AI营销案例"]


def test_llm_outline_expandable_parents_ignore_unused_agenda_signal_for_text_toc() -> None:
    tree = [
        {
            "title": "目录",
            "node_type": "catalog_group",
            "nodes": [
                {"title": "国外大厂AI应用落地", "start_index": 3, "end_index": 8, "nodes": []},
                {"title": "国内大厂AI应用落地", "start_index": 9, "end_index": 15, "nodes": []},
                {"title": "产业链梳理", "start_index": 16, "end_index": 17, "nodes": []},
                {"title": "风险提示", "start_index": 18, "end_index": 21, "nodes": []},
            ],
        }
    ]

    parents = PageIndexService._llm_outline_expandable_parents(
        tree,
        page_count=21,
        analysis={
            "route_decision": {"selected_path": "visible_toc_no_pages"},
            "toc_source": "toc_page_text_rule",
            "layout_type": "native_text_report",
            "content_type": "text",
            "agenda_outline_candidate": True,
        },
    )

    assert [parent["title"] for parent in parents] == [
        "国外大厂AI应用落地",
        "国内大厂AI应用落地",
    ]


def test_main_toc_member_nodes_are_expandable_not_catalog_containers() -> None:
    tree = [
        {
            "title": "目录",
            "toc_section_kind": "main_toc",
            "nodes": [
                {
                    "title": "第一章：发展学生智能素养",
                    "section_kind": "main_toc",
                    "catalog_type": "main",
                    "start_index": 5,
                    "end_index": 33,
                    "nodes": [],
                }
            ],
        }
    ]

    parents = PageIndexService._llm_outline_expandable_parents(tree, page_count=201)

    assert [parent["title"] for parent in parents] == ["第一章：发展学生智能素养"]


def test_content_outline_path_uses_internal_llm_outline(monkeypatch):
    service = PageIndexService()

    async def fake_extract_hierarchical_toc(page_texts, model):
        assert page_texts == ["Opening page", "Chapter-like page", "Closing page"]
        assert model == "qwen3.6-flash"
        return {
            "toc_items": [
                {"title": "Opening", "physical_index": 1, "level": 1},
                {"title": "Chapter-like page", "physical_index": 2, "level": 1},
            ],
            "source": "hierarchical",
        }

    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    result = asyncio.run(
        service._extract_content_outline_candidate(
            {"page_texts": ["Opening page", "Chapter-like page", "Closing page"]},
            page_count=3,
            model="qwen3.6-flash",
        )
    )

    assert result["source"] == "content_outline"
    assert result["internal_source"] == "hierarchical"
    assert [item["title"] for item in result["toc_items"]] == ["Opening", "Chapter-like page"]


def test_content_outline_path_falls_back_to_text_headings_when_llm_collapses(monkeypatch):
    service = PageIndexService()

    async def fake_extract_hierarchical_toc(page_texts, model):
        return {
            "toc_items": [
                {"title": "Document Content", "physical_index": 1, "level": 1},
            ],
            "source": "hierarchical",
        }

    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    page_texts = [
        "Paper Title\nAuthors\nABSTRACT\nBody\n1.\nINTRODUCTION\nBody",
        "2.\nPRELIMINARIES\nBody",
        "2.1\nComputing the EMD\nBody",
        "3.\nSCALING UP SSP\nBody",
        "REFERENCES\n[1] Example",
    ]
    result = asyncio.run(
        service._extract_content_outline_candidate(
            {"page_texts": page_texts},
            page_count=len(page_texts),
            model="qwen3.6-flash",
        )
    )

    assert result["source"] == "content_outline"
    assert result["internal_source"] == "text_heading"
    assert [item["title"] for item in result["toc_items"][:4]] == [
        "ABSTRACT",
        "1 INTRODUCTION",
        "2 PRELIMINARIES",
        "2.1 Computing the EMD",
    ]


def test_content_outline_path_keeps_reasonable_llm_outline_over_text_headings(monkeypatch):
    service = PageIndexService()

    async def fake_extract_hierarchical_toc(page_texts, model):
        return {
            "toc_items": [
                {"title": "Opening", "physical_index": 1, "level": 1},
                {"title": "Analysis", "physical_index": 2, "level": 1},
            ],
            "source": "hierarchical",
        }

    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    result = asyncio.run(
        service._extract_content_outline_candidate(
            {"page_texts": ["ABSTRACT\nBody", "1.\nINTRODUCTION\nBody"]},
            page_count=2,
            model="qwen3.6-flash",
        )
    )

    assert result["internal_source"] == "hierarchical"
    assert [item["title"] for item in result["toc_items"]] == ["Opening", "Analysis"]


def test_content_outline_path_prepends_preface_when_first_root_starts_after_page_one(monkeypatch):
    service = PageIndexService()

    async def fake_extract_hierarchical_toc(page_texts, model):
        return {
            "toc_items": [
                {"title": "About the Federal Reserve", "physical_index": 5, "level": 1},
                {"title": "1 Overview", "physical_index": 7, "level": 1},
            ],
            "source": "hierarchical",
        }

    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    result = asyncio.run(
        service._extract_content_outline_candidate(
            {"page_texts": ["Cover", "", "Contents", "More contents", "About"]},
            page_count=10,
            model="qwen3.6-flash",
        )
    )

    assert [item["title"] for item in result["toc_items"][:3]] == [
        "Preface",
        "About the Federal Reserve",
        "1 Overview",
    ]
    assert result["toc_items"][0]["physical_index"] == 1


def test_content_outline_path_renames_title_front_matter_before_numbered_body(monkeypatch):
    service = PageIndexService()

    async def fake_extract_hierarchical_toc(page_texts, model):
        return {
            "toc_items": [
                {"title": "Four Lectures on Standard ML", "physical_index": 1, "level": 1},
                {"title": "ML at a Glance", "physical_index": 2, "level": 1},
            ],
            "source": "hierarchical",
        }

    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    result = asyncio.run(
        service._extract_content_outline_candidate(
                {
                    "page_texts": [
                        "Four Lectures on Standard ML\nThe following notes give an overview.",
                    "$\\text { 1 ML at a Glance }$\nBody",
                    ]
                },
            page_count=2,
            model="qwen3.6-flash",
        )
    )

    first = result["toc_items"][0]
    assert first["title"] == "Preface"
    assert first["metadata"]["original_title"] == "Four Lectures on Standard ML"


def test_content_outline_path_renames_short_cover_page_front_matter(monkeypatch):
    service = PageIndexService()

    async def fake_extract_hierarchical_toc(page_texts, model):
        return {
            "toc_items": [
                {
                    "title": "REPORT TO CONGRESS 110th Annual Report of the Board of Governors of the Federal Reserve System 2023",
                    "physical_index": 1,
                    "level": 1,
                },
                {"title": "About the Federal Reserve", "physical_index": 5, "level": 1},
            ],
            "source": "hierarchical",
        }

    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    result = asyncio.run(
        service._extract_content_outline_candidate(
            {
                "page_texts": [
                    "REPORT TO CONGRESS\n110th Annual Report\n2023",
                    "",
                    "Contents\nAbout the Federal Reserve iii",
                    "",
                    "About the Federal Reserve\nThe Federal Reserve was created...",
                ]
            },
            page_count=5,
            model="qwen3.6-flash",
        )
    )

    first = result["toc_items"][0]
    assert first["title"] == "Preface"
    assert first["metadata"]["original_title"].startswith("REPORT TO CONGRESS")


def test_llm_outline_expansion_falls_back_to_page_labeled_content_outline(monkeypatch):
    service = PageIndexService()
    tree = [
        {
            "title": "Appendix A: The bare Interpreter",
            "structure": "A",
            "start_index": 44,
            "end_index": 52,
            "nodes": [],
        }
    ]
    page_texts = [f"Page {page}" for page in range(1, 54)]
    page_texts[43] = "Appendix page " + ("full text " * 40)

    async def fake_expand_chapter(*_args, **_kwargs):
        return []

    async def fake_content_outline(page_texts_arg, model, physical_start_page=1):
        assert physical_start_page == 44
        assert page_texts_arg == page_texts[43:52]
        assert len(page_texts_arg[0]) > 200
        return {
            "toc_items": [
                {
                    "title": "Appendix A: The bare Interpreter",
                    "physical_index": 44,
                    "start_index": 44,
                    "end_index": 52,
                    "nodes": [
                        {"title": "Syntax", "physical_index": 44, "start_index": 44, "end_index": 44, "nodes": []},
                        {"title": "Parsing", "physical_index": 45, "start_index": 45, "end_index": 45, "nodes": []},
                    ],
                }
            ]
        }

    monkeypatch.setattr("pageindex.hierarchical_extractor.expand_chapter", fake_expand_chapter)
    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_page_labeled_content_outline",
        fake_content_outline,
    )

    added = asyncio.run(
        service._expand_page_outline_with_llm_snippets(
            tree,
            {
                "top_level_frozen": True,
                "allow_child_expansion": True,
                "page_texts": page_texts,
            },
            page_count=53,
            model="qwen3.6-flash",
        )
    )

    assert added == 2
    assert [node["title"] for node in tree[0]["nodes"]] == ["Syntax", "Parsing"]
    assert tree[0]["nodes"][0]["start_index"] == 44


def test_legacy_llm_toc_text_path_uses_shared_marker_normalization(monkeypatch):
    service = PageIndexService()

    async def fake_completion(*_args, **_kwargs):
        payload = {
            "toc_items": [
                {"title": "汇报提纲", "level": 1, "page": None},
                {"title": "AI驱动的第五科研范式", "level": 1, "page": None},
                {"title": "一", "level": 1, "page": None},
                {"title": "百花齐放的大模型时代", "level": 1, "page": None},
                {"title": "二", "level": 1, "page": None},
            ]
        }
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))
                )
            ]
        )

    monkeypatch.setattr(service, "_indexing_completion", fake_completion)

    result = asyncio.run(
        service._extract_toc_text(
            {"page_texts": ["Cover", "TOC page text"]},
            toc_pages=[2],
            page_count=10,
            model="qwen3.6-flash",
        )
    )

    assert result is not None
    assert [item["title"] for item in result["toc_draft"]["items"]] == [
        "一 AI驱动的第五科研范式",
        "二 百花齐放的大模型时代",
    ]
    assert result["toc_draft"]["items"][0]["raw_page_label"] is None
    assert all("physical_index" not in item for item in result["toc_draft"]["items"])


def test_final_mapping_skips_items_already_mapped_by_unified_s5() -> None:
    analysis = {
        "toc_content_mapping": {
            "source": "unified_s5",
            "status": "ok",
            "strategy": "physical_identity",
        }
    }
    toc_items = [
        {"title": "Alpha", "physical_index": 4, "start_index": 4},
        {"title": "Beta", "physical_index": 8, "start_index": 8},
    ]

    should_map = PageIndexService._should_run_final_content_mapping(
        toc_source="llm_toc_page",
        toc_items=toc_items,
        page_list=[("Cover",), ("Contents",), ("Intro",), ("Alpha",), ("Body",), ("Body",), ("Body",), ("Beta",)],
        page_count=8,
        toc_pages=[2],
        analysis=analysis,
        needs_ocr=False,
    )

    assert should_map is False


def test_final_mapping_preserves_verified_unpaged_toc_physical_pages():
    toc_items = [
        {"title": "Alpha Research", "physical_index": 3, "level": 1},
        {"title": "Beta Models", "physical_index": 5, "level": 1},
        {"title": "Gamma Hypotheses", "physical_index": 7, "level": 1},
        {"title": "Delta Papers", "physical_index": 9, "level": 1},
        {"title": "Epsilon Outlook", "physical_index": 11, "level": 1},
    ]
    page_list = [
        ("Cover",),
        ("Contents\nAlpha Research\nBeta Models\nGamma Hypotheses\nDelta Papers\nEpsilon Outlook",),
        ("Alpha Research\nBody",),
        ("Beta Models\nGamma Hypotheses\nDelta Papers\nEpsilon Outlook\nOverview",),
        ("Beta Models\nBody",),
        ("More beta",),
        ("Gamma Hypotheses\nBody",),
        ("More gamma",),
        ("Delta Papers\nBody",),
        ("More delta",),
        ("Epsilon Outlook\nBody",),
        ("Appendix",),
    ]
    analysis = {
        "toc_source": "llm_toc_page",
        "llm_toc_page": {
            "status": "ok",
            "source": "llm_toc_page",
            "has_printed_page_numbers": False,
        },
    }

    mapped = PageIndexService._map_toc_items_after_content_ocr(
        toc_items,
        page_list=page_list,
        page_count=len(page_list),
        toc_pages=[2],
        analysis=analysis,
    )

    assert [item["physical_index"] for item in mapped] == [3, 5, 7, 9, 11]
    assert analysis["toc_content_mapping"]["status"] == "ok"
    assert analysis["toc_content_mapping"]["strategy"] == "existing_physical_mapping"
    assert analysis["toc_content_mapping"]["title_match_rate"] == 1.0


def test_final_mapping_treats_start_index_as_existing_physical_mapping():
    toc_items = [
        {"title": "Alpha Research", "start_index": 3, "level": 1},
        {"title": "Beta Models", "start_index": 5, "level": 1},
        {"title": "Gamma Hypotheses", "start_index": 7, "level": 1},
        {"title": "Delta Papers", "start_index": 9, "level": 1},
        {"title": "Epsilon Outlook", "start_index": 11, "level": 1},
    ]
    page_list = [
        ("Cover",),
        ("Contents\nAlpha Research\nBeta Models\nGamma Hypotheses\nDelta Papers\nEpsilon Outlook",),
        ("Alpha Research\nBody",),
        ("Beta Models\nGamma Hypotheses\nDelta Papers\nEpsilon Outlook\nOverview",),
        ("Beta Models\nBody",),
        ("More beta",),
        ("Gamma Hypotheses\nBody",),
        ("More gamma",),
        ("Delta Papers\nBody",),
        ("More delta",),
        ("Epsilon Outlook\nBody",),
        ("Appendix",),
    ]
    analysis = {
        "toc_source": "llm_toc_page",
        "llm_toc_page": {
            "status": "ok",
            "source": "llm_toc_page",
            "has_printed_page_numbers": False,
        },
    }

    mapped = PageIndexService._map_toc_items_after_content_ocr(
        toc_items,
        page_list=page_list,
        page_count=len(page_list),
        toc_pages=[2],
        analysis=analysis,
    )

    assert [item["start_index"] for item in mapped] == [3, 5, 7, 9, 11]
    assert analysis["toc_content_mapping"]["status"] == "ok"
    assert analysis["toc_content_mapping"]["strategy"] == "existing_physical_mapping"


def test_final_mapping_falls_back_to_existing_unpaged_mapping_when_title_search_collapses():
    toc_items = [
        {"title": "Alpha Research", "physical_index": 3, "level": 1},
        {"title": "Beta Models", "physical_index": 5, "level": 1},
        {"title": "Gamma Hypotheses", "physical_index": 7, "level": 1},
        {"title": "Delta Papers", "physical_index": 9, "level": 1},
        {"title": "Epsilon Outlook", "physical_index": 11, "level": 1},
    ]
    page_list = [
        ("Cover",),
        ("Contents\nAlpha Research\nBeta Models\nGamma Hypotheses\nDelta Papers\nEpsilon Outlook",),
        ("Section body without visible heading",),
        ("Beta Models\nGamma Hypotheses\nDelta Papers\nEpsilon Outlook\nOverview",),
        ("More beta body without heading",),
        ("More beta",),
        ("More gamma body without heading",),
        ("More gamma",),
        ("More delta body without heading",),
        ("More delta",),
        ("Final outlook body without heading",),
        ("Appendix",),
    ]
    analysis = {
        "toc_source": "llm_toc_page",
        "llm_toc_page": {
            "status": "ok",
            "source": "llm_toc_page",
            "has_printed_page_numbers": False,
        },
    }

    mapped = PageIndexService._map_toc_items_after_content_ocr(
        toc_items,
        page_list=page_list,
        page_count=len(page_list),
        toc_pages=[2],
        analysis=analysis,
    )

    assert [item["physical_index"] for item in mapped] == [3, 5, 7, 9, 11]
    assert analysis["toc_content_mapping"]["status"] == "ok"
    assert analysis["toc_content_mapping"]["strategy"] == "existing_physical_mapping"
    assert analysis["toc_content_mapping"]["fallback_from"] == "content_title_search"


def test_final_mapping_falls_back_to_existing_mapping_when_printed_page_remap_fails():
    toc_items = [
        {"title": "Case 01", "page": 1, "physical_index": 3, "level": 1},
        {"title": "Case 02", "page": 5, "physical_index": 4, "level": 1},
        {"title": "Case 03", "page": 3, "physical_index": 5, "level": 1},
        {"title": "Case 04", "page": 7, "physical_index": 6, "level": 1},
        {"title": "Case 05", "page": 9, "physical_index": 7, "level": 1},
    ]
    page_list = [
        ("Cover",),
        ("Contents",),
        ("Case 01\nBody",),
        ("Case 02\nBody",),
        ("Case 03\nBody",),
        ("Case 04\nBody",),
        ("Case 05\nBody",),
    ]
    analysis = {
        "toc_source": "llm_toc_page",
        "llm_toc_page": {
            "status": "ok",
            "source": "llm_toc_page",
            "has_printed_page_numbers": True,
        },
    }

    mapped = PageIndexService._map_toc_items_after_content_ocr(
        toc_items,
        page_list=page_list,
        page_count=len(page_list),
        toc_pages=[2],
        analysis=analysis,
    )

    assert [item["physical_index"] for item in mapped] == [3, 4, 5, 6, 7]
    assert analysis["toc_content_mapping"]["status"] == "ok"
    assert analysis["toc_content_mapping"]["strategy"] == "existing_physical_mapping"
    assert analysis["toc_content_mapping"]["fallback_from"] == "printed_page_offset"


def test_unpaged_toc_existing_mapping_prefers_matching_chapter_dividers():
    toc_items = [
        {"title": "One AI research paradigm", "level": 2, "physical_index": 4},
        {"title": "Two model landscape", "level": 4, "physical_index": 17},
        {"title": "Three hypothesis generation", "level": 4, "physical_index": 30},
        {"title": "Four papers and projects", "level": 4, "physical_index": 43},
        {"title": "Five outlook", "level": 4, "physical_index": 56},
    ]
    page_list = [("Body",)] * 68
    analysis = {
        "toc_source": "llm_toc_page",
        "toc_pages": [2, 3],
        "chapter_dividers": [2, 3, 13, 35, 49, 61],
        "llm_toc_page": {
            "status": "ok",
            "source": "llm_toc_page",
            "has_printed_page_numbers": False,
        },
    }

    mapped = PageIndexService._map_toc_items_after_content_ocr(
        toc_items,
        page_list=page_list,
        page_count=len(page_list),
        toc_pages=[2, 3],
        analysis=analysis,
    )

    assert [item["physical_index"] for item in mapped] == [3, 13, 35, 49, 61]
    assert analysis["toc_content_mapping"]["strategy"] == "chapter_divider_sequence"
    assert analysis["toc_content_mapping"]["status"] == "ok"


def test_llm_quality_advisory_score_does_not_trigger_hard_failure():
    reasons = PageIndexService._collect_toc_quality_failure_reasons(
        analysis={},
        completeness={"needs_repair": False},
        llm_quality_check={
            "verdict": "fail",
            "overall_score": 0.5,
            "needs_repair": True,
            "suggestions": ["Clean noisy appendix entries."],
        },
        quality_report={"status": "needs_review", "hard_fail_reasons": []},
    )

    assert reasons == []


def test_llm_quality_explicit_hard_reasons_trigger_failure_in_tuning_mode():
    reasons = PageIndexService._collect_toc_quality_failure_reasons(
        analysis={},
        completeness={"needs_repair": False},
        llm_quality_check={
            "verdict": "fail",
            "overall_score": 0.2,
            "hard_fail_reasons": ["single_node_toc"],
        },
        quality_report={"status": "needs_review", "hard_fail_reasons": []},
    )

    assert reasons == ["llm_quality_check:single_node_toc"]


def test_llm_quality_long_leaf_reason_requires_deterministic_gate_support():
    reasons = PageIndexService._collect_toc_quality_failure_reasons(
        analysis={},
        completeness={
            "needs_repair": False,
            "balanced_quality_gate": {
                "child_expansion_expected": False,
                "unexpanded_long_leaf_hard_count": 0,
            },
        },
        llm_quality_check={
            "verdict": "fail",
            "overall_score": 0.3,
            "hard_fail_reasons": ["unexpanded_long_leaf_after_expansion"],
        },
        quality_report={"status": "needs_review", "hard_fail_reasons": []},
    )

    assert reasons == []


def test_llm_quality_hard_reasons_can_be_kept_advisory_by_config():
    reasons = PageIndexService._collect_toc_quality_failure_reasons(
        analysis={"llm_quality_advisory_only": True},
        completeness={"needs_repair": False},
        llm_quality_check={
            "verdict": "fail",
            "overall_score": 0.2,
            "hard_fail_reasons": ["single_node_toc"],
        },
        quality_report={"status": "needs_review", "hard_fail_reasons": []},
    )

    assert reasons == []


def test_embedded_code_toc_long_leaf_failure_can_be_retained_as_best_candidate():
    result = {
        "route_decision": {
            "selected_path": "embedded_toc",
            "execution_mode": "fast",
            "initial_execution_mode": "fast",
            "final_execution_mode": "fast",
            "toc_source": "code_toc",
        },
        "quality_report": {
            "status": "failed:toc_quality",
            "hard_fail_reasons": ["unexpanded_long_leaf_after_expansion"],
        },
    }
    reasons = ["llm_quality_check:unexpanded_long_leaf_after_expansion"]

    assert PageIndexService._can_retain_best_candidate_after_retry_failure(result, reasons)

    PageIndexService._retain_best_candidate_after_quality_retry_failure(
        result,
        reasons,
        retry_error=RuntimeError("balanced failed"),
    )

    assert result["quality_report"]["status"] == "needs_review"
    assert result["quality_report"]["hard_fail_reasons"] == []
    assert result["quality_report"]["suppressed_hard_fail_reasons"] == [
        "llm_quality_check:unexpanded_long_leaf_after_expansion"
    ]
    assert result["route_decision"]["best_candidate"]["source"] == "code_toc"
    assert result["route_decision"]["attempt_chain"][-1]["status"] == "failed"


def test_mapping_failure_cannot_be_retained_as_best_candidate_after_retry_failure():
    result = {
        "route_decision": {
            "selected_path": "embedded_toc",
            "execution_mode": "fast",
            "initial_execution_mode": "fast",
            "final_execution_mode": "fast",
            "toc_source": "code_toc",
        },
        "quality_report": {
            "status": "failed:toc_quality",
            "hard_fail_reasons": ["toc_content_mapping_failed"],
        },
    }
    reasons = [
        "content_mapping:mapping_non_monotonic",
        "quality_report:toc_content_mapping_failed",
    ]

    assert not PageIndexService._can_retain_best_candidate_after_retry_failure(result, reasons)
