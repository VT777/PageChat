from collections.abc import AsyncIterator
from dataclasses import dataclass
import inspect
from typing import Any

from app.agent.events import PAGECHAT_EVENT_TYPES, PageChatEventEmitter
from app.agent.state import AgentRunState


@dataclass(frozen=True, slots=True)
class PageChatRuntimeEvent:
    event_type: str
    payload: dict[str, Any]


class PageChatAgentRuntime:
    """Small adapter that keeps PageChat's event contract outside graph internals."""

    def __init__(self, graph: Any):
        self.graph = graph

    async def stream(self, state: AgentRunState) -> AsyncIterator[PageChatRuntimeEvent]:
        emitter = PageChatEventEmitter(
            run_id=state.run_id,
            conversation_id=state.conversation_id,
            message_id=state.message_id,
        )

        yield self._build_event(emitter, "run_started", {"status": "running"})
        try:
            async for raw_event in self._stream_graph(state):
                normalized = self._normalize_graph_event(raw_event)
                if normalized is None:
                    continue
                event_type, payload = normalized
                yield self._build_event(emitter, event_type, payload)
        except Exception as exc:
            yield self._build_event(
                emitter,
                "run_failed",
                {"status": "failed", "error": str(exc)},
            )
            return
        yield self._build_event(emitter, "run_completed", {"status": "completed"})

    async def _stream_graph(self, state: AgentRunState) -> AsyncIterator[Any]:
        astream = getattr(self.graph, "astream", None)
        if callable(astream):
            kwargs = self._stream_kwargs_for(astream)
            async for event in astream(state, **kwargs):
                yield event
            return
        stream = getattr(self.graph, "stream", None)
        if callable(stream):
            kwargs = self._stream_kwargs_for(stream)
            for event in stream(state, **kwargs):
                yield event
            return
        raise TypeError("PageChatAgentRuntime graph must provide stream() or astream()")

    @staticmethod
    def _stream_kwargs_for(stream_fn: Any) -> dict[str, Any]:
        signature = inspect.signature(stream_fn)
        params = signature.parameters
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in params.values()
        )
        kwargs: dict[str, Any] = {}
        if accepts_kwargs or "stream_mode" in params:
            kwargs["stream_mode"] = "custom"
        if accepts_kwargs or "version" in params:
            kwargs["version"] = "v2"
        return kwargs

    @classmethod
    def _normalize_graph_event(cls, raw_event: Any) -> tuple[str, dict[str, Any]] | None:
        if isinstance(raw_event, PageChatRuntimeEvent):
            return raw_event.event_type, raw_event.payload
        if isinstance(raw_event, tuple) and len(raw_event) == 2:
            event_type, payload = raw_event
            return str(event_type), dict(payload or {})
        if isinstance(raw_event, dict):
            if cls._is_langgraph_stream_chunk(raw_event):
                if raw_event.get("type") != "custom":
                    return None
                return cls._normalize_graph_event(raw_event.get("data"))

            event_type = raw_event.get("event_type") or raw_event.get("type")
            payload = raw_event.get("payload")
            if payload is None:
                data = raw_event.get("data")
                if event_type in PAGECHAT_EVENT_TYPES and isinstance(data, dict):
                    payload = data
                else:
                    payload = {
                        key: value
                        for key, value in raw_event.items()
                        if key not in {"event_type", "type"}
                    }
            if not event_type:
                raise ValueError("Graph event is missing event_type")
            return str(event_type), dict(payload or {})
        raise TypeError(f"Unsupported graph event: {raw_event!r}")

    @staticmethod
    def _is_langgraph_stream_chunk(raw_event: dict[str, Any]) -> bool:
        return raw_event.get("type") in {
            "custom",
            "updates",
            "values",
            "messages",
            "debug",
        } and "data" in raw_event and "ns" in raw_event

    @staticmethod
    def _build_event(
        emitter: PageChatEventEmitter,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> PageChatRuntimeEvent:
        sanitized_payload = {
            key: value
            for key, value in (payload or {}).items()
            if key not in {"run_id", "conversation_id", "message_id", "seq", "ts"}
        }
        built_type, built_payload = emitter.build(event_type, sanitized_payload)
        return PageChatRuntimeEvent(event_type=built_type, payload=built_payload)
