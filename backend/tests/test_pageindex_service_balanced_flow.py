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
    page_texts[43] = "Syntax\nAppendix page " + ("full text " * 40)
    page_texts[44] = "Parsing\nAppendix continuation"

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


def test_fast_embedded_attempt_failure_can_retry_balanced() -> None:
    assert PageIndexService._should_retry_toc_attempt_with_balanced(
        {"selected_path": "embedded_toc"},
        requested_mode="smart",
        initial_execution_mode="fast",
    )
    assert not PageIndexService._should_retry_toc_attempt_with_balanced(
        {"selected_path": "visible_toc_with_pages"},
        requested_mode="smart",
        initial_execution_mode="balanced",
    )


def test_quality_retry_keeps_embedded_code_toc_available() -> None:
    route_decision = {"selected_path": "embedded_toc", "toc_source": "code_toc"}

    assert not PageIndexService._should_disable_code_toc_for_balanced_retry(
        route_decision,
        retry_reason="quality_failure",
    )
    assert PageIndexService._should_disable_code_toc_for_balanced_retry(
        route_decision,
        retry_reason="no_candidate",
    )


def test_no_candidate_payload_is_failed_report_not_exception_shape() -> None:
    payload = PageIndexService._build_no_candidate_index_payload(
        file_name="sample.pdf",
        page_count=12,
        analysis={
            "text_coverage": 1.0,
            "toc_attempt_chain": [
                {
                    "path": "content_outline",
                    "status": "rejected",
                    "failure_reasons": ["draft_empty"],
                }
            ],
        },
        route_decision={
            "selected_path": "content_outline",
            "execution_mode": "balanced",
            "attempts": [{"path": "content_outline"}],
        },
        requested_mode="smart",
        execution_mode="balanced",
        initial_execution_mode="balanced",
        failure_reasons=["draft_empty"],
    )

    assert payload["doc_name"] == "sample.pdf"
    assert payload["structure"][0]["start_index"] == 1
    assert payload["structure"][0]["end_index"] == 12
    assert payload["route_decision"]["attempt_chain"][0]["failure_reasons"] == ["draft_empty"]
    assert payload["quality_report"]["status"] == "failed:toc_pipeline"
    assert payload["quality_report"]["hard_fail_reasons"] == ["no_toc_candidate"]


def test_quality_failure_payload_is_failed_report_not_exception_shape() -> None:
    payload = {
        "doc_name": "sample.pdf",
        "page_count": 12,
        "structure": [{"title": "Chapter", "start_index": 1, "end_index": 12}],
        "route_decision": {"selected_path": "content_outline"},
        "quality_report": {"status": "needs_review", "hard_fail_reasons": []},
        "enrichment_status": "pending",
    }

    PageIndexService._mark_toc_quality_failure_payload(
        payload,
        ["content_mapping:mapping_non_monotonic", "quality_report:toc_content_mapping_failed"],
    )

    assert payload["enrichment_status"] == "failed"
    assert payload["quality_report"]["status"] == "failed:toc_quality"
    assert payload["quality_report"]["hard_fail_reasons"] == [
        "content_mapping:mapping_non_monotonic",
        "quality_report:toc_content_mapping_failed",
    ]
    assert payload["route_decision"]["quality_failure_reasons"] == [
        "content_mapping:mapping_non_monotonic",
        "quality_report:toc_content_mapping_failed",
    ]
