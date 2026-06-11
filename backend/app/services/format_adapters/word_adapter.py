from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from app.services.format_adapters.base import ContentBlock, DocumentContent, IndexNode

MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE = 12000


def _xml_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _summary(text: str, max_len: int = 180) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= max_len else clean[: max_len - 1] + "..."


def _error_content(file_path: Path, exc: Exception) -> DocumentContent:
    return DocumentContent(
        format="docx",
        title=file_path.name,
        doc_description=f"Could not parse Word file: {file_path.name}",
        unit_type="paragraph",
        unit_count=0,
        nodes=[],
        blocks=[],
        metadata={"adapter": "canonical_docx", "parse_status": "error", "error": str(exc)},
    )


def _style_levels(zf: zipfile.ZipFile) -> dict[str, int]:
    if "word/styles.xml" not in zf.namelist():
        return {}
    levels: dict[str, int] = {}
    root = ET.fromstring(zf.read("word/styles.xml"))
    for style in root.iter():
        if _xml_ns(style.tag) != "style":
            continue
        style_id = style.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId") or style.attrib.get("styleId")
        text = style_id or ""
        for child in style:
            if _xml_ns(child.tag) == "name":
                text += " " + (child.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") or child.attrib.get("val") or "")
        match = re.search(r"heading\s*([1-9])", text, re.IGNORECASE)
        if match and style_id:
            levels[style_id] = int(match.group(1))
    return levels


def _paragraph_text(p: ET.Element) -> str:
    return "".join(child.text or "" for child in p.iter() if _xml_ns(child.tag) == "t").strip()


def _paragraph_style(p: ET.Element) -> str:
    for child in p.iter():
        if _xml_ns(child.tag) == "pStyle":
            return child.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val") or child.attrib.get("val") or ""
    return ""


def _table_rows(tbl: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tbl:
        if _xml_ns(tr.tag) != "tr":
            continue
        row: list[str] = []
        for tc in tr:
            if _xml_ns(tc.tag) == "tc":
                row.append(" ".join(_paragraph_text(p) for p in tc.iter() if _xml_ns(p.tag) == "p").strip())
        if any(row):
            rows.append(row)
    return rows


def _visual_count(root: ET.Element, zf: zipfile.ZipFile) -> int:
    xml_count = sum(1 for child in root.iter() if _xml_ns(child.tag) in {"drawing", "pic"})
    media_count = sum(1 for name in zf.namelist() if name.startswith("word/media/"))
    return max(xml_count, media_count)


def parse_docx(file_path: Path) -> DocumentContent:
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            if "word/document.xml" not in zf.namelist():
                raise ValueError("word/document.xml is missing")
            levels = _style_levels(zf)
            root = ET.fromstring(zf.read("word/document.xml"))
            image_count = _visual_count(root, zf)
    except Exception as exc:
        return _error_content(file_path, exc)

    paragraphs: list[dict[str, Any]] = []
    blocks: list[ContentBlock] = []
    para_num = 0
    table_num = 0
    for element in root.iter():
        tag = _xml_ns(element.tag)
        if tag == "p":
            para_num += 1
            text = _paragraph_text(element)
            style = _paragraph_style(element)
            level = levels.get(style)
            if not level:
                numbered = re.match(r"^(\d+(?:\.\d+){0,4})\s+", text)
                if numbered:
                    level = min(numbered.group(1).count(".") + 1, 6)
            if text:
                paragraphs.append({"num": para_num, "text": text, "level": level})
                blocks.append(
                    ContentBlock(
                        id=f"para_{para_num}",
                        type="heading" if level else "paragraph",
                        content=text,
                        metadata={"paragraph_number": para_num, "level": level},
                        source_anchor={
                            "format": "docx",
                            "unit_type": "paragraph",
                            "start_paragraph": para_num,
                            "end_paragraph": para_num,
                        },
                    )
                )
        elif tag == "tbl":
            table_num += 1
            rows = _table_rows(element)
            if rows:
                blocks.append(
                    ContentBlock(
                        id=f"table_{table_num}",
                        type="table",
                        content={"rows": rows},
                        metadata={"table_number": table_num, "row_count": len(rows)},
                        source_anchor={
                            "format": "docx",
                            "unit_type": "paragraph",
                            "start_paragraph": max(1, para_num),
                            "end_paragraph": max(1, para_num),
                        },
                    )
                )

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for para in paragraphs:
        if para.get("level"):
            if current:
                sections.append(current)
            current = {
                "title": para["text"],
                "level": int(para["level"]),
                "start": int(para["num"]),
                "end": int(para["num"]),
                "texts": [para["text"]],
            }
            continue
        if current is None:
            current = {"title": "Document start", "level": 1, "start": int(para["num"]), "end": int(para["num"]), "texts": []}
        current["texts"].append(para["text"])
        current["end"] = int(para["num"])
    if current:
        sections.append(current)

    nodes: list[IndexNode] = []
    for section in sections:
        text = "\n".join(section["texts"]).strip()
        if not text:
            continue
        nodes.append(
            IndexNode(
                node_id=f"para_{section['start']}_{section['end']}",
                title=str(section["title"]),
                summary=_summary(text),
                text=text[:MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE],
                start_index=int(section["start"]),
                end_index=int(section["end"]),
                source_anchor={
                    "format": "docx",
                    "unit_type": "paragraph",
                    "start_paragraph": int(section["start"]),
                    "end_paragraph": int(section["end"]),
                },
                level=int(section["level"]),
            )
        )

    needs_visual = image_count > 0 and sum(len(p["text"]) for p in paragraphs) < 40
    return DocumentContent(
        format="docx",
        title=file_path.name,
        doc_description=nodes[0].summary if nodes else f"Word document: {file_path.name}",
        unit_type="paragraph",
        unit_count=para_num,
        nodes=nodes,
        blocks=blocks,
        metadata={
            "adapter": "canonical_docx",
            "paragraph_count": para_num,
            "image_count": image_count,
            "needs_visual_enhancement": needs_visual,
            **({"visual_reason": "document has little text and embedded images"} if needs_visual else {}),
        },
    )
