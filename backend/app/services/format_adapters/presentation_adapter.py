from __future__ import annotations

import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from app.services.format_adapters.base import ContentBlock, DocumentContent, IndexNode

MULTIFORMAT_MAX_SLIDES_PER_DECK = 200
MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE = 12000


def _xml_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _sort_key(path: str) -> int:
    match = re.search(r"(\d+)", path)
    return int(match.group(1)) if match else 0


def _summary(text: str, max_len: int = 180) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= max_len else clean[: max_len - 1] + "..."


def _texts(root: ET.Element) -> list[str]:
    return [
        child.text.strip()
        for child in root.iter()
        if _xml_ns(child.tag) == "t" and child.text and child.text.strip()
    ]


def _visual_count(root: ET.Element) -> int:
    return sum(1 for child in root.iter() if _xml_ns(child.tag) in {"pic", "graphicFrame"})


def _error_content(file_path: Path, exc: Exception) -> DocumentContent:
    return DocumentContent(
        format="pptx",
        title=file_path.name,
        doc_description=f"Could not parse PowerPoint file: {file_path.name}",
        unit_type="slide",
        unit_count=0,
        nodes=[],
        blocks=[],
        metadata={"adapter": "canonical_pptx", "parse_status": "error", "error": str(exc)},
    )


def parse_pptx(file_path: Path) -> DocumentContent:
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            slide_paths = [
                name
                for name in zf.namelist()
                if name.startswith("ppt/slides/") and name.endswith(".xml") and "_rels" not in name
            ]
            slide_paths.sort(key=_sort_key)
            notes_paths = { _sort_key(name): name for name in zf.namelist() if name.startswith("ppt/notesSlides/") and name.endswith(".xml") }
            slides: list[dict[str, object]] = []
            for slide_path in slide_paths[:MULTIFORMAT_MAX_SLIDES_PER_DECK]:
                slide_num = _sort_key(slide_path)
                root = ET.fromstring(zf.read(slide_path))
                texts = _texts(root)
                note_texts: list[str] = []
                if slide_num in notes_paths:
                    note_texts = _texts(ET.fromstring(zf.read(notes_paths[slide_num])))
                visual_count = _visual_count(root)
                slides.append({"num": slide_num, "texts": texts, "notes": note_texts, "visual_count": visual_count})
    except Exception as exc:
        return _error_content(file_path, exc)

    nodes: list[IndexNode] = []
    blocks: list[ContentBlock] = []
    needs_visual = False
    for slide in slides:
        slide_num = int(slide["num"])
        texts = list(slide["texts"])
        notes = list(slide["notes"])
        visual_count = int(slide["visual_count"])
        body = "\n".join(texts + notes).strip()
        slide_needs_visual = visual_count > 0 and len(body) < 40
        needs_visual = needs_visual or slide_needs_visual
        anchor = {"format": "pptx", "unit_type": "slide", "start_slide": slide_num, "end_slide": slide_num}
        title = texts[0] if texts else f"Slide {slide_num}"
        nodes.append(
            IndexNode(
                node_id=f"slide_{slide_num}",
                title=title,
                summary=_summary(body) or title,
                text=body[:MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE],
                start_index=slide_num,
                end_index=slide_num,
                source_anchor=anchor,
            )
        )
        blocks.append(
            ContentBlock(
                id=f"slide_{slide_num}",
                type="slide",
                content={"slide_number": slide_num, "title": title, "text": "\n".join(texts), "notes": notes},
                metadata={
                    "slide_number": slide_num,
                    "title": title,
                    "needs_visual_enhancement": slide_needs_visual,
                    **({"visual_reason": "slide has little text and multiple image shapes"} if slide_needs_visual else {}),
                },
                source_anchor=anchor,
            )
        )

    return DocumentContent(
        format="pptx",
        title=file_path.name,
        doc_description=nodes[0].summary if nodes else f"PowerPoint document: {file_path.name}",
        unit_type="slide",
        unit_count=len(slides),
        nodes=nodes,
        blocks=blocks,
        metadata={
            "adapter": "canonical_pptx",
            "slide_count": len(slides),
            "needs_visual_enhancement": needs_visual,
            **({"visual_reason": "slide has little text and multiple image shapes"} if needs_visual else {}),
        },
    )
