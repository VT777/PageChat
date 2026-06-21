from pathlib import Path
import sys
import asyncio
import json
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_should_skip_legacy_toc_detection_when_anchor_toc_exists_and_provider_succeeded():
    analysis = {"toc_pages": [2], "toc_page": {"has_toc_page": True, "pages": [2]}}
    result = {"items": [{"title": "A"}], "prevalidated": True, "source": "toc_page_text"}

    assert PageIndexService._should_skip_legacy_toc_detection(analysis, result) is True


def test_should_not_skip_legacy_toc_detection_without_result():
    analysis = {"toc_pages": [2], "toc_page": {"has_toc_page": True, "pages": [2]}}

    assert PageIndexService._should_skip_legacy_toc_detection(analysis, None) is False


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


def test_collect_candidates_respects_selected_visible_toc_path(monkeypatch, tmp_path):
    service = PageIndexService()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("selected visible TOC path must not run other complete TOC builders")

    async def fake_extract_toc_text(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "第一章", "page": 5, "physical_index": 5, "level": 1}
            ],
            "source": "llm_toc_page",
        }

    monkeypatch.setattr(service, "_try_balanced_provider_shortcut", forbidden)
    monkeypatch.setattr(service, "_try_text_heading_toc", forbidden)
    monkeypatch.setattr(service, "_extract_toc_text", fake_extract_toc_text)
    monkeypatch.setattr(
        service,
        "_build_text_toc_candidate",
        lambda *_args, **_kwargs: forbidden(),
    )

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": ["", "目录\n第一章 ........ 5", "正文"],
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "sample.pdf",
            page_count=10,
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert [candidate["source"] for candidate in candidates] == ["llm_toc_page"]


def test_collect_candidates_uses_page_text_map_for_layout_required_visible_toc(monkeypatch, tmp_path):
    service = PageIndexService()
    calls = {"llm": 0}

    def fake_rule(*_args, **_kwargs):
        return None

    async def fake_extract_toc_text(*_args, **_kwargs):
        calls["llm"] += 1
        return {
            "toc_items": [
                {"title": "01 Case Alpha", "page": 1, "physical_index": 3, "level": 1},
                {"title": "02 Case Beta", "page": 3, "physical_index": 5, "level": 1},
            ],
            "source": "llm_toc_page",
        }

    monkeypatch.setattr(
        "pageindex.visible_toc_rule_extractor.extract_visible_toc_with_pages",
        fake_rule,
    )
    monkeypatch.setattr(service, "_extract_toc_text", fake_extract_toc_text)

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "layout_type": "scanned_image_pdf",
                "structure_policy": "layout_required",
                "content_type": "ocr",
                "page_texts": [
                    "Cover",
                    "Catalog\n01 Case Alpha ........ 1\n02 Case Beta ........ 3",
                    "01 Case Alpha\nBody",
                    "More body",
                    "02 Case Beta\nBody",
                ],
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "scan.pdf",
            page_count=5,
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert calls["llm"] == 1
    assert [candidate["source"] for candidate in candidates] == ["llm_toc_page"]


def test_legacy_visual_toc_layout_is_disabled_by_default_after_s1() -> None:
    analysis = {
        "structure_policy": "layout_required",
        "page_texts": [],
    }
    route_decision = {
        "path": "ppocr_layout",
        "selected_path": "content_outline",
    }

    assert not PageIndexService._should_run_legacy_toc_layout(route_decision, analysis)


def test_legacy_visual_toc_layout_requires_explicit_opt_in_and_no_page_text_map() -> None:
    route_decision = {
        "path": "ppocr_layout",
        "allow_legacy_visual_toc": True,
    }

    assert PageIndexService._should_run_legacy_toc_layout(
        route_decision,
        {"structure_policy": "layout_required", "page_texts": []},
    )
    assert not PageIndexService._should_run_legacy_toc_layout(
        route_decision,
        {"structure_policy": "layout_required", "page_texts": ["OCR text"]},
    )


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

    assert [node["title"] for node in parents] == ["Medium", "Long"]


def test_collect_candidates_falls_back_to_text_tree_for_paged_visible_toc(monkeypatch, tmp_path):
    service = PageIndexService()
    calls = {"text_tree": 0}

    monkeypatch.setattr(
        "pageindex.visible_toc_rule_extractor.extract_visible_toc_with_pages",
        lambda *_args, **_kwargs: None,
    )

    async def empty_llm_toc(*_args, **_kwargs):
        return None

    async def fake_text_tree(*_args, **_kwargs):
        calls["text_tree"] += 1
        return {
            "toc_items": [
                {"title": "Case 01", "physical_index": 3, "level": 1},
                {"title": "Case 02", "physical_index": 5, "level": 1},
            ],
            "source": "text_tree",
        }

    monkeypatch.setattr(service, "_extract_toc_text", empty_llm_toc)
    monkeypatch.setattr(service, "_build_text_toc_candidate", fake_text_tree)

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": [
                    "Cover",
                    "Catalog\nCase 01 .... 1\nCase 02 .... 3",
                    "Case 01\nBody",
                    "More body",
                    "Case 02\nBody",
                ],
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "scan.pdf",
            page_count=5,
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert calls["text_tree"] == 1
    assert [candidate["source"] for candidate in candidates] == ["text_tree"]


def test_collect_candidates_adds_content_outline_backup_for_weak_paged_toc(monkeypatch, tmp_path):
    service = PageIndexService()

    monkeypatch.setattr(
        "pageindex.visible_toc_rule_extractor.extract_visible_toc_with_pages",
        lambda *_args, **_kwargs: None,
    )

    async def weak_llm_toc(*_args, **_kwargs):
        return {
            "toc_items": [{"title": "Catalog fragment", "page": 99, "level": 1}],
            "source": "llm_toc_page",
        }

    async def fake_content_outline(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Case 01", "physical_index": 3, "level": 1},
                {"title": "Case 02", "physical_index": 5, "level": 1},
            ],
            "source": "content_outline",
        }

    monkeypatch.setattr(service, "_extract_toc_text", weak_llm_toc)
    monkeypatch.setattr(service, "_extract_content_outline_candidate", fake_content_outline)

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": [
                    "Cover",
                    "Catalog\nCase 01 .... 1\nCase 02 .... 3",
                    "Case 01\nBody",
                    "More body",
                    "Case 02\nBody",
                ],
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "scan.pdf",
            page_count=5,
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert [candidate["source"] for candidate in candidates] == [
        "llm_toc_page",
        "content_outline",
    ]


def test_collect_candidates_keeps_rule_and_llm_for_standard_paged_visible_toc(monkeypatch, tmp_path):
    service = PageIndexService()

    async def fake_extract_toc_text(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "OpenAI product matrix", "page": 4, "physical_index": 4, "level": 1},
                {"title": "Model capability outlook", "page": 10, "physical_index": 10, "level": 1},
                {"title": "AGI platform entrance", "page": 18, "physical_index": 18, "level": 1},
                {"title": "Risk warning", "page": 25, "physical_index": 25, "level": 1},
            ],
            "source": "llm_toc_page",
            "mapped": True,
        }

    monkeypatch.setattr(service, "_extract_toc_text", fake_extract_toc_text)

    page_texts = [
        "Cover",
        (
            "目录\n"
            "第一章 复盘：OpenAI 产品矩阵 ................ 4\n"
            "第二章 展望：模型能力持续提升 ................ 10\n"
            "第三章 愿景：AGI 平台入口 ................ 18\n"
            "第四章 风险提示 ................ 25\n"
            "图目录\n"
            "图1 OpenAI 产品时间线 ................ 5"
        ),
        "表目录\n表1 OpenAI 融资情况梳理 ................ 8",
        "第一章 复盘：OpenAI 产品矩阵\n正文",
        "图1 OpenAI 产品时间线\n正文",
        "正文",
        "正文",
        "表1 OpenAI 融资情况梳理\n正文",
        "正文",
        "第二章 展望：模型能力持续提升\n正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "第三章 愿景：AGI 平台入口\n正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "第四章 风险提示\n正文",
        "尾页",
    ]

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": page_texts,
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2, 3],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "sample.pdf",
            page_count=len(page_texts),
            model="qwen3.6-flash",
            anchors={"toc_pages": [2, 3]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert [candidate["source"] for candidate in candidates] == ["toc_page_text_rule", "llm_toc_page"]
    roots = candidates[0]["items"]
    assert [root["title"] for root in roots] == ["目录", "图目录", "表目录"]


def test_collect_candidates_keeps_rule_and_llm_for_unpaged_visible_toc(monkeypatch, tmp_path):
    service = PageIndexService()

    async def fake_extract_toc_text(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Global AI applications", "physical_index": 3, "level": 1},
                {"title": "China AI applications", "physical_index": 4, "level": 1},
                {"title": "Industry chain", "physical_index": 5, "level": 1},
                {"title": "Risk warning", "physical_index": 6, "level": 1},
            ],
            "source": "llm_toc_page",
            "mapped": True,
        }

    monkeypatch.setattr(service, "_extract_toc_text", fake_extract_toc_text)
    page_texts = [
        "Cover",
        (
            "目录\n"
            "国外大厂AI应用落地\n"
            "01\n"
            "国内大厂AI应用落地\n"
            "02\n"
            "产业链梳理\n"
            "03\n"
            "风险提示\n"
            "04"
        ),
        "国外大厂AI应用落地\n正文",
        "国内大厂AI应用落地\n正文",
        "产业链梳理\n正文",
        "风险提示\n正文",
    ]

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": page_texts,
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": False,
                },
            },
            route_decision={
                "selected_path": "visible_toc_no_pages",
                "path": "visible_toc_no_pages",
            },
            file_path=tmp_path / "sample.pdf",
            page_count=len(page_texts),
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert [candidate["source"] for candidate in candidates] == ["toc_page_text_rule", "llm_toc_page"]
    assert candidates[0]["evidence"]["semi_frozen"] is True


def test_collect_candidates_continues_when_rule_draft_mapping_fails(monkeypatch, tmp_path):
    service = PageIndexService()
    calls = {"content_outline": 0}

    def fake_rule_draft(*_args, **_kwargs):
        return {
            "type": "toc_draft",
            "source": "toc_page_text_rule",
            "has_page_numbers": True,
            "items": [
                {"title": "第一章 错误页码", "level": 1, "raw_page_label": 99},
                {"title": "第二章 错误页码", "level": 1, "raw_page_label": 199},
            ],
        }

    def fake_mapper(*_args, **_kwargs):
        return [], {
            "status": "failed",
            "strategy": "printed_offset",
            "reasons": ["title_match_rate_below_threshold"],
        }

    async def empty_llm_toc(*_args, **_kwargs):
        return None

    async def fake_content_outline(*_args, **_kwargs):
        calls["content_outline"] += 1
        return {
            "toc_items": [
                {"title": "正文第一章", "physical_index": 3, "level": 1},
                {"title": "正文第二章", "physical_index": 6, "level": 1},
            ],
            "source": "content_outline",
        }

    monkeypatch.setattr(
        "pageindex.visible_toc_rule_extractor.extract_visible_toc_with_pages_draft",
        fake_rule_draft,
    )
    monkeypatch.setattr("pageindex.toc_mapping.map_toc_draft_to_physical", fake_mapper)
    monkeypatch.setattr(service, "_extract_toc_text", empty_llm_toc)
    monkeypatch.setattr(service, "_extract_content_outline_candidate", fake_content_outline)

    candidates = asyncio.run(
        service._collect_text_toc_candidates(
            analysis={
                "page_texts": [
                    "Cover",
                    "目录\n第一章 错误页码 ........ 99\n第二章 错误页码 ........ 199",
                    "正文第一章\nBody",
                    "Body",
                    "Body",
                    "正文第二章\nBody",
                ],
                "toc_page_detection": {
                    "status": "detected",
                    "pages": [2],
                    "has_page_numbers": True,
                },
            },
            route_decision={
                "selected_path": "visible_toc_with_pages",
                "path": "visible_toc_with_pages",
            },
            file_path=tmp_path / "sample.pdf",
            page_count=6,
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert calls["content_outline"] == 1
    assert [candidate["source"] for candidate in candidates] == ["content_outline"]


def test_unified_controller_preserves_child_expansion_state_for_unpaged_rule(monkeypatch, tmp_path):
    service = PageIndexService()

    async def fake_llm_toc(*_args, **_kwargs):
        return {
            "toc_items": [
                {"title": "Chapter One", "level": 1, "physical_index": 3},
                {"title": "Chapter Two", "level": 1, "physical_index": 5},
                {"title": "Chapter Three", "level": 1, "physical_index": 7},
            ],
            "source": "llm_toc_page",
            "mapped": True,
        }

    def fake_rule_draft(*_args, **_kwargs):
        return {
            "type": "toc_draft",
            "source": "toc_page_text_rule",
            "has_page_numbers": False,
            "items": [
                {"title": "Chapter One", "level": 1},
                {"title": "Chapter Two", "level": 1},
                {"title": "Chapter Three", "level": 1},
            ],
        }

    def fake_mapper(*_args, **_kwargs):
        return [
            {"title": "Chapter One", "level": 1, "physical_index": 3, "start_index": 3},
            {"title": "Chapter Two", "level": 1, "physical_index": 5, "start_index": 5},
            {"title": "Chapter Three", "level": 1, "physical_index": 7, "start_index": 7},
        ], {
            "status": "ok",
            "strategy": "title_search",
            "title_match_rate": 1.0,
            "strong_anchor_count": 3,
            "reasons": [],
        }

    monkeypatch.setattr(
        "pageindex.visible_toc_rule_extractor.extract_visible_toc_no_pages_draft",
        fake_rule_draft,
    )
    monkeypatch.setattr("pageindex.toc_mapping.map_toc_draft_to_physical", fake_mapper)
    monkeypatch.setattr(service, "_extract_toc_text", fake_llm_toc)
    page_texts = [
        "Cover",
        (
            "Contents\n"
            "Chapter One\n"
            "01\n"
            "Chapter Two\n"
            "02\n"
            "Chapter Three\n"
            "03"
        ),
        "Chapter One\nBody",
        "More one",
        "Chapter Two\nBody",
        "More two",
        "Chapter Three\nBody",
    ]
    analysis = {
        "page_texts": page_texts,
        "toc_page_detection": {
            "status": "detected",
            "pages": [2],
            "has_page_numbers": False,
        },
    }

    result = asyncio.run(
        service._run_unified_toc_controller(
            file_path=tmp_path / "sample.pdf",
            requested_mode="smart",
            analysis=analysis,
            route_decision={
                "selected_path": "visible_toc_no_pages",
                "path": "visible_toc_no_pages",
            },
            page_count=len(page_texts),
            model="qwen3.6-flash",
            anchors={"toc_pages": [2]},
            ocr_text_map=None,
            dividers=[],
        )
    )

    assert result is not None
    assert result["source"] == "toc_page_text_rule"
    assert result["allow_child_expansion"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_semi_frozen"] is True


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


def test_content_outline_path_uses_internal_llm_outline_before_segment_fallback(monkeypatch):
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

    monkeypatch.setattr(service, "_try_text_heading_toc", lambda _analysis: None)
    monkeypatch.setattr(
        "pageindex.hierarchical_extractor.extract_hierarchical_toc",
        fake_extract_hierarchical_toc,
    )

    result = asyncio.run(
        service._build_text_toc_candidate(
            {"page_texts": ["Opening page", "Chapter-like page", "Closing page"]},
            toc_pages=[],
            page_count=3,
            model="qwen3.6-flash",
        )
    )

    assert result["source"] == "content_outline"
    assert result["internal_source"] == "hierarchical"
    assert [item["title"] for item in result["toc_items"]] == ["Opening", "Chapter-like page"]


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
