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
            "end_index": 24,
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


def test_expand_visual_page_outline_prefers_page_evidence_over_flat_text():
    tree = [
        {
            "title": "Chapter 2 Applications",
            "structure": "2",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        }
    ]
    analysis = {
        "toc_semi_frozen": True,
        "page_evidence": [
            {
                "page": 12,
                "primary_role": "content_slide",
                "evidence_spans": [
                    {
                        "role": "page_title",
                        "text": "Industry AI adoption",
                        "confidence": 0.9,
                    }
                ],
            }
        ],
    }

    added = PageIndexService._expand_visual_page_outline_if_needed(
        toc_tree=tree,
        analysis=analysis,
        page_count=43,
        toc_source="vlm_toc_skeleton",
        page_list=[["noise"]] * 43,
    )

    assert added == 1
    assert tree[0]["nodes"][0]["title"] == "Industry AI adoption"
    assert tree[0]["nodes"][0]["source"] == "structured_evidence"


def test_expand_visual_page_outline_uses_canonical_freeze_state():
    tree = [
        {
            "title": "Chapter 2 Applications",
            "structure": "2",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        }
    ]
    analysis = {
        "top_level_frozen": True,
        "allow_child_expansion": True,
        "page_evidence": [
            {
                "page": 12,
                "primary_role": "content_slide",
                "evidence_spans": [
                    {
                        "role": "page_title",
                        "text": "Industry AI adoption",
                        "confidence": 0.9,
                    }
                ],
            }
        ],
    }

    added = PageIndexService._expand_visual_page_outline_if_needed(
        toc_tree=tree,
        analysis=analysis,
        page_count=43,
        toc_source="vlm_toc_skeleton",
        page_list=[["noise"]] * 43,
    )

    assert added == 1
    assert tree[0]["nodes"][0]["title"] == "Industry AI adoption"


def test_child_expansion_is_not_tied_to_vlm_toc_source():
    tree = [
        {
            "title": "Chapter 2 Applications",
            "structure": "2",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        }
    ]
    analysis = {
        "top_level_frozen": True,
        "allow_child_expansion": True,
        "page_evidence": [
            {
                "page": 12,
                "primary_role": "content_slide",
                "evidence_spans": [
                    {
                        "role": "page_title",
                        "text": "Industry AI adoption",
                        "confidence": 0.9,
                    }
                ],
            }
        ],
    }

    added = PageIndexService._expand_visual_page_outline_if_needed(
        toc_tree=tree,
        analysis=analysis,
        page_count=43,
        toc_source="toc_page",
        page_list=[["noise"]] * 43,
    )

    assert added == 1
    assert analysis["outline_expansion"]["source"] == "page_evidence"
    assert tree[0]["nodes"][0]["title"] == "Industry AI adoption"


def test_visual_vlm_child_expansion_runs_when_text_expansion_bad(monkeypatch):
    tree = [
        {
            "title": "Chapter 2 Applications",
            "structure": "2",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        }
    ]
    analysis = {
        "top_level_frozen": True,
        "allow_child_expansion": True,
        "document_path": "demo.pdf",
    }

    async def fake_extract_visual_child_titles(*, file_path, tree, page_count, model=None):
        assert file_path == "demo.pdf"
        return {
            "added_children": 2,
            "quality": "good",
            "expected_children": 3,
            "actual_children": 2,
            "needs_repair": False,
        }

    monkeypatch.setattr(
        PageIndexService,
        "_extract_visual_child_titles_for_flat_skeleton",
        fake_extract_visual_child_titles,
    )

    added = asyncio.run(
        PageIndexService._expand_visual_page_outline_with_vlm_fallback(
            toc_tree=tree,
            analysis=analysis,
            page_count=43,
            toc_source="vlm_toc_skeleton",
            page_list=[["noise"]] * 43,
        )
    )

    assert added == 2
    assert analysis["outline_expansion"]["source"] == "vlm_page_titles"


def test_low_quality_text_skips_flat_fallback_and_uses_vlm(monkeypatch):
    tree = [
        {
            "title": "Chapter 2 Applications",
            "structure": "2",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        }
    ]
    analysis = {
        "top_level_frozen": True,
        "allow_child_expansion": True,
        "document_path": "demo.pdf",
        "text_quality": {"is_low_quality": True},
    }

    def fail_flat_fallback(*args, **kwargs):
        raise AssertionError("flat fallback should be skipped for low-quality text")

    async def fake_extract_visual_child_titles(*, file_path, tree, page_count, model=None):
        return {
            "added_children": 3,
            "quality": "good",
            "expected_children": 3,
            "actual_children": 3,
            "needs_repair": False,
        }

    monkeypatch.setattr(
        "pageindex.visual_page_outline_extractor.expand_flat_toc_with_page_titles",
        fail_flat_fallback,
    )
    monkeypatch.setattr(
        PageIndexService,
        "_extract_visual_child_titles_for_flat_skeleton",
        fake_extract_visual_child_titles,
    )

    added = asyncio.run(
        PageIndexService._expand_visual_page_outline_with_vlm_fallback(
            toc_tree=tree,
            analysis=analysis,
            page_count=43,
            toc_source="vlm_toc_skeleton",
            page_list=[["garbled"]] * 43,
        )
    )

    assert added == 3
    assert analysis["outline_expansion"]["source"] == "vlm_page_titles"
    assert analysis["outline_expansion"]["reason"] == "low_quality_text"


def test_vlm_child_expansion_respects_generic_expansion_policy(monkeypatch):
    tree = [
        {
            "title": "Chapter 2 Applications",
            "structure": "2",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        }
    ]
    analysis = {
        "top_level_frozen": False,
        "allow_child_expansion": False,
        "document_path": "demo.pdf",
        "text_quality": {"is_low_quality": True},
    }

    async def fail_visual_expansion(*args, **kwargs):
        raise AssertionError("VLM child expansion should require the generic expansion policy")

    monkeypatch.setattr(
        PageIndexService,
        "_extract_visual_child_titles_for_flat_skeleton",
        fail_visual_expansion,
    )

    added = asyncio.run(
        PageIndexService._expand_visual_page_outline_with_vlm_fallback(
            toc_tree=tree,
            analysis=analysis,
            page_count=43,
            toc_source="toc_page",
            page_list=[["garbled"]] * 43,
        )
    )

    assert added == 0
    assert "outline_expansion" not in analysis


def test_visual_path_bad_flat_expansion_triggers_vlm_child_fallback(monkeypatch):
    tree = [
        {
            "title": "Part02：增长引擎一：AI心智占位",
            "structure": "2",
            "start_index": 13,
            "end_index": 24,
            "nodes": [],
        }
    ]
    analysis = {
        "top_level_frozen": True,
        "allow_child_expansion": True,
        "balanced_path": "visual",
        "document_path": "demo.pdf",
        "text_coverage": 0.71,
    }

    async def fake_extract_visual_child_titles(*, file_path, tree, page_count, model=None):
        return {
            "added_children": 4,
            "quality": "good",
            "expected_children": 4,
            "actual_children": 4,
            "needs_repair": False,
        }

    monkeypatch.setattr(
        PageIndexService,
        "_extract_visual_child_titles_for_flat_skeleton",
        fake_extract_visual_child_titles,
    )

    added = asyncio.run(
        PageIndexService._expand_visual_page_outline_with_vlm_fallback(
            toc_tree=tree,
            analysis=analysis,
            page_count=62,
            toc_source="vlm_toc_skeleton",
            page_list=[[""]] * 62,
        )
    )

    assert added == 4
    assert analysis["outline_expansion"]["source"] == "vlm_page_titles"


def test_content_ocr_stage_name_distinguishes_content_fill_from_structure_ocr():
    assert PageIndexService._content_ocr_stage_name() == "content_ocr"


def test_legacy_visual_balanced_result_sets_semi_frozen_build_state():
    analysis = {}
    balanced_result = {
        "source": "vlm_toc_skeleton",
        "toc_items": [{"title": "Part01", "level": 1, "physical_index": 5}],
        "mapped": True,
        "semi_frozen": True,
        "prevalidated": True,
    }

    PageIndexService._apply_balanced_result_state(analysis, balanced_result)

    assert analysis["top_level_frozen"] is True
    assert analysis["allow_child_expansion"] is True
    assert analysis["toc_frozen"] is False
    assert analysis["toc_semi_frozen"] is True
    assert analysis["toc_frozen_source"] == "vlm_toc_skeleton"
    assert analysis["build_state"]["top_level_frozen"] is True
    assert analysis["build_state"]["allow_child_expansion"] is True
