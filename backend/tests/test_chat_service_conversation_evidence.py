import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema, sse_frame  # noqa: E402


class EvidenceAgent:
    async def run_agent_stream(self, **kwargs):
        assert kwargs["conversation_id"] == "conv-evidence-chat"
        yield sse_frame(
            "tool_started",
            {
                "tool_name": "get_page_content",
                "arguments": {"doc_id": "doc-alpha", "pages": "2"},
            },
        )
        yield sse_frame(
            "tool_completed",
            {
                "tool_name": "get_page_content",
                "result": {
                    "success": True,
                    "data": {
                        "doc_id": "doc-alpha",
                        "doc_name": "alpha.pdf",
                        "content": [
                            {
                                "page": 2,
                                "text": "可复用的页面证据。",
                                "page_image_base64": "must-not-store",
                            }
                        ],
                    },
                },
                "elapsed_ms": 5,
            },
        )
        yield sse_frame("answer_delta", {"content": "回答。"})


class CompactEvidenceAgent:
    async def run_agent_stream(self, **_kwargs):
        yield sse_frame(
            "tool_started",
            {
                "tool_name": "get_page_content",
                "arguments": {"doc_id": "doc-alpha", "pages": "3"},
            },
        )
        yield sse_frame(
            "tool_completed",
            {
                "tool_name": "get_page_content",
                "result": {
                    "doc_id": "doc-alpha",
                    "doc_name": "alpha.pdf",
                    "items": [{"page": 3, "text": "runtime 已经压缩好的证据。"}],
                    "citations": [],
                },
                "elapsed_ms": 2,
            },
        )
        yield sse_frame("answer_delta", {"content": "回答。"})


def test_chat_service_records_tool_completed_evidence() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-evidence-chat', 'Evidence Chat', 'user-a')
                """
            )
            await db.execute(
                """
                INSERT INTO documents (
                    id, name, original_name, file_path, file_size, file_type,
                    status, updated_at, user_id
                )
                VALUES (
                    'doc-alpha', 'alpha.pdf', 'alpha.pdf', '/tmp/alpha.pdf', 123, 'pdf',
                    'completed', '2026-06-26 10:00:00', 'user-a'
                )
                """
            )
            await db.commit()

            service = ChatService(db)
            service._get_agent_service = lambda: EvidenceAgent()
            frames = [
                frame
                async for frame in service.stream_chat(
                    question="说明第二页",
                    conversation_id="conv-evidence-chat",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT tool_name, doc_id, doc_name, page, snippet, payload_json
                FROM conversation_evidence
                WHERE conversation_id = 'conv-evidence-chat'
                """
            )
            rows = await cursor.fetchall()

        assert any("event: run_completed" in frame for frame in frames)
        assert len(rows) == 1
        assert rows[0][0:5] == (
            "get_page_content",
            "doc-alpha",
            "alpha.pdf",
            2,
            "可复用的页面证据。",
        )
        assert "must-not-store" not in rows[0][5]
        assert "page_image_base64" not in rows[0][5]

    asyncio.run(run())


def test_chat_service_records_already_compact_runtime_evidence() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-compact-evidence', 'Compact Evidence', 'user-a')
                """
            )
            await db.execute(
                """
                INSERT INTO documents (
                    id, name, original_name, file_path, file_size, file_type,
                    status, updated_at, user_id
                )
                VALUES (
                    'doc-alpha', 'alpha.pdf', 'alpha.pdf', '/tmp/alpha.pdf', 123, 'pdf',
                    'completed', '2026-06-26 10:00:00', 'user-a'
                )
                """
            )
            await db.commit()

            service = ChatService(db)
            service._get_agent_service = lambda: CompactEvidenceAgent()
            frames = [
                frame
                async for frame in service.stream_chat(
                    question="继续说明第三页",
                    conversation_id="conv-compact-evidence",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT page, snippet
                FROM conversation_evidence
                WHERE conversation_id = 'conv-compact-evidence'
                """
            )
            rows = await cursor.fetchall()

        assert any("event: run_completed" in frame for frame in frames)
        assert rows == [(3, "runtime 已经压缩好的证据。")]

    asyncio.run(run())
