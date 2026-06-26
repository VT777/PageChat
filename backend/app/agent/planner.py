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
    """LLM-driven planner that asks the model for one visible thought and action."""

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
            )
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
        )
        if not hasattr(response, "__aiter__"):
            yield self._parse_action(self._extract_response_content(response))
            return

        content = ""
        last_thought = ""
        async for chunk in response:
            delta = self._extract_chunk_content(chunk)
            if not delta:
                continue
            content += delta
            thought = self._extract_partial_thought(content)
            if thought and thought != last_thought:
                last_thought = thought
                yield {"type": "thought", "message": thought}

        try:
            action = self._parse_action(content)
        except Exception:
            action = await self.next_action(state)
        yield action

    async def _default_completion(self, **kwargs: Any) -> Any:
        from app.core.llm import chat_by_scenario

        return await chat_by_scenario(**kwargs)

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
            "document_registry": self._compact_document_registry(
                state.scope.get("document_registry")
            ),
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
            "Choose the next single PageChat agent action.\n"
            "Return JSON only with this schema:\n"
            "{\"thought\": string, \"action\": {\"type\": "
            "\"call_tool|answer|ask_clarification|fail\", \"tool_name\": "
            "string|null, \"arguments\": object, \"content\": string|null}}\n"
            "The thought is a short user-visible decision note, not hidden chain-of-thought. "
            "It should sound natural, calm, and helpful. "
            "Do not narrate implementation details such as empty scope, policy checks, JSON, "
            "or backend mechanics. When a tool is useful, describe the user-facing goal in "
            "plain language instead of saying that you will use a specific tool, "
            "and avoid robotic phrases such as 'The user asked...' or 'I will use ... tool'. "
            "Do not draft the final answer unless action.type is answer. "
            "For evidence-backed document answers, prefer action.type=answer with empty content "
            "so PageChat can stream the final answer from the answer generator. "
            "For simple library inventory questions, prefer one decisive browse_documents call "
            "with recursive=true when the root or current folder may contain subfolders. "
            "Use the same language as the user's question when possible. "
            "Choose tools freely from available_tools; policy will validate safety and evidence."
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
        }
        return {key: value for key, value in scope.items() if key in allowed}

    def _compact_document_registry(self, registry: Any) -> list[dict[str, Any]]:
        if not isinstance(registry, list):
            return []
        compact: list[dict[str, Any]] = []
        for item in registry[:80]:
            if not isinstance(item, dict):
                continue
            document_id = item.get("document_id") or item.get("doc_id") or item.get("id")
            document_name = (
                item.get("document_name")
                or item.get("doc_name")
                or item.get("name")
                or item.get("original_name")
            )
            if not document_id or not document_name:
                continue
            entry: dict[str, Any] = {
                "document_id": str(document_id),
                "document_name": str(document_name),
            }
            for key in ("folder_id", "path"):
                value = item.get(key)
                if value not in (None, ""):
                    entry[key] = value
            compact.append(entry)
        return compact
