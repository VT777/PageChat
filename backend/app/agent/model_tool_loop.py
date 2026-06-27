from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import time
from typing import Any

from app.agent.model_turn import ModelTextDelta, ModelToolCall, ModelToolCallDelta, ModelTurn
from app.agent.runtime_boundary_policy import RuntimeBoundaryPolicy
from app.agent.state import AgentRunState
from app.agent.tool_messages import build_tool_result_message


@dataclass(frozen=True, slots=True)
class RuntimeStreamEvent:
    type: str
    payload: dict[str, Any]


class ModelToolLoopRuntime:
    def __init__(
        self,
        *,
        model: Any,
        tool_runner: Any,
        tools: list[dict[str, Any]],
        boundary_policy: RuntimeBoundaryPolicy | None = None,
        system_prompt: str | None = None,
        max_steps: int = 8,
    ) -> None:
        self.model = model
        self.tool_runner = tool_runner
        self.tools = tools
        self.boundary_policy = boundary_policy or RuntimeBoundaryPolicy(tools=tools)
        self.system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self.max_steps = max(1, max_steps)

    async def stream(self, state: AgentRunState) -> AsyncIterator[RuntimeStreamEvent]:
        messages = self._initial_messages(state)
        for _step in range(1, self.max_steps + 1):
            turn = await self._collect_model_turn(messages, state)
            if turn.has_tool_calls:
                messages.append(self._assistant_tool_call_message(turn))
                for call in turn.tool_calls:
                    async for event in self._execute_tool_call(call, state, messages):
                        yield event
                continue
            if turn.content.strip():
                state.answer += turn.content
                yield RuntimeStreamEvent("answer_delta", {"content": turn.content})
                return
            yield RuntimeStreamEvent(
                "run_failed",
                {"error": "Model returned neither tool calls nor final text."},
            )
            return

        yield RuntimeStreamEvent("run_failed", {"error": "Maximum tool loop steps exceeded."})

    async def _collect_model_turn(
        self,
        messages: list[dict[str, Any]],
        state: AgentRunState,
    ) -> ModelTurn:
        final_turn: ModelTurn | None = None
        content_parts: list[str] = []
        async for event in self.model.stream_turn(
            messages=messages,
            tools=self.tools,
            user_id=state.scope.get("user_id"),
        ):
            if isinstance(event, ModelTextDelta):
                content_parts.append(event.delta)
                continue
            if isinstance(event, ModelToolCallDelta):
                continue
            if isinstance(event, ModelTurn):
                final_turn = event
        if final_turn is None:
            return ModelTurn(content="".join(content_parts))
        if content_parts and not final_turn.content:
            return ModelTurn(content="".join(content_parts), tool_calls=final_turn.tool_calls)
        return final_turn

    async def _execute_tool_call(
        self,
        call: ModelToolCall,
        state: AgentRunState,
        messages: list[dict[str, Any]],
    ) -> AsyncIterator[RuntimeStreamEvent]:
        validation = self.boundary_policy.validate_tool_call(call, scope=state.scope)
        repaired = validation.repaired_call
        yield RuntimeStreamEvent(
            "tool_started",
            {
                "tool_call_id": repaired.id,
                "tool_name": repaired.name,
                "arguments": repaired.arguments,
            },
        )
        started = time.perf_counter()
        if validation.allowed:
            result = await self.tool_runner.execute(repaired.name, repaired.arguments)
        else:
            result = validation.tool_error
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        tool_message, ui_result = build_tool_result_message(repaired, result)
        messages.append(tool_message)
        state.tool_results.append(
            {
                "tool_name": repaired.name,
                "arguments": repaired.arguments,
                "result": result,
                "elapsed_ms": elapsed_ms,
            }
        )
        yield RuntimeStreamEvent(
            "tool_completed",
            {
                "tool_call_id": repaired.id,
                "tool_name": repaired.name,
                "arguments": repaired.arguments,
                "result": ui_result,
                "elapsed_ms": elapsed_ms,
            },
        )

    def _initial_messages(self, state: AgentRunState) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        selected_scope_summary = state.scope.get("selected_scope_summary")
        if isinstance(selected_scope_summary, dict) and selected_scope_summary:
            messages.append(
                {
                    "role": "system",
                    "content": "Selected scope summary: "
                    + json.dumps(selected_scope_summary, ensure_ascii=False, separators=(",", ":")),
                }
            )
        messages.extend(self._compact_history(state.history))
        messages.append({"role": "user", "content": state.question})
        return messages

    def _compact_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact: list[dict[str, Any]] = []
        for item in history[-10:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant", "tool", "system"} and content:
                compact.append({"role": role, "content": str(content)})
        return compact

    def _assistant_tool_call_message(self, turn: ModelTurn) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": turn.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in turn.tool_calls
            ],
        }


_DEFAULT_SYSTEM_PROMPT = (
    "You are PageChat. Decide dynamically whether to answer directly or call tools. "
    "Use tool results as evidence, then answer in the user's language. "
    "Do not expose hidden backend checks."
)
