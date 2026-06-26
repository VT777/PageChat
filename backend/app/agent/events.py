import json
from datetime import datetime, timezone
from typing import Any

from app.agent.citations import citation_events_from_tool_result

PAGECHAT_EVENT_TYPES = {
    "run_started",
    "progress",
    "tool_started",
    "tool_completed",
    "answer_delta",
    "citation_added",
    "run_completed",
    "run_failed",
    "run_cancelled",
}

REQUIRED_EVENT_METADATA = ("run_id", "conversation_id", "message_id", "seq", "ts")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_pagechat_event_payload(event_type: str, payload: dict[str, Any]) -> None:
    if event_type not in PAGECHAT_EVENT_TYPES:
        raise ValueError(f"Unsupported PageChat event type: {event_type}")
    for field in REQUIRED_EVENT_METADATA:
        if payload.get(field) in (None, ""):
            raise ValueError(f"PageChat event missing {field}")
    seq = payload.get("seq")
    if not isinstance(seq, int) or seq < 1:
        raise ValueError("PageChat event seq must be a positive integer")


class PageChatEventEmitter:
    def __init__(self, *, run_id: str, conversation_id: str, message_id: str):
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.message_id = message_id
        self._seq = 0

    @property
    def seq(self) -> int:
        return self._seq

    def build(self, event_type: str, payload: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
        self._seq += 1
        data = {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "seq": self._seq,
            "ts": utc_now_iso(),
        }
        if payload:
            data.update(payload)
        validate_pagechat_event_payload(event_type, data)
        return event_type, data

    def sse(self, event_type: str, payload: dict[str, Any] | None = None) -> str:
        event, data = self.build(event_type, payload)
        return sse_frame(event, data)


def sse_frame(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def parse_sse_frame(frame: str) -> tuple[str | None, dict[str, Any]]:
    event_type = None
    data: dict[str, Any] = {}
    for line in frame.strip().splitlines():
        if line.startswith("event: "):
            event_type = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            data = json.loads(line.removeprefix("data: "))
    return event_type, data
