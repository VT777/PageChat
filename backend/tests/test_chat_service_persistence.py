import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_service import ChatService  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema, parse_sse_frames  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402


def test_stream_chat_persists_messages_across_reopened_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "stream-chat.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)

            service = ChatService(db)
            frames = [
                frame
                async for frame in service.stream_chat(
                    question="有哪些工具",
                    conversation_id=None,
                    user_id="user-a",
                )
            ]

        events = parse_sse_frames(frames)
        conversation_id = next(
            event["data"]["conversation_id"]
            for event in events
            if event["event"] == "run_started"
        )
        assistant_content = "".join(
            event["data"].get("content", "")
            for event in events
            if event["event"] == "answer_delta"
        )

        assert conversation_id is not None

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT content, sequence, run_id, status
                FROM messages
                WHERE conversation_id = (
                    SELECT id FROM conversations ORDER BY created_at DESC LIMIT 1
                )
                ORDER BY sequence
                """
            )
            rows = await cursor.fetchall()

        assert rows[0][0] == "有哪些工具"
        assert rows[0][1] == 1
        assert rows[1][3] == "completed"
        assert "当前可用工具如下" in assistant_content

    asyncio.run(run())

def test_truncate_conversation_from_message_removes_later_history_and_run_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "truncate-chat.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                "INSERT INTO conversations (id, title, user_id) VALUES ('conv-a', 'Chat', 'user-a')"
            )
            await db.executemany(
                """
                INSERT INTO messages (id, conversation_id, role, content, status, sequence, run_id)
                VALUES (?, 'conv-a', ?, ?, 'completed', ?, ?)
                """,
                [
                    ('u1', 'user', 'First question', 1, None),
                    ('a1', 'assistant', 'First answer', 2, 'run-1'),
                    ('u2', 'user', 'Second question', 3, None),
                    ('a2', 'assistant', 'Stale answer', 4, 'run-2'),
                ],
            )
            await db.executemany(
                """
                INSERT INTO agent_runs (id, conversation_id, user_message_id, assistant_message_id, status, protocol)
                VALUES (?, 'conv-a', ?, ?, 'completed', 'chat_completions')
                """,
                [
                    ('run-1', 'u1', 'a1'),
                    ('run-2', 'u2', 'a2'),
                ],
            )
            await db.execute(
                """
                INSERT INTO agent_run_events (run_id, seq, event_type, payload_json)
                VALUES ('run-2', 1, 'run_started', '{}')
                """
            )
            await db.execute(
                """
                INSERT INTO message_citations (
                    id,
                    message_id,
                    citation_key,
                    document_id,
                    document_name,
                    source_anchor_json,
                    display_label,
                    preview_kind
                )
                VALUES (
                    'cit-a2',
                    'a2',
                    'doc:1',
                    'doc-a',
                    'Document A',
                    '{"page":1}',
                    'Document A p.1',
                    'document_page'
                )
                """
            )
            await db.execute(
                """
                INSERT INTO conversation_evidence (
                    conversation_id,
                    run_id,
                    tool_name,
                    tool_arguments_json,
                    snippet,
                    payload_json,
                    scope_key
                )
                VALUES (
                    'conv-a',
                    'run-2',
                    'get_page_content',
                    '{"document_id":"doc-a","page":1}',
                    'stale',
                    '{"snippet":"stale"}',
                    'scope'
                )
                """
            )
            await db.commit()

            service = ChatService(db)
            await service.truncate_conversation_from_message('conv-a', 'user-a', 'u2')

            cursor = await db.execute(
                "SELECT id FROM messages WHERE conversation_id = 'conv-a' ORDER BY sequence"
            )
            assert [row[0] for row in await cursor.fetchall()] == ['u1', 'a1']

            for table in ('agent_run_events', 'conversation_evidence'):
                cursor = await db.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = 'run-2'")
                assert (await cursor.fetchone())[0] == 0
            cursor = await db.execute("SELECT COUNT(*) FROM agent_runs WHERE id = 'run-2'")
            assert (await cursor.fetchone())[0] == 0
            cursor = await db.execute("SELECT COUNT(*) FROM message_citations WHERE message_id = 'a2'")
            assert (await cursor.fetchone())[0] == 0

    asyncio.run(run())
