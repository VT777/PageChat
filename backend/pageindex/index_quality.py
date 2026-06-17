"""Pure deterministic quality helpers for PageIndex outputs and TOC candidates."""

from __future__ import annotations

from collections import Counter
import re
from typing import Any, Dict, List, Optional


def _flatten_index_nodes(nodes: Any, depth: int = 1) -> List[Dict[str, Any]]:
    if not isinstance(nodes, list):
        return []

    flattened: List[Dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        item = dict(node)
        item["_quality_depth"] = depth
        flattened.append(item)
        children = node.get("nodes") or node.get("children") or []
        flattened.extend(_flatten_index_nodes(children, depth + 1))
    return flattened


def _positive_page(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def _node_page_range(node: Dict[str, Any]) -> Optional[tuple[int, int]]:
    anchor = node.get("source_anchor")
    if isinstance(anchor, dict) and anchor.get("unit_type") == "page":
        start = _positive_page(anchor.get("start_page") or anchor.get("page"))
        end = _positive_page(anchor.get("end_page") or anchor.get("page"))
    else:
        start = _positive_page(
            node.get("start_index")
            or node.get("start_page")
            or node.get("page")
            or node.get("physical_index")
        )
        end = _positive_page(
            node.get("end_index")
            or node.get("end_page")
            or node.get("page")
            or node.get("physical_index")
        )

    if start is None or end is None:
        return None
    if end < start:
        return None
    return start, end


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _is_ocr_segment_fallback(index_payload: Dict[str, Any]) -> bool:
    route_decision = index_payload.get("route_decision")
    if not isinstance(route_decision, dict):
        route_decision = {}

    toc_source = (
        route_decision.get("toc_source")
        or route_decision.get("source")
        or index_payload.get("toc_source")
    )
    if str(toc_source or "").strip().lower() != "segment_fallback":
        return False

    pipeline_path = str(
        route_decision.get("pipeline_path")
        or index_payload.get("pipeline_path")
        or ""
    ).strip().lower()
    return (
        _truthy(index_payload.get("ocr_used"))
        or _truthy(route_decision.get("ocr_used"))
        or _truthy(route_decision.get("is_image_only_pdf"))
        or "ocr" in pipeline_path
    )


def _is_flat_or_full_span_fallback(
    nodes: List[Dict[str, Any]],
    *,
    max_depth: int,
    page_total: int,
) -> bool:
    if len(nodes) <= 2:
        return True
    if max_depth > 2 or page_total <= 0:
        return False

    full_span_nodes = 0
    for node in nodes:
        page_range = _node_page_range(node)
        if page_range is None:
            continue
        start, end = page_range
        if start <= 1 and end >= page_total:
            full_span_nodes += 1

    return full_span_nodes >= max(1, len(nodes) // 2)


def _toc_content_mapping_failed(index_payload: Dict[str, Any]) -> bool:
    mapping = _resolve_effective_mapping_report(index_payload)
    return isinstance(mapping, dict) and str(mapping.get("status") or "").strip().lower().startswith("failed")


def _bounded_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _ratio_from_counts(numerator: Any, denominator: Any) -> float:
    try:
        numerator_value = float(numerator)
        denominator_value = float(denominator)
    except (TypeError, ValueError):
        return 0.0
    if denominator_value <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator_value / denominator_value))


def _resolve_effective_mapping_report(index_payload: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = index_payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    payload_judge = index_payload.get("toc_judge")
    if not isinstance(payload_judge, dict):
        payload_judge = {}
    diagnostics_judge = diagnostics.get("toc_judge")
    if not isinstance(diagnostics_judge, dict):
        diagnostics_judge = {}
    toc_judge = diagnostics_judge or payload_judge
    evidence = toc_judge.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}

    for candidate in (
        diagnostics.get("toc_content_mapping"),
        index_payload.get("toc_content_mapping"),
        toc_judge.get("content_mapping"),
        evidence.get("content_mapping"),
    ):
        if isinstance(candidate, dict) and candidate:
            return _normalize_mapping_report(candidate, evidence=evidence)

    if evidence:
        return _mapping_report_from_evidence(evidence)
    return {}


def _mapping_report_from_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    report = dict(evidence)
    status = str(report.get("status") or "").strip().lower()
    has_explicit_physical = _truthy(report.get("has_explicit_physical"))
    mapping_pending = _truthy(report.get("mapping_pending"))
    page_score_present = "page_mapping_score" in report and report.get("page_mapping_score") is not None
    title_match_present = "title_match_rate" in report and report.get("title_match_rate") is not None
    page_score = _bounded_float(report.get("page_mapping_score"))
    title_match = _bounded_float(report.get("title_match_rate"))
    mapped_ratio = _bounded_float(report.get("mapped_ratio"))
    verified_ratio = _ratio_from_counts(report.get("verified_item_count"), report.get("total_item_count"))
    explicit_ratio = max(mapped_ratio, verified_ratio)

    if not page_score_present:
        page_score = max(page_score, explicit_ratio)
    if not title_match_present:
        if explicit_ratio > 0.0 or has_explicit_physical:
            title_match = max(title_match, explicit_ratio)
            if title_match <= 0.0 and page_score > 0.0:
                title_match = page_score

    if not status:
        if mapping_pending:
            status = "pending"
        elif explicit_ratio > 0.0:
            status = "ok"
        elif has_explicit_physical and (page_score > 0.0 or title_match > 0.0):
            status = "ok"
        else:
            status = "unknown"

    report["status"] = status or "unknown"
    report["page_mapping_score"] = round(page_score, 4)
    report["title_match_rate"] = round(title_match, 4)
    return report


def _normalize_mapping_report(
    mapping: Dict[str, Any],
    *,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    report = dict(mapping)
    status = str(report.get("status") or "").strip().lower()
    if status.startswith("failed"):
        report["status"] = status
        report["page_mapping_score"] = round(_bounded_float(report.get("page_mapping_score")), 4)
        report["title_match_rate"] = round(_bounded_float(report.get("title_match_rate")), 4)
        return report

    evidence = evidence if isinstance(evidence, dict) else {}
    page_score_present = "page_mapping_score" in report and report.get("page_mapping_score") is not None
    title_match_present = "title_match_rate" in report and report.get("title_match_rate") is not None
    mapped_ratio = _bounded_float(report.get("mapped_ratio"))
    verified_ratio = _ratio_from_counts(report.get("verified_item_count"), report.get("total_item_count"))
    explicit_ratio = max(mapped_ratio, verified_ratio)
    page_score = _bounded_float(report.get("page_mapping_score"))
    title_match = _bounded_float(report.get("title_match_rate"))
    has_explicit_physical = _truthy(report.get("has_explicit_physical")) or _truthy(evidence.get("has_explicit_physical"))

    if not page_score_present:
        page_score = max(
            page_score,
            title_match,
            explicit_ratio,
            _bounded_float(evidence.get("page_mapping_score")),
            max(
                _bounded_float(evidence.get("mapped_ratio")),
                _ratio_from_counts(evidence.get("verified_item_count"), evidence.get("total_item_count")),
            ),
        )
    if not title_match_present:
        if explicit_ratio > 0.0 or has_explicit_physical:
            title_match = max(
                title_match,
                explicit_ratio,
                _bounded_float(evidence.get("title_match_rate")),
                _bounded_float(evidence.get("mapped_ratio")),
                _ratio_from_counts(evidence.get("verified_item_count"), evidence.get("total_item_count")),
            )
            if title_match <= 0.0 and page_score > 0.0:
                title_match = page_score
    if not status:
        mapping_pending = _truthy(report.get("mapping_pending")) or _truthy(evidence.get("mapping_pending"))
        if mapping_pending:
            status = "pending"
        elif explicit_ratio > 0.0:
            status = "ok"
        elif has_explicit_physical and (page_score > 0.0 or title_match > 0.0):
            status = "ok"
        else:
            status = "unknown"

    report["status"] = status or "unknown"
    report["page_mapping_score"] = round(page_score, 4)
    report["title_match_rate"] = round(title_match, 4)
    return report

def _normalize_title_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _is_synthetic_root_title(title: Any) -> bool:
    normalized = _normalize_title_key(title)
    return normalized in {"目录", "contents", "tableofcontents", "preface"}




def _is_synthetic_placeholder_title(title: Any) -> bool:
    normalized = _normalize_title_key(title)
    return _is_synthetic_root_title(title) or normalized in {
        "documentcontent",
        "fulltext",
        "body",
        "正文",
    }


def _candidate_count(candidate: Dict[str, Any]) -> int:
    for key in ("items", "item_count", "title_count", "evidence_title_count"):
        value = candidate.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, str) and value.strip().isdigit():
            return max(0, int(value.strip()))
    return 0


def _candidate_sample_titles(candidate: Dict[str, Any]) -> List[str]:
    values: List[Any] = []
    for key in ("sample_titles", "titles"):
        value = candidate.get(key)
        if isinstance(value, list):
            values.extend(value)
    items = candidate.get("items")
    if isinstance(items, list):
        for item in items[:50]:
            if isinstance(item, dict):
                values.append(item.get("title"))
    titles = []
    seen = set()
    for value in values:
        title = str(value or "").strip()
        key = _normalize_title_key(title)
        if not title or not key or key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles[:50]


def _evidence_title_stats(index_payload: Dict[str, Any], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    diagnostics = index_payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    summaries = diagnostics.get("toc_candidates_summary") or index_payload.get("toc_candidates_summary") or []
    if not isinstance(summaries, list):
        summaries = []

    best_count = 0
    best_source = ""
    best_titles: List[str] = []
    for candidate in summaries:
        if not isinstance(candidate, dict):
            continue
        source = str(candidate.get("source") or "").strip()
        if source == "segment_fallback":
            continue
        count = _candidate_count(candidate)
        titles = _candidate_sample_titles(candidate)
        count = max(count, len(titles))
        if count > best_count:
            best_count = count
            best_source = source
            best_titles = titles

    final_title_keys = []
    for node in nodes:
        title = str(node.get("title") or "").strip()
        if not title or _is_synthetic_placeholder_title(title):
            continue
        final_title_keys.append(_normalize_title_key(title))
    final_title_keys = [key for key in final_title_keys if key]
    final_title_count = len(set(final_title_keys))

    if best_titles:
        final_key_set = set(final_title_keys)
        sample_keys = [_normalize_title_key(title) for title in best_titles]
        sample_keys = [key for key in sample_keys if key]
        preserved = sum(1 for key in sample_keys if key in final_key_set)
        preservation_rate = preserved / len(sample_keys) if sample_keys else 0.0
    elif best_count:
        preservation_rate = min(1.0, final_title_count / best_count)
    else:
        preservation_rate = 1.0

    return {
        "evidence_title_count": best_count,
        "evidence_source": best_source,
        "final_tree_title_count": final_title_count,
        "title_preservation_rate": round(preservation_rate, 4),
    }
def _visible_top_level_nodes(structure: Any) -> List[Dict[str, Any]]:
    if not isinstance(structure, list):
        return []

    roots = [dict(node) for node in structure if isinstance(node, dict)]
    if len(roots) != 1:
        return roots

    root = roots[0]
    children = root.get("nodes") or root.get("children") or []
    if _is_synthetic_root_title(root.get("title")) and isinstance(children, list):
        return [dict(node) for node in children if isinstance(node, dict)]
    return roots


def _has_children(node: Dict[str, Any]) -> bool:
    return bool(node.get("nodes") or node.get("children"))


def _detect_toc_style(nodes: List[Dict[str, Any]]) -> str:
    top_level_count = len(nodes)
    child_count = sum(1 for node in nodes if _has_children(node))
    if top_level_count <= 1:
        return "collapsed" if child_count == 0 else "hierarchical"
    if child_count == 0:
        return "flat"
    if child_count == top_level_count:
        return "hierarchical"
    return "mixed"


def _tail_collapse(mapped_pages: List[int], item_count: int) -> bool:
    if item_count < 5 or not mapped_pages:
        return False
    last_page = max(mapped_pages)
    if last_page <= 0:
        return False
    count = sum(1 for page in mapped_pages if page == last_page)
    return count / item_count > 0.3 and count >= 3


def _leading_numeric_label(value: Any) -> Optional[int]:
    match = re.match(r"^\s*(\d{1,3})(?:[.)\s\u3001\uff0e-]+|$)", str(value or ""))
    if not match:
        return None
    return _positive_page(match.group(1))


def _numeric_labels_from_nodes(nodes: List[Dict[str, Any]]) -> List[int]:
    labels: List[int] = []
    for node in nodes:
        label = _leading_numeric_label(node.get("title"))
        if label is not None:
            labels.append(label)
    return labels


def _raw_toc_numeric_label_loss(index_payload: Dict[str, Any], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    diagnostics = index_payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {"checked": False}
    llm_toc = diagnostics.get("llm_toc_page")
    if not isinstance(llm_toc, dict) or str(llm_toc.get("status") or "") != "ok":
        return {"checked": False}

    raw_values = llm_toc.get("raw_numeric_labels") or llm_toc.get("extracted_numeric_labels") or []
    raw_labels = sorted({label for label in (_positive_page(value) for value in raw_values) if label is not None})
    if len(raw_labels) < 5:
        return {"checked": False, "raw_label_count": len(raw_labels)}

    expected = set(range(raw_labels[0], raw_labels[-1] + 1))
    is_contiguous = len(expected.difference(raw_labels)) == 0
    if not is_contiguous:
        return {"checked": False, "raw_label_count": len(raw_labels), "raw_contiguous": False}

    final_labels = set(_numeric_labels_from_nodes(nodes))
    missing = sorted(expected.difference(final_labels))
    missing_rate = len(missing) / len(expected) if expected else 0.0
    return {
        "checked": True,
        "raw_label_count": len(expected),
        "final_label_count": len(final_labels.intersection(expected)),
        "missing_count": len(missing),
        "missing_rate": round(missing_rate, 4),
        "missing_sample": missing[:20],
        "failed": missing_rate > 0.15,
    }


def _raw_toc_hierarchy_flattened(index_payload: Dict[str, Any], nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    diagnostics = index_payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return {"checked": False}
    llm_toc = diagnostics.get("llm_toc_page")
    if not isinstance(llm_toc, dict) or str(llm_toc.get("status") or "") != "ok":
        return {"checked": False}

    level_distribution = llm_toc.get("level_distribution") or {}
    raw_max_level = llm_toc.get("max_level")
    if not isinstance(raw_max_level, int) or raw_max_level < 2:
        try:
            raw_max_level = max(int(key) for key in level_distribution.keys())
        except Exception:
            raw_max_level = 1

    if raw_max_level < 2:
        return {"checked": False, "raw_max_level": raw_max_level}

    final_depth = max(int(node.get("_quality_depth") or 1) for node in nodes)
    top_level_items = [node for node in nodes if int(node.get("_quality_depth") or 1) == 1]
    final_hierarchical = any(
        isinstance(node.get("nodes"), list) and node.get("nodes")
        for node in top_level_items
    ) or final_depth > 1

    final_top_level_count = len(_visible_top_level_nodes(index_payload.get("structure", [])))
    raw_top_level_count = 0
    try:
        raw_top_level_count = int(level_distribution.get("1") or level_distribution.get(1) or 0)
    except Exception:
        raw_top_level_count = 0

    raw_lower_level_count = 0
    try:
        raw_lower_level_count = sum(
            int(count)
            for level, count in level_distribution.items()
            if int(level) > 1
        )
    except Exception:
        raw_lower_level_count = 0

    flattened = bool(
        raw_max_level >= 2
        and raw_lower_level_count >= 1
        and final_depth <= 1
        and (
            final_top_level_count <= 1
            or (raw_top_level_count > 0 and final_top_level_count > raw_top_level_count)
        )
    )
    return {
        "checked": True,
        "raw_max_level": raw_max_level,
        "raw_top_level_count": raw_top_level_count,
        "raw_lower_level_count": raw_lower_level_count,
        "final_top_level_count": final_top_level_count,
        "final_depth": final_depth,
        "flattened": flattened,
    }


def build_toc_fidelity_digest(
    index_payload: Dict[str, Any],
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a compact deterministic digest for TOC fidelity auditing."""
    structure = (
        index_payload.get("structure", [])
        if isinstance(index_payload, dict)
        else []
    )
    if isinstance(structure, dict):
        structure = structure.get("structure", [])

    nodes = _flatten_index_nodes(structure)
    node_count = len(nodes)
    page_total = int(page_count or index_payload.get("page_count") or 0)
    diagnostics = index_payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    route_decision = index_payload.get("route_decision")
    if not isinstance(route_decision, dict):
        route_decision = {}

    if node_count == 0:
        return {
            "status": "failed:indexing",
            "score": 0.0,
            "node_count": 0,
            "top_level_count": 0,
            "child_count": 0,
            "leaf_count": 0,
            "max_depth": 0,
            "detected_style": "collapsed",
            "style_fit": "poor",
            "page_range_coverage": 0.0,
            "duplicate_title_ratio": 0.0,
            "empty_summary_ratio": 0.0,
            "unmapped_pages": list(range(1, page_total + 1)),
            "anchor_confidence": 0.0,
            "warnings": ["empty structure"],
            "hard_fail_reasons": ["empty_structure"],
            "toc_source": str(route_decision.get("toc_source") or index_payload.get("toc_source") or ""),
        }

    root_nodes = _visible_top_level_nodes(structure)
    top_level_count = len(root_nodes)
    child_count = sum(1 for node in root_nodes if _has_children(node))
    leaf_count = max(0, top_level_count - child_count)
    max_depth = max(int(node.get("_quality_depth") or 1) for node in nodes)
    titles = [
        str(node.get("title") or "").strip().lower()
        for node in nodes
        if str(node.get("title") or "").strip()
    ]
    title_counts = Counter(titles)
    duplicate_title_count = sum(count - 1 for count in title_counts.values() if count > 1)
    duplicate_title_ratio = duplicate_title_count / node_count

    empty_summary_count = sum(
        1 for node in nodes if not str(node.get("summary") or "").strip()
    )
    empty_summary_ratio = empty_summary_count / node_count

    covered_pages = set()
    valid_anchor_count = 0
    for node in nodes:
        page_range = _node_page_range(node)
        if page_range is None:
            continue
        valid_anchor_count += 1
        start, end = page_range
        if page_total > 0:
            start = max(1, min(start, page_total))
            end = max(1, min(end, page_total))
        covered_pages.update(range(start, end + 1))

    if page_total > 0:
        page_range_coverage = len(covered_pages) / page_total
        unmapped_pages = [
            page for page in range(1, page_total + 1) if page not in covered_pages
        ]
    else:
        page_range_coverage = 1.0 if covered_pages else 0.0
        unmapped_pages = []

    anchor_confidence = valid_anchor_count / node_count
    detected_style = _detect_toc_style(root_nodes)
    evidence_stats = _evidence_title_stats(index_payload, nodes)
    raw_label_loss = _raw_toc_numeric_label_loss(index_payload, nodes)
    hierarchy_flattened = _raw_toc_hierarchy_flattened(index_payload, nodes)

    mapping = _resolve_effective_mapping_report(index_payload)
    if not isinstance(mapping, dict):
        mapping = {}
    mapping_status = str(mapping.get("status") or "").strip().lower()
    mapping_score = _bounded_float(mapping.get("page_mapping_score"))
    title_match_rate = _bounded_float(mapping.get("title_match_rate"))
    mapping_tail_collapse = bool(mapping.get("tail_collapse"))
    mapping_reasons = [str(reason) for reason in (mapping.get("reasons") or []) if str(reason).strip()]

    warnings: List[str] = []
    hard_fail_reasons: List[str] = []

    if page_range_coverage < 0.7:
        warnings.append("page range coverage below threshold")
    if duplicate_title_ratio > 0.35:
        warnings.append("duplicate title ratio above threshold")
    if empty_summary_ratio > 0.5:
        warnings.append("empty summary ratio above threshold")
    if anchor_confidence < 0.7:
        warnings.append("anchor confidence below threshold")
    if detected_style == "collapsed":
        warnings.append("collapsed TOC structure")

    evidence_title_count = int(evidence_stats.get("evidence_title_count") or 0)
    final_tree_title_count = int(evidence_stats.get("final_tree_title_count") or 0)
    title_preservation_rate = _bounded_float(evidence_stats.get("title_preservation_rate"))
    if evidence_title_count >= 5 and (
        (detected_style == "collapsed" and final_tree_title_count <= 1)
        or title_preservation_rate < 0.35
    ):
        warnings.append("evidence-backed TOC titles lost in final tree")
        hard_fail_reasons.append("evidence_titles_lost_in_final_tree")

    if mapping_status.startswith("failed"):
        warnings.append("toc content mapping failed")
        hard_fail_reasons.append("toc_content_mapping_failed")
    if mapping_tail_collapse:
        warnings.append("tail collapse detected")
        hard_fail_reasons.append("tail_collapse")

    if raw_label_loss.get("failed"):
        warnings.append("raw TOC numeric labels missing in final tree")
        hard_fail_reasons.append("raw_toc_numeric_labels_missing_in_final_tree")

    if hierarchy_flattened.get("flattened"):
        warnings.append("raw TOC hierarchy flattened in final tree")
        hard_fail_reasons.append("raw_toc_hierarchy_flattened")

    is_segment_fallback = _is_ocr_segment_fallback(index_payload)
    if is_segment_fallback and detected_style == "collapsed":
        warnings.append("segment_fallback used for OCR/image document with flat full-document structure")
        hard_fail_reasons.append("collapsed_single_entry")
    if is_segment_fallback and detected_style == "collapsed" and page_range_coverage >= 0.9:
        hard_fail_reasons.append("segment_fallback_flat_full_document")

    if page_range_coverage < 0.35 and is_segment_fallback:
        hard_fail_reasons.append("segment_fallback_low_coverage")
    if mapping_reasons and "tail_collapse" in mapping_reasons and is_segment_fallback:
        hard_fail_reasons.append("mapping_tail_collapse")

    if hard_fail_reasons:
        style_fit = "poor"
    elif detected_style == "flat" and page_range_coverage >= 0.7 and anchor_confidence >= 0.7:
        style_fit = "acceptable"
    elif warnings:
        style_fit = "warning"
    else:
        style_fit = "acceptable"

    status = (
        "failed:toc_quality"
        if hard_fail_reasons
        else ("needs_review" if warnings else "completed")
    )

    score = (
        page_range_coverage * 0.4
        + (1.0 - min(duplicate_title_ratio, 1.0)) * 0.2
        + (1.0 - min(empty_summary_ratio, 1.0)) * 0.2
        + anchor_confidence * 0.2
    )
    if status.startswith("failed"):
        score = min(score, 0.49)

    return {
        "status": status,
        "score": round(score, 4),
        "node_count": node_count,
        "top_level_count": top_level_count,
        "child_count": child_count,
        "leaf_count": leaf_count,
        "max_depth": max_depth,
        "detected_style": detected_style,
        "style_fit": style_fit,
        "page_range_coverage": round(page_range_coverage, 4),
        "duplicate_title_ratio": round(duplicate_title_ratio, 4),
        "empty_summary_ratio": round(empty_summary_ratio, 4),
        "unmapped_pages": unmapped_pages,
        "anchor_confidence": round(anchor_confidence, 4),
        "page_mapping_score": round(mapping_score, 4),
        "title_match_rate": round(title_match_rate, 4),
        "mapping_status": mapping_status or "unknown",
        "mapping_tail_collapse": mapping_tail_collapse,
        "warnings": warnings,
        "hard_fail_reasons": sorted(set(hard_fail_reasons)),
        "evidence_title_count": int(evidence_stats.get("evidence_title_count") or 0),
        "final_tree_title_count": int(evidence_stats.get("final_tree_title_count") or 0),
        "title_preservation_rate": round(_bounded_float(evidence_stats.get("title_preservation_rate")), 4),
        "raw_toc_numeric_label_loss": raw_label_loss,
        "raw_toc_hierarchy_flattened": hierarchy_flattened,
        "toc_source": str(route_decision.get("toc_source") or index_payload.get("toc_source") or ""),
    }


def build_index_quality_report(
    index_payload: Dict[str, Any],
    page_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a deterministic, conservative quality report for an index payload."""
    return build_toc_fidelity_digest(index_payload, page_count=page_count)
class TocQualityChecker:
    """Validate whether an extracted TOC is good enough to preserve."""

    PAGE_FIELDS = ("start_index", "page", "logical_page", "physical_index")
    SYNTHETIC_ROOT_TITLES = {
        "目录",
        "目 录",
        "contents",
        "table of contents",
        "preface",
    }

    @staticmethod
    def _positive_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                parsed = int(stripped)
                return parsed if parsed > 0 else None
        return None

    def _page_stats(self, toc_items: List[Dict]) -> Dict[str, Any]:
        best_field = None
        best_pages: List[int] = []

        for field in self.PAGE_FIELDS:
            pages = []
            for item in toc_items:
                parsed = self._positive_int(item.get(field))
                if parsed is not None:
                    pages.append(parsed)
            if len(pages) > len(best_pages):
                best_field = field
                best_pages = pages

        monotonic = all(
            best_pages[i] <= best_pages[i + 1]
            for i in range(len(best_pages) - 1)
        )
        unique_ratio = len(set(best_pages)) / len(best_pages) if best_pages else 0.0
        diffs = [
            best_pages[i + 1] - best_pages[i]
            for i in range(len(best_pages) - 1)
            if best_pages[i + 1] >= best_pages[i]
        ]
        common_step = Counter(diffs).most_common(1)[0][0] if diffs else None

        return {
            "valid_page_field": best_field,
            "valid_page_count": len(best_pages),
            "page_monotonic": monotonic,
            "page_unique_ratio": unique_ratio,
            "common_page_step": common_step,
        }

    @staticmethod
    def _page_mapping_valid(
        *,
        item_count: int,
        valid_pages: int,
        page_monotonic: bool,
        unique_ratio: float,
        common_step: Optional[int],
    ) -> bool:
        if item_count <= 0 or valid_pages <= 0:
            return False

        enough_pages = valid_pages >= max(2, item_count * 0.5)
        if not enough_pages or not page_monotonic:
            return False

        if valid_pages == 1:
            return item_count == 1

        if unique_ratio < 0.5:
            return False

        if common_step == 0:
            return False

        return True

    @classmethod
    def _is_synthetic_root(cls, item: Dict) -> bool:
        title = str(item.get("title", "")).strip().lower()
        return title in cls.SYNTHETIC_ROOT_TITLES

    def _has_page_value(self, item: Dict) -> bool:
        return any(self._positive_int(item.get(field)) is not None for field in self.PAGE_FIELDS)

    def _infer_structural_synthetic_root(
        self,
        real_items: List[Dict],
        levels: List[int],
    ) -> Optional[Dict[str, Any]]:
        """Detect a single wrapper title above the actual TOC groups."""
        if not levels:
            return None

        min_level = min(levels)
        top_items = [
            item for item in real_items
            if item.get("level", min_level) == min_level
        ]
        if len(top_items) != 1:
            return None

        child_level = min((level for level in levels if level > min_level), default=None)
        if child_level is None:
            return None

        child_items = [
            item for item in real_items
            if item.get("level", min_level) == child_level
        ]
        paged_descendants = [
            item for item in real_items
            if item.get("level", min_level) > child_level and self._has_page_value(item)
        ]

        root = top_items[0]
        root_has_page = self._has_page_value(root)
        if len(child_items) >= 2 and paged_descendants and not root_has_page:
            return {
                "items": child_items,
                "detected": True,
                "reason": (
                    "single unpaged top-level wrapper with "
                    f"{len(child_items)} child groups"
                ),
            }
        return None

    def _effective_top_level_info(self, toc_items: List[Dict]) -> Dict[str, Any]:
        """Count real top-level groups after ignoring synthetic TOC roots."""
        real_items = [
            item for item in toc_items
            if str(item.get("title", "")).strip()
            and not self._is_synthetic_root(item)
        ]
        if not real_items:
            return {
                "items": [],
                "synthetic_root_detected": False,
                "synthetic_root_reason": "",
                "raw_min_level_count": 0,
                "level_distribution": {},
            }

        levels = [
            item.get("level", 1)
            for item in real_items
            if isinstance(item.get("level", 1), int)
            and not isinstance(item.get("level", 1), bool)
        ]
        if not levels:
            return {
                "items": real_items,
                "synthetic_root_detected": False,
                "synthetic_root_reason": "no numeric levels",
                "raw_min_level_count": len(real_items),
                "level_distribution": {},
            }

        min_level = min(levels)
        raw_top_level = [
            item for item in real_items
            if item.get("level", min_level) == min_level
        ]
        level_distribution = dict(Counter(levels))

        inferred = self._infer_structural_synthetic_root(real_items, levels)
        if inferred:
            return {
                "items": inferred["items"],
                "synthetic_root_detected": True,
                "synthetic_root_reason": inferred["reason"],
                "raw_min_level_count": len(raw_top_level),
                "level_distribution": level_distribution,
            }

        explicit_root_count = len(toc_items) - len(real_items)
        return {
            "items": raw_top_level,
            "synthetic_root_detected": explicit_root_count > 0,
            "synthetic_root_reason": (
                "explicit synthetic root title" if explicit_root_count > 0 else ""
            ),
            "raw_min_level_count": len(raw_top_level),
            "level_distribution": level_distribution,
        }

    def _effective_top_level(self, toc_items: List[Dict]) -> List[Dict]:
        return self._effective_top_level_info(toc_items)["items"]

    def check(self, toc_items: List[Dict], toc_pages: List[int]) -> Dict[str, Any]:
        if not toc_items:
            return {
                "is_valid": False,
                "skeleton_valid": False,
                "page_mapping_valid": False,
                "hierarchy_valid": False,
                "decision": "REJECT",
                "has_hierarchy": False,
                "top_level_count": 0,
                "item_count": 0,
                "valid_page_field": None,
                "valid_page_count": 0,
                "page_monotonic": False,
                "page_unique_ratio": 0.0,
                "common_page_step": None,
                "reason": "no TOC items",
            }

        top_level_info = self._effective_top_level_info(toc_items)
        top_level = top_level_info["items"]
        has_hierarchy = any(item.get("level", 1) > 1 for item in toc_items)
        page_stats = self._page_stats(toc_items)
        valid_pages = page_stats["valid_page_count"]
        non_empty_titles = sum(
            1 for item in toc_items
            if str(item.get("title", "")).strip()
        )
        title_ratio = non_empty_titles / len(toc_items)

        skeleton_valid = (
            len(top_level) >= 2
            and title_ratio >= 0.8
        )
        hierarchy_valid = has_hierarchy
        page_mapping_valid = self._page_mapping_valid(
            item_count=len(toc_items),
            valid_pages=valid_pages,
            page_monotonic=page_stats["page_monotonic"],
            unique_ratio=page_stats["page_unique_ratio"],
            common_step=page_stats["common_page_step"],
        )
        if skeleton_valid and page_mapping_valid:
            decision = "USE_DIRECT"
        elif skeleton_valid:
            decision = "USE_SKELETON_MAP_LATER"
        else:
            decision = "REJECT"

        is_valid = skeleton_valid and page_mapping_valid

        result = {
            "is_valid": is_valid,
            "skeleton_valid": skeleton_valid,
            "page_mapping_valid": page_mapping_valid,
            "hierarchy_valid": hierarchy_valid,
            "decision": decision,
            "has_hierarchy": has_hierarchy,
            "top_level_count": len(top_level),
            "item_count": len(toc_items),
            "title_ratio": title_ratio,
            "reason": f"{len(top_level)} top-level items, {'has' if has_hierarchy else 'no'} hierarchy",
        }
        result.update(page_stats)
        result.update({
            "synthetic_root_detected": top_level_info["synthetic_root_detected"],
            "synthetic_root_reason": top_level_info["synthetic_root_reason"],
            "raw_min_level_count": top_level_info["raw_min_level_count"],
            "level_distribution": top_level_info["level_distribution"],
        })
        return result
