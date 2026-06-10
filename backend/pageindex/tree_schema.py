"""Final tree node normalization helpers for balanced TOC output."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any, Dict, Optional


def normalize_title(title: str) -> str:
    """Normalize a title for matching, ids, and duplicate checks."""
    text = re.sub(r"\s+", "", str(title or "").strip().lower())
    return re.sub(r"[：:，,、。.\-—_]+", "", text)


def normalize_display_title(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip())


def normalize_tree_node(
    node: Dict[str, Any],
    *,
    doc_id: str,
    page_count: int,
    parent: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a canonical TreeNode-compatible dict.

    Ranges are 1-based physical PDF pages and inclusive on both ends.
    """
    normalized = deepcopy(node or {})
    title = normalize_display_title(normalized.get("title", ""))
    normalized["title"] = title
    normalized["normalized_title"] = normalized.get("normalized_title") or normalize_title(title)
    normalized["level"] = _positive_int(normalized.get("level")) or (
        (_positive_int(parent.get("level")) + 1) if parent else 1
    )

    start = _positive_int(normalized.get("start_index"))
    end = _positive_int(normalized.get("end_index"))
    start = _clamp_page(start or _positive_int(normalized.get("physical_index")) or 1, page_count)
    end = _clamp_page(end or start, page_count)
    if end < start:
        end = start

    repair_reasons = list(normalized.get("repair_reasons") or [])
    if parent:
        parent_start = _positive_int(parent.get("start_index")) or 1
        parent_end = _positive_int(parent.get("end_index")) or page_count
        clamped_start = min(max(start, parent_start), parent_end)
        clamped_end = min(max(end, clamped_start), parent_end)
        if clamped_start != start or clamped_end != end:
            repair_reasons.append("range_outside_parent")
            normalized["needs_repair"] = True
        start, end = clamped_start, clamped_end

    normalized["start_index"] = start
    normalized["end_index"] = end
    normalized["source"] = str(normalized.get("source") or "unknown")
    normalized["evidence_pages"] = list(normalized.get("evidence_pages") or [])
    normalized["mapping_confidence"] = float(normalized.get("mapping_confidence") or 0.0)
    normalized["title_confidence"] = float(normalized.get("title_confidence") or 0.0)
    normalized["needs_repair"] = bool(normalized.get("needs_repair", False))
    normalized["repair_reasons"] = repair_reasons
    normalized["is_auxiliary"] = bool(
        normalized.get("is_auxiliary")
        or normalized.get("node_type") in {"auxiliary_catalog", "auxiliary_catalog_item"}
    )
    if normalized["is_auxiliary"]:
        normalized["exclude_from_coverage"] = True
        normalized["exclude_from_llm_qc"] = True

    normalized["metadata"] = dict(normalized.get("metadata") or {})
    normalized["id"] = normalized.get("id") or _stable_node_id(normalized, doc_id=doc_id)

    children = normalized.get("nodes") or normalized.get("children") or []
    normalized["nodes"] = [
        normalize_tree_node(child, doc_id=doc_id, page_count=page_count, parent=normalized)
        for child in children
        if isinstance(child, dict)
    ]
    normalized["children"] = normalized["nodes"]
    return normalized


def _stable_node_id(node: Dict[str, Any], *, doc_id: str) -> str:
    raw = "|".join(
        [
            str(doc_id or ""),
            str(node.get("source") or ""),
            str(node.get("normalized_title") or ""),
            str(node.get("start_index") or ""),
            str(node.get("level") or ""),
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"node_{digest}"


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _clamp_page(value: int, page_count: int) -> int:
    upper = max(1, int(page_count or 1))
    return max(1, min(int(value), upper))
