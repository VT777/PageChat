import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.agent_service import AgentService  # noqa: E402
from phase0_chat_helpers import parse_sse_frames, sse_frame  # noqa: E402


class FakeDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return [
            SimpleNamespace(
                id="doc-alpha",
                name="alpha.pdf",
                original_name="alpha.pdf",
                folder_id=None,
                folder_path="root",
                status="completed",
                page_count=3,
            )
        ]


class FakeLoopRuntime:
    def __init__(self):
        self.states = []

    async def stream(self, state):
        self.states.append(state)
        yield SimpleNamespace(
            event_type="progress",
            payload={"kind": "plan", "message": "Loop planner selected a tool.", "step": 1},
        )
        yield SimpleNamespace(
            event_type="tool_started",
            payload={"tool_name": "get_document_structure", "arguments": {"doc_id": "doc-alpha"}},
        )
        yield SimpleNamespace(
            event_type="tool_completed",
            payload={
                "tool_name": "get_document_structure",
                "result": {"success": True, "documents": []},
                "elapsed_ms": 1,
            },
        )
        yield SimpleNamespace(
            event_type="progress",
            payload={
                "kind": "observation",
                "message": "Observed document structure.",
                "step": 1,
                "tool_name": "get_document_structure",
            },
        )
        yield SimpleNamespace(
            event_type="answer_delta",
            payload={"content": "Alpha answer"},
        )


def test_agent_service_builds_structured_llm_planner_for_product_runtime() -> None:
    service = AgentService.__new__(AgentService)
    runtime = service.build_agent_loop_runtime(
        tool_executor=object(),
        web_search_settings={"enabled": False},
        runtime_tools=[
            {"type": "function", "function": {"name": "view_folder_structure"}},
        ],
        user_id="user-a",
    )

    assert type(runtime.planner).__name__ == "StructuredLLMPlanner"
    assert type(runtime.policy).__name__ == "AgentPolicy"
    assert type(runtime.planner).__name__ != "PolicyGuidedPlanner"


def test_agent_service_passes_runtime_tool_catalog_to_planner_and_policy() -> None:
    service = AgentService.__new__(AgentService)
    tools = [
        {"type": "function", "function": {"name": "view_folder_structure"}},
        {"type": "function", "function": {"name": "web_search"}},
    ]

    runtime = service.build_agent_loop_runtime(
        tool_executor=object(),
        web_search_settings={"enabled": True, "requested": True},
        runtime_tools=tools,
        user_id="user-a",
    )

    assert runtime.planner.tools == tools
    assert runtime.policy.allowed_tools == {"view_folder_structure", "web_search"}


def test_agent_service_stream_uses_loop_runtime_not_initial_retrieval(monkeypatch) -> None:
    async def run() -> None:
        service = AgentService.__new__(AgentService)
        service.db = None
        service.pageindex_service = object()
        service.document_service = FakeDocumentService()
        service.folder_service = None
        loop_runtime = FakeLoopRuntime()

        async def fail_initial_retrieval(**_kwargs):
            raise AssertionError("legacy initial retrieval must not run")

        def fake_build_loop_runtime(self, **_kwargs):
            return loop_runtime

        async def fake_web_search_settings_for_request(**_kwargs):
            return {"enabled": False}

        async def fake_simple_chat_stream(*_args, **_kwargs):
            yield sse_frame("answer_delta", {"content": "simple"})

        monkeypatch.setattr(
            AgentService,
            "_execute_initial_retrieval_plan",
            staticmethod(fail_initial_retrieval),
        )
        monkeypatch.setattr(
            AgentService,
            "build_agent_loop_runtime",
            fake_build_loop_runtime,
            raising=False,
        )
        monkeypatch.setattr(
            service,
            "_web_search_settings_for_request",
            fake_web_search_settings_for_request,
        )
        monkeypatch.setattr(service, "_simple_chat_stream", fake_simple_chat_stream)

        frames = [
            frame
            async for frame in service.run_agent_stream(
                question="Summarize alpha",
                conversation_id="conv-alpha",
                document_ids=["doc-alpha"],
                preferred_document_ids=["doc-alpha"],
                strict_scope=True,
                user_id="user-a",
                history_messages=[],
            )
        ]

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == [
            "progress",
            "tool_started",
            "tool_completed",
            "progress",
            "answer_delta",
        ]
        assert loop_runtime.states[0].scope["document_ids"] == ["doc-alpha"]
        assert "retrieval_plan" not in loop_runtime.states[0].scope

    asyncio.run(run())


def test_agent_service_passes_streaming_answer_generator_to_loop_runtime(monkeypatch) -> None:
    async def run() -> None:
        service = AgentService.__new__(AgentService)
        service.db = None
        service.pageindex_service = object()
        service.document_service = FakeDocumentService()
        service.folder_service = None
        captured = {}

        class NoopRuntime:
            async def stream(self, _state):
                yield SimpleNamespace(
                    event_type="answer_delta",
                    payload={"content": "stream-ready"},
                )

        def fake_build_loop_runtime(self, **kwargs):
            captured["answer_generator_name"] = getattr(
                kwargs.get("answer_generator"), "__name__", ""
            )
            return NoopRuntime()

        async def fake_web_search_settings_for_request(**_kwargs):
            return {"enabled": False}

        monkeypatch.setattr(
            AgentService,
            "build_agent_loop_runtime",
            fake_build_loop_runtime,
            raising=False,
        )
        monkeypatch.setattr(
            service,
            "_web_search_settings_for_request",
            fake_web_search_settings_for_request,
        )

        frames = [
            frame
            async for frame in service.run_agent_stream(
                question="Summarize alpha",
                conversation_id="conv-alpha",
                document_ids=["doc-alpha"],
                preferred_document_ids=["doc-alpha"],
                strict_scope=True,
                user_id="user-a",
                history_messages=[],
            )
        ]

        events = parse_sse_frames(frames)
        assert events[-1]["event"] == "answer_delta"
        assert captured["answer_generator_name"] == "_stream_graph_answer"

    asyncio.run(run())


def test_agent_service_resolves_exact_filename_before_loop_runtime(monkeypatch) -> None:
    async def run() -> None:
        service = AgentService.__new__(AgentService)
        service.db = None
        service.pageindex_service = object()
        service.document_service = FakeDocumentService()
        service.folder_service = None
        loop_runtime = FakeLoopRuntime()

        def fake_build_loop_runtime(self, **_kwargs):
            return loop_runtime

        async def fail_simple_chat(*_args, **_kwargs):
            raise AssertionError("filename questions must not use simple chat")
            yield

        async def fake_web_search_settings_for_request(**_kwargs):
            return {"enabled": False}

        monkeypatch.setattr(
            AgentService,
            "build_agent_loop_runtime",
            fake_build_loop_runtime,
            raising=False,
        )
        monkeypatch.setattr(service, "_simple_chat_stream", fail_simple_chat)
        monkeypatch.setattr(
            service,
            "_web_search_settings_for_request",
            fake_web_search_settings_for_request,
        )

        frames = [
            frame
            async for frame in service.run_agent_stream(
                question="alpha.pdf mainly says what?",
                conversation_id="conv-alpha",
                user_id="user-a",
                history_messages=[],
            )
        ]

        events = parse_sse_frames(frames)
        assert events[0]["event"] == "progress"
        assert loop_runtime.states[0].scope["document_ids"] == ["doc-alpha"]
        assert loop_runtime.states[0].scope["preferred_document_ids"] == ["doc-alpha"]

    asyncio.run(run())
