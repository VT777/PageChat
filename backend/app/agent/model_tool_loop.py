from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import time
from typing import Any

from app.agent.model_turn import (
    ModelReasoningDelta,
    ModelTextDelta,
    ModelToolCall,
    ModelToolCallDelta,
    ModelTurn,
)
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
            turn: ModelTurn | None = None
            streamed_content = ""
            candidate_text = ""
            buffered_text_deltas: list[str] = []
            tool_call_stream_started = False
            async for model_event in self.model.stream_turn(
                messages=messages,
                tools=self.tools,
                user_id=state.scope.get("user_id"),
            ):
                if isinstance(model_event, ModelReasoningDelta):
                    yield RuntimeStreamEvent(
                        "reasoning_delta",
                        {"content": model_event.delta, "status": "streaming"},
                    )
                    continue
                if isinstance(model_event, ModelTextDelta):
                    streamed_content += model_event.delta
                    if tool_call_stream_started:
                        yield RuntimeStreamEvent(
                            "processing_delta",
                            {"content": model_event.delta, "status": "streaming"},
                        )
                    else:
                        candidate_text += model_event.delta
                        yield RuntimeStreamEvent(
                            "answer_candidate_delta",
                            {"content": model_event.delta},
                        )
                        buffered_text_deltas.append(model_event.delta)
                    continue
                if isinstance(model_event, ModelToolCallDelta):
                    if not tool_call_stream_started:
                        tool_call_stream_started = True
                        if candidate_text:
                            yield RuntimeStreamEvent(
                                "answer_candidate_retract",
                                {"content": candidate_text},
                            )
                            candidate_text = ""
                        buffered_text_deltas = []
                    yield RuntimeStreamEvent(
                        "tool_call_delta",
                        {
                            "tool_call_id": model_event.id,
                            "tool_name": model_event.name,
                            "arguments_delta": model_event.arguments_delta,
                            "status": "streaming",
                        },
                    )
                    continue
                if isinstance(model_event, ModelTurn):
                    turn = model_event

            if turn is None:
                turn = ModelTurn(content=streamed_content)
            elif streamed_content and not turn.content and not turn.tool_calls:
                turn = ModelTurn(content=streamed_content)

            if turn.has_tool_calls:
                if candidate_text:
                    yield RuntimeStreamEvent(
                        "answer_candidate_retract",
                        {"content": candidate_text},
                    )
                    candidate_text = ""
                    buffered_text_deltas = []
                messages.append(self._assistant_tool_call_message(turn))
                for call in turn.tool_calls:
                    async for event in self._execute_tool_call(call, state, messages):
                        yield event
                continue
            if turn.content.strip():
                if candidate_text:
                    state.answer += candidate_text
                    yield RuntimeStreamEvent(
                        "answer_candidate_commit",
                        {"content": candidate_text},
                    )
                    remainder = ""
                    if turn.content.startswith(streamed_content):
                        remainder = turn.content[len(streamed_content):]
                    elif not turn.content.startswith(candidate_text):
                        remainder = turn.content
                    if remainder:
                        state.answer += remainder
                        yield RuntimeStreamEvent("answer_delta", {"content": remainder})
                elif streamed_content:
                    state.answer += turn.content
                    yield RuntimeStreamEvent("answer_delta", {"content": turn.content})
                else:
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
            source = selected_scope_summary.get("source")
            if source == "user_selected":
                scope_label = "User-selected scope summary: "
            elif source == "auto_matched":
                scope_label = "Automatically matched scope summary: "
            else:
                scope_label = "Selected scope summary: "
            messages.append(
                {
                    "role": "system",
                    "content": scope_label
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
    "You are PageChat, a document intelligence assistant. Decide dynamically "
    "whether to answer directly, ask a clarifying question, or call tools. "
    "Choose tools only when they close an information gap for the current turn; "
    "there is no fixed document workflow. When tool results are enough, answer "
    "in the user's language. When using document evidence, put the provided "
    "human-readable citation_marker, formatted like [[display_label]], immediately "
    "after the supported claim. Never write internal IDs, citation_key values, "
    "or raw markers such as [cite: ...]. For web evidence, cite with normal "
    "markdown links. For user-provided URLs, call web_search with intent=read_url "
    "or extract and pass the URL in urls; never pass a URL as a document doc_id. "
    "Keep progress notes concise. Do not expose internal mechanics."
)


def _processing_note_for_tool(tool_name: str, question: str) -> str:
    zh = _looks_chinese(question)
    notes = {
        "view_folder_structure": ("正在查看文件夹结构。", "Checking the folder structure."),
        "browse_documents": ("正在查看文档库。", "Checking the document library."),
        "get_document_structure": ("正在查看文档结构。", "Checking the document structure."),
        "search_within_document": ("正在文档内搜索相关内容。", "Searching within the document."),
        "get_page_content": ("正在读取相关页面。", "Reading the relevant page."),
        "get_page_image": ("正在获取页面图像。", "Getting the page image."),
        "get_document_image": ("正在获取文档图像。", "Getting the document image."),
        "web_search": ("正在搜索网页。", "Searching the web."),
    }
    zh_note, en_note = notes.get(
        tool_name,
        ("正在使用工具核对信息。", "Checking information with a tool."),
    )
    return zh_note if zh else en_note


def _looks_chinese(text: str) -> bool:
    if not text:
        return False
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return cjk > 0 and cjk / max(len(text), 1) >= 0.15
