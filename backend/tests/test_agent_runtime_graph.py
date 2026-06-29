import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.runtime import PageChatAgentRuntime  # noqa: E402
from app.agent.state import AgentRunState  # noqa: E402
from app.agent.graph import PageChatAgentGraph  # noqa: E402
from app.agent.nodes import AgentNodeDependencies  # noqa: E402
from app.services.agent_service import AgentService  # noqa: E402


class FakeGraph:
    async def astream(self, state: AgentRunState):
        assert state.question == "Summarize alpha"
        yield {
            "event_type": "progress",
            "payload": {"message": "Preparing scoped evidence"},
        }
        yield {
            "event_type": "answer_delta",
            "payload": {"content": "Alpha summary"},
        }


class FakeLangGraphV2CustomGraph:
    def __init__(self):
        self.stream_kwargs = None

    async def astream(self, state: AgentRunState, **kwargs):
        self.stream_kwargs = kwargs
        yield {
            "type": "updates",
            "ns": (),
            "data": {"prepare_scope": {"scope": state.scope}},
        }
        yield {
            "type": "custom",
            "ns": (),
            "data": {
                "event_type": "progress",
                "payload": {"message": "Scoped evidence is ready"},
            },
        }
        yield {
            "type": "custom",
            "ns": (),
            "data": {
                "type": "answer_delta",
                "data": {"content": "Alpha from LangGraph"},
            },
        }


class FailingGraph:
    async def astream(self, state: AgentRunState, **kwargs):
        raise RuntimeError("graph exploded")
        yield


def test_runtime_wraps_fake_graph_events_as_pagechat_events() -> None:
    async def run() -> None:
        state = AgentRunState(
            question="Summarize alpha",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["doc-alpha"]},
            history=[{"role": "user", "content": "Earlier question"}],
            provider_capabilities={"supports_streaming": True},
        )

        runtime = PageChatAgentRuntime(graph=FakeGraph())
        events = [event async for event in runtime.stream(state)]

        assert [event.event_type for event in events] == [
            "run_started",
            "progress",
            "answer_delta",
            "run_completed",
        ]
        assert [event.payload["seq"] for event in events] == [1, 2, 3, 4]
        assert all(event.payload["run_id"] == "run-alpha" for event in events)
        assert all(
            event.payload["conversation_id"] == "conv-alpha" for event in events
        )
        assert all(event.payload["message_id"] == "msg-alpha" for event in events)
        assert all(event.payload["ts"] for event in events)
        assert events[1].payload["message"] == "Preparing scoped evidence"
        assert events[2].payload["content"] == "Alpha summary"

    asyncio.run(run())


def test_runtime_translates_langgraph_v2_custom_chunks_only() -> None:
    async def run() -> None:
        state = AgentRunState(
            question="Summarize alpha",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        graph = FakeLangGraphV2CustomGraph()
        runtime = PageChatAgentRuntime(graph=graph)
        events = [event async for event in runtime.stream(state)]

        assert graph.stream_kwargs == {"stream_mode": "custom", "version": "v2"}
        assert [event.event_type for event in events] == [
            "run_started",
            "progress",
            "answer_delta",
            "run_completed",
        ]
        assert events[1].payload["message"] == "Scoped evidence is ready"
        assert events[2].payload["content"] == "Alpha from LangGraph"

    asyncio.run(run())


def test_runtime_emits_run_failed_without_reraising_graph_errors() -> None:
    async def run() -> None:
        state = AgentRunState(
            question="Summarize alpha",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        runtime = PageChatAgentRuntime(graph=FailingGraph())
        events = [event async for event in runtime.stream(state)]

        assert [event.event_type for event in events] == [
            "run_started",
            "run_failed",
        ]
        assert events[1].payload["status"] == "failed"
        assert events[1].payload["error"] == "graph exploded"

    asyncio.run(run())


class RecordingToolExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        return {
            "status": "success",
            "page_image_base64": "raw-image-payload",
            "text_content": "raw page text that should not be emitted in tool events",
            "documents": [
                {
                    "doc_id": arguments.get("doc_id") or "doc-alpha",
                    "doc_name": "alpha.pdf",
                    "source_anchor": {
                        "format": "pdf",
                        "unit_type": "page",
                        "start_page": 2,
                        "end_page": 2,
                    },
                    "display_label": "alpha p.2",
                }
            ],
        }


class FakeDocument:
    def __init__(self, doc_id: str, folder_id: str | None = None):
        self.id = doc_id
        self.folder_id = folder_id


class FakeDocumentService:
    def __init__(self):
        self.indexed_calls = []
        self.list_calls = []

    async def get_indexed_documents(self, user_id=None):
        self.indexed_calls.append(user_id)
        return [FakeDocument("doc-library-a"), FakeDocument("doc-library-b")]

    async def list_documents(self, **kwargs):
        self.list_calls.append(kwargs)
        return [FakeDocument("doc-folder-a", folder_id=kwargs.get("folder_id"))], 1


class LargeFolderDocumentService(FakeDocumentService):
    async def list_documents(self, **kwargs):
        self.list_calls.append(kwargs)
        page = int(kwargs.get("page") or 1)
        page_size = int(kwargs.get("page_size") or 500)
        docs = [
            FakeDocument(f"doc-folder-{index}", folder_id=kwargs.get("folder_id"))
            for index in range(501)
        ]
        start = (page - 1) * page_size
        end = start + page_size
        return docs[start:end], len(docs)


class FakeFolderService:
    def __init__(self):
        self.get_calls = []

    async def get_folder(self, folder_id, user_id=None):
        self.get_calls.append({"folder_id": folder_id, "user_id": user_id})
        if folder_id == "folder-a":
            return object()
        return None


class RecordingFinalizer:
    def __init__(self):
        self.finalized_state = None

    async def __call__(self, state: AgentRunState):
        self.finalized_state = state


class RecordingFailureHandler:
    def __init__(self):
        self.failed = None

    async def __call__(self, state: AgentRunState, error: str):
        self.failed = (state, error)


async def fake_answer_generator(state: AgentRunState) -> str:
    assert state.tool_results
    return "Alpha summary with evidence."


async def fake_answer_generator_without_tools(state: AgentRunState) -> str:
    assert state.tool_results == []
    return "Hello."


async def failing_answer_generator(state: AgentRunState) -> str:
    raise RuntimeError("provider failed")


def test_agent_graph_runs_explicit_nodes_and_emits_pagechat_events() -> None:
    async def run() -> None:
        tool_executor = RecordingToolExecutor()
        finalizer = RecordingFinalizer()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator,
                finalizer=finalizer,
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="Summarize this document",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["doc-alpha"], "strict_scope": True},
        )

        events = [event async for event in runtime.stream(state)]
        event_types = [event.event_type for event in events]

        assert event_types == [
            "run_started",
            "progress",
            "progress",
            "tool_started",
            "tool_completed",
            "progress",
            "answer_delta",
            "citation_added",
            "progress",
            "run_completed",
        ]
        assert tool_executor.calls == [
            ("get_document_structure", {"doc_id": "doc-alpha", "compact": True})
        ]
        tool_completed = [event for event in events if event.event_type == "tool_completed"][0]
        assert "page_image_base64" not in str(tool_completed.payload)
        assert "raw page text" not in str(tool_completed.payload)
        assert tool_completed.payload["result"]["items"][0]["document_id"] == "doc-alpha"
        assert state.tool_results[0]["tool_name"] == "get_document_structure"
        assert state.scope["evidence_pack"] == [
            {
                "tool_name": "get_document_structure",
                "arguments": {"doc_id": "doc-alpha", "compact": True},
                "status": "success",
                "summary": "",
                "items": [
                    {
                        "document_id": "doc-alpha",
                        "document_name": "alpha.pdf",
                        "display_label": "alpha p.2",
                        "source_anchor": {
                            "format": "pdf",
                            "unit_type": "page",
                            "start_page": 2,
                            "end_page": 2,
                        },
                    }
                ],
                "citations": state.scope["evidence_pack"][0]["citations"],
            }
        ]
        assert state.scope["evidence_pack"][0]["citations"][0]["document_id"] == "doc-alpha"
        assert "result" not in state.scope["evidence_pack"][0]
        assert state.answer == "Alpha summary with evidence."
        assert state.citations[0]["document_id"] == "doc-alpha"
        assert finalizer.finalized_state is state

    asyncio.run(run())


def test_agent_graph_requires_user_id_before_document_scope_resolution() -> None:
    async def run() -> None:
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=FakeDocumentService(),
                tool_executor=RecordingToolExecutor(),
                answer_generator=fake_answer_generator,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="Summarize available documents",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        events = await _consume_runtime(runtime, state)

        assert [event.event_type for event in events] == ["run_started", "run_failed"]
        assert "user_id" in events[1].payload["error"]

    asyncio.run(run())


def test_agent_graph_failure_handler_persists_failed_runs() -> None:
    async def run() -> None:
        failure_handler = RecordingFailureHandler()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                tool_executor=RecordingToolExecutor(),
                answer_generator=failing_answer_generator,
                finalizer=RecordingFinalizer(),
                failure_handler=failure_handler,
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="Summarize this document",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["doc-alpha"], "strict_scope": True},
        )

        events = await _consume_runtime(runtime, state)

        assert events[-1].event_type == "run_failed"
        assert failure_handler.failed == (state, "provider failed")

    asyncio.run(run())


def test_agent_graph_resolves_user_library_before_retrieval_decision() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="Summarize available documents",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        await _consume_runtime(runtime, state)

        assert document_service.indexed_calls == ["user-a"]
        assert state.scope["user_library_document_ids"] == [
            "doc-library-a",
            "doc-library-b",
        ]
        assert tool_executor.calls == [
            (
                "browse_documents",
                {
                    "query": "Summarize available documents",
                    "sort": "relevance",
                    "document_ids": ["doc-library-a", "doc-library-b"],
                },
            )
        ]

    asyncio.run(run())


def test_agent_graph_skips_document_retrieval_for_general_greeting() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator_without_tools,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="\u4f60\u597d",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
        )

        events = await _consume_runtime(runtime, state)

        assert document_service.indexed_calls == ["user-a"]
        assert state.scope["retrieval_plan"] == []
        assert tool_executor.calls == []
        assert "tool_started" not in [event.event_type for event in events]

    asyncio.run(run())


def test_agent_graph_explicit_empty_document_scope_does_not_fallback_to_library() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator_without_tools,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="summarize selected document",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": []},
        )

        events = await _consume_runtime(runtime, state)

        assert state.scope["document_ids"] == []
        assert state.scope["retrieval_plan"] == []
        assert tool_executor.calls == []
        assert "tool_started" not in [event.event_type for event in events]

    asyncio.run(run())


def test_agent_graph_invalid_document_scope_does_not_fallback_to_library() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator_without_tools,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="\u4f60\u597d",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"document_ids": ["missing-doc"]},
        )

        events = await _consume_runtime(runtime, state)

        assert state.scope["document_ids"] == []
        assert state.scope["retrieval_plan"] == []
        assert tool_executor.calls == []
        assert "tool_started" not in [event.event_type for event in events]

    asyncio.run(run())


def test_agent_graph_uses_web_search_when_requested_and_enabled() -> None:
    async def run() -> None:
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="\u5317\u4eac\u5929\u6c14",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={
                "web_search_requested": True,
                "web_search_enabled": True,
                "web_search_tool": "web_search",
            },
        )

        await _consume_runtime(runtime, state)

        assert tool_executor.calls == [
            ("web_search", {"query": "\u5317\u4eac\u5929\u6c14"})
        ]

    asyncio.run(run())


def test_agent_graph_resolves_selected_folder_before_retrieval_decision() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        folder_service = FakeFolderService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                folder_service=folder_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="Summarize selected folder",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"folder_id": "folder-a", "include_subfolders": True},
        )

        await _consume_runtime(runtime, state)

        assert folder_service.get_calls == [
            {"folder_id": "folder-a", "user_id": "user-a"}
        ]
        assert document_service.list_calls == []
        assert state.scope["document_ids"] == []
        assert tool_executor.calls[0] == (
            "browse_documents",
            {
                "query": "Summarize selected folder",
                "sort": "relevance",
                "folder_id": "folder-a",
                "recursive": True,
            },
        )

    asyncio.run(run())


def test_agent_graph_non_strict_folder_scope_expands_without_folder_filter() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        folder_service = FakeFolderService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                folder_service=folder_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="find related risk",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={
                "folder_id": "folder-a",
                "include_subfolders": True,
                "strict_scope": False,
            },
        )

        await _consume_runtime(runtime, state)

        assert document_service.list_calls == []
        assert tool_executor.calls[0] == (
            "browse_documents",
            {"query": "find related risk", "sort": "relevance"},
        )

    asyncio.run(run())


def test_agent_graph_folder_scope_is_not_truncated_to_first_document_page() -> None:
    async def run() -> None:
        document_service = LargeFolderDocumentService()
        folder_service = FakeFolderService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                folder_service=folder_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="Summarize selected folder",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"folder_id": "folder-a", "include_subfolders": True},
        )

        await _consume_runtime(runtime, state)

        assert document_service.list_calls == []
        assert "document_ids" not in tool_executor.calls[0][1]
        assert tool_executor.calls[0][1]["folder_id"] == "folder-a"

    asyncio.run(run())


def test_agent_graph_ignores_empty_semantic_folder_scope() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        folder_service = FakeFolderService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                folder_service=folder_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator_without_tools,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="\u4f60\u597d",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"folder_id": "root", "include_subfolders": True},
        )

        await _consume_runtime(runtime, state)

        assert folder_service.get_calls == []
        assert state.scope["folder_id"] is None
        assert state.scope["retrieval_plan"] == []
        assert tool_executor.calls == []

    asyncio.run(run())


def test_agent_graph_invalid_folder_scope_does_not_fallback_to_library() -> None:
    async def run() -> None:
        document_service = FakeDocumentService()
        folder_service = FakeFolderService()
        tool_executor = RecordingToolExecutor()
        graph = PageChatAgentGraph(
            AgentNodeDependencies(
                document_service=document_service,
                folder_service=folder_service,
                user_id="user-a",
                tool_executor=tool_executor,
                answer_generator=fake_answer_generator_without_tools,
                finalizer=RecordingFinalizer(),
            )
        )
        runtime = PageChatAgentRuntime(graph=graph)
        state = AgentRunState(
            question="summarize selected folder",
            conversation_id="conv-alpha",
            run_id="run-alpha",
            message_id="msg-alpha",
            scope={"folder_id": "missing-folder"},
        )

        await _consume_runtime(runtime, state)

        assert folder_service.get_calls == [
            {"folder_id": "missing-folder", "user_id": "user-a"}
        ]
        assert state.scope["folder_id"] is None
        assert state.scope["suppress_user_library_fallback"] is True
        assert state.scope["retrieval_plan"] == []
        assert tool_executor.calls == []

    asyncio.run(run())


def test_agent_service_graph_factory_wires_default_provider_and_finalizer() -> None:
    service = AgentService.__new__(AgentService)
    service.db = object()

    graph = service.build_explicit_agent_graph(tool_executor=RecordingToolExecutor())

    assert graph.dependencies.answer_generator is not None
    assert graph.dependencies.finalizer is not None
    assert graph.dependencies.failure_handler is not None


async def _consume_runtime(
    runtime: PageChatAgentRuntime,
    state: AgentRunState,
) -> list:
    return [event async for event in runtime.stream(state)]
