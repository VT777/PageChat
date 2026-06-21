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

SECTION_RE = re.compile(r"^([1-9]\d?)\.(\d{1,2})\s+(.+)")
EN_NUMBERED_LINE_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)\.?$")
EN_NUMBERED_TITLE_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)[.)]?\s+(.+)$")

EN_SKIP_EXACT = {
    "annual report",
    "authors",
    "body",
    "paper title",
    "report to congress",
}

EN_SKIP_PREFIXES = (
    "algorithm ",
    "annual report",
    "corollary ",
    "definition ",
    "figure ",
    "fig. ",
    "lemma ",
    "proof ",
    "table ",
    "theorem ",
)

EN_ALLOWED_SINGLE_WORD_HEADINGS = {
    "abstract",
    "acknowledgment",
    "acknowledgement",
    "conclusion",
    "contents",
    "index",
    "introduction",
    "preface",
    "references",
}

EN_SENTENCE_STARTS = (
    "the ",
    "this ",
    "these ",
    "we ",
    "our ",
    "it ",
    "in ",
)


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


def _is_english_noise_line(line: str) -> bool:
    normalized = _clean_line(line)
    if not normalized:
        return True
    lowered = normalized.casefold()
    if lowered in EN_SKIP_EXACT:
        return True
    if lowered.startswith(EN_SKIP_PREFIXES):
        return True
    if lowered.startswith("("):
        return True
    if ":=" in normalized or "∪" in normalized:
        return True
    if _looks_like_short_legend_noise(normalized):
        return True
    if _looks_like_numeric_noise(normalized):
        return True
    if _looks_like_measurement_noise(normalized):
        return True
    if re.fullmatch(r"[\d\s.,:%$()/-]+", normalized):
        return True
    if re.match(r"^\[\d+\]", normalized):
        return True
    if re.match(r"^\d+:", normalized):
        return True
    return False


def _looks_like_short_legend_noise(line: str) -> bool:
    normalized = _clean_line(line)
    if not normalized:
        return False
    if re.search(r"\.\d", normalized):
        return True
    tokens = [token for token in re.split(r"[\s,/]+", normalized) if token]
    if "/" in normalized and len(tokens) >= 2 and all(re.fullmatch(r"[A-Z0-9-]{1,8}", token) for token in tokens):
        return True
    if len(tokens) >= 3 and all(re.fullmatch(r"[A-Z0-9-]{1,4}", token) for token in tokens):
        return True
    comma_parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if len(comma_parts) >= 3:
        acronym_like = sum(1 for part in comma_parts if re.fullmatch(r"[A-Z0-9 .-]{2,18}", part))
        if acronym_like >= 2:
            return True
    return False


def _looks_like_measurement_noise(line: str) -> bool:
    tokens = line.split()
    if len(tokens) < 2:
        return False
    noisy = 0
    for token in tokens:
        if re.fullmatch(r"[\d,.]+[kmbKMB%]?", token):
            noisy += 1
    return noisy / len(tokens) >= 0.6


def _looks_like_section_number(number: str) -> bool:
    parts = str(number or "").split(".")
    if not parts:
        return False
    try:
        numeric = [int(part) for part in parts]
    except ValueError:
        return False
    if any(part != "0" and part.startswith("0") for part in parts):
        return False
    if numeric[0] <= 0 or numeric[0] > 30:
        return False
    if len(numeric) > 1 and any(value <= 0 or value > 50 for value in numeric[1:]):
        return False
    return True


def _is_sentence_like(line: str) -> bool:
    normalized = _clean_line(line)
    if not normalized:
        return True
    lowered = normalized.casefold()
    if normalized.endswith((".", ";", ",")):
        return True
    return lowered.startswith(EN_SENTENCE_STARTS) and len(normalized.split()) >= 5


def _uppercase_ratio(line: str) -> float:
    letters = [char for char in line if char.isalpha()]
    if not letters:
        return 0.0
    uppercase = sum(1 for char in letters if char.upper() == char and char.lower() != char)
    return uppercase / len(letters)


def _looks_like_all_caps_heading(line: str) -> bool:
    normalized = _clean_line(line)
    if _is_english_noise_line(normalized):
        return False
    if len(normalized) < 3 or len(normalized) > 140:
        return False
    words = [word for word in re.split(r"\s+", normalized) if word]
    if len(words) == 1 and normalized.casefold() not in EN_ALLOWED_SINGLE_WORD_HEADINGS:
        return False
    return _uppercase_ratio(normalized) >= 0.75


def _looks_like_title_case_heading(line: str) -> bool:
    normalized = _clean_line(line)
    if _is_english_noise_line(normalized) or _is_sentence_like(normalized):
        return False
    words = [word for word in re.split(r"\s+", normalized) if word]
    if not 2 <= len(words) <= 8:
        return False
    alpha_words = [word for word in words if re.search(r"[A-Za-z]", word)]
    if len(alpha_words) < 2:
        return False
    titleish = sum(
        1
        for word in alpha_words
        if word[:1].isupper() or word.casefold() in {"and", "of", "the", "in", "at", "a", "an"}
    )
    return titleish / len(alpha_words) >= 0.75


def _looks_like_numbered_heading_continuation(line: str) -> bool:
    normalized = _clean_line(line)
    if _is_english_noise_line(normalized) or _is_sentence_like(normalized):
        return False
    words = [word for word in re.split(r"\s+", normalized) if word]
    if not 1 <= len(words) <= 10:
        return False
    alpha_words = [word for word in words if re.search(r"[A-Za-z]", word)]
    if not alpha_words:
        return False
    titleish = sum(
        1
        for word in alpha_words
        if word[:1].isupper() or word.casefold() in {"and", "of", "the", "in", "at", "a", "an"}
    )
    return titleish / len(alpha_words) >= 0.75


def _join_english_heading_lines(lines: List[str], start: int, max_extra: int = 1) -> Tuple[str, int]:
    parts = [_clean_line(lines[start])]
    consumed = 1
    for index in range(start + 1, min(len(lines), start + 1 + max_extra)):
        line = _clean_line(lines[index])
        if not line or _is_english_noise_line(line) or _is_sentence_like(line):
            break
        if _looks_like_all_caps_heading(line) or _looks_like_numbered_heading_continuation(line):
            parts.append(line)
            consumed += 1
            continue
        break
    return " ".join(parts), consumed


def _join_all_caps_heading_lines(lines: List[str], start: int, max_extra: int = 1) -> Tuple[str, int]:
    parts = [_clean_line(lines[start])]
    consumed = 1
    for index in range(start + 1, min(len(lines), start + 1 + max_extra)):
        line = _clean_line(lines[index])
        if not _looks_like_all_caps_heading(line):
            break
        parts.append(line)
        consumed += 1
    return " ".join(parts), consumed


def _english_structure_from_title(title: str, physical_page: int) -> Tuple[str, int]:
    title = _clean_line(title)
    numbered = EN_NUMBERED_TITLE_RE.match(title)
    if numbered:
        number = numbered.group(1)
        return number, 2 if "." in number else 1
    normalized = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    if normalized in {"abstract", "references", "acknowledgment", "acknowledgement"}:
        return normalized, 1
    return f"front-{physical_page}", 1


def _english_heading_items(page_text: str, physical_page: int) -> List[Dict[str, Any]]:
    lines = [
        _clean_line(raw)
        for raw in str(page_text or "").splitlines()[:240]
        if _clean_line(raw)
    ]
    if not lines:
        return []

    items: List[Dict[str, Any]] = []
    consumed_indexes: set[int] = set()
    for index, line in enumerate(lines):
        if index in consumed_indexes:
            continue
        match = EN_NUMBERED_TITLE_RE.match(line)
        if match and not _is_english_noise_line(line):
            if not _looks_like_section_number(match.group(1)):
                continue
            rest = match.group(2).strip()
            if not (_looks_like_all_caps_heading(rest) or _looks_like_numbered_heading_continuation(rest)):
                continue
            title = f"{match.group(1)} {match.group(2).strip()}"
            structure, level = _english_structure_from_title(title, physical_page)
            items.append(
                {
                    "structure": structure,
                    "title": title,
                    "level": level,
                    "physical_index": physical_page,
                    "_line_index": index,
                }
            )
            consumed_indexes.add(index)
            continue

        number_line = EN_NUMBERED_LINE_RE.match(line)
        if number_line and index + 1 < len(lines):
            if not _looks_like_section_number(number_line.group(1)):
                continue
            next_line = lines[index + 1]
            if _looks_like_all_caps_heading(next_line) or _looks_like_numbered_heading_continuation(next_line):
                heading, consumed = _join_english_heading_lines(lines, index + 1, max_extra=1)
                title = f"{number_line.group(1)} {heading}"
                structure, level = _english_structure_from_title(title, physical_page)
                items.append(
                    {
                        "structure": structure,
                        "title": title,
                        "level": level,
                        "physical_index": physical_page,
                        "_line_index": index,
                    }
                )
                consumed_indexes.update(range(index, index + consumed + 1))
                continue

    for index, line in enumerate(lines):
        if index in consumed_indexes:
            continue
        if _looks_like_all_caps_heading(line):
            heading, consumed = _join_all_caps_heading_lines(lines, index, max_extra=1)
            structure, level = _english_structure_from_title(heading, physical_page)
            items.append(
                {
                    "structure": structure,
                    "title": heading,
                    "level": level,
                    "physical_index": physical_page,
                    "_line_index": index,
                }
            )
            consumed_indexes.update(range(index, index + consumed))

    for index, line in enumerate(lines[:4]):
        if index in consumed_indexes:
            continue
        if _looks_like_title_case_heading(line):
            structure, level = _english_structure_from_title(line, physical_page)
            items.append(
                {
                    "structure": structure,
                    "title": line,
                    "level": level,
                    "physical_index": physical_page,
                    "_line_index": index,
                }
            )
            break

    items.sort(key=lambda item: int(item.pop("_line_index", 10**9)))
    return items


def _english_heading_item(page_text: str, physical_page: int) -> Optional[Dict[str, Any]]:
    items = _english_heading_items(page_text, physical_page)
    return items[0] if items else None


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
        if not heading:
            english_items = _english_heading_items(page_text, physical_page)
            for english_item in english_items:
                structure = str(english_item.get("structure") or "")
                if structure in seen:
                    continue
                seen.add(structure)
                items.append(english_item)
            continue
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
