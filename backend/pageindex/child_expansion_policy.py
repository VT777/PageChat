"""Fact-based policy for deciding when TOC leaves need child expansion."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pageindex.tree_schema import normalize_title


ATTEMPT_MIN_SPAN = 8
HARD_FAIL_MIN_SPAN = 16


def collect_child_expansion_parents(
    nodes: List[Dict[str, Any]],
    *,
    page_count: int,
    min_span: int = ATTEMPT_MIN_SPAN,
) -> List[Dict[str, Any]]:
    """Return leaf nodes that are worth sending to LLM child expansion."""
    parents: List[Dict[str, Any]] = []

    def visit(items: List[Dict[str, Any]]) -> None:
        for node in items or []:
            if not isinstance(node, dict) or _is_auxiliary(node):
                continue
            children = _children(node)
            if _is_catalog_container(node):
                visit(children)
                continue
            if children:
                visit(children)
                continue
            if should_attempt_child_expansion(node, page_count=page_count, min_span=min_span):
                parents.append(node)

    visit(nodes)
    return parents


def analyze_child_expansion(
    nodes: List[Dict[str, Any]],
    *,
    page_count: int,
) -> Dict[str, Any]:
    """Summarize unexpanded long leaves using stable factual thresholds."""
    required: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    hard: List[Dict[str, Any]] = []

    def visit(items: List[Dict[str, Any]], content_depth: int) -> None:
        for node in items or []:
            if not isinstance(node, dict) or _is_auxiliary(node):
                continue
            children = _children(node)
            if _is_catalog_container(node):
                visit(children, content_depth)
                continue
            current_depth = content_depth + 1
            if children:
                visit(children, current_depth)
                continue
            if not should_attempt_child_expansion(node, page_count=page_count):
                continue
            page_range = _node_page_range(node, page_count=page_count)
            if page_range is None:
                continue
            start, end = page_range
            span = end - start + 1
            sample = {
                "title": str(node.get("title") or "").strip(),
                "start": start,
                "end": end,
                "span": span,
                "depth": current_depth,
            }
            required.append(sample)
            if current_depth <= 1 and span >= HARD_FAIL_MIN_SPAN:
                hard.append(sample)
            else:
                warnings.append(sample)

    visit(nodes, 0)

    return {
        "required_count": len(required),
        "unexpanded_count": len(required),
        "warning_count": len(warnings),
        "hard_count": len(hard),
        "required_sample": required[:5],
        "warning_sample": warnings[:5],
        "hard_sample": hard[:5],
    }


def should_attempt_child_expansion(
    node: Dict[str, Any],
    *,
    page_count: int,
    min_span: int = ATTEMPT_MIN_SPAN,
) -> bool:
    if _is_auxiliary(node) or _is_front_matter(node) or _is_back_matter(node):
        return False
    if _children(node):
        return False
    page_range = _node_page_range(node, page_count=page_count)
    if page_range is None:
        return False
    start, end = page_range
    return end - start + 1 >= max(1, int(min_span or ATTEMPT_MIN_SPAN))


def _children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    children = node.get("nodes") or node.get("children") or []
    return [child for child in children if isinstance(child, dict)] if isinstance(children, list) else []


def _node_page_range(node: Dict[str, Any], *, page_count: int) -> Optional[tuple[int, int]]:
    start = _positive_int(node.get("start_index")) or _positive_int(node.get("physical_index"))
    end = _positive_int(node.get("end_index")) or start
    if start is None or end is None:
        return None
    upper = max(1, int(page_count or 1))
    start = max(1, min(start, upper))
    end = max(start, min(end, upper))
    return start, end


def _is_catalog_container(node: Dict[str, Any]) -> bool:
    if node.get("page_type") == "catalog_group" or node.get("node_type") == "catalog_group":
        return True
    title = re.sub(r"\s+", "", str(node.get("title") or "")).casefold()
    return title in {"目录", "目次", "contents", "tableofcontents"}


def _is_auxiliary(node: Dict[str, Any]) -> bool:
    catalog_type = str(node.get("catalog_type") or "").strip().lower()
    return bool(
        node.get("is_auxiliary")
        or node.get("exclude_from_coverage")
        or node.get("node_type") in {"auxiliary_catalog", "auxiliary_catalog_item"}
        or catalog_type in {"figure", "table", "figure_toc", "table_toc"}
    )


def _is_front_matter(node: Dict[str, Any]) -> bool:
    raw_title = re.sub(r"\s+", " ", str(node.get("title") or "").strip().lower())
    normalized = normalize_title(raw_title)
    if not normalized:
        return False
    if re.match(r"^(preface|foreword|front matter|cover|contents|table of contents)\b", raw_title):
        return True
    return normalized in {"目录", "目次", "前言", "序言", "序", "封面", "封面页"}


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
            "附录",
            "參考文獻",
            "参考文献",
            "参考资料",
            "文献目录",
            "索引",
            "后记",
            "跋",
            "致谢",
        )
    )


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
