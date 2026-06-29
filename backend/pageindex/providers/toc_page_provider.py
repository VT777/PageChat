"""Text TOC page provider for formal TOC skeletons."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pageindex.contracts import make_toc_skeleton_context
from pageindex.evidence_classifier import classify_page_text
from pageindex.index_quality import TocQualityChecker


_ENTRY_RE = re.compile(
    r"^\s*(?P<num>(?:第[一二三四五六七八九十百]+[章节篇部分]|[0-9]{1,2}(?:\.[0-9]{1,2})*|[一二三四五六七八九十]+[、.．]))\s+"
    r"(?P<title>.+?)(?:\s*(?:\.{2,}|[·•]{2,}|\s{2,})\s*(?P<page>\d{1,4}))?\s*$"
)


class TocPageTextProvider:
    name = "toc_page_text"
    priority = 20

    def can_run(self, analysis: Dict[str, Any]) -> bool:
        return bool(_toc_pages(analysis) and analysis.get("page_texts"))

    def run(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pages = _toc_pages(analysis)
        page_texts = analysis.get("page_texts") or []
        if not pages or not page_texts:
            return None

        toc_text = "\n".join(
            page_texts[page - 1]
            for page in pages
            if isinstance(page, int) and 0 <= page - 1 < len(page_texts)
        )
        evidence = classify_page_text(toc_text, page_number=pages[0])
        if evidence["evidence_type"] not in {"formal_toc", "no_page_toc"}:
            return None

        items = _extract_items(toc_text)
        if len(items) < 3:
            return None

        quality = TocQualityChecker().check(items, pages)
        if not quality.get("skeleton_valid"):
            return None

        return make_toc_skeleton_context(
            source="toc_page_text",
            items=items,
            toc_pages=pages,
            skeleton_valid=True,
            page_mapping_valid=bool(quality.get("page_mapping_valid")),
            hierarchy_valid=bool(quality.get("hierarchy_valid")),
            has_page_numbers=bool(quality.get("valid_page_count")),
            authoritative_top_level=True,
            confidence=max(float(evidence.get("confidence") or 0.0), 0.75),
            debug={
                "quality": quality,
                "evidence": evidence,
            },
        )


def _toc_pages(analysis: Dict[str, Any]) -> List[int]:
    pages = analysis.get("toc_pages") or (analysis.get("toc_page") or {}).get("pages") or []
    return [int(page) for page in pages if isinstance(page, int) and page > 0]


def _extract_items(text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"contents", "table of contents", "目录", "目 录", "目次"}:
            continue
        match = _ENTRY_RE.match(line)
        if not match:
            continue
        number = match.group("num").strip()
        title = _clean_title(match.group("title"))
        page = match.group("page")
        if not title:
            continue
        key = (number, title, page)
        if key in seen:
            continue
        seen.add(key)

        item: Dict[str, Any] = {
            "title": title,
            "level": _level_from_number(number),
            "structure": _structure_from_number(number),
        }
        if page:
            item["physical_index"] = int(page)
        items.append(item)
    return items


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"[\.\u00b7\u2026·•]+$", "", title or "").strip()
    return re.sub(r"\s+", " ", cleaned)


def _level_from_number(number: str) -> int:
    if re.match(r"^\d+(?:\.\d+)+", number):
        return number.count(".") + 1
    return 1


def _structure_from_number(number: str) -> str:
    numeric = re.match(r"^\d+(?:\.\d+)*", number)
    if numeric:
        return numeric.group(0)
    return ""
