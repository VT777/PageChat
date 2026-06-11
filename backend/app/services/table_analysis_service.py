from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models.retrieval import build_source_display_label


def _to_number(value: Any) -> float | None:
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


class TableAnalysisService:
    """Lightweight aggregation service for csv, tsv, and xlsx datasets."""

    def load_table_documents(self, docs: list[Any]) -> dict[str, Any]:
        datasets: list[dict[str, Any]] = []
        quality_notes: list[str] = []

        from app.services.format_adapters.table_adapter import parse_table

        for doc in docs:
            file_type = (doc.file_type or "").lower()
            path = Path(doc.file_path)
            if not path.exists():
                quality_notes.append(f"Document {doc.original_name} file does not exist, skipped")
                continue

            if file_type not in {".csv", ".tsv", ".xlsx"}:
                quality_notes.append(
                    f"Document {doc.original_name} is not an aggregatable table format, skipped"
                )
                continue

            content = parse_table(path)
            if content.metadata.get("parse_status") == "error":
                quality_notes.append(
                    f"Document {doc.original_name} table parse failed: {content.metadata.get('error')}"
                )
                continue

            for item in content.tables:
                dataset = dict(item)
                dataset["doc_id"] = doc.id
                dataset["doc_name"] = doc.original_name
                dataset["file_type"] = file_type
                datasets.append(dataset)

        return {"datasets": datasets, "quality_notes": quality_notes}

    def aggregate(
        self, datasets: list[dict[str, Any]], operation_spec: dict[str, Any]
    ) -> dict[str, Any]:
        operation = str(operation_spec.get("operation", "count")).lower()
        target_column = operation_spec.get("target_column")
        group_by = operation_spec.get("group_by")
        limit = int(operation_spec.get("limit", 100))

        quality_notes: list[str] = []
        all_rows: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []

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
                    "start_row": (ds.get("source_anchor") or {}).get("start_row", 2),
                    "end_row": (ds.get("source_anchor") or {}).get("end_row", len(rows) + 1),
                    "source_anchor": ds.get("source_anchor"),
                    "display_label": (
                        build_source_display_label(
                            str(ds.get("doc_name") or ""),
                            ds.get("source_anchor") or {},
                        )
                        if ds.get("source_anchor")
                        else None
                    ),
                }
            )

        if not all_rows:
            return {
                "result_table": [],
                "schema_mapping": {},
                "quality_notes": ["No data available for aggregation"],
                "citations": [],
            }

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
            quality_notes.append(f"Unsupported operation: {operation}")

        return {
            "result_table": result_table,
            "schema_mapping": self._infer_schema(all_rows),
            "quality_notes": quality_notes,
            "citations": citations,
        }

    def _scalar_aggregate(
        self,
        rows: list[dict[str, Any]],
        operation: str,
        target_column: str | None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if operation == "count":
            return [{"count": len(rows)}], []
        if not target_column:
            return [], ["Missing target_column for scalar aggregation"]

        nums = [_to_number(row.get(target_column)) for row in rows]
        nums = [value for value in nums if value is not None]
        if not nums:
            return [], [f"Column {target_column} has no numeric values"]

        if operation == "sum":
            return [{target_column: sum(nums)}], []
        if operation == "avg":
            return [{target_column: sum(nums) / len(nums)}], []
        if operation == "min":
            return [{target_column: min(nums)}], []
        if operation == "max":
            return [{target_column: max(nums)}], []
        return [], [f"Unknown operation: {operation}"]

    def _groupby_aggregate(
        self,
        rows: list[dict[str, Any]],
        group_by: str | None,
        target_column: str | None,
        metric: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not group_by:
            return [], ["groupby is missing group_by"]

        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get(group_by, "")).strip() or "(empty)"
            buckets.setdefault(key, []).append(row)

        table: list[dict[str, Any]] = []
        notes: list[str] = []
        for key, items in buckets.items():
            if metric == "count":
                table.append({group_by: key, "count": len(items)})
                continue
            if not target_column:
                notes.append("groupby numeric aggregation is missing target_column")
                continue

            nums = [_to_number(row.get(target_column)) for row in items]
            nums = [value for value in nums if value is not None]
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
                notes.append(f"Unsupported groupby metric: {metric}")
                continue
            table.append({group_by: key, f"{metric}_{target_column}": value})

        table.sort(key=lambda row: list(row.values())[1] if len(row) > 1 else 0, reverse=True)
        return table, notes

    @staticmethod
    def _infer_schema(rows: list[dict[str, Any]]) -> dict[str, str]:
        if not rows:
            return {}
        schema: dict[str, str] = {}
        for col in rows[0].keys():
            sample = [row.get(col) for row in rows[:50]]
            numeric = sum(1 for value in sample if _to_number(value) is not None)
            schema[col] = "number" if numeric >= max(1, len(sample) // 2) else "string"
        return schema
