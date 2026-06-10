import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.contracts import (
    make_build_state,
    make_mapped_outline,
    make_outline_candidate,
    make_toc_skeleton_context,
)


def test_make_toc_skeleton_context_preserves_validity_flags():
    context = make_toc_skeleton_context(
        items=[{"title": "Chapter 1", "level": 1}],
        source="toc_page_visual",
        toc_pages=[2],
        skeleton_valid=True,
        page_mapping_valid=False,
        hierarchy_valid=False,
        has_page_numbers=False,
        authoritative_top_level=True,
        confidence=0.9,
    )

    assert context["source"] == "toc_page_visual"
    assert context["toc_pages"] == [2]
    assert context["items"][0]["title"] == "Chapter 1"
    assert context["skeleton_valid"] is True
    assert context["page_mapping_valid"] is False
    assert context["hierarchy_valid"] is False
    assert context["has_page_numbers"] is False
    assert context["authoritative_top_level"] is True
    assert context["confidence"] == 0.9
    assert context["debug"] == {}


def test_make_outline_candidate_requires_source():
    with pytest.raises(ValueError, match="source"):
        make_outline_candidate(source="", items=[])


def test_make_outline_candidate_defaults_to_non_final_tree():
    candidate = make_outline_candidate(
        source="slide_outline",
        items=[{"title": "Slide topic", "level": 1, "physical_index": 3}],
        confidence=0.8,
        evidence_type="page_title",
        coverage=0.75,
        granularity="page",
        mapping_strategy="page_title",
    )

    assert candidate["source"] == "slide_outline"
    assert candidate["top_level_frozen"] is True
    assert candidate["allow_child_expansion"] is True
    assert candidate["semi_frozen"] is True
    assert candidate["skeleton_frozen"] is False
    assert candidate["risk_flags"] == []
    assert "structure" not in candidate


def test_make_mapped_outline_preserves_mapping_metadata():
    mapped = make_mapped_outline(
        source="toc_page_visual",
        items=[
            {
                "title": "Chapter 1",
                "start_index": 5,
                "end_index": 12,
                "mapping_confidence": 0.85,
            }
        ],
        mapping_strategy="divider_sequence",
        mapping_quality=0.82,
    )

    assert mapped["source"] == "toc_page_visual"
    assert mapped["range_mapped"] is True
    assert mapped["mapping_strategy"] == "divider_sequence"
    assert mapped["mapping_quality"] == 0.82
    assert mapped["items"][0]["start_index"] == 5


def test_make_build_state_defaults_to_expandable_unfrozen_state():
    state = make_build_state(skeleton_source="toc_page_visual")

    assert state["skeleton_source"] == "toc_page_visual"
    assert state["top_level_frozen"] is False
    assert state["top_level_source"] is None
    assert state["range_locked"] is False
    assert state["children_locked"] is False
    assert state["tree_complete"] is False
    assert state["needs_repair"] is False
    assert state["repair_actions"] == []
    assert state["skeleton_frozen"] is False
    assert state["skeleton_frozen_source"] is None
    assert state["range_mapped"] is False
    assert state["children_expanded"] is False
    assert state["allow_top_level_regroup"] is True
    assert state["allow_child_expansion"] is True
    assert state["allow_auxiliary_catalogs"] is True


def test_make_build_state_maps_legacy_frozen_to_top_level_only():
    state = make_build_state(
        skeleton_source="toc_page_visual",
        skeleton_frozen=True,
        skeleton_frozen_source="toc_page_visual",
        range_mapped=True,
    )

    assert state["top_level_frozen"] is True
    assert state["top_level_source"] == "toc_page_visual"
    assert state["range_locked"] is False
    assert state["children_locked"] is False
    assert state["tree_complete"] is False
    assert state["skeleton_frozen"] is True
    assert state["frozen"] is True
