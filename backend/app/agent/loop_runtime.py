from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import inspect
import json
import time
from typing import Any, Literal

from app.agent.runtime import PageChatRuntimeEvent
from app.agent.state import AgentRunState
from app.agent.nodes import compact_tool_result


ActionType = Literal["call_tool", "answer", "ask_clarification", "fail"]
AnswerGenerator = Callable[[AgentRunState], Any]


@dataclass(frozen=True, slots=True)
class PlannerAction:
    action_type: ActionType
    thought: str = ""
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    error: str = ""

    @classmethod
    def call_tool(
        cls,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        thought: str = "",
    ) -> "PlannerAction":
        return cls(
            action_type="call_tool",
            thought=thought,
            tool_name=tool_name,
            arguments=dict(arguments or {}),
        )

    @classmethod
    def answer(cls, content: str = "", *, thought: str = "") -> "PlannerAction":
        return cls(action_type="answer", thought=thought, content=content)

    @classmethod
    def ask_clarification(cls, content: str, *, thought: str = "") -> "PlannerAction":
        return cls(action_type="ask_clarification", thought=thought, content=content)

    @classmethod
    def fail(cls, error: str, *, thought: str = "") -> "PlannerAction":
        return cls(action_type="fail", thought=thought, error=error)


class AgentLoopRuntime:
    def __init__(
        self,
        *,
        planner: Any,
        tool_runner: Any,
        observation_builder: Any | None = None,
        answer_generator: AnswerGenerator | None = None,
        policy: Any | None = None,
        max_steps: int = 8,
    ) -> None:
        self.planner = planner
        self.tool_runner = tool_runner
        self.observation_builder = observation_builder or ObservationBuilder()
        self.answer_generator = answer_generator
        self.policy = policy
        self.max_steps = max_steps

    async def stream(self, state: AgentRunState):
        state.scope.setdefault("observations", [])
        state.scope.setdefault("evidence_pack", [])

        for step in range(1, self.max_steps + 1):
            action, streamed_thought = None, ""
            emitted_plan = False
            stream_next_action = getattr(self.planner, "stream_next_action", None)
            if callable(stream_next_action):
                async for planner_event in stream_next_action(state):
                    if isinstance(planner_event, PlannerAction):
                        action = planner_event
                        continue
                    if not isinstance(planner_event, dict):
                        continue
                    if planner_event.get("type") != "thought":
                        continue
                    message = str(planner_event.get("message") or "").strip()
                    if not message or message == streamed_thought:
                        continue
                    streamed_thought = message
                    yield PageChatRuntimeEvent(
                        "progress",
                        {
                            "kind": "plan",
                            "message": message,
                            "step": step,
                            "status": "streaming",
                        },
                    )
                    emitted_plan = True
            else:
                action = await self.planner.next_action(state)

            if action is None:
                raise RuntimeError("Planner did not return an action")

            if action.thought and action.thought != streamed_thought:
                yield PageChatRuntimeEvent(
                    "progress",
                    {"kind": "plan", "message": action.thought, "step": step},
                )
                emitted_plan = True

            if self.policy is not None:
                validation = self.policy.validate(action, state)
                if not validation.allowed:
                    observation = dict(validation.observation or {})
                    observation.setdefault("kind", "guardrail")
                    observation.setdefault("step", step)
                    observation.setdefault(
                        "message",
                        "The planner action was rejected by policy.",
                    )
                    state.scope["observations"].append(observation)
                    if emitted_plan:
                        yield PageChatRuntimeEvent(
                            "progress",
                            {
                                "kind": "plan_retract",
                                "message": "",
                                "step": step,
                                "target_kind": "plan",
                            },
                        )
                    continue
                if validation.action is not None:
                    action = validation.action

            if action.action_type == "call_tool":
                async for event in self._execute_tool_action(state, action, step):
                    yield event
                mark_tool_executed = getattr(self.policy, "mark_tool_executed", None)
                if callable(mark_tool_executed):
                    mark_tool_executed(action)
                continue

            if action.action_type in {"answer", "ask_clarification"}:
                content = action.content
                if action.action_type == "answer" and not content and self.answer_generator:
                    async for event in self._stream_generated_answer(state):
                        yield event
                    if not state.answer:
                        raise RuntimeError("No final answer generated by the selected model")
                    return
                state.answer = content or ""
                if state.answer:
                    yield PageChatRuntimeEvent("answer_delta", {"content": state.answer})
                return

            if action.action_type == "fail":
                raise RuntimeError(action.error or "Agent loop failed")

            raise RuntimeError(f"Unsupported planner action: {action.action_type}")

        if self.answer_generator is not None:
            async for event in self._stream_generated_answer(state):
                yield event
            if state.answer:
                return
        raise RuntimeError("No final answer generated by the selected model")

    async def _stream_generated_answer(self, state: AgentRunState):
        if self.answer_generator is None:
            return
        result = self.answer_generator(state)
        if hasattr(result, "__aiter__"):
            answer = ""
            async for chunk in result:
                content = str(chunk or "")
                if not content:
                    continue
                answer += content
                state.answer = answer
                yield PageChatRuntimeEvent("answer_delta", {"content": content})
            return

        content = await result if inspect.isawaitable(result) else result
        state.answer = str(content or "")
        if state.answer:
            yield PageChatRuntimeEvent("answer_delta", {"content": state.answer})

    async def _execute_tool_action(
        self,
        state: AgentRunState,
        action: PlannerAction,
        step: int,
    ):
        cached_evidence = self._matching_prior_evidence(state, action)
        if cached_evidence:
            result = cached_evidence.get("result")
            if not isinstance(result, dict):
                result = {
                    key: value
                    for key, value in cached_evidence.items()
                    if key not in {"arguments", "result", "reused"}
                }
            evidence_pack_item = {
                "tool_name": action.tool_name,
                "arguments": action.arguments,
                **result,
            }
            if evidence_pack_item not in state.scope["evidence_pack"]:
                state.scope["evidence_pack"].append(evidence_pack_item)
            observation = self._reuse_observation(
                action=action,
                cached_evidence=cached_evidence,
                step=step,
            )
            state.scope["observations"].append(observation)
            yield PageChatRuntimeEvent("progress", observation)
            return

        yield PageChatRuntimeEvent(
            "tool_started",
            {
                "tool_name": action.tool_name,
                "arguments": action.arguments,
                "step": step,
            },
        )
        started = time.perf_counter()
        result = await self.tool_runner.execute(action.tool_name, action.arguments)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        compact_result = compact_tool_result(result, tool_name=action.tool_name)
        state.tool_results.append(
            {
                "tool_name": action.tool_name,
                "arguments": action.arguments,
                "result": result,
                "elapsed_ms": elapsed_ms,
            }
        )
        state.scope["evidence_pack"].append(
            {
                "tool_name": action.tool_name,
                "arguments": action.arguments,
                **compact_result,
            }
        )
        yield PageChatRuntimeEvent(
            "tool_completed",
            {
                "tool_name": action.tool_name,
                "result": compact_result,
                "elapsed_ms": elapsed_ms,
                "step": step,
            },
        )
        observation = self.observation_builder.build(
            tool_name=action.tool_name,
            arguments=action.arguments,
            result=result,
            step=step,
        )
        state.scope["observations"].append(observation)
        yield PageChatRuntimeEvent("progress", observation)

    def _matching_prior_evidence(
        self,
        state: AgentRunState,
        action: PlannerAction,
    ) -> dict[str, Any] | None:
        action_signature = self._tool_signature(action.tool_name, action.arguments)
        for evidence in state.scope.get("prior_evidence") or []:
            if not isinstance(evidence, dict):
                continue
            if self._tool_signature(
                str(evidence.get("tool_name") or ""),
                dict(evidence.get("arguments") or {}),
            ) == action_signature:
                return evidence
        return None

    def _reuse_observation(
        self,
        *,
        action: PlannerAction,
        cached_evidence: dict[str, Any],
        step: int,
    ) -> dict[str, Any]:
        doc_id = cached_evidence.get("doc_id")
        page = cached_evidence.get("page")
        return {
            "kind": "reuse",
            "tool_name": action.tool_name,
            "arguments": dict(action.arguments or {}),
            "message": "Using previous evidence.",
            "step": step,
            "reused": True,
            "candidate_document_ids": [str(doc_id)] if doc_id else [],
            "candidate_pages": [int(page)] if isinstance(page, int) else [],
            "evidence_sufficient": action.tool_name
            in {
                "get_page_content",
                "get_page_image",
                "get_document_image",
                "search_within_document",
                "web_search",
            },
        }

    def _tool_signature(self, tool_name: str, arguments: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)}"


class ObservationBuilder:
    def build(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        step: int,
    ) -> dict[str, Any]:
        payload = result if isinstance(result, dict) else {}
        compact = compact_tool_result(payload, tool_name=tool_name)
        observation: dict[str, Any] = {
            "kind": "observation",
            "tool_name": tool_name,
            "message": self._message(tool_name, payload),
            "step": step,
            "candidate_document_ids": self._candidate_document_ids(payload),
            "candidate_pages": self._candidate_pages(payload),
            "evidence_sufficient": self._evidence_sufficient(tool_name, payload),
        }
        if arguments:
            observation["arguments"] = dict(arguments)
        for key in ("success", "status", "error", "next_steps", "summary"):
            if compact.get(key) not in (None, "", []):
                observation[key] = compact[key]
        return observation

    def _message(self, tool_name: str, result: dict[str, Any]) -> str:
        if result.get("error"):
            return str(result.get("error"))
        if tool_name == "view_folder_structure":
            total = result.get("total_folders")
            return f"Observed folder structure with {total or 0} folder(s)."
        if tool_name == "browse_documents":
            folders = len(result.get("folders") or [])
            documents = len(result.get("documents") or [])
            return f"Found {documents} candidate document(s) and {folders} folder(s)."
        if tool_name == "get_document_structure":
            name = result.get("doc_name") or result.get("document_name") or "document"
            return f"Read structure for {name}."
        if tool_name in {"get_page_content", "get_page_image", "get_document_image"}:
            return "Fetched page evidence for the answer."
        if tool_name == "search_within_document":
            matches = len(result.get("matches") or result.get("items") or [])
            return f"Found {matches} keyword match(es) inside the document."
        if tool_name == "web_search":
            results = len(result.get("results") or result.get("items") or [])
            return f"Found {results} web result(s)."
        return "Observed tool result."

    def _candidate_document_ids(self, result: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for key in ("documents", "matches", "items", "results"):
            value = result.get(key)
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                doc_id = item.get("doc_id") or item.get("document_id")
                if doc_id and doc_id not in ids:
                    ids.append(str(doc_id))
        doc_id = result.get("doc_id") or result.get("document_id")
        if doc_id and doc_id not in ids:
            ids.append(str(doc_id))
        data = result.get("data")
        if isinstance(data, dict):
            nested = data.get("doc_id") or data.get("document_id")
            if nested and nested not in ids:
                ids.append(str(nested))
        return ids

    def _candidate_pages(self, result: dict[str, Any]) -> list[int]:
        pages: list[int] = []

        def add_page(value: Any) -> None:
            try:
                page = int(value)
            except (TypeError, ValueError):
                return
            if page > 0 and page not in pages:
                pages.append(page)

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key in ("page", "page_num", "start_page", "start_index"):
                    add_page(value.get(key))
                anchor = value.get("source_anchor")
                if isinstance(anchor, dict):
                    add_page(anchor.get("start_page") or anchor.get("page"))
                for child_key in ("structure", "children", "nodes", "matches", "items", "pages", "content"):
                    visit(value.get(child_key))
            elif isinstance(value, list):
                for item in value[:20]:
                    visit(item)

        visit(result)
        data = result.get("data")
        if isinstance(data, dict):
            visit(data)
        return pages[:5]

    def _evidence_sufficient(self, tool_name: str, result: dict[str, Any]) -> bool:
        if tool_name == "get_page_content":
            compact = compact_tool_result(result, tool_name=tool_name)
            return self._page_content_has_readable_evidence(compact)
        if tool_name in {"get_page_image", "get_document_image"}:
            return not result.get("error")
        if tool_name == "web_search":
            return bool(result.get("results") or result.get("items"))
        return False

    def _page_content_has_readable_evidence(self, compact: dict[str, Any]) -> bool:
        items = compact.get("items")
        if isinstance(items, list) and items:
            return any(self._page_item_has_readable_evidence(item) for item in items)
        if compact.get("visual_evidence_required") is True:
            return False
        return not compact.get("error")

    def _page_item_has_readable_evidence(self, item: Any) -> bool:
        if not isinstance(item, dict):
            return bool(str(item or "").strip())
        for key in ("text", "snippet", "markdown", "structured_content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, (list, dict)) and value:
                return True
        if item.get("visual_evidence_required") is True:
            return False
        if item.get("text_omitted_reason") == "visual_evidence_required":
            return False
        return False


class PolicyGuidedPlanner:
    def __init__(self, *, answer_generator: AnswerGenerator | None = None) -> None:
        self.answer_generator = answer_generator

    async def next_action(self, state: AgentRunState) -> PlannerAction:
        observations = list(state.scope.get("observations") or [])
        if not observations:
            return self._first_action(state)

        last = observations[-1]
        tool_name = last.get("tool_name")
        if tool_name == "view_folder_structure":
            return PlannerAction.call_tool(
                "browse_documents",
                self._browse_arguments(state),
                thought="I found the folder tree. Next I will browse candidate documents.",
            )
        if tool_name == "browse_documents":
            doc_id = self._first_candidate_document_id(observations)
            if doc_id:
                return PlannerAction.call_tool(
                    "get_document_structure",
                    {"doc_id": doc_id, "compact": True},
                    thought="I found a candidate document. Next I will read its structure.",
                )
            return PlannerAction.answer(thought="No candidate document was found.")
        if tool_name in {"get_document_structure", "search_within_document"}:
            doc_id = self._first_candidate_document_id(observations) or self._first_scope_doc_id(state)
            pages = self._page_request(last)
            if doc_id and pages:
                return PlannerAction.call_tool(
                    "get_page_content",
                    {"doc_id": doc_id, "pages": pages},
                    thought="I found likely source pages. Next I will read page evidence.",
                )
            return PlannerAction.answer(thought="The structure is enough to answer at a high level.")
        if tool_name in {"get_page_content", "get_page_image", "get_document_image", "web_search"}:
            return PlannerAction.answer(thought="I have enough observed evidence to answer.")
        return PlannerAction.answer(thought="I will answer from the observations gathered so far.")

    def _first_action(self, state: AgentRunState) -> PlannerAction:
        scope = state.scope
        if scope.get("web_search_requested") and scope.get("web_search_enabled"):
            return PlannerAction.call_tool(
                "web_search",
                {"query": state.question},
                thought="I will search the web because Web Search is enabled for this question.",
            )

        doc_ids = list(scope.get("document_ids") or [])
        if len(doc_ids) == 1:
            if self._looks_like_locating_question(state.question):
                return PlannerAction.call_tool(
                    "search_within_document",
                    {"doc_id": doc_ids[0], "query": state.question},
                    thought="I will locate the relevant mention inside the selected document.",
                )
            return PlannerAction.call_tool(
                "get_document_structure",
                {"doc_id": doc_ids[0], "compact": True},
                thought="I will inspect the selected document structure first.",
            )

        if doc_ids:
            return PlannerAction.call_tool(
                "browse_documents",
                {"query": state.question, "sort": "relevance", "document_ids": doc_ids},
                thought="I will browse the selected documents to find candidates.",
            )

        return PlannerAction.call_tool(
            "view_folder_structure",
            {"folder_id": scope.get("folder_id")} if scope.get("folder_id") else {},
            thought="I will inspect the folder tree before choosing documents.",
        )

    def _browse_arguments(self, state: AgentRunState) -> dict[str, Any]:
        scope = state.scope
        args: dict[str, Any] = {"query": state.question, "sort": "relevance"}
        if scope.get("folder_id"):
            args["folder_id"] = scope["folder_id"]
            args["recursive"] = bool(scope.get("include_subfolders", True))
        if scope.get("document_ids"):
            args["document_ids"] = list(scope.get("document_ids") or [])
        return args

    def _first_candidate_document_id(self, observations: list[dict[str, Any]]) -> str | None:
        for observation in reversed(observations):
            for doc_id in observation.get("candidate_document_ids") or []:
                if doc_id:
                    return str(doc_id)
        return None

    def _first_scope_doc_id(self, state: AgentRunState) -> str | None:
        doc_ids = list(state.scope.get("document_ids") or [])
        return str(doc_ids[0]) if doc_ids else None

    def _page_request(self, observation: dict[str, Any]) -> str:
        pages = observation.get("candidate_pages") or []
        if not pages:
            return "1-3"
        first = int(pages[0])
        if len(pages) == 1:
            return str(first)
        return ",".join(str(int(page)) for page in pages[:3])

    def _looks_like_locating_question(self, question: str) -> bool:
        q = (question or "").lower()
        hints = ("where", "locate", "find", "mention", "search", "page")
        zh_hints = ("哪里", "在哪", "查找", "搜索", "检索", "提到", "出现", "第几页")
        return any(hint in q for hint in hints) or any(hint in q for hint in zh_hints)
