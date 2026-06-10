"""Deterministic outline extraction for slide-like PDF reports."""

import re
from collections import Counter
from typing import Any, Dict, List, Optional


AGENDA_KEYWORDS = ("汇报提纲", "目录", "Agenda", "AGENDA", "Contents")
CHINESE_SECTION_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def clean_slide_bookmark_title(title: str) -> str:
    """Return a user-facing title from PPT-exported bookmark labels."""
    value = str(title or "").strip()
    if not value:
        return ""
    if value in {"默认节", "Default Section"}:
        return ""
    bare_slide = re.match(r"^(?:幻灯片|Slide)\s*\d+\s*$", value, re.IGNORECASE)
    if bare_slide:
        return ""
    prefixed = re.match(
        r"^(?:幻灯片|Slide)\s*\d+\s*[:：]\s*(.+)$",
        value,
        re.IGNORECASE,
    )
    if prefixed:
        return prefixed.group(1).strip()
    return value


def is_agenda_page(text: str) -> bool:
    stripped = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not stripped:
        return False
    joined = "\n".join(stripped)
    has_keyword = any(keyword in joined for keyword in AGENDA_KEYWORDS)
    numbered_markers = sum(1 for line in stripped if line in CHINESE_SECTION_NUMBERS)
    numbered_titles = sum(1 for line in stripped if _parse_numbered_slide_title(line))
    return has_keyword and (numbered_markers >= 2 or len(stripped) >= 6) and numbered_titles == 0


def is_slide_like_document(analysis: Dict[str, Any]) -> bool:
    page_texts = analysis.get("page_texts") or []
    page_count = int(analysis.get("page_count") or len(page_texts))
    if page_count < 8 or not page_texts:
        return False
    if float(analysis.get("text_coverage") or 0.0) < 0.6:
        return False

    agenda_pages = [idx + 1 for idx, text in enumerate(page_texts) if is_agenda_page(text)]
    title_pages = [
        idx + 1
        for idx, text in enumerate(page_texts)
        if _parse_numbered_slide_title(_first_text_line(text) or "")
    ]
    dividers = analysis.get("chapter_dividers") or []

    return (
        len(agenda_pages) >= 2
        or len(dividers) >= 5
    ) and len(title_pages) >= 5


def build_slide_outline(analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    page_texts = analysis.get("page_texts") or []
    if not is_slide_like_document(analysis):
        return None

    items: List[Dict[str, Any]] = []
    seen_slides = set()
    slide_first_titles = _collect_first_slide_titles(page_texts)
    agenda_titles = _align_agenda_titles(
        _extract_agenda_title_order(page_texts),
        slide_first_titles,
    )
    if not agenda_titles:
        return None

    for page_index, text in enumerate(page_texts, start=1):
        if is_agenda_page(text):
            continue
        first_line = _first_text_line(text)
        parsed = _parse_numbered_slide_title(first_line or "")
        if not parsed:
            continue
        chapter_no, title = parsed
        if chapter_no not in agenda_titles:
            continue

        chapter_structure = str(chapter_no)
        if not any(item.get("structure") == chapter_structure for item in items):
            items.append(
                {
                    "structure": chapter_structure,
                    "title": agenda_titles[chapter_no],
                    "physical_index": page_index,
                    "level": 1,
                }
            )

        slide_key = (chapter_no, title)
        if slide_key in seen_slides:
            continue
        seen_slides.add(slide_key)
        items.append(
            {
                "structure": _normalize_slide_structure(first_line or "", chapter_no, items),
                "title": title,
                "physical_index": page_index,
                "level": 2,
            }
        )

    if len(items) < 5:
        return None

    print(
        f"[SLIDE-OUTLINE] built outline: "
        f"chapters={sum(1 for item in items if item.get('level') == 1)}, "
        f"slides={sum(1 for item in items if item.get('level') == 2)}"
    )
    return {
        "toc_items": items,
        "source": "slide_outline",
        "mapped": True,
        "semi_frozen": True,
    }


def _first_text_line(text: str) -> Optional[str]:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _parse_numbered_slide_title(line: str) -> Optional[tuple[int, str]]:
    match = re.match(r"^(\d{1,2})\.(\d{1,2})\s+(.+)$", line.strip())
    if not match:
        return None
    chapter_no = int(match.group(1))
    title = f"{match.group(1)}.{match.group(2)} {match.group(3).strip()}"
    return chapter_no, title


def _slide_chapter_title(title: str) -> str:
    cleaned = re.sub(r"^\d{1,2}\.\d{1,2}\s+", "", title).strip()
    return cleaned.split("—")[0].split("-")[0].strip() or cleaned


def _collect_first_slide_titles(page_texts: List[str]) -> Dict[int, str]:
    result: Dict[int, str] = {}
    for text in page_texts:
        if is_agenda_page(text):
            continue
        parsed = _parse_numbered_slide_title(_first_text_line(text) or "")
        if not parsed:
            continue
        chapter_no, title = parsed
        result.setdefault(chapter_no, _slide_chapter_title(title))
    return result


def _normalize_slide_structure(line: str, chapter_no: int, items: List[Dict[str, Any]]) -> str:
    sibling_count = sum(
        1
        for item in items
        if str(item.get("structure", "")).startswith(f"{chapter_no}.")
    )
    return f"{chapter_no}.{sibling_count + 1}"


def _extract_agenda_title_order(page_texts: List[str]) -> List[str]:
    candidates: List[List[str]] = []
    for text in page_texts:
        if not is_agenda_page(text):
            continue
        parsed = _parse_agenda_titles(text)
        if parsed:
            candidates.append(parsed)

    if not candidates:
        return []

    return Counter(tuple(candidate) for candidate in candidates).most_common(1)[0][0]


def _parse_agenda_titles(text: str) -> List[str]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    titles: List[str] = []
    for line in lines:
        if line in AGENDA_KEYWORDS:
            continue
        if line in CHINESE_SECTION_NUMBERS:
            continue
        if _parse_numbered_slide_title(line):
            continue
        if 4 <= len(line) <= 60:
            titles.append(line)
    return titles


def _align_agenda_titles(
    agenda_order: List[str],
    slide_first_titles: Dict[int, str],
) -> Dict[int, str]:
    remaining = list(agenda_order)
    result: Dict[int, str] = {}

    for chapter_no in sorted(slide_first_titles):
        slide_title = slide_first_titles[chapter_no]
        match_index = None
        for idx, agenda_title in enumerate(remaining):
            if _titles_match(agenda_title, slide_title):
                match_index = idx
                break
        if match_index is None:
            match_index = 0 if remaining else None
        if match_index is not None:
            result[chapter_no] = remaining.pop(match_index)
        else:
            result[chapter_no] = slide_title

    return result


def _titles_match(agenda_title: str, slide_title: str) -> bool:
    compact_agenda = re.sub(r"\s+", "", agenda_title)
    compact_slide = re.sub(r"\s+", "", slide_title)
    if not compact_agenda or not compact_slide:
        return False
    return compact_agenda in compact_slide or compact_slide in compact_agenda
