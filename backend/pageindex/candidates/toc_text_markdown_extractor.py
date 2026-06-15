"""Extract TOC candidates from OCR Markdown, text, and structured items."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pageindex.layout.document_layout import DocumentLayout, OCRLayoutPage


class TOCTextMarkdownExtractor:
    def extract(self, layout: DocumentLayout) -> Optional[Dict[str, Any]]:
        candidate_items: List[Dict[str, Any]] = []
        toc_pages: List[int] = []
        evidence_levels: List[str] = []
        rejected_titles: List[str] = []
        had_source_without_page_numbers = False

        for page in layout.pages:
            source_text = _page_source_text(page)
            if not source_text and not page.structured_items:
                continue
            toc_pages.append(page.page)
            evidence_levels.append(page.evidence_level)

            structured = _items_from_structured(page, source_text)
            rejected_titles.extend(structured["rejected_titles"])
            candidate_items.extend(structured["items"])
            if page.evidence_level == "model_inferred" and structured["rejected_titles"]:
                continue

            text_items = _items_from_text(page, source_text)
            if source_text and not text_items:
                had_source_without_page_numbers = True
            candidate_items.extend(text_items)

        candidate_items = _dedupe_items(candidate_items)
        if not candidate_items and rejected_titles:
            return None
        if not candidate_items and not had_source_without_page_numbers:
            return None

        reasons: List[str] = []
        if had_source_without_page_numbers and not candidate_items:
            reasons.append("no_page_numbers")
        if rejected_titles:
            reasons.append("structured_title_not_in_source")

        monotonic = _is_monotonic([item.get("page") for item in candidate_items])
        confidence = _confidence(candidate_items, evidence_levels, reasons, monotonic)
        return {
            "candidate_id": "ocr_text_markdown_001",
            "source": "ocr_text_markdown",
            "cost_level": "medium",
            "items": candidate_items,
            "raw_confidence": confidence,
            "reasons": reasons,
            "evidence": {
                "toc_pages": toc_pages,
                "evidence_level": _dominant_evidence_level(evidence_levels),
                "page_monotonic": monotonic,
                "page_mapping_score": 1.0 if monotonic and candidate_items else 0.0,
                "title_presence_score": 1.0 if candidate_items and not rejected_titles else 0.45,
                "rejected_titles": rejected_titles,
            },
        }


def _page_source_text(page: OCRLayoutPage) -> str:
    return (page.markdown or page.plain_text or "").strip()


def _items_from_structured(page: OCRLayoutPage, source_text: str) -> Dict[str, List[Any]]:
    items: List[Dict[str, Any]] = []
    rejected: List[str] = []
    normalized_source = _normalize_for_match(source_text)
    for raw in page.structured_items:
        title = _clean_title(raw.get("title") or "")
        if not title:
            continue
        if normalized_source and _normalize_for_match(title) not in normalized_source:
            rejected.append(title)
            continue
        logical_page = _parse_int(raw.get("page") or raw.get("physical_index"))
        if logical_page is None:
            continue
        items.append(
            _item(
                title=title,
                page_num=logical_page,
                level=_parse_int(raw.get("level")) or _level_for_title(title),
                source_page=page.page,
                confidence=float(raw.get("confidence") or 0.72),
            )
        )
    return {"items": items, "rejected_titles": rejected}


def _items_from_text(page: OCRLayoutPage, text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or _is_toc_heading(line):
            continue
        title, logical_page, markdown_level = _parse_toc_line(line)
        if logical_page is None or not title:
            continue
        items.append(
            _item(
                title=title,
                page_num=logical_page,
                level=markdown_level or _level_for_title(title),
                source_page=page.page,
                confidence=0.62 if page.evidence_level == "text_only" else 0.72,
            )
        )
    return items


def _parse_toc_line(line: str) -> tuple[str, Optional[int], Optional[int]]:
    markdown_level = None
    heading = re.match(r"^(#{1,6})\s+(.+)$", line)
    if heading:
        markdown_level = max(1, len(heading.group(1)) - 1)
        line = heading.group(2).strip()
    bullet = re.match(r"^[-*+]\s+(.+)$", line)
    if bullet:
        line = bullet.group(1).strip()
    match = re.match(r"^(.*?)(?:\s*(?:\.{2,}|…+)\s*|\s+)(\d{1,4})$", line)
    if not match:
        return _clean_title(line), None, markdown_level
    return _clean_title(match.group(1)), int(match.group(2)), markdown_level


def _item(*, title: str, page_num: int, level: int, source_page: int, confidence: float) -> Dict[str, Any]:
    return {
        "title": title,
        "level": max(1, int(level or 1)),
        "page": int(page_num),
        "physical_index": int(page_num),
        "source_page": source_page,
        "confidence": confidence,
        "nodes": [],
    }


def _clean_title(text: Any) -> str:
    title = re.sub(r"^#+\s*", "", str(text or "").strip())
    title = re.sub(r"^[-*+]\s+", "", title)
    title = re.sub(r"[\s.…]+$", "", title)
    return title.strip()


def _is_toc_heading(text: str) -> bool:
    normalized = _clean_title(text).lower()
    return normalized in {"contents", "table of contents", "目录", "目錄"}


def _level_for_title(title: str) -> int:
    stripped = title.strip()
    if re.match(r"^\d+\.\d+", stripped):
        return 2
    if re.match(r"^\d+", stripped):
        return 1
    return 1


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def _parse_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for item in items:
        key = (_normalize_for_match(item.get("title") or ""), item.get("page"), item.get("level"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _is_monotonic(values: List[Any]) -> bool:
    pages = [int(value) for value in values if isinstance(value, int)]
    return all(left <= right for left, right in zip(pages, pages[1:]))


def _confidence(items: List[Dict[str, Any]], evidence_levels: List[str], reasons: List[str], monotonic: bool) -> float:
    if not items:
        return 0.25
    base = 0.55 + min(0.2, len(items) * 0.04)
    if "model_inferred" in evidence_levels:
        base += 0.05
    if monotonic:
        base += 0.1
    if reasons:
        base -= 0.18
    return round(max(0.0, min(0.9, base)), 4)


def _dominant_evidence_level(levels: List[str]) -> str:
    if "line_box" in levels:
        return "line_box"
    if "model_inferred" in levels:
        return "model_inferred"
    return levels[0] if levels else "text_only"
