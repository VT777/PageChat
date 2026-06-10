"""Canonical contracts for the balanced TOC pipeline.

The helpers intentionally return plain dictionaries so the current pipeline can
adopt the contracts incrementally without a large type-system migration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _require_source(source: str) -> str:
    normalized = str(source or "").strip()
    if not normalized:
        raise ValueError("source is required")
    return normalized


def make_toc_skeleton_context(
    *,
    items: List[Dict[str, Any]],
    source: str,
    toc_pages: Optional[List[int]] = None,
    skeleton_valid: bool = False,
    page_mapping_valid: bool = False,
    hierarchy_valid: bool = False,
    has_page_numbers: bool = False,
    authoritative_top_level: bool = False,
    confidence: float = 0.0,
    debug: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a canonical TOC skeleton context."""
    return {
        "type": "toc_skeleton",
        "items": list(items or []),
        "source": _require_source(source),
        "toc_pages": list(toc_pages or []),
        "skeleton_valid": bool(skeleton_valid),
        "page_mapping_valid": bool(page_mapping_valid),
        "hierarchy_valid": bool(hierarchy_valid),
        "has_page_numbers": bool(has_page_numbers),
        "authoritative_top_level": bool(authoritative_top_level),
        "confidence": float(confidence or 0.0),
        "debug": dict(debug or {}),
    }


def make_outline_candidate(
    *,
    source: str,
    items: List[Dict[str, Any]],
    confidence: float = 0.0,
    evidence_type: str = "",
    coverage: float = 0.0,
    granularity: str = "chapter",
    skeleton_frozen: bool = False,
    semi_frozen: bool = True,
    top_level_frozen: Optional[bool] = None,
    allow_child_expansion: Optional[bool] = None,
    mapping_strategy: str = "estimated",
    risk_flags: Optional[List[str]] = None,
    debug: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a canonical candidate from a non-formal outline provider."""
    effective_top_level_frozen = bool(semi_frozen) if top_level_frozen is None else bool(top_level_frozen)
    effective_allow_child_expansion = (
        bool(semi_frozen)
        if allow_child_expansion is None
        else bool(allow_child_expansion)
    )
    return {
        "type": "outline_candidate",
        "source": _require_source(source),
        "items": list(items or []),
        "confidence": float(confidence or 0.0),
        "evidence_type": str(evidence_type or ""),
        "coverage": float(coverage or 0.0),
        "granularity": str(granularity or "chapter"),
        "top_level_frozen": effective_top_level_frozen,
        "allow_child_expansion": effective_allow_child_expansion,
        # Legacy aliases kept during migration.
        "skeleton_frozen": bool(skeleton_frozen),
        "semi_frozen": bool(semi_frozen),
        "mapping_strategy": str(mapping_strategy or "estimated"),
        "risk_flags": list(risk_flags or []),
        "debug": dict(debug or {}),
    }


def make_mapped_outline(
    *,
    source: str,
    items: List[Dict[str, Any]],
    mapping_strategy: str,
    mapping_quality: float = 0.0,
    range_mapped: bool = True,
    debug: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a canonical mapped outline."""
    return {
        "type": "mapped_outline",
        "source": _require_source(source),
        "items": list(items or []),
        "range_mapped": bool(range_mapped),
        "mapping_strategy": str(mapping_strategy or ""),
        "mapping_quality": float(mapping_quality or 0.0),
        "debug": dict(debug or {}),
    }


def make_build_state(
    *,
    skeleton: Optional[Dict[str, Any]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    page_mapping: Optional[Dict[str, Any]] = None,
    selected_source: Optional[str] = None,
    frozen: Optional[bool] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
    skeleton_source: Optional[str] = None,
    skeleton_frozen: bool = False,
    skeleton_frozen_source: Optional[str] = None,
    top_level_frozen: Optional[bool] = None,
    top_level_source: Optional[str] = None,
    range_locked: bool = False,
    children_locked: bool = False,
    tree_complete: bool = False,
    needs_repair: bool = False,
    repair_actions: Optional[List[str]] = None,
    range_mapped: bool = False,
    children_expanded: bool = False,
    allow_top_level_regroup: bool = True,
    allow_child_expansion: bool = True,
    allow_auxiliary_catalogs: bool = True,
) -> Dict[str, Any]:
    """Build explicit balanced TOC state."""
    effective_skeleton_source = skeleton_source
    if effective_skeleton_source is None and skeleton:
        effective_skeleton_source = skeleton.get("source")
    effective_frozen = bool(skeleton_frozen)
    if frozen is not None:
        effective_frozen = bool(frozen)
    effective_top_level_frozen = (
        effective_frozen
        if top_level_frozen is None
        else bool(top_level_frozen)
    )
    effective_top_level_source = top_level_source or skeleton_frozen_source
    if effective_top_level_source is None and effective_top_level_frozen:
        effective_top_level_source = effective_skeleton_source

    return {
        "skeleton": skeleton,
        "candidates": list(candidates or []),
        "page_mapping": page_mapping,
        "selected_source": selected_source,
        "top_level_frozen": effective_top_level_frozen,
        "top_level_source": effective_top_level_source,
        "range_locked": bool(range_locked),
        "children_locked": bool(children_locked),
        "tree_complete": bool(tree_complete),
        "needs_repair": bool(needs_repair),
        "repair_actions": list(repair_actions or []),
        # Legacy aliases kept during migration.
        "frozen": effective_top_level_frozen,
        "diagnostics": dict(diagnostics or {}),
        "skeleton_source": effective_skeleton_source,
        "skeleton_frozen": effective_top_level_frozen,
        "skeleton_frozen_source": skeleton_frozen_source,
        "range_mapped": bool(range_mapped),
        "children_expanded": bool(children_expanded),
        "allow_top_level_regroup": bool(allow_top_level_regroup),
        "allow_child_expansion": bool(allow_child_expansion),
        "allow_auxiliary_catalogs": bool(allow_auxiliary_catalogs),
    }
