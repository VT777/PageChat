"""Parser-free TOC page detection for layout-first indexing."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def detect_toc_pages_from_layout(
    layout: Any,
    *,
    page_count: int,
) -> Dict[str, Any]:
    if not layout or not getattr(layout, "pages", None):
        return {
            "source": "layout",
            "status": "not_found",
            "pages": [],
            "candidates": [],
            "reason": "empty_layout",
        }

    candidates: List[Dict[str, Any]] = []
    pages = sorted(list(getattr(layout, "pages", []) or []), key=lambda item: int(getattr(item, "page", 0) or 0))
    for page in pages:
        text = strip_ocr_markdown_fences(str(getattr(page, "markdown", "") or getattr(page, "plain_text", "") or ""))
        catalog_line_count = count_catalog_like_lines(text)
        unpaged_catalog_line_count = count_unpaged_catalog_like_lines(text)
        toc_heading = has_toc_page_heading(text)
        features = getattr(page, "features", {}) or {}
        feature_score = coerce_float(features.get("toc_score"), default=0.0)
        body_signal = body_page_signal(text)
        score = 0.0
        if toc_heading:
            score += 0.42
        if catalog_line_count >= 8:
            score += 0.34
        elif catalog_line_count >= 4:
            score += 0.24
        if feature_score >= 0.5:
            score += 0.16
        elif feature_score >= 0.3:
            score += 0.08
        if catalog_line_count >= 6:
            score += 0.08
        elif catalog_line_count >= 3:
            score += 0.04
        if unpaged_catalog_line_count >= 5:
            score += 0.34
        elif unpaged_catalog_line_count >= 3:
            score += 0.24
        score -= min(0.32, body_signal)
        score = round(max(0.0, min(1.0, score)), 4)
        is_toc = bool(
            score >= 0.55
            and (
                toc_heading
                or catalog_line_count >= 5
                or unpaged_catalog_line_count >= 5
                or feature_score >= 0.65
            )
        )
        candidates.append(
            {
                "page": int(getattr(page, "page", 0) or 0),
                "score": score,
                "is_toc": is_toc,
                "toc_heading": toc_heading,
                "catalog_line_count": catalog_line_count,
                "unpaged_catalog_line_count": unpaged_catalog_line_count,
                "feature_toc_score": round(feature_score, 4),
                "body_signal": round(body_signal, 4),
            }
        )

    detected_pages = select_detected_toc_page_run(candidates)
    return {
        "source": "layout",
        "status": "detected" if detected_pages else "not_found",
        "pages": detected_pages,
        "candidates": candidates,
        "reason": "confirmed_by_layout_signals" if detected_pages else "no_confirmed_toc_pages",
    }


def select_detected_toc_page_run(candidates: List[Dict[str, Any]]) -> List[int]:
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


def strip_ocr_markdown_fences(text: str) -> str:
    value = str(text or "").strip()
    if not value.startswith("```"):
        return value
    lines = value.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def has_toc_page_heading(text: str) -> bool:
    normalized = re.sub(r"\s+", "", str(text or "").lower())
    return any(
        marker in normalized
        for marker in (
            "\u76ee\u5f55",
            "contents",
            "tableofcontents",
        )
    )


def count_catalog_like_lines(text: str) -> int:
    lines = [
        re.sub(r"^#{1,6}\s+", "", line).strip()
        for line in strip_ocr_markdown_fences(text).splitlines()
    ]
    lines = [line for line in lines if line]
    count = 0
    for index, line in enumerate(lines):
        compact = re.sub(r"\s+", " ", line)
        if re.search(r"(?:\.{2,}|_{2,}|\u2026{1,})\s*\d{1,4}\s*$", compact):
            count += 1
            continue
        if compact.startswith("|") and "|" in compact[1:] and len(re.findall(r"\b\d{1,4}\b", compact)) >= 2:
            count += 1
            continue
        if (
            len(compact) <= 150
            and re.match(r"^(?:[-*+]\s*)?(?:\d{1,3}[\s.)\u3001\uff0e-]+)?\S.{2,}", compact)
            and re.search(r"\s+\d{1,4}\s*$", compact)
        ):
            count += 1
            continue
        if index + 1 < len(lines) and re.fullmatch(r"\d{1,4}", lines[index + 1].strip()) and 4 <= len(compact) <= 150:
            count += 1
    return count


def count_unpaged_catalog_like_lines(text: str) -> int:
    lines = [
        re.sub(r"^#{1,6}\s+", "", line).strip()
        for line in strip_ocr_markdown_fences(text).splitlines()
    ]
    lines = [line for line in lines if line]
    count = 0
    for line in lines:
        compact = re.sub(r"\s+", " ", line).strip()
        if not compact or len(compact) > 160:
            continue
        lower = compact.lower()
        if lower.startswith("<") or "<img" in lower:
            continue
        if has_toc_page_heading(compact):
            continue
        if re.fullmatch(r"\d{1,4}", compact):
            continue
        if re.search(r"(?:\.{2,}|_{2,}|\u2026{1,})\s*\d{1,4}\s*$", compact):
            continue
        if re.match(r"^(?:part|chapter|section)\s*0?\d{1,3}\b\s*[::\uff1a.\-]?\s*\S.*$", compact, re.IGNORECASE):
            count += 1
            continue
        if re.match(r"^(?:\u7b2c\s*)?[\d\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e]{1,4}\s*[\u7ae0\u8282\u7bc7\u90e8]\s*[:\uff1a.\-]?\s*\S.*$", compact):
            count += 1
            continue
        if re.match(r"^[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\d]{1,3}[\u3001.)\uff0e]\s*\S.{2,}$", compact):
            count += 1
    return count


def body_page_signal(text: str) -> float:
    lines = [line.strip() for line in strip_ocr_markdown_fences(text).splitlines() if line.strip()]
    if not lines:
        return 0.0
    long_lines = sum(1 for line in lines if len(line) >= 90)
    paragraph_lines = sum(
        1
        for line in lines
        if len(line) >= 45 and not re.search(r"(?:\.{2,}|_{2,}|\u2026{1,})\s*\d{1,4}\s*$", line)
    )
    image_lines = sum(1 for line in lines if "<img" in line.lower() or line.lower().startswith("<div"))
    signal = 0.0
    if long_lines >= 2:
        signal += 0.16
    if paragraph_lines / max(1, len(lines)) >= 0.35:
        signal += 0.14
    if image_lines:
        signal += 0.04
    return min(0.36, signal)


def coerce_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))
