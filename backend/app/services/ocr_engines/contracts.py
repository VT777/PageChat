"""Shared OCR engine contracts used by PageIndex integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


OCRTask = Literal["toc_page", "page_text"]
OCREvidenceLevel = Literal["line_box", "text_only", "model_inferred"]


@dataclass
class OCRLine:
    text: str
    score: float = 1.0
    box: List[float] = field(default_factory=list)
    poly: List[List[float]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "score": float(self.score),
            "box": [float(value) for value in self.box],
            "poly": [[float(value) for value in point] for point in self.poly],
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
            "width": self.width,
            "height": self.height,
            "raw": dict(self.raw),
        }


@dataclass
class OCRPageResult:
    page_num: int
    evidence_level: OCREvidenceLevel
    width: int = 0
    height: int = 0
    lines: List[OCRLine] = field(default_factory=list)
    markdown: str = ""
    structured_items: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    error: str = ""

    @property
    def plain_text(self) -> str:
        if self.markdown.strip():
            return self.markdown.strip()
        return "\n".join(line.text for line in self.lines if line.text).strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_num": int(self.page_num),
            "width": int(self.width),
            "height": int(self.height),
            "evidence_level": self.evidence_level,
            "plain_text": self.plain_text,
            "lines": [line.to_dict() for line in self.lines],
            "markdown": self.markdown,
            "structured_items": [dict(item) for item in self.structured_items],
            "raw": dict(self.raw),
            "ok": bool(self.ok),
            "error": self.error,
        }


@dataclass
class OCRDocumentResult:
    task: OCRTask
    engine_type: str
    model: str
    pages: List[OCRPageResult] = field(default_factory=list)
    profile_id: Optional[str] = None
    profile_version: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "engine_type": self.engine_type,
            "model": self.model,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "diagnostics": dict(self.diagnostics),
            "pages": [page.to_dict() for page in self.pages],
            "raw": dict(self.raw),
        }
