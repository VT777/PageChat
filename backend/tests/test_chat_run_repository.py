import asyncio
import json
from pathlib import Path
import sys

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema  # noqa: E402


def test_repository_assigns_message_sequence_and_persists_run_events() -> None:
    async def run() -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-repo', 'Repository regression', 'user-a')
                """
            )
            await db.commit()

            repo = ChatRunRepository(db)
            user_message_id = await repo.create_user_message(
                "conv-repo", "Question?"
            )
            run_id = "run-repo"
            assistant_message_id = await repo.create_assistant_placeholder(
                "conv-repo", run_id
            )
            await repo.create_run(
                run_id=run_id,
                conversation_id="conv-repo",
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                provider_id="provider-a",
                model="model-a",
                protocol="chat_completions",
            )
            first_seq = await repo.append_run_event(
                run_id,
                "run_started",
                {
                    "run_id": run_id,
                    "conversation_id": "conv-repo",
                    "message_id": assistant_message_id,
                    "ts": "2026-06-26T10:00:00Z",
                    "status": "running",
                },
            )
            second_seq = await repo.append_run_event(
                run_id,
                "answer_delta",
                {
                    "run_id": run_id,
                    "conversation_id": "conv-repo",
                    "message_id": assistant_message_id,
                    "ts": "2026-06-26T10:00:01Z",
                    "content": "Answer.",
                },
            )
            await repo.complete_run(
                run_id,
                final_content="Answer.",
                citations=[
                    {
                        "citation_key": "c1",
                        "document_id": "doc-a",
                        "document_name": "alpha.pdf",
                        "source_anchor": {"format": "pdf", "start_page": 2},
                        "display_label": "alpha.pdf p.2",
                        "preview_kind": "pdf",
                    }
                ],
            )

            cursor = await db.execute(
                """
                SELECT id, role, sequence, run_id, content, status
                FROM messages
                WHERE conversation_id = 'conv-repo'
                ORDER BY sequence
                """
            )
            messages = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT seq, event_type, payload_json
                FROM agent_run_events
                WHERE run_id = ?
                ORDER BY seq
                """,
                (run_id,),
            )
            events = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT citation_key, document_id, document_name, source_anchor_json,
                       display_label, preview_kind
                FROM message_citations
                WHERE message_id = ?
                """,
                (assistant_message_id,),
            )
            citations = await cursor.fetchall()

        assert messages == [
            (user_message_id, "user", 1, None, "Question?", "completed"),
            (assistant_message_id, "assistant", 2, run_id, "Answer.", "completed"),
        ]
        assert [first_seq, second_seq] == [1, 2]
        assert [(row[0], row[1]) for row in events] == [
            (1, "run_started"),
            (2, "answer_delta"),
        ]
        assert json.loads(events[1][2]) == {
            "run_id": run_id,
            "conversation_id": "conv-repo",
            "message_id": assistant_message_id,
            "seq": 2,
            "ts": "2026-06-26T10:00:01Z",
            "content": "Answer.",
        }
        assert citations == [
            (
                "c1",
                "doc-a",
                "alpha.pdf",
                json.dumps({"format": "pdf", "start_page": 2}, ensure_ascii=False),
                "alpha.pdf p.2",
                "pdf",
            )
        ]

    asyncio.run(run())


def test_repository_rejects_run_events_without_pagechat_metadata() -> None:
    async def run() -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            repo = ChatRunRepository(db)

            with pytest.raises(ValueError, match="run_id"):
                await repo.append_run_event(
                    "run-invalid",
                    "progress",
                    {"message": "missing metadata"},
                )

    asyncio.run(run())


def test_repository_lists_messages_with_structured_citations() -> None:
    async def run() -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-list', 'List regression', 'user-a')
                """
            )
            await db.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES
                  ('msg-user', 'conv-list', 'user', 'Question?', '[]', '[]',
                   'completed', 1, NULL),
                  ('msg-assistant', 'conv-list', 'assistant', 'Answer.', '[]', '[]',
                   'completed', 2, 'run-list')
                """
            )
            await db.execute(
                """
                INSERT INTO message_citations (
                    id, message_id, citation_key, document_id, document_name,
                    source_anchor_json, display_label, preview_kind
                )
                VALUES ('cit-1', 'msg-assistant', 'c1', 'doc-a', 'alpha.pdf',
                        ?, 'alpha.pdf p.2', 'pdf')
                """,
                (json.dumps({"format": "pdf", "start_page": 2}),),
            )
            await db.commit()

            messages = await ChatRunRepository(db).list_messages("conv-list")

        assert messages == [
            {
                "id": "msg-user",
                "role": "user",
                "content": "Question?",
                "thinking": "",
                "sources": [],
                "agent_steps": [],
                "status": "completed",
                "created_at": messages[0]["created_at"],
                "updated_at": messages[0]["updated_at"],
                "sequence": 1,
                "run_id": None,
                "attachments": [],
                "citations": [],
            },
            {
                "id": "msg-assistant",
                "role": "assistant",
                "content": "Answer.",
                "thinking": "",
                "sources": [],
                "agent_steps": [],
                "status": "completed",
                "created_at": messages[1]["created_at"],
                "updated_at": messages[1]["updated_at"],
                "sequence": 2,
                "run_id": "run-list",
                "attachments": [],
                "citations": [
                    {
                        "citation_key": "c1",
                        "document_id": "doc-a",
                        "document_name": "alpha.pdf",
                        "source_anchor": {"format": "pdf", "start_page": 2},
                        "display_label": "alpha.pdf p.2",
                        "preview_kind": "pdf",
                    }
                ],
            },
        ]

    asyncio.run(run())


def test_repository_lists_messages_for_conversation_owner_only() -> None:
    async def run() -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-owned', 'Owned chat', 'user-a')
                """
            )
            await db.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES ('msg-owned', 'conv-owned', 'user', 'secret question',
                        '[]', '[]', 'completed', 1, NULL)
                """
            )
            await db.commit()

            repo = ChatRunRepository(db)
            owner_messages = await repo.list_messages_for_user("conv-owned", "user-a")
            other_messages = await repo.list_messages_for_user("conv-owned", "user-b")

        assert [message["content"] for message in owner_messages] == ["secret question"]
        assert other_messages == []

    asyncio.run(run())


def test_repository_titles_new_conversation_from_first_user_message() -> None:
    async def run() -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-title', '新对话', 'user-a')
                """
            )
            await db.commit()

            repo = ChatRunRepository(db)
            await repo.create_user_message(
                "conv-title",
                "请总结一下重庆人工智能典型案例集里有哪些重点方向？",
            )

            cursor = await db.execute(
                "SELECT title FROM conversations WHERE id = 'conv-title'"
            )
            row = await cursor.fetchone()

        assert row[0] == "请总结一下重庆人工智能典型案例集里有哪些重点方向？"

    asyncio.run(run())


def test_repository_serializes_concurrent_message_and_event_sequences() -> None:
    async def run() -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-concurrent', 'Concurrent regression', 'user-a')
                """
            )
            await db.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES
                  ('msg-user-run', 'conv-concurrent', 'user', 'Question?', '[]', '[]',
                   'completed', 1, NULL),
                  ('msg-assistant-run', 'conv-concurrent', 'assistant', '', '[]', '[]',
                   'streaming', 2, 'run-concurrent')
                """
            )
            await db.execute(
                """
                INSERT INTO agent_runs (
                    id, conversation_id, user_message_id, assistant_message_id,
                    status, protocol
                )
                VALUES (
                    'run-concurrent', 'conv-concurrent', 'msg-user-run',
                    'msg-assistant-run', 'running', 'chat_completions'
                )
                """
            )
            await db.commit()

            repo = ChatRunRepository(db)
            await asyncio.gather(
                *[
                    repo.create_user_message("conv-concurrent", f"Question {index}?")
                    for index in range(20)
                ]
            )
            await asyncio.gather(
                *[
                    repo.append_run_event(
                        "run-concurrent",
                        "progress",
                        {
                            "run_id": "run-concurrent",
                            "conversation_id": "conv-concurrent",
                            "message_id": "msg-assistant-run",
                            "ts": f"2026-06-26T10:00:{index:02d}Z",
                            "message": f"progress {index}",
                        },
                    )
                    for index in range(20)
                ]
            )

            cursor = await db.execute(
                """
                SELECT sequence
                FROM messages
                WHERE conversation_id = 'conv-concurrent'
                ORDER BY sequence
                """
            )
            message_sequences = [row[0] for row in await cursor.fetchall()]
            cursor = await db.execute(
                """
                SELECT seq
                FROM agent_run_events
                WHERE run_id = 'run-concurrent'
                ORDER BY seq
                """
            )
            event_sequences = [row[0] for row in await cursor.fetchall()]

        assert message_sequences == list(range(1, 23))
        assert event_sequences == list(range(1, 21))

    asyncio.run(run())


def test_repository_commits_messages_so_reopened_connections_can_read(tmp_path: Path) -> None:
    db_path = tmp_path / "durable-chat.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-durable', 'Durable regression', 'user-a')
                """
            )
            await db.commit()

    async def write_message() -> str:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(db_path) as db:
            return await ChatRunRepository(db).create_user_message(
                "conv-durable", "Persist me"
            )

    async def read_message(message_id: str) -> tuple[str, int]:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT content, sequence FROM messages WHERE id = ?",
                (message_id,),
            )
            row = await cursor.fetchone()
            return row[0], row[1]

    async def run() -> None:
        await setup()
        message_id = await write_message()
        assert await read_message(message_id) == ("Persist me", 1)

    asyncio.run(run())


def test_repository_serializes_sequences_across_instances_and_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent-chat.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-cross-instance', 'Cross instance regression', 'user-a')
                """
            )
            await db.execute(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES
                  ('msg-user-cross', 'conv-cross-instance', 'user', 'Question?', '[]', '[]',
                   'completed', 1, NULL),
                  ('msg-assistant-cross', 'conv-cross-instance', 'assistant', '', '[]', '[]',
                   'streaming', 2, 'run-cross-instance')
                """
            )
            await db.execute(
                """
                INSERT INTO agent_runs (
                    id, conversation_id, user_message_id, assistant_message_id,
                    status, protocol
                )
                VALUES (
                    'run-cross-instance', 'conv-cross-instance', 'msg-user-cross',
                    'msg-assistant-cross', 'running', 'chat_completions'
                )
                """
            )
            await db.commit()

    async def write_message(index: int) -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(db_path) as db:
            await ChatRunRepository(db).create_user_message(
                "conv-cross-instance", f"Question {index}?"
            )

    async def write_event(index: int) -> None:
        from app.services.chat_run_repository import ChatRunRepository

        async with aiosqlite.connect(db_path) as db:
            await ChatRunRepository(db).append_run_event(
                "run-cross-instance",
                "progress",
                {
                    "run_id": "run-cross-instance",
                    "conversation_id": "conv-cross-instance",
                    "message_id": "msg-assistant-cross",
                    "ts": f"2026-06-26T10:01:{index:02d}Z",
                    "message": f"progress {index}",
                },
            )

    async def read_sequences() -> tuple[list[int], list[int]]:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT sequence
                FROM messages
                WHERE conversation_id = 'conv-cross-instance'
                ORDER BY sequence
                """
            )
            message_sequences = [row[0] for row in await cursor.fetchall()]
            cursor = await db.execute(
                """
                SELECT seq
                FROM agent_run_events
                WHERE run_id = 'run-cross-instance'
                ORDER BY seq
                """
            )
            event_sequences = [row[0] for row in await cursor.fetchall()]
            return message_sequences, event_sequences

    async def run() -> None:
        await setup()
        await asyncio.gather(*[write_message(index) for index in range(10)])
        await asyncio.gather(*[write_event(index) for index in range(10)])
        message_sequences, event_sequences = await read_sequences()
        assert message_sequences == list(range(1, 13))
        assert event_sequences == list(range(1, 11))

    asyncio.run(run())
