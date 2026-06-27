from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import json
from typing import Any

from app.agent.model_turn import (
    ModelTextDelta,
    ModelToolCall,
    ModelToolCallDelta,
    ModelTurn,
)


CompletionFn = Callable[..., Awaitable[Any]]


class ToolCallingModelAdapter:
    def __init__(
        self,
        *,
        completion_fn: CompletionFn | None = None,
        scenario: str = "qa",
        disable_thinking: bool = True,
    ) -> None:
        self.completion_fn = completion_fn or self._default_completion
        self.scenario = scenario
        self.disable_thinking = disable_thinking

    async def stream_turn(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        user_id: str | None = None,
    ) -> AsyncIterator[ModelTextDelta | ModelToolCallDelta | ModelTurn]:
        response = await self.completion_fn(
            scenario=self.scenario,
            messages=messages,
            stream=True,
            tools=tools,
            tool_choice="auto",
            user_id=user_id,
            allow_deterministic_tools=True,
            disable_thinking=self.disable_thinking,
        )
        if not hasattr(response, "__aiter__"):
            yield self._parse_response_turn(response)
            return

        content_parts: list[str] = []
        tool_call_buffers: dict[int, dict[str, str]] = {}
        async for chunk in response:
            for delta in self._extract_chunk_tool_call_deltas(chunk):
                index = int(delta.index)
                current = tool_call_buffers.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )
                if delta.id:
                    current["id"] = delta.id
                if delta.name:
                    current["name"] = delta.name
                if delta.arguments_delta:
                    current["arguments"] += delta.arguments_delta
                yield delta

            text_delta = self._extract_chunk_content(chunk)
            if text_delta:
                content_parts.append(text_delta)
                yield ModelTextDelta(delta=text_delta)

        if tool_call_buffers:
            yield ModelTurn(
                content="".join(content_parts),
                tool_calls=[
                    ModelToolCall(
                        id=item.get("id") or f"call_{index}",
                        name=item.get("name") or "",
                        arguments=self._parse_arguments(item.get("arguments") or ""),
                    )
                    for index, item in sorted(tool_call_buffers.items())
                    if item.get("name")
                ],
            )
            return
        yield ModelTurn(content="".join(content_parts))

    async def _default_completion(self, **kwargs: Any) -> Any:
        from app.core.llm import chat_by_scenario

        return await chat_by_scenario(**kwargs)

    def _parse_response_turn(self, response: Any) -> ModelTurn:
        tool_calls = self._extract_response_tool_calls(response)
        if tool_calls:
            return ModelTurn(tool_calls=tool_calls)
        return ModelTurn(content=self._extract_response_content(response))

    def _extract_response_tool_calls(self, response: Any) -> list[ModelToolCall]:
        choices = self._get_value(response, "choices") or []
        if not choices:
            return []
        message = self._get_value(choices[0], "message") or {}
        raw_tool_calls = self._get_value(message, "tool_calls") or []
        calls: list[ModelToolCall] = []
        for position, raw_call in enumerate(raw_tool_calls):
            function = self._get_value(raw_call, "function") or {}
            name = str(self._get_value(function, "name") or "").strip()
            if not name:
                continue
            calls.append(
                ModelToolCall(
                    id=str(self._get_value(raw_call, "id") or f"call_{position}"),
                    name=name,
                    arguments=self._parse_arguments(
                        str(self._get_value(function, "arguments") or "")
                    ),
                )
            )
        return calls

    def _extract_response_content(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        choices = self._get_value(response, "choices") or []
        if choices:
            message = self._get_value(choices[0], "message") or {}
            content = self._get_value(message, "content")
            if content is not None:
                return str(content or "")
        return str(self._get_value(response, "content") or self._get_value(response, "output_text") or "")

    def _extract_chunk_tool_call_deltas(self, chunk: Any) -> list[ModelToolCallDelta]:
        choices = self._get_value(chunk, "choices") or []
        if not choices:
            return []
        delta = self._get_value(choices[0], "delta") or {}
        raw_tool_calls = self._get_value(delta, "tool_calls") or []
        deltas: list[ModelToolCallDelta] = []
        for position, raw_call in enumerate(raw_tool_calls):
            function = self._get_value(raw_call, "function") or {}
            deltas.append(
                ModelToolCallDelta(
                    index=int(self._get_value(raw_call, "index") or position),
                    id=str(self._get_value(raw_call, "id") or ""),
                    name=str(self._get_value(function, "name") or ""),
                    arguments_delta=str(self._get_value(function, "arguments") or ""),
                )
            )
        return deltas

    def _extract_chunk_content(self, chunk: Any) -> str:
        choices = self._get_value(chunk, "choices") or []
        if not choices:
            return ""
        delta = self._get_value(choices[0], "delta") or {}
        return str(self._get_value(delta, "content") or "")

    def _parse_arguments(self, text: str) -> dict[str, Any]:
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _get_value(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)
