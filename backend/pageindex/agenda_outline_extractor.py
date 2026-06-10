"""Deterministic outline extraction for agenda/menu based report PDFs."""

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


AGENDA_KEYWORDS = {"目录", "Agenda", "AGENDA", "Contents", "CONTENTS"}
HEADER_PREFIXES = (
    "请务必阅读正文之后的免责声明",
    "资料来源：",
    "作者：",
)
SKIP_TITLE_PREFIXES = ("图：", "表：", "Figure", "Table")
APPENDIX_TITLES = {"免责声明", "国信证券经济研究所", "联系方式"}
TABLE_HEADER_TITLES = {"应用方向", "标的", "公司", "当前市值", "多模态"}


def is_agenda_page(text: str) -> bool:
    sections = extract_agenda_sections(text)
    if len(sections) < 3:
        return False
    lines = _clean_lines(text)
    return any(line in AGENDA_KEYWORDS for line in lines)


def extract_agenda_sections(text: str) -> List[Dict[str, Any]]:
    lines = _clean_lines(text)
    sections: List[Dict[str, Any]] = []
    pending_title: Optional[str] = None

    for line in lines:
        if _is_noise_line(line) or line in AGENDA_KEYWORDS:
            continue
        number = _parse_section_number(line)
        if number is not None:
            if pending_title:
                sections.append({"number": number, "title": pending_title})
                pending_title = None
            continue
        if _looks_like_agenda_title(line):
            pending_title = line

    return _dedupe_sections(sections)


def extract_page_title(text: str) -> Optional[str]:
    lines = _clean_lines(text)
    meaningful = [line for line in lines if not _is_noise_line(line)]
    if "应用方向" in meaningful[:3] and "标的" in meaningful[:4]:
        return None
    candidates = [
        line
        for line in lines
        if not _is_noise_line(line)
        and line not in AGENDA_KEYWORDS
        and not _is_bullet_line(line)
        and not _looks_like_source_line(line)
    ]

    for line in candidates:
        if line in APPENDIX_TITLES:
            return line
        if line in TABLE_HEADER_TITLES:
            continue
        if _is_generic_table_or_figure_title(line):
            continue
        if line.endswith("："):
            next_line = _next_title_continuation(line, candidates)
            if next_line:
                return f"{line}{next_line}"
        if _is_good_page_title(line):
            return line
    return None


def is_agenda_outline_document(analysis: Dict[str, Any]) -> bool:
    page_texts = analysis.get("page_texts") or []
    page_count = int(analysis.get("page_count") or len(page_texts))
    if page_count < 8 or not page_texts:
        return False
    if float(analysis.get("text_coverage") or 0.0) < 0.8:
        return False

    agenda_pages = _find_agenda_pages(page_texts)
    if len(agenda_pages) < 2:
        return False

    common_sections = _common_agenda_sections(page_texts, agenda_pages)
    if not (3 <= len(common_sections) <= 8):
        return False

    titled_pages = [
        idx
        for idx, text in enumerate(page_texts, start=1)
        if idx not in agenda_pages and extract_page_title(text)
    ]
    return len(titled_pages) >= len(common_sections)


def build_agenda_outline(analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    page_texts = analysis.get("page_texts") or []
    if not is_agenda_outline_document(analysis):
        return None

    agenda_pages = _find_agenda_pages(page_texts)
    sections = _common_agenda_sections(page_texts, agenda_pages)
    if not sections:
        return None

    items: List[Dict[str, Any]] = []
    preface_pages = [idx for idx in range(1, min(agenda_pages) if agenda_pages else 1)]
    if preface_pages:
        items.append(
            {
                "structure": "0",
                "title": "Preface",
                "physical_index": preface_pages[0],
                "start_index": preface_pages[0],
                "end_index": min(agenda_pages) if agenda_pages else preface_pages[-1],
                "_fixed_range": True,
                "level": 1,
            }
        )
        for offset, page in enumerate(preface_pages, start=1):
            title = extract_page_title(page_texts[page - 1])
            if title:
                items.append(
                    {
                        "structure": f"0.{offset}",
                        "title": title,
                        "physical_index": page,
                        "start_index": page,
                        "end_index": page,
                        "_fixed_range": True,
                        "level": 2,
                    }
                )

    section_ranges = _section_ranges(agenda_pages, sections, page_texts)
    for section_index, section in enumerate(sections, start=1):
        content_pages = section_ranges.get(section_index, [])
        if not content_pages:
            continue
        items.append(
            {
                "structure": str(section_index),
                "title": section["title"],
                "physical_index": content_pages[0],
                "start_index": content_pages[0],
                "end_index": _parent_end_for_section(section_index, agenda_pages, content_pages),
                "_fixed_range": True,
                "level": 1,
            }
        )
        titled_pages = [
            page
            for page in content_pages
            if extract_page_title(page_texts[page - 1])
            and extract_page_title(page_texts[page - 1]) != section["title"]
        ]
        for child_index, page in enumerate(titled_pages, start=1):
            title = extract_page_title(page_texts[page - 1])
            next_page = titled_pages[child_index] if child_index < len(titled_pages) else content_pages[-1] + 1
            items.append(
                {
                    "structure": f"{section_index}.{child_index}",
                    "title": title,
                    "physical_index": page,
                    "start_index": page,
                    "end_index": max(page, next_page - 1),
                    "_fixed_range": True,
                    "level": 2,
                }
            )

    appendix_pages = _appendix_pages(page_texts, agenda_pages, section_ranges)
    if appendix_pages:
        items.append(
            {
                "structure": "A",
                "title": "Appendix",
                "physical_index": appendix_pages[0],
                "start_index": appendix_pages[0],
                "end_index": appendix_pages[-1],
                "_fixed_range": True,
                "level": 1,
            }
        )
        for child_index, page in enumerate(appendix_pages, start=1):
            title = extract_page_title(page_texts[page - 1])
            if not title:
                continue
            items.append(
                {
                    "structure": f"A.{child_index}",
                    "title": title,
                    "physical_index": page,
                    "start_index": page,
                    "end_index": page,
                    "_fixed_range": True,
                    "level": 2,
                }
            )

    if len(items) < len(sections) + 3:
        return None

    print(
        f"[AGENDA-OUTLINE] built outline: "
        f"sections={len(sections)}, items={len(items)}, agenda_pages={agenda_pages}"
    )
    return {
        "toc_items": items,
        "source": "agenda_outline",
        "mapped": True,
        "semi_frozen": True,
    }


def _clean_lines(text: str) -> List[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _is_noise_line(line: str) -> bool:
    if any(line.startswith(prefix) for prefix in HEADER_PREFIXES):
        return True
    if re.match(r"^\d{4}年\d{1,2}月\d{1,2}日$", line):
        return True
    if re.match(r"^\d{2,4}[-\d\s]+$", line):
        return True
    if "@" in line and "." in line:
        return True
    return False


def _is_bullet_line(line: str) -> bool:
    return bool(re.match(r"^[uØ•●]\s*", line))


def _looks_like_source_line(line: str) -> bool:
    return line.startswith("资料来源") or line.startswith("数据来源")


def _parse_section_number(line: str) -> Optional[int]:
    stripped = line.strip()
    if re.match(r"^0?[1-9]$", stripped):
        return int(stripped)
    match = re.match(r"^0?([1-9])\s+(.+)$", stripped)
    if match:
        return int(match.group(1))
    return None


def _looks_like_agenda_title(line: str) -> bool:
    if len(line) < 2 or len(line) > 40:
        return False
    if _is_bullet_line(line) or _is_generic_table_or_figure_title(line):
        return False
    if re.match(r"^\d", line):
        return False
    return True


def _is_good_page_title(line: str) -> bool:
    if len(line) < 2 or len(line) > 60:
        return False
    if re.match(r"^\d{4}年", line):
        return False
    return True


def _next_title_continuation(current: str, candidates: List[str]) -> Optional[str]:
    try:
        index = candidates.index(current)
    except ValueError:
        return None
    for line in candidates[index + 1:index + 3]:
        if _is_good_page_title(line) and not _is_bullet_line(line):
            return line
    return None


def _is_generic_table_or_figure_title(line: str) -> bool:
    return line.startswith(SKIP_TITLE_PREFIXES)


def _dedupe_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    seen = set()
    for section in sections:
        key = (section["number"], section["title"])
        if key in seen:
            continue
        seen.add(key)
        result.append(section)
    return sorted(result, key=lambda section: section["number"])


def _find_agenda_pages(page_texts: List[str]) -> List[int]:
    return [idx for idx, text in enumerate(page_texts, start=1) if is_agenda_page(text)]


def _common_agenda_sections(page_texts: List[str], agenda_pages: List[int]) -> List[Dict[str, Any]]:
    section_sets = [
        tuple((section["number"], section["title"]) for section in extract_agenda_sections(page_texts[page - 1]))
        for page in agenda_pages
    ]
    if not section_sets:
        return []
    common = Counter(section_sets).most_common(1)[0][0]
    return [{"number": number, "title": title} for number, title in common]


def _section_ranges(
    agenda_pages: List[int],
    sections: List[Dict[str, Any]],
    page_texts: List[str],
) -> Dict[int, List[int]]:
    page_count = len(page_texts)
    ranges: Dict[int, List[int]] = {}
    for idx, section in enumerate(sections, start=1):
        if idx - 1 >= len(agenda_pages):
            continue
        start = agenda_pages[idx - 1] + 1
        end = (agenda_pages[idx] - 1) if idx < len(agenda_pages) else page_count
        for page in range(start, end + 1):
            title = extract_page_title(page_texts[page - 1])
            if title in APPENDIX_TITLES:
                end = page - 1
                break
        ranges[idx] = [
            page
            for page in range(start, end + 1)
            if page <= page_count and page not in agenda_pages
        ]
    return ranges


def _appendix_pages(
    page_texts: List[str],
    agenda_pages: List[int],
    section_ranges: Dict[int, List[int]],
) -> List[int]:
    assigned = set(agenda_pages)
    for pages in section_ranges.values():
        assigned.update(pages)

    appendix = []
    for page, text in enumerate(page_texts, start=1):
        if page in assigned:
            continue
        title = extract_page_title(text)
        if title in APPENDIX_TITLES:
            appendix.append(page)
    return appendix


def _parent_end_for_section(section_index: int, agenda_pages: List[int], content_pages: List[int]) -> int:
    if section_index < len(agenda_pages):
        return agenda_pages[section_index]
    return content_pages[-1]
