from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from app.services.format_adapters.base import ContentBlock, DocumentContent, IndexNode

MULTIFORMAT_MAX_ROWS_PER_CHUNK = 100
MULTIFORMAT_MAX_TABLE_CHUNKS_PER_SHEET = 20
MULTIFORMAT_MAX_SHEETS_PER_WORKBOOK = 20


def _xml_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _summary(text: str, max_len: int = 180) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= max_len else clean[: max_len - 1] + "..."


def _to_number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def _schema(rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {}
    result: dict[str, str] = {}
    for key in rows[0]:
        sample = [row.get(key) for row in rows[:50]]
        numeric = sum(1 for value in sample if _to_number(value) is not None)
        result[key] = "number" if numeric >= max(1, len(sample) // 2) else "string"
    return result


def _error_content(fmt: str, file_path: Path, exc: Exception) -> DocumentContent:
    return DocumentContent(
        format=fmt,
        title=file_path.name,
        doc_description=f"Could not parse table file: {file_path.name}",
        unit_type="row_range",
        unit_count=0,
        nodes=[],
        blocks=[],
        tables=[],
        metadata={"adapter": "canonical_table", "parse_status": "error", "error": str(exc)},
    )


def _content_from_tables(fmt: str, file_path: Path, tables: list[dict[str, Any]], blocks: list[ContentBlock]) -> DocumentContent:
    nodes: list[IndexNode] = []
    node_idx = 1
    total_rows = 0
    for table in tables[:MULTIFORMAT_MAX_SHEETS_PER_WORKBOOK]:
        rows = table["raw_rows"]
        total_rows += len(rows)
        for chunk_idx in range(0, len(rows), MULTIFORMAT_MAX_ROWS_PER_CHUNK):
            if chunk_idx // MULTIFORMAT_MAX_ROWS_PER_CHUNK >= MULTIFORMAT_MAX_TABLE_CHUNKS_PER_SHEET:
                break
            chunk = rows[chunk_idx : chunk_idx + MULTIFORMAT_MAX_ROWS_PER_CHUNK]
            if not chunk:
                continue
            start_row = int(chunk[0]["row_number"])
            end_row = int(chunk[-1]["row_number"])
            text = "\n".join(f"row {row['row_number']}: " + " | ".join(row["values"]) for row in chunk)
            anchor = {
                "format": fmt,
                "unit_type": "row_range",
                "start_row": start_row,
                "end_row": end_row,
            }
            if table.get("sheet"):
                anchor["sheet"] = table["sheet"]
            nodes.append(
                IndexNode(
                    node_id=f"table_{node_idx}",
                    title=f"{table.get('sheet') or file_path.stem} rows {start_row}-{end_row}",
                    summary=_summary(text),
                    text=text,
                    start_index=start_row,
                    end_index=end_row,
                    source_anchor=anchor,
                )
            )
            node_idx += 1

    public_tables = []
    for table in tables:
        public_table = {key: value for key, value in table.items() if key != "raw_rows"}
        raw_rows = table.get("raw_rows") or []
        if raw_rows:
            start_row = int(raw_rows[0]["row_number"])
            end_row = int(raw_rows[-1]["row_number"])
            anchor = {
                "format": fmt,
                "unit_type": "row_range",
                "start_row": start_row,
                "end_row": end_row,
            }
            if table.get("sheet") and fmt == "xlsx":
                anchor["sheet"] = table["sheet"]
            public_table["source_anchor"] = anchor
        public_tables.append(public_table)
    return DocumentContent(
        format=fmt,
        title=file_path.name,
        doc_description=nodes[0].summary if nodes else f"Table file: {file_path.name}",
        unit_type="row_range",
        unit_count=total_rows,
        nodes=nodes,
        blocks=blocks,
        tables=public_tables,
        metadata={"adapter": "canonical_table", "row_count": total_rows, "table_count": len(tables)},
    )


def _parse_csv_like(file_path: Path, delimiter: str) -> DocumentContent:
    fmt = "tsv" if delimiter == "\t" else "csv"
    raw_rows: list[dict[str, Any]] = []
    blocks: list[ContentBlock] = []
    with open(file_path, "r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row_number, row in enumerate(reader, start=1):
            if not any(str(cell).strip() for cell in row):
                continue
            values = [str(cell).strip() for cell in row]
            raw_rows.append({"row_number": row_number, "values": values})
            blocks.append(
                ContentBlock(
                    id=f"row_{row_number}",
                    type="table_row",
                    content=values,
                    metadata={"row_index": row_number - 1, "row_number": row_number},
                    source_anchor={"format": fmt, "unit_type": "row_range", "start_row": row_number, "end_row": row_number},
                )
            )
    headers = raw_rows[0]["values"] if raw_rows else []
    data_rows = [
        {header: row["values"][idx] if idx < len(row["values"]) else "" for idx, header in enumerate(headers)}
        for row in raw_rows[1:]
    ]
    table = {"sheet": file_path.stem, "headers": headers, "rows": data_rows, "schema": _schema(data_rows), "raw_rows": raw_rows}
    return _content_from_tables(fmt, file_path, [table], blocks)


def _sheet_names(zf: zipfile.ZipFile) -> dict[str, str]:
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


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(child.text or "" for child in si.iter() if _xml_ns(child.tag) == "t").strip()
        for si in root
        if _xml_ns(si.tag) == "si"
    ]


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    inline = "".join(child.text or "" for child in cell.iter() if _xml_ns(child.tag) == "t").strip()
    if inline:
        return inline
    value = next((child.text for child in cell if _xml_ns(child.tag) == "v"), None)
    if value is None:
        return ""
    if cell.attrib.get("t") == "s":
        try:
            return shared[int(value)]
        except Exception:
            return ""
    return value.strip()


def _parse_xlsx(file_path: Path) -> DocumentContent:
    tables: list[dict[str, Any]] = []
    blocks: list[ContentBlock] = []
    with zipfile.ZipFile(file_path, "r") as zf:
        shared = _shared_strings(zf)
        names = _sheet_names(zf)
        sheet_files = [name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")]
        sheet_files.sort(key=lambda value: int(re.search(r"(\d+)", value).group(1)) if re.search(r"(\d+)", value) else 0)
        for sheet_file in sheet_files[:MULTIFORMAT_MAX_SHEETS_PER_WORKBOOK]:
            sheet = names.get(sheet_file, Path(sheet_file).stem)
            root = ET.fromstring(zf.read(sheet_file))
            raw_rows: list[dict[str, Any]] = []
            for row in root.iter():
                if _xml_ns(row.tag) != "row":
                    continue
                row_number = int(row.attrib.get("r", "0") or 0)
                values = [_cell_value(cell, shared) for cell in row if _xml_ns(cell.tag) == "c"]
                if not any(values):
                    continue
                raw_rows.append({"row_number": row_number, "values": values})
            if not raw_rows:
                continue
            headers = raw_rows[0]["values"]
            data_rows = [
                {header: row["values"][idx] if idx < len(row["values"]) else "" for idx, header in enumerate(headers)}
                for row in raw_rows[1:]
            ]
            start_row = raw_rows[0]["row_number"]
            end_row = raw_rows[-1]["row_number"]
            blocks.append(
                ContentBlock(
                    id=f"sheet_{len(tables) + 1}",
                    type="sheet",
                    content={
                        "name": sheet,
                        "rows": [
                            {"row_number": row["row_number"], "cells": [{"col": idx + 1, "value": value} for idx, value in enumerate(row["values"])]}
                            for row in raw_rows
                        ],
                        "row_count": len(raw_rows),
                        "col_count": max(len(row["values"]) for row in raw_rows),
                    },
                    metadata={"sheet_name": sheet, "row_count": len(raw_rows), "col_count": max(len(row["values"]) for row in raw_rows)},
                    source_anchor={"format": "xlsx", "unit_type": "row_range", "sheet": sheet, "start_row": start_row, "end_row": end_row},
                )
            )
            tables.append({"sheet": sheet, "headers": headers, "rows": data_rows, "schema": _schema(data_rows), "raw_rows": raw_rows})
    return _content_from_tables("xlsx", file_path, tables, blocks)


def parse_table(file_path: Path) -> DocumentContent:
    suffix = file_path.suffix.lower()
    try:
        if suffix == ".csv":
            return _parse_csv_like(file_path, ",")
        if suffix == ".tsv":
            return _parse_csv_like(file_path, "\t")
        if suffix == ".xlsx":
            return _parse_xlsx(file_path)
        raise ValueError(f"Unsupported table format: {suffix}")
    except Exception as exc:
        return _error_content(suffix.lstrip(".") or "table", file_path, exc)
