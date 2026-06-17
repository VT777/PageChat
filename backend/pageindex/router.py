"""Smart extraction route selection for PDF TOC generation."""

import re
from typing import Any, Dict, List


PATH_TOC_PAGE = "toc_page"
PATH_HIERARCHICAL = "hierarchical"
PATH_BATCH = "batch"
PATH_FAST_TEXT = "fast_text"
PATH_PPOCR_LAYOUT = "ppocr_layout"

ALL_PATHS = [
    PATH_TOC_PAGE,
    PATH_HIERARCHICAL,
    PATH_BATCH,
    PATH_FAST_TEXT,
    PATH_PPOCR_LAYOUT,
]


def normalize_confidence(value: Any) -> float:
    """Normalize numeric or symbolic confidence values to a float in [0, 1]."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        mapped = {
            "high": 0.9,
            "medium": 0.6,
            "low": 0.3,
            "anchor": 0.7,
            "detected": 0.7,
            "known": 0.7,
        }
        stripped = value.strip().lower()
        if stripped in mapped:
            return mapped[stripped]
        try:
            return max(0.0, min(1.0, float(stripped)))
        except ValueError:
            return 0.0
    return 0.0


def decide_extraction_path(analysis: Dict[str, Any], mode: str = "smart") -> Dict[str, Any]:
    """Choose the best extraction path from analysis signals."""
    page_count = analysis.get("page_count", 0)
    text_coverage = analysis.get("text_coverage", 0)
    is_image_only = analysis.get("is_image_only_pdf", False)
    is_garbled = analysis.get("is_garbled_pdf", False)
    quality = analysis.get("text_quality", {})
    chapter_dividers = analysis.get("chapter_dividers", [])
    toc_page_info = analysis.get("toc_page", {})
    slide_outline_candidate = bool(analysis.get("slide_outline_candidate"))
    agenda_outline_candidate = bool(analysis.get("agenda_outline_candidate"))
    deterministic_outline_candidate = slide_outline_candidate or agenda_outline_candidate

    reasons: List[str] = []
    alternatives: List[str] = []

    if is_image_only:
        reasons.append(f"Image PDF: text_coverage={text_coverage:.0%}")
        return _make_decision(PATH_PPOCR_LAYOUT, 0.95, reasons, [PATH_BATCH])

    if is_garbled or (quality.get("meaningful_ratio", 1) < 0.15 and text_coverage < 0.3):
        reasons.append(f"Low quality text: meaningful={quality.get('meaningful_ratio', 0):.0%}")
        return _make_decision(PATH_PPOCR_LAYOUT, 0.9, reasons, [PATH_BATCH])

    if mode == "fast":
        if page_count <= 20 and text_coverage > 0.5 and not is_garbled:
            reasons.append("Fast mode: short text document")
            return _make_decision(PATH_FAST_TEXT, 0.9, reasons, [PATH_HIERARCHICAL])
        if toc_page_info.get("has_toc_page") and normalize_confidence(toc_page_info.get("confidence", 0)) >= 0.5:
            reasons.append("Fast mode: TOC page detected")
            return _make_decision(PATH_TOC_PAGE, 0.85, reasons, [PATH_FAST_TEXT])
        reasons.append("Fast mode: fallback to fast text")
        return _make_decision(PATH_FAST_TEXT, 0.7, reasons, [PATH_HIERARCHICAL])

    if mode == "balanced":
        if toc_page_info.get("has_toc_page") and normalize_confidence(toc_page_info.get("confidence", 0)) >= 0.5:
            reasons.append("Balanced mode: TOC page detected")
            return _make_decision(PATH_TOC_PAGE, 0.8, reasons, [PATH_HIERARCHICAL])

    if toc_page_info.get("has_toc_page"):
        toc_conf = normalize_confidence(toc_page_info.get("confidence", 0))
        if toc_conf >= 0.6:
            reasons.append(f"TOC page detected (confidence={toc_conf:.2f})")
            return _make_decision(PATH_TOC_PAGE, toc_conf, reasons, [PATH_HIERARCHICAL])
        if toc_conf >= 0.4:
            alternatives.append(PATH_TOC_PAGE)
            reasons.append(f"Possible TOC page (confidence={toc_conf:.2f})")

    if len(chapter_dividers) >= 5 and not deterministic_outline_candidate:
        reasons.append(f"{len(chapter_dividers)} chapter dividers detected")
        return _make_decision(PATH_BATCH, 0.85, reasons, [PATH_HIERARCHICAL])

    if len(chapter_dividers) >= 5 and deterministic_outline_candidate:
        alternatives.append(PATH_BATCH)
        reasons.append(f"Deterministic outline candidate with {len(chapter_dividers)} dividers")

    if page_count <= 20 and text_coverage > 0.5 and not is_garbled:
        heading_density = calculate_heading_density(analysis)
        if heading_density < 0.3:
            reasons.append(f"Short document with low heading density ({heading_density:.2f})")
            return _make_decision(PATH_FAST_TEXT, 0.8, reasons, [PATH_HIERARCHICAL])
        alternatives.append(PATH_FAST_TEXT)
        reasons.append(f"Short document with high heading density ({heading_density:.2f})")

    reasons.append(f"Long document ({page_count} pages), using hierarchical extraction")
    return _make_decision(
        PATH_HIERARCHICAL,
        0.75,
        reasons,
        alternatives or [PATH_FAST_TEXT],
    )


def _make_decision(path: str, confidence: float, reasons: List[str], alternatives: List[str]) -> Dict[str, Any]:
    return {
        "path": path,
        "confidence": confidence,
        "reasons": reasons,
        "alternatives": alternatives,
    }


def calculate_heading_density(analysis: Dict[str, Any]) -> float:
    """Estimate average heading-line count per page."""
    page_texts = analysis.get("page_texts", [])
    if not page_texts:
        return 0.0

    heading_patterns = [
        r"^第[一二三四五六七八九十百零〇两\d]+[章节部分篇]",
        r"^\d{1,2}(?:\.\d{1,2}){0,2}\s+[^\s]",
        r"^[一二三四五六七八九十]+[、.]",
        r"^[（(][一二三四五六七八九十\d]+[)）]",
        r"^\d+\.\s+[^\d]",
        r"^(?:Chapter|Section|Part)\s+\d+",
    ]
    combined = re.compile("|".join(f"({pattern})" for pattern in heading_patterns))

    total_headings = 0
    for text in page_texts:
        for line in text.splitlines():
            line = line.strip()
            if 10 <= len(line) <= 80 and combined.match(line):
                total_headings += 1

    return total_headings / len(page_texts)


def get_path_description(path: str) -> str:
    descriptions = {
        PATH_TOC_PAGE: "TOC page extraction",
        PATH_HIERARCHICAL: "Hierarchical extraction",
        PATH_BATCH: "Batch page extraction",
        PATH_FAST_TEXT: "Fast text extraction",
        PATH_PPOCR_LAYOUT: "PP-OCRv6 layout extraction",
    }
    return descriptions.get(path, f"Unknown path: {path}")
