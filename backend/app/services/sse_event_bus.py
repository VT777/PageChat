import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Optional

from app.core import config


class FirstEventSLAAggregator:
    def __init__(
        self,
        window_seconds: int = config.SSE_SLA_WINDOW_SECONDS,
        min_samples: int = config.SSE_SLA_MIN_SAMPLES,
    ):
        self.window_seconds = window_seconds
        self.min_samples = min_samples
        self._samples: Deque[tuple[float, float]] = deque()

    def record(self, latency_ms: float, at: Optional[float] = None) -> None:
        now = at if at is not None else time.time()
        self._samples.append((now, float(latency_ms)))
        self._evict(now)

    def snapshot(self, at: Optional[float] = None) -> dict:
        now = at if at is not None else time.time()
        self._evict(now)
        values = sorted(sample for _, sample in self._samples)
        count = len(values)
        if not values:
            return {
                "samples": 0,
                "p95_ms": None,
                "p99_ms": None,
                "thresholds": {
                    "p95_ms": config.FIRST_EVENT_P95_MS,
                    "p99_ms": config.FIRST_EVENT_P99_MS,
                },
                "enforced": False,
            }

        return {
            "samples": count,
            "p95_ms": _percentile(values, 95),
            "p99_ms": _percentile(values, 99),
            "thresholds": {
                "p95_ms": config.FIRST_EVENT_P95_MS,
                "p99_ms": config.FIRST_EVENT_P99_MS,
            },
            "enforced": count >= self.min_samples,
        }

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()


def _percentile(values: list[float], pct: int) -> float:
    if len(values) == 1:
        return values[0]
    rank = (len(values) - 1) * (pct / 100)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    weight = rank - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 2)


first_event_sla_aggregator = FirstEventSLAAggregator()


class SSEEventBus:
    HAPPY_PATH_ORDER = [
        "session_started",
        "intent_start",
        "intent_done",
        "retrieval_start",
        "retrieval_done",
        "answer_delta",
        "answer_done",
        "citations_ready",
        "done",
    ]
    _INTERNAL_DEBUG_TERMS = (
        "debug",
        "trace",
        "tool_call",
        "function_call",
        "agent_loop",
        "rerank",
        "prompt",
    )

    def __init__(
        self,
        turn_id: str,
        session_started_at: Optional[float] = None,
        sla_aggregator: Optional[FirstEventSLAAggregator] = None,
    ):
        self.turn_id = turn_id
        self.session_started_at = session_started_at
        self.sla_aggregator = sla_aggregator
        self.should_emit_done = True
        self._first_event_tracked = False
        self._step_counter = 0

    def emit(
        self,
        event: str,
        summary: str,
        detail: Optional[str],
        data: Optional[dict],
    ) -> str:
        if event == "done" and not self.should_emit_done:
            raise ValueError("done is suppressed after terminal error")

        payload = data or {}
        self._validate_data(event, payload)

        if event == "error":
            self.should_emit_done = False

        if event == "session_started":
            self._record_first_event_latency()

        self._step_counter += 1
        envelope = {
            "event": event,
            "turn_id": self.turn_id,
            "step_id": f"{self.turn_id}-{self._step_counter}",
            "ts": datetime.now(timezone.utc).isoformat(),
            "summary": self._sanitize_summary(summary),
            "detail": detail,
            "data": payload,
        }
        return f"event: {event}\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"

    def validate_order(self, events: list[str]) -> bool:
        expected = [e for e in self.HAPPY_PATH_ORDER if e != "answer_delta"]
        pointer = 0
        seen_answer_done = False
        terminated = False

        for event in events:
            if terminated:
                return False

            if event == "warn":
                continue
            if event == "error":
                terminated = True
                continue
            if event == "answer_delta":
                if (
                    not seen_answer_done
                    and pointer >= expected.index("retrieval_done") + 1
                ):
                    continue
                return False

            if pointer >= len(expected) or event != expected[pointer]:
                return False
            if event == "answer_done":
                seen_answer_done = True
            pointer += 1

        if terminated:
            return True
        return pointer == len(expected)

    def _record_first_event_latency(self) -> None:
        if self._first_event_tracked:
            return
        if self.session_started_at is None:
            return
        if self.sla_aggregator is None:
            return

        latency_ms = max(0.0, (time.monotonic() - self.session_started_at) * 1000)
        self.sla_aggregator.record(latency_ms)
        self._first_event_tracked = True

    def _sanitize_summary(self, summary: str) -> str:
        cleaned = summary or ""
        for term in self._INTERNAL_DEBUG_TERMS:
            cleaned = cleaned.replace(term, " ")
            cleaned = cleaned.replace(term.upper(), " ")
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            cleaned = "当前阶段已处理完成"
        if len(cleaned) < 8:
            cleaned = f"{cleaned}，请稍候"
        if len(cleaned) < 8:
            cleaned = f"{cleaned}处理中"
        return cleaned[:40]

    def _validate_data(self, event: str, data: dict) -> None:
        if event == "answer_delta":
            self._require_keys(event, data, ["text", "sentence_id"])
        elif event == "citations_ready":
            self._require_keys(event, data, ["bindings"])
            if not isinstance(data["bindings"], list):
                raise ValueError("citations_ready.bindings must be an array")
        elif event == "answer_done":
            self._require_keys(event, data, ["char_count"])
            if not isinstance(data["char_count"], (int, float)):
                raise ValueError("answer_done.char_count must be a number")
        elif event == "warn":
            self._require_keys(event, data, ["code", "message", "impact"])
            if data["impact"] not in ("none", "partial"):
                raise ValueError("warn.impact must be none|partial")
        elif event == "error":
            self._require_keys(event, data, ["code", "message", "recoverable"])
            if data["recoverable"] is not False:
                raise ValueError("error.recoverable must be false")

    @staticmethod
    def _require_keys(event: str, data: dict, keys: list[str]) -> None:
        missing = [k for k in keys if k not in data]
        if missing:
            joined = ",".join(missing)
            raise ValueError(f"{event} missing keys: {joined}")


def new_turn_bus(session_started_at: Optional[float] = None) -> SSEEventBus:
    turn_id = str(uuid.uuid4())[:12]
    return SSEEventBus(
        turn_id=turn_id,
        session_started_at=session_started_at
        if session_started_at is not None
        else time.monotonic(),
        sla_aggregator=first_event_sla_aggregator,
    )
