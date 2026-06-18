"""Canonical per-page text representation for PDF indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Literal, Sequence, Tuple


PageTextSource = Literal["pdf_text", "ocr", "mixed"]
PageTextQuality = Literal["reliable", "partial", "low"]


@dataclass
class PageTextEntry:
    physical_page: int
    text: str
    source: PageTextSource
    quality: PageTextQuality = "reliable"
    ocr_used: bool = False
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.physical_page = int(self.physical_page)
        self.text = str(self.text or "")
        self.ocr_used = bool(self.ocr_used)
        if self.source not in {"pdf_text", "ocr", "mixed"}:
            raise ValueError(f"Unsupported PageTextEntry source: {self.source}")
        if self.quality not in {"reliable", "partial", "low"}:
            raise ValueError(f"Unsupported PageTextEntry quality: {self.quality}")

    @property
    def token_count(self) -> int:
        return _estimate_tokens(self.text)

    def to_page_list_item(self) -> Tuple[str, int]:
        return self.text, self.token_count

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "physical_page": self.physical_page,
            "text": self.text,
            "source": self.source,
            "quality": self.quality,
            "ocr_used": self.ocr_used,
        }
        if self.diagnostics:
            payload["diagnostics"] = dict(self.diagnostics)
        return payload


class PageTextMap:
    def __init__(self, entries: Iterable[PageTextEntry]) -> None:
        self.entries: List[PageTextEntry] = sorted(
            list(entries),
            key=lambda entry: entry.physical_page,
        )
        self._validate_unique_pages()

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def page_count(self) -> int:
        return len(self.entries)

    def _validate_unique_pages(self) -> None:
        seen: set[int] = set()
        for entry in self.entries:
            if entry.physical_page <= 0:
                raise ValueError("physical_page must be 1-indexed and positive")
            if entry.physical_page in seen:
                raise ValueError(f"duplicate physical_page: {entry.physical_page}")
            seen.add(entry.physical_page)

    def page_texts(self) -> List[str]:
        return [entry.text for entry in self.entries]

    def ocr_page_numbers(self) -> List[int]:
        return [entry.physical_page for entry in self.entries if entry.ocr_used]

    def to_page_list(self) -> List[Tuple[str, int]]:
        return [entry.to_page_list_item() for entry in self.entries]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_count": self.page_count,
            "entries": [entry.to_dict() for entry in self.entries],
            "diagnostics": self.to_diagnostics(),
        }

    def to_diagnostics(self) -> Dict[str, Any]:
        sources: Dict[str, int] = {}
        qualities: Dict[str, int] = {}
        for entry in self.entries:
            sources[entry.source] = sources.get(entry.source, 0) + 1
            qualities[entry.quality] = qualities.get(entry.quality, 0) + 1
        return {
            "page_count": self.page_count,
            "ocr_pages": self.ocr_page_numbers(),
            "ocr_page_count": len(self.ocr_page_numbers()),
            "sources": sources,
            "qualities": qualities,
        }

    @classmethod
    def from_page_list(
        cls,
        page_list: Sequence[Any],
        *,
        source: PageTextSource = "pdf_text",
        quality: PageTextQuality = "reliable",
    ) -> "PageTextMap":
        entries: List[PageTextEntry] = []
        for index, page in enumerate(page_list, start=1):
            text = ""
            if isinstance(page, (list, tuple)) and page:
                text = str(page[0] or "")
            else:
                text = str(page or "")
            entries.append(
                PageTextEntry(
                    physical_page=index,
                    text=text,
                    source=source,
                    quality=quality if text.strip() else "low",
                    ocr_used=source in {"ocr", "mixed"},
                )
            )
        return cls(entries)


def coerce_page_text_map(value: Any) -> PageTextMap:
    if isinstance(value, PageTextMap):
        return value
    if isinstance(value, list):
        entries = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, PageTextEntry):
                entries.append(item)
                continue
            if isinstance(item, dict) and "physical_page" in item:
                entries.append(
                    PageTextEntry(
                        physical_page=int(item.get("physical_page") or index),
                        text=str(item.get("text") or ""),
                        source=item.get("source") or "pdf_text",
                        quality=item.get("quality") or "reliable",
                        ocr_used=bool(item.get("ocr_used")),
                        diagnostics=dict(item.get("diagnostics") or {}),
                    )
                )
                continue
            text = str(item[0] if isinstance(item, (tuple, list)) and item else item or "")
            entries.append(
                PageTextEntry(
                    physical_page=index,
                    text=text,
                    source="pdf_text",
                    quality="reliable" if text.strip() else "low",
                )
            )
        return PageTextMap(entries)
    raise TypeError(f"Cannot coerce {type(value)!r} to PageTextMap")


def _estimate_tokens(text: str) -> int:
    text = str(text or "")
    if not text:
        return 1
    return max(1, int(len(text) * 0.7))
