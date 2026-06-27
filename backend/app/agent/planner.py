from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from typing import Any, Protocol

from app.agent.loop_runtime import PlannerAction
from app.agent.state import AgentRunState


CompletionFn = Callable[..., Awaitable[Any]]


class PlannerAdapter(Protocol):
    async def next_action(self, state: AgentRunState) -> PlannerAction:
        ...


class StructuredLLMPlanner:
    """LLM-driven planner that asks the model for one visible turn decision."""

    def __init__(
        self,
        *,
        completion_fn: CompletionFn | None = None,
        tools: list[dict[str, Any]] | None = None,
        user_id: str | None = None,
        max_retries: int = 1,
    ) -> None:
        self.completion_fn = completion_fn or self._default_completion
        self.tools = list(tools or [])
        self.user_id = user_id
        self.max_retries = max(0, int(max_retries))

    async def next_action(self, state: AgentRunState) -> PlannerAction:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            messages = self._messages(state, retry_error=last_error if attempt else "")
            response = await self.completion_fn(
                scenario="qa",
                messages=messages,
                stream=False,
                user_id=self.user_id or state.scope.get("user_id"),
                disable_thinking=True,
                **self._native_tool_kwargs(),
            )
            native_tool_calls = self._extract_response_tool_calls(response)
            if native_tool_calls:
                return PlannerAction.call_tools(native_tool_calls)
            content = self._extract_response_content(response)
            try:
                return self._parse_action(content)
            except Exception as exc:
                last_error = str(exc)
        raise RuntimeError(f"Planner output was invalid JSON: {last_error}")

    async def stream_next_action(self, state: AgentRunState):
        messages = self._messages(state)
        response = await self.completion_fn(
            scenario="qa",
            messages=messages,
            stream=True,
            user_id=self.user_id or state.scope.get("user_id"),
            disable_thinking=True,
            **self._native_tool_kwargs(),
        )
        if not hasattr(response, "__aiter__"):
            native_tool_calls = self._extract_response_tool_calls(response)
            if native_tool_calls:
                yield PlannerAction.call_tools(native_tool_calls)
                return
            yield self._parse_action(self._extract_response_content(response))
            return

        content = ""
        last_thought = ""
        tool_call_buffers: dict[int, dict[str, Any]] = {}
        async for chunk in response:
            for tool_delta in self._extract_chunk_tool_call_deltas(chunk):
                index = int(tool_delta.get("index") or 0)
                current = tool_call_buffers.setdefault(
                    index,
                    {"tool_call_id": "", "tool_name": "", "arguments": ""},
                )
                if tool_delta.get("tool_call_id"):
                    current["tool_call_id"] = tool_delta["tool_call_id"]
                if tool_delta.get("tool_name"):
                    current["tool_name"] = tool_delta["tool_name"]
                if tool_delta.get("arguments_delta"):
                    current["arguments"] = (
                        str(current.get("arguments") or "")
                        + str(tool_delta.get("arguments_delta") or "")
                    )
                yield {
                    "type": "tool_call_delta",
                    "tool_call_id": current.get("tool_call_id") or "",
                    "tool_name": current.get("tool_name") or "",
                    "arguments_delta": str(tool_delta.get("arguments_delta") or ""),
                }
            delta = self._extract_chunk_content(chunk)
            if not delta:
                continue
            content += delta
            thought = self._extract_partial_thought(content)
            if thought and thought != last_thought:
                last_thought = thought
                yield {"type": "thought", "message": thought}

        if tool_call_buffers:
            yield PlannerAction.call_tools(
                [
                    {
                        "tool_name": str(item.get("tool_name") or ""),
                        "arguments": self._parse_tool_arguments(
                            str(item.get("arguments") or "")
                        ),
                    }
                    for _, item in sorted(tool_call_buffers.items())
                    if item.get("tool_name")
                ]
            )
            return

        try:
            action = self._parse_action(content)
        except Exception:
            action = await self.next_action(state)
        yield action

    async def _default_completion(self, **kwargs: Any) -> Any:
        from app.core.llm import chat_by_scenario

        return await chat_by_scenario(**kwargs)

    def _native_tool_kwargs(self) -> dict[str, Any]:
        if not self.tools:
            return {}
        return {
            "tools": self.tools,
            "tool_choice": "auto",
            "allow_deterministic_tools": True,
        }

    def _messages(self, state: AgentRunState, *, retry_error: str = "") -> list[dict[str, str]]:
        tools = [
            {
                "name": tool.get("function", {}).get("name"),
                "description": tool.get("function", {}).get("description", ""),
                "parameters": tool.get("function", {}).get("parameters", {}),
            }
            for tool in self.tools
            if tool.get("function", {}).get("name")
        ]
        payload = {
            "question": state.question,
            "history": self._compact_history(state.history),
            "scope": self._compact_scope(state.scope),
            "available_tools": tools,
            "observations": list(state.scope.get("observations") or [])[-8:],
            "evidence_pack": list(state.scope.get("evidence_pack") or [])[-6:],
            "tool_results_count": len(state.tool_results),
        }
        if retry_error:
            payload["retry_instruction"] = (
                "The previous planner output was invalid JSON or invalid schema: "
                f"{retry_error}. Return only valid JSON now."
            )
        instruction = (
            "Choose the next PageChat agent turn.\n"
            "Return JSON only with this schema:\n"
            "{\"thought\": string, \"action\": {\"type\": "
            "\"call_tool|answer|ask_clarification|fail\", \"tool_name\": "
            "string|null, \"arguments\": object, \"tool_calls\": "
            "[{\"tool_name\": string, \"arguments\": object}]|null, "
            "\"content\": string|null}}\n"
            "You decide whether to answer, ask for clarification, or call tools. "
            "When several independent tools are useful in the same turn, put them in "
            "action.tool_calls instead of forcing extra planning rounds. "
            "Policy only enforces boundaries such as available tools, scope, citations, "
            "and unsafe or unsupported final answers; it does not plan the route for you. "
            "The thought is a short user-visible decision note, not hidden chain-of-thought. "
            "It should sound natural, calm, and helpful. "
            "Do not narrate implementation details such as empty scope, policy checks, JSON, "
            "or backend mechanics. When a tool is useful, describe the user-facing goal in "
            "plain language instead of saying that you will use a specific tool, "
            "and avoid robotic phrases such as 'The user asked...' or 'I will use ... tool'. "
            "Do not draft the final answer unless action.type is answer. "
            "For evidence-backed document answers, prefer action.type=answer with empty content "
            "so PageChat can stream the final answer from the answer generator. "
            "For simple selected-scope inventory or count questions, answer directly when "
            "scope.selected_scope_summary already provides the requested count. "
            "If observations or evidence_pack contain reused prior evidence that answers the question, "
            "choose answer instead of calling the same tool again. "
            "Do not repeat a tool call with the same arguments unless the prior evidence has an explicit gap. "
            "Only browse documents when the user needs a document list or content selection "
            "that is not already covered by the selected scope summary. "
            "Use the same language as the user's question when possible. "
            "Choose tools freely from available_tools according to the information gap."
        )
        if retry_error:
            instruction += "\nThe previous planner output was invalid; follow the JSON schema exactly."
        return [
            {"role": "system", "content": instruction},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ]

    def _parse_action(self, content: str) -> PlannerAction:
        data = json.loads(self._extract_json_object(content))
        if not isinstance(data, dict):
            raise ValueError("Planner response must be a JSON object")
        thought = str(data.get("thought") or "").strip()
        raw_action = data.get("action")
        if not isinstance(raw_action, dict):
            raise ValueError("Planner response action must be an object")

        action_type = str(raw_action.get("type") or "").strip()
        if action_type == "call_tool":
            tool_calls = raw_action.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                return PlannerAction.call_tools(tool_calls, thought=thought)
            tool_name = str(raw_action.get("tool_name") or "").strip()
            arguments = raw_action.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("call_tool arguments must be an object")
            return PlannerAction.call_tool(tool_name, arguments, thought=thought)
        if action_type == "answer":
            return PlannerAction.answer(
                str(raw_action.get("content") or ""),
                thought=thought,
            )
        if action_type == "ask_clarification":
            return PlannerAction.ask_clarification(
                str(raw_action.get("content") or ""),
                thought=thought,
            )
        if action_type == "fail":
            return PlannerAction.fail(
                str(raw_action.get("content") or raw_action.get("error") or "Planner failed"),
                thought=thought,
            )
        raise ValueError(f"Unsupported planner action type: {action_type}")

    def _extract_json_object(self, content: str) -> str:
        text = (content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        raise ValueError("No JSON object found")

    def _extract_response_content(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message") or {}
                    if isinstance(message, dict):
                        return str(message.get("content") or "")
                    delta = first.get("delta") or {}
                    if isinstance(delta, dict):
                        return str(delta.get("content") or "")
            return str(response.get("content") or response.get("output_text") or "")
        choices = getattr(response, "choices", None)
        if choices:
            first = choices[0]
            message = getattr(first, "message", None)
            if message is not None:
                return str(getattr(message, "content", "") or "")
            delta = getattr(first, "delta", None)
            if delta is not None:
                return str(getattr(delta, "content", "") or "")
        return str(getattr(response, "content", "") or getattr(response, "output_text", "") or "")

    def _extract_response_tool_calls(self, response: Any) -> list[dict[str, Any]]:
        choices = self._get_value(response, "choices") or []
        if not choices:
            return []
        first = choices[0]
        message = self._get_value(first, "message") or {}
        raw_tool_calls = self._get_value(message, "tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        for raw_call in raw_tool_calls:
            function = self._get_value(raw_call, "function") or {}
            tool_name = str(self._get_value(function, "name") or "").strip()
            if not tool_name:
                continue
            tool_calls.append(
                {
                    "tool_name": tool_name,
                    "arguments": self._parse_tool_arguments(
                        str(self._get_value(function, "arguments") or "")
                    ),
                }
            )
        return tool_calls

    def _extract_chunk_content(self, chunk: Any) -> str:
        if isinstance(chunk, dict):
            choices = chunk.get("choices") or []
            if choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta") or {}
                if isinstance(delta, dict):
                    return str(delta.get("content") or "")
            return ""
        choices = getattr(chunk, "choices", None)
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return ""
        return str(getattr(delta, "content", "") or "")

    def _extract_chunk_tool_call_deltas(self, chunk: Any) -> list[dict[str, Any]]:
        choices = self._get_value(chunk, "choices") or []
        if not choices:
            return []
        first = choices[0]
        delta = self._get_value(first, "delta") or {}
        raw_tool_calls = self._get_value(delta, "tool_calls") or []
        deltas: list[dict[str, Any]] = []
        for position, raw_call in enumerate(raw_tool_calls):
            function = self._get_value(raw_call, "function") or {}
            deltas.append(
                {
                    "index": self._get_value(raw_call, "index") or position,
                    "tool_call_id": self._get_value(raw_call, "id") or "",
                    "tool_name": self._get_value(function, "name") or "",
                    "arguments_delta": self._get_value(function, "arguments") or "",
                }
            )
        return deltas

    def _parse_tool_arguments(self, text: str) -> dict[str, Any]:
        if not text:
            return {}
        try:
            value = json.loads(text)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _get_value(self, value: Any, key: str) -> Any:
        if isinstance(value, dict):
            return value.get(key)
        return getattr(value, key, None)

    def _extract_partial_thought(self, content: str) -> str:
        key_index = content.find('"thought"')
        if key_index < 0:
            return ""
        colon_index = content.find(":", key_index)
        if colon_index < 0:
            return ""
        quote_index = content.find('"', colon_index)
        if quote_index < 0:
            return ""
        chars: list[str] = []
        escaped = False
        for char in content[quote_index + 1 :]:
            if escaped:
                chars.append(char)
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                return "".join(chars)
            chars.append(char)
        return "".join(chars)

    def _compact_history(self, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact: list[dict[str, Any]] = []
        for item in history[-6:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                compact.append({"role": role, "content": content[:1200]})
        return compact

    def _compact_scope(self, scope: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "document_ids",
            "preferred_document_ids",
            "folder_id",
            "include_subfolders",
            "strict_scope",
            "web_search_requested",
            "web_search_enabled",
            "suppress_user_library_fallback",
            "selected_scope_summary",
        }
        return {key: value for key, value in scope.items() if key in allowed}
