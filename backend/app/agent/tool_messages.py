from __future__ import annotations

import json
from typing import Any

from app.agent.model_turn import ModelToolCall
from app.agent.nodes import compact_tool_result


_SENSITIVE_KEYS = {
    "base64",
    "content_base64",
    "citation_key",
    "embedding",
    "embeddings",
    "file_path",
    "local_path",
    "ocr_text",
    "page_image_base64",
    "path_on_disk",
    "raw_ocr_text",
    "rerank_score",
    "score",
    "scores",
    "text_content",
}


def build_tool_result_message(
    call: ModelToolCall,
    result: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ui_result = compact_tool_result(result, tool_name=call.name)
    model_result = _add_model_citation_markers(_compact_for_model(ui_result))
    message = {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": json.dumps(model_result, ensure_ascii=False, separators=(",", ":")),
    }
    return message, ui_result


def _add_model_citation_markers(value: Any, *, is_root: bool = True) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key == "citations" and isinstance(item, list):
                citations = [
                    citation
                    for citation in (_citation_for_model(record) for record in item)
                    if citation
                ]
                if citations:
                    compact[key] = citations
                continue
            cleaned = _add_model_citation_markers(item, is_root=False)
            if cleaned not in (None, "", [], {}):
                compact[key] = cleaned
        marker = _citation_marker_for_record(compact)
        if marker and "citation_marker" not in compact:
            compact["citation_marker"] = marker
        if is_root:
            markers = _collect_citation_markers(compact)
            if markers:
                compact["citation_markers"] = markers[:8]
        return compact
    if isinstance(value, list):
        return [
            cleaned
            for item in value[:8]
            if (cleaned := _add_model_citation_markers(item, is_root=False))
            not in (None, "", [], {})
        ]
    return value


def _citation_for_model(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    display_label = str(record.get("display_label") or "").strip()
    marker = _citation_marker_for_record(record)
    if not display_label or not marker:
        return {}
    source_anchor = record.get("source_anchor") if isinstance(record.get("source_anchor"), dict) else {}
    compact = {
        "display_label": display_label,
        "citation_marker": marker,
    }
    if source_anchor:
        compact["source_anchor"] = source_anchor
    preview_kind = str(record.get("preview_kind") or "").strip()
    if preview_kind:
        compact["preview_kind"] = preview_kind
    document_name = str(record.get("document_name") or "").strip()
    if document_name:
        compact["document_name"] = document_name
    return compact


def _citation_marker_for_record(record: dict[str, Any]) -> str:
    display_label = str(record.get("display_label") or "").strip()
    if not display_label or not _has_precise_source(record):
        return ""
    return f"[[{display_label}]]"


def _has_precise_source(record: dict[str, Any]) -> bool:
    source_anchor = record.get("source_anchor") if isinstance(record.get("source_anchor"), dict) else {}
    if str(record.get("preview_kind") or "").lower() == "web":
        return False
    if str(source_anchor.get("format") or "").lower() == "web":
        return False
    if record.get("url"):
        return False
    precise_anchor_keys = (
        "start_page",
        "page",
        "start_line",
        "start_row",
        "start_paragraph",
        "start_slide",
        "slide",
    )
    if any(source_anchor.get(key) not in (None, "") for key in precise_anchor_keys):
        return True
    return record.get("page") not in (None, "")


def _collect_citation_markers(value: Any) -> list[str]:
    markers: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            marker = item.get("citation_marker")
            if isinstance(marker, str) and marker and marker not in markers:
                markers.append(marker)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return markers


def _compact_for_model(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if _should_strip_key(key):
                continue
            cleaned = _compact_for_model(item)
            if cleaned in (None, "", [], {}):
                continue
            compact[key] = _stringify_next_steps(cleaned) if key == "next_steps" else cleaned
        return compact
    if isinstance(value, list):
        return [
            cleaned
            for item in value[:8]
            if (cleaned := _compact_for_model(item)) not in (None, "", [], {})
        ]
    if isinstance(value, str):
        return _truncate(value)
    return value


def _should_strip_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in _SENSITIVE_KEYS or normalized.endswith("_base64")


def _stringify_next_steps(value: Any) -> str:
    if isinstance(value, str):
        return _truncate(value, limit=240)
    if isinstance(value, list):
        parts = [_truncate(str(item), limit=120) for item in value if item not in (None, "")]
        return " ".join(parts[:3])
    return _truncate(str(value), limit=240)


def _truncate(value: str, limit: int = 1500) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
