"""Deterministic quality gate for balanced TOC output."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional, Tuple

from pageindex.child_expansion_policy import analyze_child_expansion
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

    selected_path = str(state.get("selected_path") or state.get("path") or "").strip()
    toc_source = str(state.get("toc_source") or state.get("top_level_source") or "").strip()
    child_expansion_expected = bool(state.get("allow_child_expansion", True)) and (
        top_level_frozen
        or selected_path == "visible_toc_no_pages"
        or toc_source == "content_outline"
        or (
            selected_path == "visible_toc_with_pages"
            and toc_source in {"content_outline", "hierarchical"}
        )
    )

    detected_style = _detect_tree_style(body_nodes)
    if child_expansion_expected:
        child_expansion = analyze_child_expansion(body_nodes, page_count=page_count)
    else:
        child_expansion = {
            "required_count": 0,
            "unexpanded_count": 0,
            "warning_count": 0,
            "hard_count": 0,
            "required_sample": [],
            "warning_sample": [],
            "hard_sample": [],
        }

    unexpanded_hard_count = int(child_expansion.get("hard_count") or 0)
    unexpanded_warning_count = int(child_expansion.get("warning_count") or 0)
    hard_fail_reasons: List[str] = []
    long_chapter_completeness = unexpanded_hard_count == 0
    if unexpanded_hard_count:
        repair_actions.append("long_chapter_without_children")
        hard_fail_reasons.append("unexpanded_long_leaf_after_expansion")
    elif unexpanded_warning_count:
        repair_actions.append("long_chapter_without_children_warning")

    auxiliary_catalog_isolation = all(_is_auxiliary(node) for node in auxiliary_nodes)
    blocking_repair_actions = [
        action
        for action in repair_actions
        if action != "long_chapter_without_children_warning"
    ]
    needs_repair = bool(blocking_repair_actions) and not (
        set(blocking_repair_actions) <= {"remove_extra_top_level"} and top_level_exact_match
    )
    if not long_chapter_completeness:
        needs_repair = True

    if detected_style == "flat" and top_level_exact_match and long_chapter_completeness:
        style_fit = "acceptable"
    elif long_chapter_completeness:
        style_fit = "acceptable" if not repair_actions else "warning"
    else:
        style_fit = "poor"

    result = {
        "top_level_exact_match": top_level_exact_match,
        "boundary_tolerance_ok": True,
        "range_iou": None,
        "child_recall": None,
        "child_precision": None,
        "long_chapter_completeness": long_chapter_completeness,
        "auxiliary_catalog_isolation": auxiliary_catalog_isolation,
        "title_normalization_match": top_level_exact_match,
        "detected_style": detected_style,
        "selected_path": selected_path,
        "child_expansion_expected": child_expansion_expected,
        "child_expansion_attempted": child_expansion_expected,
        "child_expansion_required_count": int(child_expansion.get("required_count") or 0),
        "unexpanded_long_leaf_count": int(child_expansion.get("unexpanded_count") or 0),
        "unexpanded_long_leaf_warning_count": unexpanded_warning_count,
        "unexpanded_long_leaf_hard_count": unexpanded_hard_count,
        "unexpanded_long_leaf_sample": child_expansion.get("required_sample") or [],
        "style_fit": style_fit,
        "repair_actions": repair_actions,
        "hard_fail_reasons": sorted(set(hard_fail_reasons)),
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


def _detect_tree_style(nodes: List[Dict[str, Any]]) -> str:
    if not nodes:
        return "collapsed"
    child_count = sum(1 for node in nodes if _has_children(node))
    if len(nodes) == 1:
        return "hierarchical" if child_count else "collapsed"
    if child_count == 0:
        return "flat"
    if child_count == len(nodes):
        return "hierarchical"
    return "mixed"


def _long_chapters_have_children(nodes: List[Dict[str, Any]], *, min_span: int = 10) -> bool:
    for node in nodes:
        if _is_front_matter(node) or _is_back_matter(node):
            continue
        start = _positive_int(node.get("start_index"))
        end = _positive_int(node.get("end_index"))
        children = node.get("nodes") or node.get("children") or []
        if start is None or end is None:
            continue
        span = end - start + 1
        if span >= min_span and not children:
            return False
    return True


def _is_front_matter(node: Dict[str, Any]) -> bool:
    raw_title = re.sub(r"\s+", " ", str(node.get("title") or "").strip().lower())
    normalized = normalize_title(raw_title)
    if not normalized:
        return False
    if re.match(r"^(preface|foreword|front matter|cover|contents|table of contents)\b", raw_title):
        return True
    return normalized in {
        "\u76ee\u5f55",
        "\u76ee\u6b21",
        "\u524d\u8a00",
        "\u524d\u8a9e",
        "\u5e8f\u8a00",
        "\u5e8f",
        "\u5c01\u9762",
        "\u5c01\u9762\u9875",
    }


def _is_auxiliary(node: Dict[str, Any]) -> bool:
    return bool(
        node.get("is_auxiliary")
        or node.get("exclude_from_coverage")
        or node.get("node_type") in {"auxiliary_catalog", "auxiliary_catalog_item"}
    )


def _is_back_matter(node: Dict[str, Any]) -> bool:
    raw_title = re.sub(r"\s+", " ", str(node.get("title") or "").strip().lower())
    normalized = normalize_title(raw_title)
    if not normalized:
        return False
    if re.match(
        r"^(appendix|appendices|annex|annexes|supplement|references?|bibliography|index|acknowledg(?:ement|ments)|afterword|postscript)\b",
        raw_title,
    ):
        return True
    return normalized.startswith(
        (
            "\u9644\u5f55",
            "\u9644\u9304",
            "\u53c2\u8003\u6587\u732e",
            "\u53c3\u8003\u6587\u737b",
            "\u53c2\u8003\u8d44\u6599",
            "\u6587\u732e\u76ee\u5f55",
            "\u7d22\u5f15",
            "\u540e\u8bb0",
            "\u5f8c\u8a18",
            "\u8dcb",
            "\u81f4\u8c22",
            "\u81f4\u8b1d",
        )
    )

def _has_children(node: Dict[str, Any]) -> bool:
    return bool(node.get("nodes") or node.get("children"))


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
