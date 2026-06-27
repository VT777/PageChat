from __future__ import annotations

import json
from typing import Any

from app.agent.model_turn import ModelToolCall
from app.agent.nodes import compact_tool_result


_SENSITIVE_KEYS = {
    "base64",
    "content_base64",
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
    model_result = _compact_for_model(ui_result)
    message = {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": json.dumps(model_result, ensure_ascii=False, separators=(",", ":")),
    }
    return message, ui_result


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
