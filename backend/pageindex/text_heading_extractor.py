"""Rule-based heading extraction for text-rich report PDFs."""

import re
from typing import Any, Dict, List, Optional, Tuple


CN_CHAPTER_NUMBERS = {
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

APPENDIX_NUMBERS = {
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

SECTION_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\s+(.+)")


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip())


def _chapter_number(title: str) -> Optional[int]:
    match = re.match(r"^第([一二三四五六七八九十]+)章", title)
    if not match:
        return None
    value = match.group(1)
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + CN_CHAPTER_NUMBERS.get(value[-1], 0)
    if value.endswith("十") and len(value) > 1:
        return CN_CHAPTER_NUMBERS.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return CN_CHAPTER_NUMBERS.get(left, 1) * 10 + CN_CHAPTER_NUMBERS.get(right, 0)
    return CN_CHAPTER_NUMBERS.get(value)


def _appendix_number(title: str) -> Optional[int]:
    match = re.match(r"^附录([一二三四五六七八九十]+)", title)
    if not match:
        return None
    return APPENDIX_NUMBERS.get(match.group(1))


def _looks_like_numeric_noise(line: str) -> bool:
    tokens = line.split()
    if len(tokens) < 3:
        return False
    numeric = 0
    for token in tokens:
        if re.fullmatch(r"\d+(?:\.\d+)?%?", token):
            numeric += 1
    return numeric / len(tokens) >= 0.8


def _first_heading_line(page_text: str) -> Optional[str]:
    for raw in str(page_text or "").splitlines()[:12]:
        line = _clean_line(raw)
        if not line or line == "目录" or _looks_like_numeric_noise(line):
            continue
        if line.startswith("序言"):
            return line
        if _chapter_number(line) is not None:
            return line
        if SECTION_RE.match(line):
            return line
        if _appendix_number(line) is not None:
            return line
    return None


def is_chapter_skeleton_toc(toc_text: str) -> Dict[str, Any]:
    """Detect a TOC page that lists only top-level chapters without pages."""
    items: List[Dict[str, Any]] = []
    has_page_numbers = False

    for raw in str(toc_text or "").splitlines():
        line = _clean_line(raw)
        if not line or line == "目录":
            continue
        if re.search(r"\s\d{1,3}$", line):
            has_page_numbers = True
        if line.startswith("序言") or _chapter_number(line) is not None:
            items.append({"title": line, "level": 1})

    chapter_count = sum(1 for item in items if _chapter_number(item["title"]) is not None)
    return {
        "is_skeleton": chapter_count >= 3 and not has_page_numbers,
        "has_page_numbers": has_page_numbers,
        "items": items,
    }


def structure_from_title(title: str) -> Optional[str]:
    title = _clean_line(title)
    chapter = _chapter_number(title)
    if chapter is not None:
        return str(chapter)
    section = SECTION_RE.match(title)
    if section:
        return f"{int(section.group(1))}.{int(section.group(2))}"
    appendix = _appendix_number(title)
    if appendix is not None:
        return f"A{appendix}"
    if title.startswith("序言"):
        return "P"
    return None


def _level_from_structure(structure: str) -> int:
    if structure in {"P"} or structure.startswith("A"):
        return 1
    return 2 if "." in structure else 1


def _normalize_section_title(title: str) -> str:
    title = _clean_line(title)
    match = SECTION_RE.match(title)
    if not match:
        return title
    return f"{int(match.group(1))}.{int(match.group(2))} {match.group(3).strip()}"


def extract_text_headings(page_texts: List[str], start_page: int = 1) -> List[Dict[str, Any]]:
    """Extract a stable outline from text page headings."""
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for offset, page_text in enumerate(page_texts):
        physical_page = start_page + offset
        heading = _first_heading_line(page_text)
        if not heading or heading == "目录":
            continue
        structure = structure_from_title(heading)
        if not structure:
            continue
        if structure in seen:
            continue
        seen.add(structure)
        title = _normalize_section_title(heading)
        items.append(
            {
                "structure": structure,
                "title": title,
                "level": _level_from_structure(structure),
                "physical_index": physical_page,
            }
        )

    return items


def repair_numbered_structures(toc_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Repair structure values when titles contain authoritative numbering."""
    repaired: List[Dict[str, Any]] = []
    for item in toc_items:
        updated = dict(item)
        structure = structure_from_title(str(updated.get("title", "")))
        if structure:
            updated["structure"] = structure
            updated["level"] = _level_from_structure(structure)
        repaired.append(updated)
    return repaired


def merge_chapter_skeleton_with_headings(
    skeleton: Dict[str, Any],
    headings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge chapter-only TOC skeleton with body headings."""
    merged_by_structure: Dict[str, Dict[str, Any]] = {
        str(item.get("structure")): dict(item)
        for item in headings
        if item.get("structure")
    }

    for raw_item in skeleton.get("items") or []:
        title = _clean_line(raw_item.get("title", ""))
        if not title:
            continue
        structure = structure_from_title(title)
        if not structure:
            continue
        if structure in merged_by_structure:
            continue

        child_pages = [
            item.get("physical_index")
            for item in headings
            if str(item.get("structure", "")).startswith(f"{structure}.")
            and isinstance(item.get("physical_index"), int)
        ]
        physical_index = min(child_pages) if child_pages else None
        if physical_index is None and structure == "P":
            physical_index = 1
        if physical_index is None:
            continue

        merged_by_structure[structure] = {
            "structure": structure,
            "title": title,
            "level": _level_from_structure(structure),
            "physical_index": physical_index,
        }

    return sorted(
        merged_by_structure.values(),
        key=lambda item: (
            item.get("physical_index") or 10**9,
            _structure_sort_key(str(item.get("structure", ""))),
        ),
    )


def _structure_sort_key(structure: str) -> Tuple[int, int]:
    if structure == "P":
        return (0, 0)
    if structure.startswith("A"):
        try:
            return (1000 + int(structure[1:]), 0)
        except ValueError:
            return (1999, 0)
    if "." in structure:
        left, right = structure.split(".", 1)
        try:
            return (int(left), int(right))
        except ValueError:
            return (999, 999)
    try:
        return (int(structure), 0)
    except ValueError:
        return (999, 999)
