import asyncio
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.model_turn import ModelTextDelta, ModelToolCall, ModelToolCallDelta, ModelTurn
from app.core import config
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService
from app.agent.tool_calling_model_adapter import ToolCallingModelAdapter
from app.models.migrations import run_migrations
from phase0_chat_helpers import create_chat_history_schema, parse_sse_frames, sse_frame


def _doc(
    doc_id: str,
    name: str,
    *,
    folder_id: str = "folder-a",
    folder_path: str = "Projects",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=doc_id,
        name=name,
        original_name=name,
        file_path=f"/tmp/{name}",
        folder_id=folder_id,
        folder_path=folder_path,
        status="completed",
        page_count=3,
        description="A compact document description.",
        created_at=datetime.utcnow(),
    )


class FakeDocumentService:
    def __init__(self):
        self.docs = [
            _doc("doc-a", "Alpha.pdf"),
            _doc("doc-b", "Beta.pdf", folder_path="Projects/Child"),
        ]

    async def get_indexed_documents(self, user_id=None):
        return list(self.docs)

    async def get_document(self, doc_id: str, user_id=None):
        for doc in self.docs:
            if doc.id == doc_id:
                return doc
        return None

    async def list_documents(
        self,
        page=1,
        page_size=500,
        folder_id=None,
        include_subfolders=False,
        user_id=None,
    ):
        docs = [
            doc
            for doc in self.docs
            if doc.folder_id == folder_id or (include_subfolders and doc.folder_path.startswith("Projects"))
        ]
        return docs, len(docs)


class FakePageIndexService:
    async def load_index(self, doc_id: str):
        return {
            "structure": [
                {
                    "node_id": "n1",
                    "title": "Overview",
                    "start_index": 1,
                    "end_index": 3,
                    "text": "overview text",
                }
            ],
            "pages": [{"page": 1, "text": "overview text", "images": []}],
        }


class FakeFlatAgent:
    async def run_agent_stream(self, **_kwargs):
        yield sse_frame(
            "processing_delta",
            {"content": "Checking selected scope.", "step": 1, "status": "streaming"},
        )
        yield sse_frame(
            "tool_call_delta",
            {
                "tool_call_id": "call-browse",
                "tool_name": "browse_documents",
                "arguments_delta": '{"folder_id":"folder-a"}',
                "status": "streaming",
            },
        )
        yield sse_frame(
            "tool_started",
            {
                "tool_call_id": "call-browse",
                "tool_name": "browse_documents",
                "arguments": {"folder_id": "folder-a"},
            },
        )
        yield sse_frame(
            "tool_completed",
            {
                "tool_call_id": "call-browse",
                "tool_name": "browse_documents",
                "arguments": {"folder_id": "folder-a"},
                "result": {"success": True, "result_label": "2 documents"},
                "elapsed_ms": 4,
            },
        )
        yield sse_frame("answer_delta", {"content": "找到 2 个文档。"})


def test_chat_service_forwards_flat_loop_delta_events(tmp_path: Path) -> None:
    db_path = tmp_path / "flat-chat-service.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            service = ChatService(db)
            service.agent_service = FakeFlatAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="现在有哪些文档",
                    conversation_id=None,
                    folder_id="folder-a",
                    include_subfolders=True,
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

        events = parse_sse_frames(frames)
        event_names = [event["event"] for event in events]
        assert "run_failed" not in event_names
        assert event_names == [
            "run_started",
            "processing_delta",
            "tool_call_delta",
            "tool_started",
            "tool_completed",
            "answer_delta",
            "run_completed",
        ]
        assert events[2]["data"]["tool_call_id"] == "call-browse"
        assert events[3]["data"]["tool_call_id"] == "call-browse"
        assert events[4]["data"]["tool_call_id"] == "call-browse"

    asyncio.run(run())


def test_agent_service_flat_loop_inventory_uses_one_browse_tool_call(monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setattr(config, "AGENT_RUNTIME_MODE", "flat_tool_loop", raising=False)
        service = AgentService.__new__(AgentService)
        service.db = None
        service.pageindex_service = FakePageIndexService()
        service.document_service = FakeDocumentService()
        service.folder_service = None
        calls = {"count": 0}

        async def fake_web_search_settings_for_request(**_kwargs):
            return {"enabled": False}

        async def fake_stream_turn(self, *, messages, tools, user_id=None):
            calls["count"] += 1
            if calls["count"] == 1:
                yield ModelToolCallDelta(
                    index=0,
                    id="call-browse",
                    name="browse_documents",
                    arguments_delta='{"folder_id":"folder-a"}',
                )
                yield ModelTurn(
                    tool_calls=[
                        ModelToolCall(
                            id="call-browse",
                            name="browse_documents",
                            arguments={"folder_id": "folder-a", "recursive": True},
                        )
                    ]
                )
            else:
                yield ModelTextDelta("当前文件夹里有 Alpha.pdf 和 Beta.pdf。")
                yield ModelTurn(content="当前文件夹里有 Alpha.pdf 和 Beta.pdf。")

        monkeypatch.setattr(
            service,
            "_web_search_settings_for_request",
            fake_web_search_settings_for_request,
        )
        monkeypatch.setattr(ToolCallingModelAdapter, "stream_turn", fake_stream_turn)

        frames = [
            frame
            async for frame in service.run_agent_stream(
                question="现在有哪些文档",
                conversation_id="conv-flat-e2e",
                folder_id="folder-a",
                include_subfolders=True,
                strict_scope=True,
                user_id="user-a",
                history_messages=[],
            )
        ]

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == [
            "tool_call_delta",
            "processing_delta",
            "tool_started",
            "tool_completed",
            "answer_delta",
        ]
        assert events[1]["data"]["content"] == "正在查看文档库。"
        assert events[2]["data"]["tool_name"] == "browse_documents"
        assert events[3]["data"]["result"]["result_label"] == "2 documents"
        assert events[4]["data"]["content"] == "当前文件夹里有 Alpha.pdf 和 Beta.pdf。"

    asyncio.run(run())
