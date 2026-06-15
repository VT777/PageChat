"""Canonical layout representation for native text and OCR-derived pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Dict, List, Optional


@dataclass
class OCRLayoutLine:
    text: str
    score: float = 1.0
    box: List[float] = field(default_factory=list)
    poly: List[List[float]] = field(default_factory=list)
    numbering: str = ""

    @property
    def x0(self) -> float:
        return float(self.box[0]) if len(self.box) >= 4 else 0.0

    @property
    def y0(self) -> float:
        return float(self.box[1]) if len(self.box) >= 4 else 0.0

    @property
    def x1(self) -> float:
        return float(self.box[2]) if len(self.box) >= 4 else 0.0

    @property
    def y1(self) -> float:
        return float(self.box[3]) if len(self.box) >= 4 else 0.0

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def x_center(self) -> float:
        return self.x0 + self.width / 2

    @property
    def y_center(self) -> float:
        return self.y0 + self.height / 2

    def to_dict(self, page_width: float = 0.0) -> Dict[str, Any]:
        return {
            "text": self.text,
            "score": self.score,
            "box": list(self.box),
            "poly": list(self.poly),
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
            "width": self.width,
            "height": self.height,
            "x_center": self.x_center,
            "y_center": self.y_center,
            "font_size_proxy": self.height,
            "is_centered": bool(page_width and abs(self.x_center - page_width / 2) <= page_width * 0.12),
            "is_right_aligned": bool(page_width and self.x1 >= page_width * 0.85),
            "numbering": self.numbering,
        }


@dataclass
class PPOCRPageResult:
    page_num: int
    width: int = 0
    height: int = 0
    lines: List[OCRLayoutLine] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: str = ""

    @property
    def plain_text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text).strip()


@dataclass
class OCRLayoutPage:
    page: int
    width: int
    height: int
    plain_text: str
    lines: List[OCRLayoutLine]
    features: Dict[str, Any]
    source: str = "ocr"
    markdown: str = ""
    structured_items: List[Dict[str, Any]] = field(default_factory=list)
    source_type: str = "ocr"
    evidence_level: str = "line_box"


@dataclass
class DocumentLayout:
    doc_id: str
    page_count: int
    source_type: str
    pages: List[OCRLayoutPage]

    def page_by_number(self, page_num: int) -> Optional[OCRLayoutPage]:
        return next((page for page in self.pages if page.page == page_num), None)


class DocumentLayoutBuilder:
    def build(
        self,
        *,
        doc_id: str,
        page_count: int,
        ppocr_pages: Optional[List[PPOCRPageResult]] = None,
        native_pages: Optional[List[str]] = None,
    ) -> DocumentLayout:
        pages: List[OCRLayoutPage] = []
        if ppocr_pages:
            for result in sorted(ppocr_pages, key=lambda item: item.page_num):
                pages.append(
                    OCRLayoutPage(
                        page=result.page_num,
                        width=result.width,
                        height=result.height,
                        plain_text=result.plain_text,
                        lines=sorted(result.lines, key=lambda line: (line.y0, line.x0)),
                        features=_page_features(result.width, result.height, result.lines),
                        source="ocr",
                        source_type="ocr",
                        evidence_level="line_box",
                    )
                )
        elif native_pages:
            for index, text in enumerate(native_pages, start=1):
                line_objs = [
                    OCRLayoutLine(text=line.strip(), box=[0, i * 20, 0, i * 20 + 16])
                    for i, line in enumerate(str(text or "").splitlines())
                    if line.strip()
                ]
                pages.append(
                    OCRLayoutPage(
                        page=index,
                        width=0,
                        height=0,
                        plain_text=str(text or ""),
                        lines=line_objs,
                        features=_page_features(0, 0, line_objs),
                        source="native_pdf",
                        source_type="native_pdf",
                        evidence_level="text_only",
                    )
                )

        return DocumentLayout(
            doc_id=doc_id,
            page_count=page_count,
            source_type="ocr" if ppocr_pages else "native_pdf",
            pages=pages,
        )


def _page_features(width: int, height: int, lines: List[OCRLayoutLine]) -> Dict[str, Any]:
    line_heights = [line.height for line in lines if line.height > 0]
    median_line_height = median(line_heights) if line_heights else 0.0
    right_aligned_number_count = sum(
        1
        for line in lines
        if _has_page_number(line.text) and (not width or line.x1 >= width * 0.65)
    )
    plain_text = "\n".join(line.text for line in lines)
    has_toc_keyword = any(keyword in plain_text.lower() for keyword in ("目录", "contents", "table of contents"))
    toc_score = 0.0
    if has_toc_keyword:
        toc_score += 0.45
    if right_aligned_number_count:
        toc_score += min(0.35, right_aligned_number_count * 0.18)
    if len(lines) >= 3:
        toc_score += 0.15
    centered_line_ratio = (
        sum(1 for line in lines if width and abs(line.x_center - width / 2) <= width * 0.12) / len(lines)
        if lines
        else 0.0
    )
    text_area = sum(max(0.0, line.width * line.height) for line in lines)
    page_area = max(1.0, float(width or 1) * float(height or 1))
    return {
        "line_count": len(lines),
        "median_line_height": median_line_height,
        "text_density": min(1.0, text_area / page_area),
        "large_text_ratio": 0.0,
        "centered_line_ratio": centered_line_ratio,
        "right_aligned_number_count": right_aligned_number_count,
        "toc_score": min(1.0, toc_score),
        "divider_score": 0.0,
        "content_score": 0.0 if has_toc_keyword else min(1.0, len(lines) / 20),
    }


def _has_page_number(text: str) -> bool:
    import re

    return bool(re.search(r"\d{1,4}\s*$", str(text or "").strip()))
