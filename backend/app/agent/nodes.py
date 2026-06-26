from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
import time
from typing import Any

from app.agent.citations import citation_events_from_tool_result, dedupe_citations
from app.agent.state import AgentRunState
from app.services.retrieval_policy import (
    normalize_folder_id,
    question_needs_document_retrieval,
)


AnswerGenerator = Callable[[AgentRunState], Awaitable[str]]
Finalizer = Callable[[AgentRunState], Awaitable[None]]
FailureHandler = Callable[[AgentRunState, str], Awaitable[None]]


@dataclass(slots=True)
class AgentNodeDependencies:
    tool_executor: Any | None = None
    document_service: Any | None = None
    folder_service: Any | None = None
    user_id: str | None = None
    answer_generator: AnswerGenerator | None = None
    finalizer: Finalizer | None = None
    failure_handler: FailureHandler | None = None


def pagechat_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event_type": event_type, "payload": payload}


async def prepare_scope(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    scope = dict(state.scope or {})
    user_id = deps.user_id or scope.get("user_id")
    if deps.document_service is not None and not user_id:
        raise ValueError("user_id is required for document scope resolution")

    explicit_document_scope = any(
        key in scope for key in ("document_ids", "selected_document_ids", "selected_docs")
    )
    document_ids = list(
        scope.get("document_ids")
        or scope.get("selected_document_ids")
        or scope.get("selected_docs")
        or []
    )
    folder_id = normalize_folder_id(scope.get("folder_id"))
    scope["folder_id"] = folder_id
    include_subfolders = bool(scope.get("include_subfolders"))
    invalid_folder_scope = False

    if deps.folder_service is not None and folder_id:
        folder = await deps.folder_service.get_folder(folder_id, user_id=user_id)
        if not folder:
            folder_id = None
            scope["folder_id"] = None
            invalid_folder_scope = True

    if deps.document_service and explicit_document_scope and document_ids:
        docs = await deps.document_service.get_indexed_documents(user_id=user_id)
        available_doc_ids = {doc.id for doc in docs}
        document_ids = [doc_id for doc_id in document_ids if doc_id in available_doc_ids]
    elif (
        deps.document_service
        and not document_ids
        and not explicit_document_scope
        and not invalid_folder_scope
        and not folder_id
    ):
        docs = await deps.document_service.get_indexed_documents(user_id=user_id)
        scope["user_library_document_ids"] = [doc.id for doc in docs]

    scope["document_ids"] = document_ids
    scope["user_id"] = user_id
    scope["strict_scope"] = bool(scope.get("strict_scope", bool(document_ids or folder_id)))
    scope["suppress_user_library_fallback"] = bool(
        scope.get("suppress_user_library_fallback")
        or invalid_folder_scope
        or (explicit_document_scope and not document_ids and not folder_id)
    )
    state.scope = scope
    yield pagechat_event(
        "progress",
        {
            "node": "prepare_scope",
            "message": "Preparing answer scope",
            "scope": {
                "document_ids": document_ids,
                "folder_id": scope.get("folder_id"),
                "strict_scope": scope.get("strict_scope"),
            },
        },
    )


async def decide_retrieval(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    del deps
    scope = state.scope
    document_ids = list(scope.get("document_ids") or [])
    user_library_document_ids = list(scope.get("user_library_document_ids") or [])
    folder_id = normalize_folder_id(scope.get("folder_id"))
    scope["folder_id"] = folder_id
    include_subfolders = bool(scope.get("include_subfolders"))
    retrieval_plan: list[dict[str, Any]] = []

    if scope.get("web_search_requested") and scope.get("web_search_enabled"):
        retrieval_plan.append(
            {
                "tool_name": scope.get("web_search_tool") or "web_search",
                "arguments": {"query": state.question},
                "reason": "Use web search because the user enabled and requested it.",
            }
        )
    elif len(document_ids) == 1 and not folder_id:
        retrieval_plan.append(
            {
                "tool_name": "get_document_structure",
                "arguments": {"doc_id": document_ids[0], "compact": True},
                "reason": "Inspect selected document structure first.",
            }
        )
    elif document_ids or folder_id:
        arguments: dict[str, Any] = {"query": state.question, "sort": "relevance"}
        if document_ids and scope.get("strict_scope"):
            arguments["document_ids"] = document_ids
        if folder_id and scope.get("strict_scope"):
            arguments["folder_id"] = folder_id
        if include_subfolders and scope.get("strict_scope"):
            arguments["recursive"] = True
        retrieval_plan.append(
            {
                "tool_name": "browse_documents",
                "arguments": arguments,
                "reason": "Find candidate documents within the selected scope.",
            }
        )
    elif (
        user_library_document_ids
        and not scope.get("suppress_user_library_fallback")
        and question_needs_document_retrieval(state.question)
    ):
        retrieval_plan.append(
            {
                "tool_name": "browse_documents",
                "arguments": {
                    "query": state.question,
                    "sort": "relevance",
                    "document_ids": user_library_document_ids,
                },
                "reason": "Find candidate documents in the user's library.",
            }
        )

    scope["retrieval_plan"] = retrieval_plan
    yield pagechat_event(
        "progress",
        {
            "node": "decide_retrieval",
            "message": "Choosing retrieval strategy",
            "tool_count": len(retrieval_plan),
        },
    )


async def execute_tools(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    retrieval_plan = list(state.scope.get("retrieval_plan") or [])
    if retrieval_plan and deps.tool_executor is None:
        raise ValueError("Agent graph requires tool_executor when retrieval_plan is not empty")

    for step in retrieval_plan:
        tool_name = str(step.get("tool_name") or "")
        arguments = dict(step.get("arguments") or {})
        yield pagechat_event(
            "tool_started",
            {"tool_name": tool_name, "arguments": arguments},
        )
        started = time.perf_counter()
        result = await deps.tool_executor.execute(tool_name, arguments)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        state.tool_results.append(
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "result": result,
                "elapsed_ms": elapsed_ms,
            }
        )
        yield pagechat_event(
            "tool_completed",
            {
                "tool_name": tool_name,
                "result": compact_tool_result(result, tool_name=tool_name),
                "elapsed_ms": elapsed_ms,
            },
        )


async def build_evidence_pack(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    del deps
    evidence_pack = [
        {
            "tool_name": item.get("tool_name"),
            "arguments": item.get("arguments"),
            **compact_tool_result(
                item.get("result"),
                tool_name=str(item.get("tool_name") or ""),
            ),
        }
        for item in state.tool_results
    ]
    state.scope["evidence_pack"] = evidence_pack
    yield pagechat_event(
        "progress",
        {
            "node": "build_evidence_pack",
            "message": "Organizing evidence",
            "evidence_count": len(evidence_pack),
        },
    )


def compact_tool_result(result: Any, tool_name: str | None = None) -> dict[str, Any]:
    citations = (
        citation_events_from_tool_result(result)
        if _tool_result_can_cite_answer(tool_name)
        else []
    )
    if not isinstance(result, dict):
        return {
            "status": "",
            "summary": _truncate(str(result or "")),
            "items": [],
            "citations": citations,
        }

    items: list[dict[str, Any]] = []
    for key in ("documents", "matches", "pages", "results", "items"):
        value = result.get(key)
        if isinstance(value, list):
            items.extend(_compact_evidence_item(item) for item in value[:5])
            break

    error = result.get("error")
    success = result.get("success")
    status = result.get("status") or ""
    if error and not status:
        status = "error"
    summary = result.get("summary") or result.get("message") or error or ""
    compact = {
        "status": str(status),
        "summary": _truncate(str(summary)),
        "items": [item for item in items if item],
        "citations": citations,
    }
    if success is not None:
        compact["success"] = bool(success)
    if error:
        compact["error"] = _truncate(str(error))
    next_steps = _compact_next_steps(result.get("next_steps"))
    if next_steps:
        compact["next_steps"] = next_steps
    return compact


def _compact_evidence_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"text": _truncate(str(item or ""))}

    compact: dict[str, Any] = {}
    key_map = {
        "document_id": ("document_id", "doc_id"),
        "document_name": ("document_name", "doc_name", "name", "title"),
        "display_label": ("display_label", "source_label"),
        "source_anchor": ("source_anchor",),
        "snippet": ("snippet", "text", "content", "summary"),
        "url": ("url",),
    }
    for target, source_keys in key_map.items():
        value = _first_item_value(item, source_keys)
        if value not in (None, ""):
            compact[target] = _truncate(value) if isinstance(value, str) else value
    return compact


def _first_item_value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _compact_next_steps(value: Any) -> list[str]:
    steps: list[str] = []

    def add(step: Any) -> None:
        if step in (None, ""):
            return
        text = _truncate(str(step), limit=180)
        if text and text not in steps:
            steps.append(text)

    if isinstance(value, dict):
        add(value.get("summary"))
        options = value.get("options")
        if isinstance(options, list):
            for option in options:
                add(option)
                if len(steps) >= 3:
                    break
        add(value.get("continuation_hint"))
    elif isinstance(value, list):
        for option in value:
            add(option)
            if len(steps) >= 3:
                break
    elif isinstance(value, str):
        add(value)

    return steps[:3]


def _tool_result_can_cite_answer(tool_name: str | None) -> bool:
    return tool_name in {
        "get_page_content",
        "get_page_image",
        "get_document_image",
        "web_search",
    }


def _truncate(value: str, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


async def generate_answer(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    if deps.answer_generator is None:
        raise ValueError("Agent graph requires answer_generator")
    answer = await deps.answer_generator(state)
    state.answer = answer or ""
    if state.answer:
        yield pagechat_event("answer_delta", {"content": state.answer})


async def bind_citations(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    del deps
    citations: list[dict[str, Any]] = []
    for tool_result in state.tool_results:
        citations.extend(citation_events_from_tool_result(tool_result.get("result")))
    state.citations = dedupe_citations(citations)
    for citation in state.citations:
        yield pagechat_event("citation_added", {"citation": citation})


async def finalize(
    state: AgentRunState,
    deps: AgentNodeDependencies,
) -> AsyncIterator[dict[str, Any]]:
    if deps.finalizer is not None:
        await deps.finalizer(state)
    yield pagechat_event(
        "progress",
        {
            "node": "finalize",
            "message": "Finalizing answer",
            "citation_count": len(state.citations),
        },
    )
