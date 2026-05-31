import csv
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _xml_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _col_letters(col_num: int) -> str:
    result = ""
    n = col_num
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


class TableAnalysisService:
    """轻量级表格聚合服务（csv/tsv/xlsx）。"""

    def load_table_documents(self, docs: List[Any]) -> Dict[str, Any]:
        datasets: List[Dict[str, Any]] = []
        quality_notes: List[str] = []

        for doc in docs:
            file_type = (doc.file_type or "").lower()
            path = Path(doc.file_path)
            if not path.exists():
                quality_notes.append(f"文档 {doc.original_name} 文件不存在，已跳过")
                continue

            if file_type in {".csv", ".tsv"}:
                rows, headers = self._load_csv_like(
                    path, delimiter="," if file_type == ".csv" else "\t"
                )
                datasets.append(
                    {
                        "doc_id": doc.id,
                        "doc_name": doc.original_name,
                        "sheet": path.stem,
                        "headers": headers,
                        "rows": rows,
                        "file_type": file_type,
                    }
                )
            elif file_type == ".xlsx":
                xlsx_sets = self._load_xlsx(path)
                for item in xlsx_sets:
                    item["doc_id"] = doc.id
                    item["doc_name"] = doc.original_name
                    item["file_type"] = file_type
                datasets.extend(xlsx_sets)
            else:
                quality_notes.append(
                    f"文档 {doc.original_name} 不是可聚合表格格式，已跳过"
                )

        return {"datasets": datasets, "quality_notes": quality_notes}

    def aggregate(
        self, datasets: List[Dict[str, Any]], operation_spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        operation = str(operation_spec.get("operation", "count")).lower()
        target_column = operation_spec.get("target_column")
        group_by = operation_spec.get("group_by")
        limit = int(operation_spec.get("limit", 100))

        quality_notes: List[str] = []
        all_rows: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []

        for ds in datasets:
            rows = ds.get("rows", [])
            if not rows:
                continue
            all_rows.extend(rows)
            citations.append(
                {
                    "doc_id": ds.get("doc_id"),
                    "doc_name": ds.get("doc_name"),
                    "sheet": ds.get("sheet"),
                    "start_row": 2,
                    "end_row": len(rows) + 1,
                }
            )

        if not all_rows:
            return {
                "result_table": [],
                "schema_mapping": {},
                "quality_notes": ["没有可用于聚合的数据"],
                "citations": [],
            }

        result_table: List[Dict[str, Any]]
        if operation == "concat":
            result_table = all_rows[:limit]
        elif operation in {"sum", "avg", "min", "max", "count"}:
            result_table, op_notes = self._scalar_aggregate(
                all_rows,
                operation=operation,
                target_column=target_column,
            )
            quality_notes.extend(op_notes)
        elif operation == "groupby":
            result_table, op_notes = self._groupby_aggregate(
                all_rows,
                group_by=group_by,
                target_column=target_column,
                metric=str(operation_spec.get("metric", "count")).lower(),
            )
            quality_notes.extend(op_notes)
            result_table = result_table[:limit]
        else:
            result_table = []
            quality_notes.append(f"暂不支持的 operation: {operation}")

        schema = self._infer_schema(all_rows)
        return {
            "result_table": result_table,
            "schema_mapping": schema,
            "quality_notes": quality_notes,
            "citations": citations,
        }

    def _scalar_aggregate(
        self,
        rows: List[Dict[str, Any]],
        operation: str,
        target_column: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        notes: List[str] = []
        if operation == "count":
            return [{"count": len(rows)}], notes

        if not target_column:
            return [], ["缺少 target_column，无法执行标量聚合"]

        nums = [_to_number(r.get(target_column)) for r in rows]
        nums = [x for x in nums if x is not None]
        if not nums:
            return [], [f"列 {target_column} 没有可聚合的数值"]

        if operation == "sum":
            return [{target_column: sum(nums)}], notes
        if operation == "avg":
            return [{target_column: sum(nums) / len(nums)}], notes
        if operation == "min":
            return [{target_column: min(nums)}], notes
        if operation == "max":
            return [{target_column: max(nums)}], notes

        return [], [f"未知操作: {operation}"]

    def _groupby_aggregate(
        self,
        rows: List[Dict[str, Any]],
        group_by: Optional[str],
        target_column: Optional[str],
        metric: str,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        notes: List[str] = []
        if not group_by:
            return [], ["groupby 缺少 group_by 字段"]

        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get(group_by, "")).strip() or "(empty)"
            buckets.setdefault(key, []).append(row)

        table: List[Dict[str, Any]] = []
        for key, items in buckets.items():
            if metric == "count":
                table.append({group_by: key, "count": len(items)})
                continue

            if not target_column:
                notes.append("groupby 数值聚合缺少 target_column")
                continue

            nums = [_to_number(r.get(target_column)) for r in items]
            nums = [x for x in nums if x is not None]
            if not nums:
                continue

            if metric == "sum":
                value = sum(nums)
            elif metric == "avg":
                value = sum(nums) / len(nums)
            elif metric == "min":
                value = min(nums)
            elif metric == "max":
                value = max(nums)
            else:
                notes.append(f"不支持的 groupby metric: {metric}")
                continue
            table.append({group_by: key, f"{metric}_{target_column}": value})

        table.sort(key=lambda x: list(x.values())[1] if len(x) > 1 else 0, reverse=True)
        return table, notes

    @staticmethod
    def _infer_schema(rows: List[Dict[str, Any]]) -> Dict[str, str]:
        if not rows:
            return {}
        schema: Dict[str, str] = {}
        for col in rows[0].keys():
            sample = [r.get(col) for r in rows[:50]]
            num_count = sum(1 for v in sample if _to_number(v) is not None)
            schema[col] = (
                "number" if num_count >= max(1, len(sample) // 2) else "string"
            )
        return schema

    @staticmethod
    def _load_csv_like(
        path: Path, delimiter: str
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            headers = list(reader.fieldnames or [])
            rows = [dict(r) for r in reader]
        return rows, headers

    def _load_xlsx(self, path: Path) -> List[Dict[str, Any]]:
        datasets: List[Dict[str, Any]] = []
        with zipfile.ZipFile(path, "r") as zf:
            shared = self._parse_shared_strings(zf)
            sheet_name_map = self._xlsx_sheet_names(zf)
            sheet_files = [
                n
                for n in zf.namelist()
                if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
            ]
            sheet_files.sort(
                key=lambda p: (
                    int(re.search(r"(\d+)", p).group(1))
                    if re.search(r"(\d+)", p)
                    else 0
                )
            )

            for sheet_file in sheet_files:
                root = ET.fromstring(zf.read(sheet_file))
                sheet_name = sheet_name_map.get(sheet_file, Path(sheet_file).stem)

                rows: List[List[str]] = []
                for row in root.iter():
                    if _xml_ns(row.tag) != "row":
                        continue
                    values: List[str] = []
                    for cell in row:
                        if _xml_ns(cell.tag) != "c":
                            continue
                        values.append(self._cell_value(cell, shared))
                    if any(v != "" for v in values):
                        rows.append(values)

                if not rows:
                    continue

                headers = [
                    h.strip() if h else f"col_{i + 1}" for i, h in enumerate(rows[0])
                ]
                data_rows: List[Dict[str, Any]] = []
                for raw in rows[1:]:
                    item: Dict[str, Any] = {}
                    for i, header in enumerate(headers):
                        item[header] = raw[i] if i < len(raw) else ""
                    data_rows.append(item)

                datasets.append(
                    {
                        "sheet": sheet_name,
                        "headers": headers,
                        "rows": data_rows,
                    }
                )

        return datasets

    @staticmethod
    def _parse_shared_strings(zf: zipfile.ZipFile) -> List[str]:
        if "xl/sharedStrings.xml" not in zf.namelist():
            return []
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        values: List[str] = []
        for si in root:
            if _xml_ns(si.tag) != "si":
                continue
            parts: List[str] = []
            for t in si.iter():
                if _xml_ns(t.tag) == "t" and t.text:
                    parts.append(t.text)
            values.append("".join(parts).strip())
        return values

    @staticmethod
    def _xlsx_sheet_names(zf: zipfile.ZipFile) -> Dict[str, str]:
        if "xl/workbook.xml" not in zf.namelist():
            return {}
        root = ET.fromstring(zf.read("xl/workbook.xml"))
        name_map: Dict[str, str] = {}
        for sheet in root.iter():
            if _xml_ns(sheet.tag) != "sheet":
                continue
            sheet_name = sheet.attrib.get("name") or "Sheet"
            sheet_id = sheet.attrib.get("sheetId")
            if sheet_id:
                name_map[f"xl/worksheets/sheet{sheet_id}.xml"] = sheet_name
        return name_map

    @staticmethod
    def _cell_value(cell: ET.Element, shared: List[str]) -> str:
        ctype = cell.attrib.get("t")
        value_el = None
        for child in cell:
            if _xml_ns(child.tag) == "v":
                value_el = child
                break
        if value_el is None or value_el.text is None:
            return ""

        raw = value_el.text
        if ctype == "s":
            try:
                idx = int(raw)
                return shared[idx] if 0 <= idx < len(shared) else ""
            except ValueError:
                return ""
        return raw.strip()
