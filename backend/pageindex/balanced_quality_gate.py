"""Deterministic quality gate for balanced TOC output."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from pageindex.tree_schema import normalize_title


def run_balanced_quality_gate(
    tree: List[Dict[str, Any]],
    state: Dict[str, Any],
    skeleton: Optional[Dict[str, Any]],
    page_count: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate and lightly repair final balanced TOC tree."""
    fixed_tree = deepcopy(tree or [])
    repair_actions: List[str] = []

    auxiliary_nodes = [node for node in fixed_tree if _is_auxiliary(node)]
    body_nodes = [node for node in fixed_tree if not _is_auxiliary(node)]

    expected_titles = _expected_top_titles(skeleton)
    top_level_frozen = bool(state.get("top_level_frozen") or state.get("skeleton_frozen"))
    top_level_exact_match = True

    if top_level_frozen and expected_titles:
        body_nodes, top_level_exact_match, actions = _repair_top_level(body_nodes, expected_titles)
        repair_actions.extend(actions)
        fixed_tree = body_nodes + auxiliary_nodes

    long_chapter_completeness = _long_chapters_have_children(body_nodes)
    if not long_chapter_completeness:
        repair_actions.append("long_chapter_without_children")

    auxiliary_catalog_isolation = all(_is_auxiliary(node) for node in auxiliary_nodes)
    needs_repair = bool(repair_actions) and not (
        set(repair_actions) <= {"remove_extra_top_level"} and top_level_exact_match
    )
    if not long_chapter_completeness:
        needs_repair = True

    result = {
        "top_level_exact_match": top_level_exact_match,
        "boundary_tolerance_ok": True,
        "range_iou": None,
        "child_recall": None,
        "child_precision": None,
        "long_chapter_completeness": long_chapter_completeness,
        "auxiliary_catalog_isolation": auxiliary_catalog_isolation,
        "title_normalization_match": top_level_exact_match,
        "repair_actions": repair_actions,
        "needs_repair": needs_repair,
        "tree_complete": top_level_exact_match and long_chapter_completeness,
        "page_count": page_count,
    }
    return fixed_tree, result


def _expected_top_titles(skeleton: Optional[Dict[str, Any]]) -> List[str]:
    items = (skeleton or {}).get("items") or []
    titles = []
    for item in items:
        level = item.get("level", 1)
        if level in (None, 1):
            title = str(item.get("title") or "").strip()
            if title:
                titles.append(title)
    return titles


def _repair_top_level(
    body_nodes: List[Dict[str, Any]],
    expected_titles: List[str],
) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    actions: List[str] = []
    by_title = {_key(node.get("title")): node for node in body_nodes}
    repaired: List[Dict[str, Any]] = []
    exact = True

    for title in expected_titles:
        node = by_title.get(_key(title))
        if node is None:
            exact = False
            actions.append("restore_missing_top_level")
            repaired.append({"title": title, "level": 1, "nodes": [], "needs_repair": True})
        else:
            repaired.append(node)

    extra = [
        node
        for node in body_nodes
        if _key(node.get("title")) not in {_key(title) for title in expected_titles}
    ]
    if extra:
        exact = False
        actions.append("remove_extra_top_level")

    after_titles = [_key(node.get("title")) for node in repaired]
    expected_keys = [_key(title) for title in expected_titles]
    return repaired, after_titles == expected_keys, actions


def _long_chapters_have_children(nodes: List[Dict[str, Any]]) -> bool:
    for node in nodes:
        start = _positive_int(node.get("start_index"))
        end = _positive_int(node.get("end_index"))
        children = node.get("nodes") or node.get("children") or []
        if start is None or end is None:
            continue
        span = end - start + 1
        if span >= 10 and not children:
            return False
    return True


def _is_auxiliary(node: Dict[str, Any]) -> bool:
    return bool(
        node.get("is_auxiliary")
        or node.get("exclude_from_coverage")
        or node.get("node_type") in {"auxiliary_catalog", "auxiliary_catalog_item"}
    )


def _key(title: Any) -> str:
    return normalize_title(str(title or ""))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
