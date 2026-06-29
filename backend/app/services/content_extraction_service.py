"""
多格式文档内容提取服务
用于前端预览时获取文档的完整内容
"""

import csv
import io
import re
import zipfile
import base64
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import xml.etree.ElementTree as ET


@dataclass
class ContentBlock:
    """内容块，用于结构化展示"""

    id: str
    type: str  # 'text', 'heading', 'image', 'table', 'slide'
    content: Any
    metadata: Dict[str, Any]
    source_anchor: Optional[Dict[str, Any]] = None


class ContentExtractionService:
    """文档内容提取服务"""

    def __init__(self):
        self.supported_formats = {
            ".txt",
            ".md",
            ".markdown",
            ".csv",
            ".tsv",
            ".xlsx",
            ".docx",
            ".pptx",
        }

    def extract_content(
        self, file_path: Path, format_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        提取文档内容

        Returns:
            {
                "format": str,
                "blocks": List[ContentBlock],
                "metadata": Dict[str, Any]
            }
        """
        suffix = (format_hint or file_path.suffix).lower()

        canonical = self._extract_canonical_content(file_path, suffix)
        if canonical is not None:
            return canonical

        if suffix == ".txt":
            return self._extract_txt_content(file_path)
        elif suffix in [".md", ".markdown"]:
            return self._extract_markdown_content(file_path)
        elif suffix == ".csv":
            return self._extract_csv_content(file_path, delimiter=",")
        elif suffix == ".tsv":
            return self._extract_csv_content(file_path, delimiter="\t")
        elif suffix == ".xlsx":
            return self._extract_xlsx_content(file_path)
        elif suffix == ".docx":
            return self._extract_docx_content(file_path)
        elif suffix == ".pptx":
            return self._extract_pptx_content(file_path)
        else:
            raise ValueError(f"Unsupported format: {suffix}")

    def _extract_canonical_content(
        self, file_path: Path, suffix: str
    ) -> Optional[Dict[str, Any]]:
        try:
            from app.services.format_adapters import (
                parse_docx,
                parse_markdown,
                parse_pptx,
                parse_table,
                parse_text,
            )

            if suffix == ".txt":
                content = parse_text(file_path)
            elif suffix in {".md", ".markdown"}:
                content = parse_markdown(file_path)
            elif suffix in {".csv", ".tsv", ".xlsx"}:
                content = parse_table(file_path)
            elif suffix == ".docx":
                content = parse_docx(file_path)
            elif suffix == ".pptx":
                content = parse_pptx(file_path)
            else:
                return None
            payload: Dict[str, Any] = {
                "format": content.format,
                "blocks": [block.to_dict() for block in content.blocks],
                "metadata": dict(content.metadata),
            }
            if "image_count" in content.metadata:
                payload["images"] = []
            return payload
        except Exception:
            return None

    def _extract_txt_content(self, file_path: Path) -> Dict[str, Any]:
        """提取 TXT 内容"""
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.split("\n")

        blocks = []
        for i, line in enumerate(lines, start=1):
            blocks.append(
                ContentBlock(
                    id=f"line_{i}",
                    type="text",
                    content=line,
                    metadata={"line_number": i},
                    source_anchor={
                        "format": "txt",
                        "unit_type": "line",
                        "start_line": i,
                        "end_line": i,
                    },
                )
            )

        return {
            "format": "txt",
            "blocks": [self._block_to_dict(b) for b in blocks],
            "metadata": {"total_lines": len(lines), "char_count": len(text)},
        }

    def _extract_markdown_content(self, file_path: Path) -> Dict[str, Any]:
        """提取 Markdown 内容"""
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.split("\n")

        blocks = []
        section_idx = 0

        for i, line in enumerate(lines, start=1):
            # 检测标题
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                section_idx += 1
                blocks.append(
                    ContentBlock(
                        id=f"section_{section_idx}",
                        type="heading",
                        content=line.lstrip("#").strip(),
                        metadata={"line_number": i, "level": level, "raw": line},
                        source_anchor={
                            "format": "markdown",
                            "unit_type": "line",
                            "start_line": i,
                            "end_line": i,
                        },
                    )
                )
            else:
                blocks.append(
                    ContentBlock(
                        id=f"line_{i}",
                        type="text",
                        content=line,
                        metadata={"line_number": i},
                        source_anchor={
                            "format": "markdown",
                            "unit_type": "line",
                            "start_line": i,
                            "end_line": i,
                        },
                    )
                )

        return {
            "format": "markdown",
            "blocks": [self._block_to_dict(b) for b in blocks],
            "metadata": {
                "total_lines": len(lines),
                "char_count": len(text),
                "section_count": section_idx,
            },
        }

    def _extract_csv_content(self, file_path: Path, delimiter: str) -> Dict[str, Any]:
        """提取 CSV/TSV 内容"""
        rows = []
        headers = []

        with open(file_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            for row_idx, row in enumerate(reader):
                if row_idx == 0:
                    headers = row
                rows.append(row)

        return {
            "format": "csv" if delimiter == "," else "tsv",
            "blocks": [
                {
                    "id": f"row_{i}",
                    "type": "table_row",
                    "content": row,
                    "metadata": {"row_index": i},
                    "source_anchor": {
                        "format": "csv" if delimiter == "," else "tsv",
                        "unit_type": "row_range",
                        "start_row": i + 1,
                        "end_row": i + 1,
                    },
                }
                for i, row in enumerate(rows)
            ],
            "metadata": {
                "total_rows": len(rows),
                "total_cols": len(headers) if headers else 0,
                "headers": headers,
                "delimiter": delimiter,
            },
        }

    def _extract_xlsx_content(self, file_path: Path) -> Dict[str, Any]:
        """提取 XLSX 内容"""
        sheets = []

        with zipfile.ZipFile(file_path, "r") as zf:
            shared_strings = self._parse_shared_strings(zf)
            sheet_name_map = self._xlsx_sheet_names(zf)
            sheet_files = [
                n
                for n in zf.namelist()
                if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
            ]
            sheet_files.sort(
                key=lambda x: (
                    int(re.search(r"(\d+)", x).group(1))
                    if re.search(r"(\d+)", x)
                    else 0
                )
            )

            for sheet_file in sheet_files:
                sheet_name = sheet_name_map.get(sheet_file, Path(sheet_file).stem)
                root = ET.fromstring(zf.read(sheet_file))

                rows = []
                max_cols = 0

                for row in root.iter():
                    if self._xml_ns(row.tag) != "row":
                        continue
                    row_num = int(row.attrib.get("r", "0"))
                    row_data = []
                    col_idx = 1

                    for cell in row:
                        if self._xml_ns(cell.tag) != "c":
                            continue
                        val = self._cell_value(cell, shared_strings)
                        row_data.append(
                            {"col": self._col_letters(col_idx), "value": val}
                        )
                        col_idx += 1

                    if row_data:
                        rows.append({"row_number": row_num, "cells": row_data})
                        max_cols = max(max_cols, len(row_data))

                sheets.append(
                    {
                        "name": sheet_name,
                        "rows": rows,
                        "row_count": len(rows),
                        "col_count": max_cols,
                    }
                )

        return {
            "format": "xlsx",
            "blocks": [
                {
                    "id": f"sheet_{i}",
                    "type": "sheet",
                    "content": sheet,
                    "metadata": {
                        "sheet_name": sheet["name"],
                        "row_count": sheet["row_count"],
                        "col_count": sheet["col_count"],
                    },
                    "source_anchor": {
                        "format": "xlsx",
                        "unit_type": "row_range",
                        "sheet": sheet["name"],
                        "start_row": sheet["rows"][0]["row_number"] if sheet["rows"] else 1,
                        "end_row": sheet["rows"][-1]["row_number"] if sheet["rows"] else 1,
                    },
                }
                for i, sheet in enumerate(sheets)
            ],
            "metadata": {
                "sheet_count": len(sheets),
                "sheets": [s["name"] for s in sheets],
            },
        }

    def _extract_docx_content(self, file_path: Path) -> Dict[str, Any]:
        """提取 DOCX 内容为 HTML"""
        blocks = []
        images = []

        with zipfile.ZipFile(file_path, "r") as zf:
            # 读取文档内容
            xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)

            # 收集所有图片
            image_map = {}
            for rel_file in zf.namelist():
                if rel_file.startswith("word/media/"):
                    img_name = Path(rel_file).name
                    img_data = zf.read(rel_file)
                    # 生成图片 hash 作为 ID
                    img_hash = hashlib.md5(img_data).hexdigest()[:8]
                    ext = Path(rel_file).suffix.lower()
                    mime_type = self._get_image_mime_type(ext)
                    b64 = base64.b64encode(img_data).decode("utf-8")
                    image_map[img_name] = {
                        "id": img_hash,
                        "data": f"data:{mime_type};base64,{b64}",
                        "name": img_name,
                    }

            # 解析段落
            para_idx = 0
            for p in root.iter():
                if self._xml_ns(p.tag) != "p":
                    continue

                para_idx += 1
                texts = []
                para_images = []

                for child in p.iter():
                    tag_name = self._xml_ns(child.tag)

                    # 提取文本
                    if tag_name == "t" and child.text:
                        texts.append(child.text)

                    # 提取图片引用
                    if tag_name == "drawing" or tag_name == "pic":
                        # 查找图片关系
                        blip = child.find(
                            ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
                        )
                        if blip is not None:
                            embed = blip.get(
                                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
                            )
                            if embed:
                                # 需要从 relationships 文件查找实际图片路径
                                pass

                text = "".join(texts).strip()
                if text or para_images:
                    blocks.append(
                        ContentBlock(
                            id=f"para_{para_idx}",
                            type="paragraph",
                            content=text,
                            metadata={
                                "paragraph_number": para_idx,
                                "images": para_images,
                            },
                            source_anchor={
                                "format": "docx",
                                "unit_type": "paragraph",
                                "start_paragraph": para_idx,
                                "end_paragraph": para_idx,
                            },
                        )
                    )

            # 简化方案：提取所有图片作为独立块
            for img_name, img_info in image_map.items():
                images.append(img_info)

        return {
            "format": "docx",
            "blocks": [self._block_to_dict(b) for b in blocks],
            "images": images,
            "metadata": {"paragraph_count": len(blocks), "image_count": len(images)},
        }

    def _extract_pptx_content(self, file_path: Path) -> Dict[str, Any]:
        """提取 PPTX 内容为幻灯片列表"""
        slides = []

        with zipfile.ZipFile(file_path, "r") as zf:
            slide_paths = [
                n
                for n in zf.namelist()
                if n.startswith("ppt/slides/")
                and n.endswith(".xml")
                and "_rels" not in n
            ]
            slide_paths.sort(
                key=lambda x: (
                    int(re.search(r"(\d+)", x).group(1))
                    if re.search(r"(\d+)", x)
                    else 0
                )
            )

            for i, slide_path in enumerate(slide_paths, start=1):
                root = ET.fromstring(zf.read(slide_path))
                texts = []

                for el in root.iter():
                    if self._xml_ns(el.tag) == "t" and el.text:
                        t = el.text.strip()
                        if t:
                            texts.append(t)

                slide_text = "\n".join(texts)

                slides.append(
                    {
                        "slide_number": i,
                        "title": texts[0] if texts else f"幻灯片 {i}",
                        "text": slide_text,
                        "text_count": len(texts),
                    }
                )

        return {
            "format": "pptx",
            "blocks": [
                {
                    "id": f"slide_{s['slide_number']}",
                    "type": "slide",
                    "content": s,
                    "metadata": {
                        "slide_number": s["slide_number"],
                        "title": s["title"],
                    },
                    "source_anchor": {
                        "format": "pptx",
                        "unit_type": "slide",
                        "start_slide": s["slide_number"],
                        "end_slide": s["slide_number"],
                    },
                }
                for s in slides
            ],
            "metadata": {"slide_count": len(slides)},
        }

    def _block_to_dict(self, block: ContentBlock) -> Dict[str, Any]:
        """转换 ContentBlock 为 dict"""
        return {
            "id": block.id,
            "type": block.type,
            "content": block.content,
            "metadata": block.metadata,
            "source_anchor": block.source_anchor,
        }

    def _xml_ns(self, tag: str) -> str:
        """提取 XML 标签名（去除命名空间）"""
        return tag.split("}", 1)[-1] if "}" in tag else tag

    def _col_letters(self, col_num: int) -> str:
        """将列号转换为字母（1->A, 2->B, ...）"""
        result = ""
        n = col_num
        while n > 0:
            n, rem = divmod(n - 1, 26)
            result = chr(65 + rem) + result
        return result

    def _parse_shared_strings(self, zf: zipfile.ZipFile) -> List[str]:
        """解析 XLSX 共享字符串"""
        if "xl/sharedStrings.xml" not in zf.namelist():
            return []

        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        values = []
        for si in root:
            if self._xml_ns(si.tag) != "si":
                continue
            parts = []
            for t in si.iter():
                if self._xml_ns(t.tag) == "t" and t.text:
                    parts.append(t.text)
            values.append("".join(parts).strip())
        return values

    def _xlsx_sheet_names(self, zf: zipfile.ZipFile) -> Dict[str, str]:
        """获取 XLSX 工作表名称映射"""
        if "xl/workbook.xml" not in zf.namelist():
            return {}

        root = ET.fromstring(zf.read("xl/workbook.xml"))
        name_map = {}
        for sheet in root.iter():
            if self._xml_ns(sheet.tag) != "sheet":
                continue
            sheet_name = sheet.attrib.get("name") or "Sheet"
            sheet_id = sheet.attrib.get("sheetId")
            if sheet_id:
                name_map[f"xl/worksheets/sheet{sheet_id}.xml"] = sheet_name
        return name_map

    def _cell_value(self, cell: ET.Element, shared_strings: List[str]) -> str:
        """获取 XLSX 单元格值"""
        ctype = cell.attrib.get("t")
        if ctype == "inlineStr":
            parts = []
            for child in cell.iter():
                if self._xml_ns(child.tag) == "t" and child.text:
                    parts.append(child.text)
            return "".join(parts).strip()

        value_el = None
        for child in cell:
            if self._xml_ns(child.tag) == "v":
                value_el = child
                break
        if value_el is None or value_el.text is None:
            return ""

        raw = value_el.text
        if ctype == "s":
            try:
                idx = int(raw)
                return shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
            except ValueError:
                return ""
        return raw.strip()

    def _get_image_mime_type(self, ext: str) -> str:
        """获取图片 MIME 类型"""
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
        }
        return mime_map.get(ext.lower(), "image/png")


# 全局实例
content_extraction_service = ContentExtractionService()
