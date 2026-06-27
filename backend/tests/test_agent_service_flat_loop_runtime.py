import sys
from pathlib import Path
from types import SimpleNamespace
import asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config
from app.services import agent_service as agent_service_module
from app.services.agent_service import AgentService
from phase0_chat_helpers import parse_sse_frames


class FakeDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return []


def test_config_default_runtime_mode_is_flat_tool_loop():
    source = (Path(__file__).resolve().parents[1] / "app" / "core" / "config.py").read_text(
        encoding="utf-8"
    )

    assert 'AGENT_RUNTIME_MODE = os.getenv("AGENT_RUNTIME_MODE", "flat_tool_loop")' in source


def test_agent_service_builds_flat_tool_loop_by_default(monkeypatch):
    monkeypatch.setattr(config, "AGENT_RUNTIME_MODE", "flat_tool_loop", raising=False)
    service = AgentService.__new__(AgentService)

    runtime = service.build_agent_loop_runtime(
        tool_executor=object(),
        web_search_settings={"enabled": False},
        runtime_tools=[{"type": "function", "function": {"name": "browse_documents"}}],
        user_id="user-a",
    )

    assert type(runtime).__name__ == "ModelToolLoopRuntime"
    assert type(runtime.model).__name__ == "ToolCallingModelAdapter"
    assert type(runtime.boundary_policy).__name__ == "RuntimeBoundaryPolicy"


def test_agent_service_keeps_legacy_runtime_when_runtime_mode_explicit(monkeypatch):
    monkeypatch.setattr(config, "AGENT_RUNTIME_MODE", "legacy_loop", raising=False)
    service = AgentService.__new__(AgentService)

    runtime = service.build_agent_loop_runtime(
        tool_executor=object(),
        web_search_settings={"enabled": False},
        runtime_tools=[{"type": "function", "function": {"name": "browse_documents"}}],
        user_id="user-a",
    )

    assert type(runtime).__name__ == "AgentLoopRuntime"
    assert type(runtime.planner).__name__ == "StructuredLLMPlanner"


def test_agent_service_passes_qa_thinking_setting_to_flat_adapter(monkeypatch):
    class FakeRuntimeSettings:
        def get_settings(self):
            return {"qa_thinking_mode": "auto"}

    monkeypatch.setattr(config, "AGENT_RUNTIME_MODE", "flat_tool_loop", raising=False)
    monkeypatch.setattr(
        agent_service_module,
        "runtime_settings_service",
        FakeRuntimeSettings(),
        raising=False,
    )
    service = AgentService.__new__(AgentService)

    runtime = service.build_agent_loop_runtime(
        tool_executor=object(),
        web_search_settings={"enabled": False},
        runtime_tools=[{"type": "function", "function": {"name": "browse_documents"}}],
        user_id="user-a",
    )

    assert runtime.model.disable_thinking is False


def test_agent_service_stream_accepts_flat_runtime_event_shape(monkeypatch):
    async def run() -> None:
        class FlatRuntime:
            async def stream(self, _state):
                yield SimpleNamespace(type="answer_delta", payload={"content": "flat"})

        service = AgentService.__new__(AgentService)
        service.db = None
        service.pageindex_service = object()
        service.document_service = FakeDocumentService()
        service.folder_service = None

        def fake_build_runtime(self, **_kwargs):
            return FlatRuntime()

        async def fake_web_search_settings_for_request(**_kwargs):
            return {"enabled": False}

        monkeypatch.setattr(
            AgentService,
            "build_agent_loop_runtime",
            fake_build_runtime,
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
                question="Hello",
                conversation_id="conv-flat",
                user_id="user-a",
                history_messages=[],
            )
        ]

        events = parse_sse_frames(frames)
        assert events == [{"event": "answer_delta", "data": {"content": "flat"}}]

    asyncio.run(run())
