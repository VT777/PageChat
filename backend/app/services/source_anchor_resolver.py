import csv
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from app.models.retrieval import build_source_display_label

MAX_TEXT_LINES = 500
MAX_TABLE_ROWS = 500
MAX_PARAGRAPHS = 300
MAX_SLIDES = 20


def _xml_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _bounded_range(
    start: Any,
    end: Any,
    *,
    default_start: int = 1,
    max_count: int = 500,
) -> tuple[int, int]:
    try:
        start_int = int(start)
    except Exception:
        start_int = default_start
    try:
        end_int = int(end) if end is not None else start_int
    except Exception:
        end_int = start_int

    start_int = max(default_start, start_int)
    end_int = max(start_int, end_int)
    end_int = min(end_int, start_int + max_count - 1)
    return start_int, end_int


def _result(
    *,
    status: str,
    document_name: str,
    anchor: Mapping[str, Any],
    content: str = "",
    reason: str = "",
) -> dict[str, Any]:
    payload = {
        "status": status,
        "content": content,
        "source_anchor": dict(anchor),
        "display_label": build_source_display_label(document_name, anchor),
    }
    if reason:
        payload["reason"] = reason
    return payload


def _resolve_lines(
    file_path: Path, document_name: str, anchor: Mapping[str, Any]
) -> dict[str, Any]:
    start, end = _bounded_range(
        anchor.get("start_line"),
        anchor.get("end_line"),
        max_count=MAX_TEXT_LINES,
    )
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    content = "\n".join(lines[start - 1 : end])
    normalized = dict(anchor)
    normalized["start_line"] = start
    normalized["end_line"] = end
    return _result(
        status="success",
        document_name=document_name,
        anchor=normalized,
        content=content,
    )


def _resolve_rows(
    file_path: Path,
    document_name: str,
    anchor: Mapping[str, Any],
    *,
    delimiter: str,
) -> dict[str, Any]:
    start, end = _bounded_range(
        anchor.get("start_row"),
        anchor.get("end_row"),
        max_count=MAX_TABLE_ROWS,
    )
    selected: list[str] = []
    with open(file_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row_idx, row in enumerate(reader, start=1):
            if start <= row_idx <= end:
                selected.append(delimiter.join(row))
            if row_idx > end:
                break

    normalized = dict(anchor)
    normalized["start_row"] = start
    normalized["end_row"] = end
    return _result(
        status="success",
        document_name=document_name,
        anchor=normalized,
        content="\n".join(selected),
    )


def _docx_paragraphs(file_path: Path) -> list[str]:
    with zipfile.ZipFile(file_path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return []
        root = ET.fromstring(zf.read("word/document.xml"))

    paragraphs: list[str] = []
    for p in root.iter():
        if _xml_ns(p.tag) != "p":
            continue
        parts = [
            child.text
            for child in p.iter()
            if _xml_ns(child.tag) == "t" and child.text
        ]
        paragraphs.append("".join(parts).strip())
    return paragraphs


def _resolve_docx(
    file_path: Path, document_name: str, anchor: Mapping[str, Any]
) -> dict[str, Any]:
    start, end = _bounded_range(
        anchor.get("start_paragraph"),
        anchor.get("end_paragraph"),
        max_count=MAX_PARAGRAPHS,
    )
    paragraphs = _docx_paragraphs(file_path)
    content = "\n".join(p for p in paragraphs[start - 1 : end] if p)
    normalized = dict(anchor)
    normalized["start_paragraph"] = start
    normalized["end_paragraph"] = end
    return _result(
        status="success",
        document_name=document_name,
        anchor=normalized,
        content=content,
    )


def _xlsx_sheet_names(zf: zipfile.ZipFile) -> dict[str, str]:
    if "xl/workbook.xml" not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read("xl/workbook.xml"))
    names: dict[str, str] = {}
    for sheet in root.iter():
        if _xml_ns(sheet.tag) != "sheet":
            continue
        sheet_id = sheet.attrib.get("sheetId")
        if sheet_id:
            names[f"xl/worksheets/sheet{sheet_id}.xml"] = sheet.attrib.get("name") or f"sheet{sheet_id}"
    return names


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root:
        if _xml_ns(si.tag) != "si":
            continue
        values.append(
            "".join(
                child.text or ""
                for child in si.iter()
                if _xml_ns(child.tag) == "t"
            ).strip()
        )
    return values


def _col_letters_from_ref(ref: str, fallback_index: int) -> str:
    match = re.match(r"([A-Z]+)", ref or "")
    if match:
        return match.group(1)
    result = ""
    n = fallback_index
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    inline_text = [
        child.text or ""
        for child in cell.iter()
        if _xml_ns(child.tag) == "t" and child.text
    ]
    if inline_text:
        return "".join(inline_text).strip()

    value = None
    for child in cell:
        if _xml_ns(child.tag) == "v":
            value = child.text
            break
    if value is None:
        return ""
    if cell.attrib.get("t") == "s":
        try:
            idx = int(value)
            return shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
        except Exception:
            return ""
    return value.strip()


def _resolve_xlsx(
    file_path: Path, document_name: str, anchor: Mapping[str, Any]
) -> dict[str, Any]:
    start, end = _bounded_range(
        anchor.get("start_row"),
        anchor.get("end_row"),
        max_count=MAX_TABLE_ROWS,
    )
    wanted_sheet = anchor.get("sheet")
    selected: list[str] = []

    with zipfile.ZipFile(file_path, "r") as zf:
        sheet_names = _xlsx_sheet_names(zf)
        shared_strings = _xlsx_shared_strings(zf)
        sheet_files = [
            name
            for name in zf.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        ]
        sheet_files.sort()
        for sheet_file in sheet_files:
            sheet_name = sheet_names.get(sheet_file, Path(sheet_file).stem)
            if wanted_sheet and sheet_name != wanted_sheet:
                continue
            root = ET.fromstring(zf.read(sheet_file))
            for row in root.iter():
                if _xml_ns(row.tag) != "row":
                    continue
                try:
                    row_num = int(row.attrib.get("r", "0"))
                except Exception:
                    row_num = 0
                if row_num < start or row_num > end:
                    continue
                cells: list[str] = []
                for col_idx, cell in enumerate(row, start=1):
                    if _xml_ns(cell.tag) != "c":
                        continue
                    value = _xlsx_cell_value(cell, shared_strings)
                    if value:
                        col = _col_letters_from_ref(cell.attrib.get("r", ""), col_idx)
                        cells.append(f"{col}={value}")
                if cells:
                    selected.append(f"row {row_num}: " + ", ".join(cells))

    normalized = dict(anchor)
    normalized["start_row"] = start
    normalized["end_row"] = end
    return _result(
        status="success",
        document_name=document_name,
        anchor=normalized,
        content="\n".join(selected),
    )


def _slide_sort_key(path: str) -> int:
    match = re.search(r"(\d+)", path)
    return int(match.group(1)) if match else 0


def _resolve_pptx(
    file_path: Path, document_name: str, anchor: Mapping[str, Any]
) -> dict[str, Any]:
    start, end = _bounded_range(
        anchor.get("start_slide"),
        anchor.get("end_slide"),
        max_count=MAX_SLIDES,
    )
    texts: list[str] = []
    with zipfile.ZipFile(file_path, "r") as zf:
        slide_paths = [
            name
            for name in zf.namelist()
            if name.startswith("ppt/slides/")
            and name.endswith(".xml")
            and "_rels" not in name
        ]
        slide_paths.sort(key=_slide_sort_key)
        for slide_path in slide_paths:
            slide_num = _slide_sort_key(slide_path)
            if slide_num < start or slide_num > end:
                continue
            root = ET.fromstring(zf.read(slide_path))
            slide_text = "\n".join(
                child.text.strip()
                for child in root.iter()
                if _xml_ns(child.tag) == "t" and child.text and child.text.strip()
            )
            if slide_text:
                texts.append(slide_text)

    normalized = dict(anchor)
    normalized["start_slide"] = start
    normalized["end_slide"] = end
    return _result(
        status="success",
        document_name=document_name,
        anchor=normalized,
        content="\n".join(texts),
    )


def resolve_source_anchor(
    file_path: Path,
    document_name: str,
    anchor: Mapping[str, Any],
) -> dict[str, Any]:
    unit_type = anchor.get("unit_type")
    fmt = str(anchor.get("format") or file_path.suffix.lstrip(".")).lower()

    try:
        if unit_type == "line":
            return _resolve_lines(file_path, document_name, anchor)
        if unit_type == "row_range" and fmt in {"csv", "tsv"}:
            return _resolve_rows(
                file_path,
                document_name,
                anchor,
                delimiter="\t" if fmt == "tsv" else ",",
            )
        if unit_type == "row_range" and fmt == "xlsx":
            return _resolve_xlsx(file_path, document_name, anchor)
        if unit_type == "paragraph" and fmt == "docx":
            return _resolve_docx(file_path, document_name, anchor)
        if unit_type == "slide" and fmt == "pptx":
            return _resolve_pptx(file_path, document_name, anchor)
        if unit_type == "page" and fmt == "pdf":
            return _result(
                status="unsupported",
                document_name=document_name,
                anchor=anchor,
                reason="PDF page anchors are resolved by the existing page-content path.",
            )
        return _result(
            status="error",
            document_name=document_name,
            anchor=anchor,
            reason=f"Unsupported source anchor: {unit_type or fmt}",
        )
    except Exception as exc:
        return _result(
            status="error",
            document_name=document_name,
            anchor=anchor,
            reason=str(exc),
        )
