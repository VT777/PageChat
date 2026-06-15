"""Extract TOC candidates from OCR layout pages."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pageindex.layout.document_layout import DocumentLayout, OCRLayoutLine


class OCRTOCPageExtractor:
    def extract(self, layout: DocumentLayout) -> Optional[Dict[str, Any]]:
        toc_pages = [page for page in layout.pages if float(page.features.get("toc_score") or 0.0) >= 0.5]
        items: List[Dict[str, Any]] = []
        for page in toc_pages:
            page_items = _extract_page_items(page.page, page.width, page.lines)
            items.extend(page_items)
        if not items:
            return None
        monotonic = _is_monotonic([item.get("page") for item in items])
        title_presence_score = 1.0 if items else 0.0
        page_mapping_score = 1.0 if monotonic else 0.45
        raw_confidence = min(0.95, 0.35 + 0.3 * page_mapping_score + 0.2 * title_presence_score + 0.1 * len(toc_pages))
        return {
            "candidate_id": "ocr_toc_page_001",
            "source": "ocr_toc_page",
            "cost_level": "medium",
            "items": items,
            "raw_confidence": raw_confidence,
            "evidence": {
                "toc_pages": [page.page for page in toc_pages],
                "page_monotonic": monotonic,
                "page_mapping_score": page_mapping_score,
                "title_presence_score": title_presence_score,
            },
        }


def _extract_page_items(page_num: int, page_width: int, lines: List[OCRLayoutLine]) -> List[Dict[str, Any]]:
    rows = _group_visual_rows(lines)
    number_column_x = _stable_number_column_x(rows, page_width)
    items: List[Dict[str, Any]] = []
    pending_title = ""
    pending_bbox: List[float] = []
    pending_score = 1.0
    pending_x0 = 0.0

    for row in rows:
        if _is_toc_heading(row.text):
            continue
        inline_title, inline_page = _split_inline_page(row.text)
        logical_page = inline_page
        title_text = inline_title
        number_line = row.right_number(number_column_x, page_width)
        if logical_page is None and number_line is not None:
            logical_page = _line_page_number(number_line.text)
            title_text = row.left_text(excluding=number_line)
        if logical_page is None:
            clean_pending = _clean_title(row.text)
            if clean_pending:
                if pending_title:
                    pending_title = f"{pending_title} {clean_pending}"
                    pending_bbox = _merge_box(pending_bbox, row.box)
                    pending_score = min(pending_score, row.score)
                else:
                    pending_title = clean_pending
                    pending_bbox = list(row.box)
                    pending_score = row.score
                    pending_x0 = row.x0
            continue
        clean_title = _clean_title(title_text)
        if pending_title and _looks_like_continuation(clean_title, pending_title, row.x0):
            clean_title = f"{pending_title} {clean_title}".strip()
            bbox = _merge_box(pending_bbox, row.box)
            score = min(pending_score, row.score)
            x0 = pending_x0
        else:
            bbox = list(row.box)
            score = row.score
            x0 = row.x0
        pending_title = ""
        pending_bbox = []
        pending_score = 1.0
        if not clean_title:
            continue
        level = _level_for_title(clean_title, x0, [r.as_line() for r in rows])
        items.append(
            {
                "title": clean_title,
                "level": level,
                "page": logical_page,
                "physical_index": None,
                "source_page": page_num,
                "bbox": bbox,
                "confidence": min(0.99, float(score or 0.0)),
                "nodes": [],
            }
        )
    return items


class _VisualRow:
    def __init__(self, lines: List[OCRLayoutLine]) -> None:
        self.lines = sorted(lines, key=lambda line: line.x0)
        self.text = " ".join(line.text.strip() for line in self.lines if line.text.strip())
        self.box = _merge_box([], *[line.box for line in self.lines])
        self.score = min((float(line.score or 0.0) for line in self.lines), default=1.0)
        self.x0 = min((line.x0 for line in self.lines), default=0.0)
        self.y0 = min((line.y0 for line in self.lines), default=0.0)
        self.y1 = max((line.y1 for line in self.lines), default=0.0)

    @property
    def y_center(self) -> float:
        return self.y0 + max(0.0, self.y1 - self.y0) / 2

    def as_line(self) -> OCRLayoutLine:
        return OCRLayoutLine(text=self.text, score=self.score, box=list(self.box))

    def right_number(self, number_column_x: float, page_width: int) -> Optional[OCRLayoutLine]:
        candidates = [line for line in self.lines if _line_page_number(line.text) is not None]
        if not candidates:
            return None
        right_candidates = [
            line
            for line in candidates
            if (number_column_x and line.x0 >= number_column_x - 40)
            or (page_width and line.x1 >= page_width * 0.60)
        ]
        return max(right_candidates or candidates, key=lambda line: line.x1)

    def left_text(self, *, excluding: OCRLayoutLine) -> str:
        parts = [line.text.strip() for line in self.lines if line is not excluding and line.text.strip()]
        return " ".join(parts)


def _group_visual_rows(lines: List[OCRLayoutLine]) -> List[_VisualRow]:
    rows: List[List[OCRLayoutLine]] = []
    for line in sorted([line for line in lines if line.text.strip()], key=lambda item: (item.y_center, item.x0)):
        placed = False
        for row in rows:
            center = sum(item.y_center for item in row) / len(row)
            median_height = max(12.0, sum(max(1.0, item.height) for item in row) / len(row))
            if abs(line.y_center - center) <= median_height * 0.55:
                row.append(line)
                placed = True
                break
        if not placed:
            rows.append([line])
    return [_VisualRow(row) for row in rows]


def _stable_number_column_x(rows: List[_VisualRow], page_width: int) -> float:
    xs = []
    for row in rows:
        for line in row.lines:
            if _line_page_number(line.text) is not None and (not page_width or line.x1 >= page_width * 0.60):
                xs.append(line.x0)
    if not xs:
        return 0.0
    return sorted(xs)[len(xs) // 2]


def _looks_like_continuation(current_title: str, pending_title: str, current_x0: float) -> bool:
    if not pending_title or not current_title:
        return False
    if re.match(r"^\d+(?:\.\d+)*\b", current_title):
        return False
    return current_x0 >= 0.0


def _merge_box(base: List[float], *boxes: List[float]) -> List[float]:
    values = [box for box in ([base] if base else []) + list(boxes) if len(box) >= 4]
    if not values:
        return []
    return [
        min(float(box[0]) for box in values),
        min(float(box[1]) for box in values),
        max(float(box[2]) for box in values),
        max(float(box[3]) for box in values),
    ]


def _nearest_number(title: OCRLayoutLine, number_lines: List[OCRLayoutLine]) -> Optional[OCRLayoutLine]:
    candidates = [line for line in number_lines if abs(line.y_center - title.y_center) <= max(18, title.height)]
    if not candidates:
        return None
    return min(candidates, key=lambda line: abs(line.y_center - title.y_center))


def _split_inline_page(text: str) -> Tuple[str, Optional[int]]:
    match = re.match(r"^(.*?)(?:\.{2,}|\s{2,})(\d{1,4})$", text.strip())
    if not match:
        return text, None
    return match.group(1), int(match.group(2))


def _line_page_number(text: str) -> Optional[int]:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    match = re.search(r"(\d{1,4})\s*$", stripped)
    if not match:
        return None
    prefix = stripped[: match.start(1)].strip()
    if prefix and not re.fullmatch(r"[\s.\u2026·•\-–—_]+", prefix):
        return None
    return int(match.group(1))


def _clean_title(text: str) -> str:
    return re.sub(r"[\s.\u2026·•\-–—_]+$", "", str(text or "").strip()).strip()


def _level_for_title(title: str, x0: float, title_lines: List[OCRLayoutLine]) -> int:
    if re.match(r"^\d+\.\d+", title.strip()):
        return 2
    if re.match(r"^\d+[\s.、]", title.strip()):
        return 1
    min_x = min((line.x0 for line in title_lines), default=x0)
    return 2 if x0 - min_x >= 30 else 1


def _is_toc_heading(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"目录", "contents", "table of contents"}


def _is_monotonic(values: List[Any]) -> bool:
    pages = [int(value) for value in values if isinstance(value, int)]
    return all(left <= right for left, right in zip(pages, pages[1:]))
