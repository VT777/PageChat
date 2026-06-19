"""Low-cost TOC page detection for the new layout-first pipeline.

This module intentionally does not call image-model detection. Image-only,
garbled, and low-text-quality documents are routed to the PP-OCR layout path by
``pageindex.router``; this detector only reuses already available text/analysis
signals.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

MAX_SCAN_PAGES = 20
SECTION_KINDS = {"main_toc", "figure_toc", "table_toc", "other_toc"}


def _positive_pages(values: Any) -> List[int]:
    pages: List[int] = []
    for value in values or []:
        try:
            page = int(value)
        except Exception:
            continue
        if page > 0:
            pages.append(page)
    return pages


def detect_toc_pages_text_report(
    page_texts: List[str],
    max_scan_pages: int = MAX_SCAN_PAGES,
) -> Dict[str, Any]:
    """Detect TOC pages from extracted text and preserve route-critical facts."""
    empty_report = {
        "source": "text_detector",
        "status": "not_found",
        "pages": [],
        "has_page_numbers": False,
        "sections": [],
        "candidates": [],
        "reason": "no_text_toc_pages",
        "classification_complete": True,
    }
    if not page_texts:
        return empty_report

    candidates = _scan_text_toc_candidates(page_texts, max_scan_pages=max_scan_pages)
    pages = _select_detected_toc_page_run(candidates)
    if pages:
        has_page_numbers = _pages_have_trailing_page_numbers(page_texts, pages)
        return {
            "source": "text_detector",
            "status": "detected",
            "pages": pages,
            "has_page_numbers": has_page_numbers,
            "sections": aggregate_toc_sections(candidates, pages=pages),
            "candidates": candidates,
            "reason": "detected_by_text_toc_detector",
            "classification_complete": True,
        }

    unpaged = _detect_unpaged_toc_pages(page_texts, max_scan_pages=max_scan_pages)
    if unpaged:
        has_page_numbers = _pages_have_trailing_page_numbers(page_texts, unpaged)
        selected_candidates = [
            _confirmed_unpaged_toc_candidate(
                _classify_text_toc_page(
                    page_texts[page - 1] if 0 <= page - 1 < len(page_texts) else "",
                    page=page,
                )
            )
            for page in unpaged
        ]
        return {
            "source": "text_detector",
            "status": "detected",
            "pages": unpaged,
            "has_page_numbers": has_page_numbers,
            "sections": aggregate_toc_sections(selected_candidates, pages=unpaged),
            "candidates": selected_candidates,
            "reason": "detected_unpaged_toc_by_text_signals",
            "classification_complete": True,
        }
    return empty_report


def detect_toc_pages_text(
    page_texts: List[str],
    max_scan_pages: int = MAX_SCAN_PAGES,
) -> Optional[List[int]]:
    """Detect TOC pages from extracted text only."""
    report = detect_toc_pages_text_report(page_texts, max_scan_pages)
    if report.get("status") == "detected":
        return list(report.get("pages") or [])
    return None


async def find_toc_pages(
    analysis: Dict[str, Any],
    file_path: str,
    model: Optional[str] = None,
) -> Optional[List[int]]:
    """Return detected TOC pages without invoking visual fallback."""
    direct_pages = _positive_pages(analysis.get("toc_pages"))
    if direct_pages:
        _store_toc_page_report(
            analysis,
            pages=direct_pages,
            has_page_numbers=_pages_have_trailing_page_numbers(
                analysis.get("page_texts") or [],
                direct_pages,
            ),
            reason="direct_toc_pages",
        )
        print(f"[TOC-PROBE] Using analysis toc_pages={direct_pages}")
        return direct_pages

    toc_page = analysis.get("toc_page") or {}
    nested_pages = _positive_pages(toc_page.get("pages"))
    if nested_pages:
        _store_toc_page_report(
            analysis,
            pages=nested_pages,
            has_page_numbers=_pages_have_trailing_page_numbers(
                analysis.get("page_texts") or [],
                nested_pages,
            ),
            reason="direct_toc_page_pages",
        )
        print(f"[TOC-PROBE] Using analysis toc_page.pages={nested_pages}")
        return nested_pages

    page_texts = analysis.get("page_texts") or []
    legacy_indices: List[int] = []
    for value in toc_page.get("page_indices") or []:
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            legacy_indices.append(index + 1)
    if legacy_indices:
        _store_toc_page_report(
            analysis,
            pages=sorted(set(legacy_indices)),
            has_page_numbers=_pages_have_trailing_page_numbers(
                page_texts,
                sorted(set(legacy_indices)),
            ),
            reason="legacy_toc_page_indices",
        )
        print(f"[TOC-PROBE] Using analysis toc_page.page_indices={legacy_indices}")
        return sorted(set(legacy_indices))

    text_pages = detect_toc_pages_text(page_texts)
    if text_pages:
        report = detect_toc_pages_text_report(page_texts)
        if report.get("status") != "detected" or list(report.get("pages") or []) != list(text_pages):
            report = _build_toc_page_report(
                pages=text_pages,
                has_page_numbers=_pages_have_trailing_page_numbers(page_texts, text_pages),
                reason="detected_by_text_toc_detector",
            )
        analysis["toc_page_detection"] = report
        analysis["toc_pages"] = list(text_pages)
        analysis["toc_page"] = {
            "has_toc_page": True,
            "pages": list(text_pages),
            "confidence": "detected",
        }
        page_type = "with_pages" if report.get("has_page_numbers") else "no_pages"
        print(f"[TOC-PROBE] Text detection found toc_pages={text_pages} type={page_type}")
        return text_pages

    print("[TOC-PROBE] No text TOC pages found; OCR/layout path owns image detection")
    return None


_TRAILING_PAGE_PATTERN = re.compile(r"(?:\.{2,}|…{1,}|[\s·]{3,})\s*\d{1,4}\s*$")
_PAGED_CATALOG_LINE_PATTERN = re.compile(
    r"^(?=.{3,180}$).+?(?:\.{2,}|…{1,}|[·•]{2,}|\s{2,})\s*\d{1,4}\s*$"
)
_FIGURE_LINE_PATTERN = re.compile(r"^(?:图|fig(?:ure)?\.?)\s*[\d一二三四五六七八九十ivxIVX.-]*\s*\S+", re.IGNORECASE)
_TABLE_LINE_PATTERN = re.compile(r"^(?:表|tab(?:le)?\.?)\s*[\d一二三四五六七八九十ivxIVX.-]*\s*\S+", re.IGNORECASE)
_CHAPTER_MARKER_PATTERN = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零〇两\d]+[章节部分篇]"
    r"|[一二三四五六七八九十]+[、.]"
    r"|(?:part|chapter)\s*\d+"
    r"|\d+(?:\.\d+){0,2}"
    r")",
    re.IGNORECASE,
)
_TOC_HEADING_PATTERN = re.compile(
    r"^(?:目录|目次|contents|table of contents|汇报提纲|提纲|agenda|outline)$",
    re.IGNORECASE,
)
_FIGURE_TOC_HEADING_PATTERN = re.compile(
    r"^(?:图目录|插图目录|图表目录|list of figures|figures|figure catalog)$",
    re.IGNORECASE,
)
_TABLE_TOC_HEADING_PATTERN = re.compile(
    r"^(?:表目录|表格目录|list of tables|tables|table catalog)$",
    re.IGNORECASE,
)


def _scan_text_toc_candidates(
    page_texts: List[str],
    *,
    max_scan_pages: int,
) -> List[Dict[str, Any]]:
    scan_limit = min(max_scan_pages, len(page_texts))
    return [
        _classify_text_toc_page(page_texts[index], page=index + 1)
        for index in range(scan_limit)
    ]


def _classify_text_toc_page(text: str, *, page: int) -> Dict[str, Any]:
    lines = [_normalize_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    heading_kinds = _heading_section_kinds(lines[:10])
    paged_count = _count_paged_catalog_like_lines(lines)
    unpaged_count = _count_unpaged_catalog_like_lines(lines)
    title_like_count = _count_short_title_like_lines(lines)
    figure_count = sum(1 for line in lines if _FIGURE_LINE_PATTERN.match(line))
    table_count = sum(1 for line in lines if _TABLE_LINE_PATTERN.match(line))
    body_signal_value = body_page_signal(text)

    signal_count = 0
    if heading_kinds:
        signal_count += 1
    if paged_count >= 3:
        signal_count += 1
    if unpaged_count >= 3 or title_like_count >= 4:
        signal_count += 1
    if figure_count >= 2 or table_count >= 2:
        signal_count += 1

    score = 0.0
    if heading_kinds:
        score += 0.34
    if paged_count >= 6:
        score += 0.36
    elif paged_count >= 3:
        score += 0.28
    if unpaged_count >= 5:
        score += 0.30
    elif unpaged_count >= 3:
        score += 0.22
    if title_like_count >= 5 and heading_kinds:
        score += 0.20
    elif title_like_count >= 3 and heading_kinds:
        score += 0.12
    if figure_count >= 2 or table_count >= 2:
        score += 0.24
    score -= min(0.34, body_signal_value)
    score = round(max(0.0, min(1.0, score)), 4)

    is_toc = bool(score >= 0.55 and signal_count >= 2)
    sections = _sections_for_text(
        lines,
        heading_kinds=heading_kinds,
        paged_count=paged_count,
        unpaged_count=unpaged_count,
        title_like_count=title_like_count,
        figure_count=figure_count,
        table_count=table_count,
    ) if is_toc else []
    primary_kind = _primary_kind(sections)

    return {
        "page": int(page),
        "source": "text_detector",
        "is_toc": is_toc,
        "score": score,
        "decision": "yes" if is_toc else "no",
        "primary_kind": primary_kind,
        "sections": sections,
        "has_page_numbers": _page_has_trailing_page_numbers(lines),
        "features": {
            "heading_kinds": sorted(heading_kinds),
            "paged_catalog_line_count": paged_count,
            "unpaged_catalog_line_count": unpaged_count,
            "title_like_line_count": title_like_count,
            "figure_line_count": figure_count,
            "table_line_count": table_count,
            "body_signal": round(body_signal_value, 4),
        },
    }


def normalize_llm_toc_page_payload(
    payload: Dict[str, Any],
    *,
    page: int,
    batch_index: int,
    batch_size: int,
) -> Dict[str, Any]:
    raw_decision = payload.get("is_toc")
    if raw_decision is None:
        raw_decision = payload.get("toc_detected")
    if raw_decision is None:
        raw_decision = payload.get("toc")
    decision = str(raw_decision or "").strip().lower()
    is_toc = decision in {"yes", "true", "1"}
    score = _coerce_confidence(payload.get("confidence"), default=1.0 if is_toc else 0.0)
    sections = _normalize_sections(payload.get("sections") or [])
    if is_toc and not sections:
        kind = str(payload.get("primary_kind") or payload.get("kind") or "main_toc").strip()
        if kind == "mixed_toc":
            kind = "main_toc"
        if kind not in SECTION_KINDS:
            kind = "other_toc"
        sections = [{"kind": kind, "confidence": score}]
    if not is_toc:
        sections = []
    primary_kind = str(payload.get("primary_kind") or "").strip()
    if primary_kind not in SECTION_KINDS and primary_kind != "mixed_toc":
        primary_kind = _primary_kind(sections)
    if not is_toc:
        primary_kind = "none"

    return {
        "page": int(page),
        "source": "llm_classifier",
        "is_toc": is_toc,
        "score": score,
        "decision": "yes" if is_toc else "no",
        "primary_kind": primary_kind,
        "sections": sections,
        "batch_index": batch_index,
        "batch_size": batch_size,
        "has_page_numbers": bool(payload.get("has_page_numbers") or payload.get("page_numbers_present")),
    }


def classify_toc_page_text(text: str, *, page: int, source: str = "text_detector") -> Dict[str, Any]:
    candidate = _classify_text_toc_page(text, page=page)
    candidate["source"] = source
    return candidate


def _confirmed_unpaged_toc_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(candidate)
    sections = list(normalized.get("sections") or [])
    if not sections:
        sections = [{"kind": "main_toc", "confidence": 0.72}]
    normalized.update(
        {
            "is_toc": True,
            "score": max(float(normalized.get("score") or 0.0), 0.72),
            "decision": "yes",
            "primary_kind": _primary_kind(sections),
            "sections": sections,
            "has_page_numbers": False,
        }
    )
    return normalized


def aggregate_toc_sections(
    candidates: List[Dict[str, Any]],
    *,
    pages: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    selected_pages = set(int(page) for page in pages or [] if int(page) > 0)
    grouped: Dict[str, List[int]] = {}
    for candidate in candidates:
        page = int(candidate.get("page") or 0)
        if selected_pages and page not in selected_pages:
            continue
        if not candidate.get("is_toc"):
            continue
        for section in candidate.get("sections") or []:
            kind = str(section.get("kind") or "").strip()
            if kind not in SECTION_KINDS:
                continue
            grouped.setdefault(kind, [])
            if page and page not in grouped[kind]:
                grouped[kind].append(page)
    order = {"main_toc": 0, "figure_toc": 1, "table_toc": 2, "other_toc": 3}
    return [
        {"kind": kind, "pages": sorted(grouped[kind])}
        for kind in sorted(grouped, key=lambda item: order.get(item, 99))
    ]


def _select_detected_toc_page_run(candidates: List[Dict[str, Any]]) -> List[int]:
    detected = [
        candidate
        for candidate in sorted(candidates, key=lambda item: int(item.get("page") or 0))
        if candidate.get("is_toc") and int(candidate.get("page") or 0) > 0
    ]
    if not detected:
        return []
    runs: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for candidate in detected:
        page = int(candidate.get("page") or 0)
        if current and page != int(current[-1].get("page") or 0) + 1:
            runs.append(current)
            current = []
        current.append(candidate)
    if current:
        runs.append(current)
    best = max(
        runs,
        key=lambda run: (
            len(run),
            sum(float(candidate.get("score") or 0.0) for candidate in run),
        ),
    )
    return [int(candidate.get("page") or 0) for candidate in best]


def _heading_section_kinds(lines: List[str]) -> set[str]:
    kinds: set[str] = set()
    compact_lines = [re.sub(r"\s+", "", line).lower() for line in lines if line]
    for first, second in zip(compact_lines, compact_lines[1:]):
        pair = first + second
        if pair in {"目录", "目次"}:
            kinds.add("main_toc")
        elif pair in {"图目录", "插图目录", "图表目录"}:
            kinds.add("figure_toc")
        elif pair in {"表目录", "表格目录"}:
            kinds.add("table_toc")
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        compact = re.sub(r"\s+", "", normalized).lower()
        if not normalized:
            continue
        if _FIGURE_TOC_HEADING_PATTERN.match(normalized) or compact in {"图目录", "插图目录", "图表目录"}:
            kinds.add("figure_toc")
            continue
        if _TABLE_TOC_HEADING_PATTERN.match(normalized) or compact in {"表目录", "表格目录"}:
            kinds.add("table_toc")
            continue
        if _TOC_HEADING_PATTERN.match(normalized) or compact in {"目录", "目次", "contents", "tableofcontents"}:
            kinds.add("main_toc")
    return kinds


def _count_paged_catalog_like_lines(lines: List[str]) -> int:
    count = 0
    for line in lines:
        compact = _normalize_line(line)
        if not compact or len(compact) > 180:
            continue
        if _PAGED_CATALOG_LINE_PATTERN.match(compact):
            count += 1
            continue
        if (
            (_FIGURE_LINE_PATTERN.match(compact) or _TABLE_LINE_PATTERN.match(compact) or _CHAPTER_MARKER_PATTERN.match(compact))
            and re.search(r"\s+\d{1,4}\s*$", compact)
        ):
            count += 1
    return count


def _count_unpaged_catalog_like_lines(lines: List[str]) -> int:
    count = 0
    for line in lines:
        compact = _normalize_line(line)
        if not compact or len(compact) > 120:
            continue
        if _is_excluded_catalog_line(compact):
            continue
        if _CHAPTER_MARKER_PATTERN.match(compact):
            count += 1
            continue
        if re.match(r"^part\s*0?\d{1,3}\b\s*[:：.\-]?\s*\S.*$", compact, re.IGNORECASE):
            count += 1
    return count


def _count_short_title_like_lines(lines: List[str]) -> int:
    return sum(1 for line in lines if _is_toc_title_line(line))


def _sections_for_text(
    lines: List[str],
    *,
    heading_kinds: set[str],
    paged_count: int,
    unpaged_count: int,
    title_like_count: int,
    figure_count: int,
    table_count: int,
) -> List[Dict[str, Any]]:
    kinds: List[str] = []
    auxiliary_page = bool(heading_kinds & {"figure_toc", "table_toc"}) or figure_count >= 2 or table_count >= 2
    main_before_aux_count = _main_catalog_line_count_before_auxiliary_content(lines)
    if (
        "main_toc" in heading_kinds
        or (auxiliary_page and main_before_aux_count >= 2)
        or (
            not auxiliary_page
            and (
                _main_catalog_line_count(lines) >= 2
                or (paged_count >= 3 or unpaged_count >= 3 or title_like_count >= 4)
            )
        )
    ):
        kinds.append("main_toc")
    if "figure_toc" in heading_kinds or figure_count >= 2:
        kinds.append("figure_toc")
    if "table_toc" in heading_kinds or table_count >= 2:
        kinds.append("table_toc")
    if not kinds and (paged_count >= 3 or unpaged_count >= 3):
        kinds.append("other_toc")
    confidence = 0.9 if len(kinds) > 1 else 0.82
    return [{"kind": kind, "confidence": confidence} for kind in kinds]


def _main_catalog_line_count_before_auxiliary_content(lines: List[str]) -> int:
    prefix: List[str] = []
    for line in lines:
        kinds = _heading_section_kinds([line])
        compact = _normalize_line(line)
        if (
            kinds & {"figure_toc", "table_toc"}
            or _FIGURE_LINE_PATTERN.match(compact)
            or _TABLE_LINE_PATTERN.match(compact)
        ):
            break
        prefix.append(line)
    return _main_catalog_line_count(prefix)


def _main_catalog_line_count(lines: List[str]) -> int:
    count = 0
    for line in lines:
        compact = _normalize_line(line)
        if not compact or _is_excluded_catalog_line(compact):
            continue
        if _FIGURE_LINE_PATTERN.match(compact) or _TABLE_LINE_PATTERN.match(compact):
            continue
        if _PAGED_CATALOG_LINE_PATTERN.match(compact) or _CHAPTER_MARKER_PATTERN.match(compact):
            count += 1
    return count


def _normalize_sections(sections: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        kind = str(section.get("kind") or "").strip()
        if kind not in SECTION_KINDS:
            continue
        confidence = _coerce_confidence(section.get("confidence"), default=0.75)
        normalized.append({"kind": kind, "confidence": confidence})
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for section in normalized:
        if section["kind"] in seen:
            continue
        seen.add(section["kind"])
        deduped.append(section)
    return deduped


def _primary_kind(sections: List[Dict[str, Any]]) -> str:
    kinds = [str(section.get("kind") or "") for section in sections if section.get("kind")]
    if not kinds:
        return "none"
    if len(set(kinds)) > 1:
        return "mixed_toc"
    return kinds[0]


def _coerce_confidence(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return round(max(0.0, min(1.0, parsed)), 4)


def _page_has_trailing_page_numbers(lines: List[str]) -> bool:
    trailing_count = sum(1 for line in lines if _TRAILING_PAGE_PATTERN.search(_normalize_line(line)))
    standalone_number_count = sum(1 for line in lines if re.fullmatch(r"\d{1,4}", _normalize_line(line)))
    dense_numbered_catalog_count = sum(
        1
        for line in lines
        if re.match(r"^\d{1,3}\s+\S.{2,}", _normalize_line(line))
    )
    return (
        trailing_count >= 3
        or standalone_number_count >= 6
        or dense_numbered_catalog_count >= 10
    )


def body_page_signal(text: str) -> float:
    lines = [_normalize_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return 0.0
    long_lines = sum(1 for line in lines if len(line) >= 90)
    paragraph_lines = sum(
        1
        for line in lines
        if len(line) >= 45 and not _TRAILING_PAGE_PATTERN.search(line)
    )
    image_lines = sum(
        1
        for line in lines
        if "<img" in line.lower() or line.lower().startswith("<div")
    )
    signal = 0.0
    if long_lines >= 2:
        signal += 0.16
    if paragraph_lines / max(1, len(lines)) >= 0.35:
        signal += 0.14
    if image_lines:
        signal += 0.04
    return min(0.36, signal)


def _is_excluded_catalog_line(line: str) -> bool:
    lowered = _normalize_line(line).lower()
    if not lowered:
        return True
    if lowered.startswith(("http://", "https://", "<")) or "<img" in lowered:
        return True
    if re.fullmatch(r"\d{1,4}", lowered):
        return True
    if re.match(r"^(page\s*)?\d+\s*/\s*\d+$", lowered, re.IGNORECASE):
        return True
    return False


def _detect_unpaged_toc_pages(
    page_texts: List[str],
    *,
    max_scan_pages: int,
) -> List[int]:
    pages: List[int] = []
    scan_limit = min(max_scan_pages, len(page_texts))
    for index in range(scan_limit):
        text = str(page_texts[index] or "")
        if _is_unpaged_toc_text(text):
            pages.append(index + 1)
            continue
        if pages:
            break
    return pages


def _is_unpaged_toc_text(text: str) -> bool:
    lines = [_normalize_line(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 4:
        return False
    trailing_page_lines = sum(1 for line in lines if _TRAILING_PAGE_PATTERN.search(line))
    if trailing_page_lines >= 3:
        return False

    heading_hits = sum(1 for line in lines[:8] if _TOC_HEADING_PATTERN.match(line))
    title_like = [_is_toc_title_line(line) for line in lines]
    title_count = sum(1 for value in title_like if value)
    marker_count = sum(1 for line in lines if _CHAPTER_MARKER_PATTERN.match(line))
    part_count = sum(1 for line in lines if re.match(r"^part\s*\d+", line, re.IGNORECASE))

    if heading_hits and title_count >= 3:
        return True
    if heading_hits and marker_count >= 2:
        return True
    if part_count >= 4 and title_count >= 4:
        return True
    return False


def _is_toc_title_line(line: str) -> bool:
    if len(line) < 2 or len(line) > 80:
        return False
    if line.isdigit():
        return False
    if re.match(r"^https?://", line, re.IGNORECASE):
        return False
    if re.match(r"^(page\s*)?\d+\s*/\s*\d+$", line, re.IGNORECASE):
        return False
    if _TOC_HEADING_PATTERN.match(line):
        return False
    return True


def _pages_have_trailing_page_numbers(page_texts: List[str], pages: List[int]) -> bool:
    trailing_count = 0
    standalone_number_count = 0
    dense_numbered_catalog_count = 0
    for page in pages:
        index = page - 1
        if index < 0 or index >= len(page_texts):
            continue
        lines = [_normalize_line(line) for line in str(page_texts[index] or "").splitlines()]
        trailing_count += sum(1 for line in lines if _TRAILING_PAGE_PATTERN.search(line))
        standalone_number_count += sum(1 for line in lines if re.fullmatch(r"\d{1,4}", line))
        dense_numbered_catalog_count += sum(
            1
            for line in lines
            if re.match(r"^\d{1,3}\s+\S.{2,}", line)
        )
    return (
        trailing_count >= 3
        or standalone_number_count >= 6
        or dense_numbered_catalog_count >= 10
    )


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "")).strip()


def _build_toc_page_report(
    *,
    pages: List[int],
    has_page_numbers: bool,
    reason: str,
) -> Dict[str, Any]:
    return {
        "source": "text_detector",
        "status": "detected" if pages else "not_found",
        "pages": list(pages),
        "has_page_numbers": bool(has_page_numbers),
        "candidates": [
            {
                "page": page,
                "source": "text_detector",
                "is_toc": True,
                "score": 1.0,
                "has_page_numbers": bool(has_page_numbers),
            }
            for page in pages
        ],
        "reason": reason if pages else "no_text_toc_pages",
        "classification_complete": True,
    }


def _store_toc_page_report(
    analysis: Dict[str, Any],
    *,
    pages: List[int],
    has_page_numbers: bool,
    reason: str,
) -> None:
    if not pages:
        return
    analysis["toc_page_detection"] = _build_toc_page_report(
        pages=pages,
        has_page_numbers=has_page_numbers,
        reason=reason,
    )
