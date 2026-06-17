"""LLM-based TOC extraction from confirmed TOC pages."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LLMTOCExtractionResult:
    items: List[Dict[str, Any]]
    has_printed_page_numbers: bool
    raw_numeric_labels: List[int]
    missing_numeric_labels: List[int]
    numeric_label_gap_count: int
    diagnostics: Dict[str, Any]


def build_llm_toc_prompt(page_blocks: List[Dict[str, Any]]) -> str:
    blocks: List[str] = []
    for block in page_blocks:
        page = _positive_int(block.get("page")) or 0
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f"[PDF page {page}]\n{text[:6000]}")
    combined = "\n\n".join(blocks).strip()
    return f"""Extract the complete table of contents from the provided TOC page text.

TOC page text:
{combined[:12000]}

Requirements:
1. Use only TOC entries.
2. Preserve original entry order, titles, hierarchy levels, and visible printed page numbers.
3. Put visible printed page numbers in "page". Use null if absent.
4. Do not infer page offsets or physical PDF pages.
5. Return JSON only with this shape:
{{"toc_items":[{{"title":"Chapter title","level":1,"page":1}}]}}
If no reliable TOC exists, return {{"toc_items":[]}}."""


def normalize_llm_toc_payload(payload: Dict[str, Any]) -> LLMTOCExtractionResult:
    raw_items = payload.get("toc_items") or payload.get("items") or []
    items: List[Dict[str, Any]] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        title = _clean_title(raw.get("title"))
        if not title or _is_plain_catalog_heading(title):
            continue
        page = _positive_int(raw.get("page"))
        level = _positive_int(raw.get("level")) or 1
        item: Dict[str, Any] = {
            "title": title,
            "level": max(1, min(6, level)),
            "page": page,
            "physical_index": None,
            "nodes": [],
        }
        items.append(item)

    labels = [label for label in (_leading_numeric_label(item.get("title")) for item in items) if label is not None]
    missing: List[int] = []
    if len(labels) >= 2:
        unique = sorted(set(labels))
        missing = [value for value in range(unique[0], unique[-1] + 1) if value not in set(unique)]
    pages = [_positive_int(item.get("page")) for item in items]
    has_page_numbers = any(page is not None for page in pages)
    level_distribution: Dict[int, int] = {}
    for item in items:
        level = _positive_int(item.get("level")) or 1
        level_distribution[level] = level_distribution.get(level, 0) + 1
    diagnostics = {
        "item_count": len(items),
        "has_printed_page_numbers": has_page_numbers,
        "raw_numeric_labels": labels,
        "missing_numeric_labels": missing,
        "numeric_label_gap_count": len(missing),
        "max_level": max(level_distribution.keys(), default=1),
        "level_distribution": dict(sorted(level_distribution.items())),
    }
    return LLMTOCExtractionResult(
        items=items,
        has_printed_page_numbers=has_page_numbers,
        raw_numeric_labels=labels,
        missing_numeric_labels=missing,
        numeric_label_gap_count=len(missing),
        diagnostics=diagnostics,
    )


def build_llm_toc_candidate(
    extraction: LLMTOCExtractionResult,
    *,
    toc_pages: List[int],
) -> Optional[Dict[str, Any]]:
    if not extraction.items:
        return None
    return {
        "candidate_id": "llm_toc_page_001",
        "source": "llm_toc_page",
        "cost_level": "high",
        "items": [dict(item) for item in extraction.items],
        "raw_confidence": 0.72 if not extraction.missing_numeric_labels else 0.58,
        "reasons": ["llm_structured_from_confirmed_toc_pages"],
        "evidence": {
            "toc_pages": list(toc_pages),
            "evidence_level": "text_only",
            "llm_structured": True,
            "has_printed_page_numbers": extraction.has_printed_page_numbers,
            "raw_numeric_labels": list(extraction.raw_numeric_labels),
            "missing_numeric_labels": list(extraction.missing_numeric_labels),
            "numeric_label_gap_count": extraction.numeric_label_gap_count,
        },
    }


def _clean_title(value: Any) -> str:
    title = re.sub(r"^#+\s*", "", str(value or "").strip())
    title = re.sub(r"^[-*+]\s+", "", title)
    return re.sub(r"[\s.…]+$", "", title).strip()


def _is_plain_catalog_heading(value: Any) -> bool:
    compact = re.sub(r"[\s\W_]+", "", str(value or "").lower(), flags=re.UNICODE)
    return compact in {
        "目录",
        "目次",
        "contents",
        "tableofcontents",
        "目录contents",
        "目次contents",
    }


def _leading_numeric_label(value: Any) -> Optional[int]:
    title = str(value or "").strip()
    match = re.match(r"^(\d{1,3})(?:[.)、．]\s*|\s+)(\S.*)$", title)
    if not match:
        return None
    return _positive_int(match.group(1))


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None
