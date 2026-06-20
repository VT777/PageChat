"""Shared reliability checks for code-extracted TOC signals."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


TRUSTED_SOURCE_PARTS = {"bookmarks", "pdf_outline", "outline", "links"}


def evaluate_code_toc(analysis: Dict[str, Any]) -> Dict[str, Any]:
    code_toc = analysis.get("code_toc") if isinstance(analysis.get("code_toc"), dict) else {}
    source = str(code_toc.get("source") or "").strip()
    items, selected_source = _effective_items_and_source(code_toc)
    page_count = _positive_int(analysis.get("page_count")) or 0
    pages = [_positive_int(item.get("physical_index") or item.get("page")) for item in items]
    pages = [page for page in pages if page is not None]
    source_parts = [part for part in source.split("+") if part]
    selected_source_parts = [part for part in selected_source.split("+") if part]
    section_kinds = [
        str(section.get("kind") or "")
        for section in code_toc.get("toc_sections") or []
        if isinstance(section, dict) and section.get("kind")
    ]
    section_reports = _section_reports(code_toc, page_count=page_count)

    reasons: List[str] = []
    warnings: List[str] = []
    if not items:
        reasons.append("no_items")
    if source and any(part not in TRUSTED_SOURCE_PARTS and part != "regex" for part in source_parts):
        reasons.append("untrusted_source")
    if not source:
        reasons.append("missing_source")

    pages_valid = bool(pages) and all(1 <= page <= page_count for page in pages) if page_count else bool(pages)
    pages_monotonic = all(left <= right for left, right in zip(pages, pages[1:]))
    if not pages_valid:
        reasons.append("invalid_pages")
    if not pages_monotonic:
        reasons.append("non_monotonic_pages")

    title_noise_ratio = _title_noise_ratio(items)
    if title_noise_ratio > 0.20:
        reasons.append("title_noise_high")

    slide_export_ratio = _slide_export_title_ratio(items)
    if slide_export_ratio >= 0.35:
        reasons.append("weak_slide_bookmarks")

    if "regex" in source_parts and not _is_verified_regex(code_toc):
        reasons.append("weak_regex")

    garbled_or_ocr = bool(
        analysis.get("is_garbled_pdf")
        or str(analysis.get("text_layer_quality") or "").lower() == "garbled"
        or str(analysis.get("content_type") or "").lower() == "ocr"
    )
    if "bookmarks" in selected_source_parts and not _bookmark_density_ok(len(items), page_count, garbled_or_ocr=garbled_or_ocr):
        reasons.append("sparse_bookmarks")

    range_coverage = max(pages) / page_count if pages and page_count else 0.0
    if range_coverage < 0.70:
        reasons.append("low_range_coverage")

    for section_report in section_reports:
        kind = section_report["kind"]
        if section_report["title_noise_ratio"] > 0.20:
            reasons.append(f"section_noise_high:{kind}")
        if not section_report["pages_valid"]:
            reasons.append(f"section_invalid_pages:{kind}")
        if not section_report["pages_monotonic"]:
            reasons.append(f"section_non_monotonic_pages:{kind}")

    quality_flags = [str(flag) for flag in code_toc.get("quality_flags") or [] if str(flag).strip()]
    if "weak_slide_export_outline" in quality_flags:
        warnings.append("weak_slide_export_outline")

    has_trusted_source = any(part in TRUSTED_SOURCE_PARTS for part in source_parts)
    has_verified_regex = "regex" in source_parts and _is_verified_regex(code_toc)
    accepted = bool(
        items
        and not reasons
        and source
        and (has_trusted_source or has_verified_regex)
    )
    return {
        "accepted": accepted,
        "effective_source": source,
        "selected_source": selected_source,
        "item_count": len(items),
        "page_count": page_count,
        "pages_valid": pages_valid,
        "pages_monotonic": pages_monotonic,
        "range_coverage": round(range_coverage, 4),
        "title_noise_ratio": round(title_noise_ratio, 4),
        "slide_export_ratio": round(slide_export_ratio, 4),
        "section_kinds": section_kinds,
        "section_reports": section_reports,
        "quality_flags": quality_flags,
        "warnings": warnings,
        "reasons": sorted(set(reasons)),
        "items": items,
    }


def reliable_code_toc_items(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    report = evaluate_code_toc(analysis)
    return list(report.get("items") or []) if report.get("accepted") else []


def _effective_items_and_source(code_toc: Dict[str, Any]) -> tuple[List[Dict[str, Any]], str]:
    sections = code_toc.get("toc_sections") or []
    for section in sections:
        if isinstance(section, dict) and section.get("kind") == "main_toc":
            return (
                [item for item in section.get("items") or [] if isinstance(item, dict)],
                str(section.get("source") or code_toc.get("source") or "").strip(),
            )
    return (
        [item for item in code_toc.get("items") or [] if isinstance(item, dict)],
        str(code_toc.get("source") or "").strip(),
    )


def _section_reports(code_toc: Dict[str, Any], *, page_count: int) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for section in code_toc.get("toc_sections") or []:
        if not isinstance(section, dict):
            continue
        kind = str(section.get("kind") or "unknown")
        items = [item for item in section.get("items") or [] if isinstance(item, dict)]
        pages = [_positive_int(item.get("physical_index") or item.get("page")) for item in items]
        pages = [page for page in pages if page is not None]
        pages_valid = bool(pages) and all(1 <= page <= page_count for page in pages) if page_count else bool(pages)
        pages_monotonic = all(left <= right for left, right in zip(pages, pages[1:]))
        reports.append(
            {
                "kind": kind,
                "source": str(section.get("source") or "").strip(),
                "item_count": len(items),
                "title_noise_ratio": round(_title_noise_ratio(items), 4),
                "pages_valid": pages_valid,
                "pages_monotonic": pages_monotonic,
            }
        )
    return reports


def _bookmark_density_ok(item_count: int, page_count: int, *, garbled_or_ocr: bool) -> bool:
    if garbled_or_ocr:
        return True
    if page_count <= 0:
        return True
    return item_count / page_count >= 0.75 or item_count >= 50


def _title_noise_ratio(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 1.0
    noisy = 0
    for item in items:
        title = str(item.get("title") or "").strip()
        if _is_noisy_title(title):
            noisy += 1
    return noisy / len(items)


def _is_noisy_title(title: str) -> bool:
    if len(title) < 2 or len(title) > 140 or title.isdigit():
        return True
    compact = re.sub(r"\s+", "", title)
    if re.fullmatch(r"\d{4}(?:[./年-]\d{1,2})?(?:月)?", compact):
        return True
    if compact in {"序号", "发布时间", "发布主体", "政策名称", "标准名称", "文件名称"}:
        return True
    if _looks_like_table_cell_organization(compact):
        return True
    return False


def _looks_like_table_cell_organization(value: str) -> bool:
    if len(value) < 6 or len(value) > 40:
        return False
    org_suffixes = (
        "委员会",
        "部",
        "厅",
        "局",
        "院",
        "中心",
        "办公室",
        "标准化技术委员会",
    )
    return value.endswith(org_suffixes) and not re.match(
        r"^(第[一二三四五六七八九十百\d]+|[一二三四五六七八九十]+[、.])",
        value,
    )


def _slide_export_title_ratio(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 0.0
    slide_export = sum(1 for item in items if _is_slide_export_title(item.get("title")))
    return slide_export / len(items)


def _is_slide_export_title(title: Any) -> bool:
    value = str(title or "").strip().lower()
    if not value:
        return False
    return bool(
        value == "default section"
        or value.startswith("slide ")
        or value.startswith("page ")
        or value.startswith("幻灯片")
        or value.startswith("默认节")
    )


def _is_verified_regex(code_toc: Dict[str, Any]) -> bool:
    quality = code_toc.get("quality") or {}
    evidence = code_toc.get("evidence") or {}
    if quality.get("verified") is True or evidence.get("verified") is True:
        return True
    try:
        score = float(quality.get("score", evidence.get("score", 0.0)) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return score >= 0.85 and bool(
        quality.get("title_match_verified")
        or evidence.get("title_match_verified")
        or quality.get("offset_verified")
        or evidence.get("offset_verified")
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
