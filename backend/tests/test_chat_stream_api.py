import asyncio
import contextlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import aiosqlite
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import chat  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from phase0_chat_helpers import (  # noqa: E402
    create_chat_history_schema,
    parse_sse_frames,
    sse_frame,
)


def _client(db_path: Path, user_id: str = "user-a") -> TestClient:
    app = FastAPI()
    app.include_router(chat.router)

    async def override_auth() -> dict:
        return {"id": user_id, "email": f"{user_id}@example.test"}

    async def override_db():
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    app.dependency_overrides[chat.require_auth] = override_auth
    app.dependency_overrides[chat.get_db] = override_db
    return TestClient(app)


def _parse_response_sse(text: str) -> list[dict]:
    return parse_sse_frames([frame + "\n\n" for frame in text.split("\n\n") if frame.strip()])


def test_run_event_replay_endpoint_returns_owned_events_after_seq(tmp_path: Path) -> None:
    db_path = tmp_path / "run-events.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-replay', 'Replay', 'user-a')
                """
            )
            await db.executemany(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES (?, 'conv-replay', ?, ?, '[]', '[]', ?, ?, ?)
                """,
                [
                    ("msg-replay-user", "user", "Question", "completed", 1, None),
                    ("msg-replay-assistant", "assistant", "Answer", "completed", 2, "run-replay"),
                ],
            )
            await db.execute(
                """
                INSERT INTO agent_runs (
                    id, conversation_id, user_message_id, assistant_message_id,
                    status, protocol
                )
                VALUES (
                    'run-replay', 'conv-replay', 'msg-replay-user',
                    'msg-replay-assistant', 'completed', 'chat_completions'
                )
                """
            )
            for seq, event_type in [
                (1, "run_started"),
                (2, "answer_delta"),
                (3, "run_completed"),
            ]:
                await db.execute(
                    """
                    INSERT INTO agent_run_events (run_id, seq, event_type, payload_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        "run-replay",
                        seq,
                        event_type,
                        json.dumps(
                            {
                                "run_id": "run-replay",
                                "conversation_id": "conv-replay",
                                "message_id": "msg-replay-assistant",
                                "seq": seq,
                                "ts": f"2026-06-26T10:00:0{seq}Z",
                                "content": "Answer" if event_type == "answer_delta" else None,
                                "status": "completed" if event_type == "run_completed" else "running",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            await db.commit()

    asyncio.run(setup())

    response = _client(db_path).get("/api/chat/runs/run-replay/events?after_seq=1")

    assert response.status_code == 200
    assert response.json() == [
        {
            "event": "answer_delta",
            "data": {
                "run_id": "run-replay",
                "conversation_id": "conv-replay",
                "message_id": "msg-replay-assistant",
                "seq": 2,
                "ts": "2026-06-26T10:00:02Z",
                "content": "Answer",
                "status": "running",
            },
        },
        {
            "event": "run_completed",
            "data": {
                "run_id": "run-replay",
                "conversation_id": "conv-replay",
                "message_id": "msg-replay-assistant",
                "seq": 3,
                "ts": "2026-06-26T10:00:03Z",
                "content": None,
                "status": "completed",
            },
        },
    ]


def test_chat_stream_api_outer_error_uses_run_failed_not_legacy_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "stream-outer-error.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)

    asyncio.run(setup())

    async def failing_stream_chat(self, **_kwargs):
        raise RuntimeError("stream setup exploded")
        yield ""  # pragma: no cover

    monkeypatch.setattr(chat, "DB_PATH", db_path)
    monkeypatch.setattr(ChatService, "stream_chat", failing_stream_chat)

    response = _client(db_path).post("/api/chat/stream", json={"question": "hello"})
    events = _parse_response_sse(response.text)

    assert response.status_code == 200
    assert "event: content" not in response.text
    assert events[0]["event"] == "run_failed"
    assert events[0]["data"]["status"] == "failed"
    assert "stream setup exploded" in events[0]["data"]["error"]

    async def assert_persisted_failure() -> None:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT status, error, protocol
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT role, content, status
                FROM messages
                ORDER BY sequence
                """
            )
            message_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        assert run_row == ("failed", "stream setup exploded", "transport")
        assert message_rows == [
            ("user", "hello", "completed"),
            ("assistant", "", "failed"),
        ]
        assert [row[0] for row in event_rows] == ["run_failed"]

    asyncio.run(assert_persisted_failure())


def test_chat_stream_api_midstream_setup_error_does_not_duplicate_messages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "stream-midstream-error.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)

    asyncio.run(setup())

    async def failing_documents(self, user_id=None):
        raise RuntimeError("document lookup exploded")

    monkeypatch.setattr(chat, "DB_PATH", db_path)
    monkeypatch.setattr(
        "app.services.document_service.DocumentService.get_indexed_documents",
        failing_documents,
    )

    response = _client(db_path).post(
        "/api/chat/stream",
        json={"question": "Summarize alpha", "document_ids": ["doc-alpha"]},
    )
    events = _parse_response_sse(response.text)

    assert response.status_code == 200
    assert [event["event"] for event in events] == ["run_started", "run_failed"]
    assert "event: content" not in response.text
    assert "document lookup exploded" in events[-1]["data"]["error"]

    async def assert_single_failed_run() -> None:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT role, content, status
                FROM messages
                ORDER BY sequence
                """
            )
            message_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT status, error, protocol
                FROM agent_runs
                ORDER BY started_at
                """
            )
            run_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        assert message_rows == [
            ("user", "Summarize alpha", "completed"),
            ("assistant", "", "failed"),
        ]
        assert run_rows == [
            ("failed", "document lookup exploded", "chat_completions")
        ]
        assert [row[0] for row in event_rows] == ["run_started", "run_failed"]

    asyncio.run(assert_single_failed_run())


def test_chat_stream_api_history_error_does_not_create_transport_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "stream-history-error.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)

    asyncio.run(setup())

    async def failing_history(self, conversation_id, limit=20):
        raise RuntimeError("history read exploded")

    monkeypatch.setattr(chat, "DB_PATH", db_path)
    monkeypatch.setattr(ChatService, "get_history_messages", failing_history)

    response = _client(db_path).post(
        "/api/chat/stream",
        json={"question": "Summarize alpha", "document_ids": ["doc-alpha"]},
    )
    events = _parse_response_sse(response.text)

    assert response.status_code == 200
    assert [event["event"] for event in events] == ["run_failed"]
    assert "event: content" not in response.text
    assert "history read exploded" in events[-1]["data"]["error"]

    async def assert_single_failed_run() -> None:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT role, content, status
                FROM messages
                ORDER BY sequence
                """
            )
            message_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT status, error, protocol
                FROM agent_runs
                ORDER BY started_at
                """
            )
            run_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        assert message_rows == [
            ("user", "Summarize alpha", "completed"),
            ("assistant", "", "failed"),
        ]
        assert run_rows == [("failed", "history read exploded", "chat_completions")]
        assert [row[0] for row in event_rows] == ["run_failed"]

    asyncio.run(assert_single_failed_run())


def test_chat_stream_api_periodic_save_error_does_not_create_transport_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "stream-periodic-save-error.db"

    async def setup() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)

    asyncio.run(setup())

    async def fake_documents(self, user_id=None):
        return [SimpleNamespace(id="doc-alpha")]

    class SlowTwoChunkAgent:
        async def run_agent_stream(self, **_kwargs):
            yield sse_frame("answer_delta", {"content": "part one"})
            await asyncio.sleep(1.05)
            yield sse_frame("answer_delta", {"content": "part two"})

    original_update_message = ChatService.update_message

    async def failing_periodic_update(
        self,
        message_id,
        content=None,
        thinking_content=None,
        agent_steps=None,
        status=None,
    ):
        if status == "streaming" and content == "part onepart two":
            raise RuntimeError("periodic save exploded")
        return await original_update_message(
            self,
            message_id,
            content=content,
            thinking_content=thinking_content,
            agent_steps=agent_steps,
            status=status,
        )

    monkeypatch.setattr(chat, "DB_PATH", db_path)
    monkeypatch.setattr(
        "app.services.document_service.DocumentService.get_indexed_documents",
        fake_documents,
    )
    monkeypatch.setattr(ChatService, "_get_agent_service", lambda self: SlowTwoChunkAgent())
    monkeypatch.setattr(ChatService, "update_message", failing_periodic_update)

    response = _client(db_path).post(
        "/api/chat/stream",
        json={"question": "Summarize alpha", "document_ids": ["doc-alpha"]},
    )
    events = _parse_response_sse(response.text)

    assert response.status_code == 200
    assert [event["event"] for event in events] == [
        "run_started",
        "answer_delta",
        "answer_delta",
        "run_failed",
    ]
    assert "event: content" not in response.text
    assert "periodic save exploded" in events[-1]["data"]["error"]

    async def assert_single_failed_run() -> None:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT role, content, status
                FROM messages
                ORDER BY sequence
                """
            )
            message_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT status, error, protocol
                FROM agent_runs
                ORDER BY started_at
                """
            )
            run_rows = await cursor.fetchall()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        assert message_rows == [
            ("user", "Summarize alpha", "completed"),
            ("assistant", "part onepart two", "failed"),
        ]
        assert run_rows == [("failed", "periodic save exploded", "chat_completions")]
        assert [row[0] for row in event_rows] == [
            "run_started",
            "answer_delta",
            "answer_delta",
            "run_failed",
        ]

    asyncio.run(assert_single_failed_run())


class SlowDocumentService:
    async def get_indexed_documents(self, user_id=None):
        return [SimpleNamespace(id="doc-alpha")]


class SlowProviderAgent:
    async def run_agent_stream(self, **_kwargs):
        yield sse_frame("answer_delta", {"content": "partial"})
        await asyncio.sleep(3600)


class LegacyInternalAgent:
    async def run_agent_stream(self, **_kwargs):
        yield sse_frame("content", {"content": "legacy content"})


def test_chat_service_marks_run_cancelled_and_keeps_partial_state() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-cancel', 'Cancel', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = SlowDocumentService()
            service._get_agent_service = lambda: SlowProviderAgent()
            frames: list[str] = []
            received_partial = asyncio.Event()

            async def consume() -> None:
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-cancel",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                ):
                    frames.append(frame)
                    if "event: answer_delta" in frame:
                        received_partial.set()

            task = asyncio.create_task(consume())
            await asyncio.wait_for(received_partial.wait(), timeout=2)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            cursor = await db.execute(
                """
                SELECT status
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT content, status
                FROM messages
                WHERE conversation_id = 'conv-cancel' AND role = 'assistant'
                ORDER BY sequence
                LIMIT 1
                """
            )
            assistant_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        assert [event["event"] for event in parse_sse_frames(frames)] == [
            "run_started",
            "answer_delta",
        ]
        assert run_row[0] == "cancelled"
        assert assistant_row == ("partial", "cancelled")
        assert [row[0] for row in event_rows] == [
            "run_started",
            "answer_delta",
            "run_cancelled",
        ]

    asyncio.run(run())


def test_chat_service_fails_unsupported_legacy_internal_agent_event() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-legacy-internal', 'Legacy internal', 'user-a')
                """
            )
            await db.commit()

            service = ChatService(db)
            service.document_service = SlowDocumentService()
            service._get_agent_service = lambda: LegacyInternalAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="Summarize alpha",
                    conversation_id="conv-legacy-internal",
                    document_ids=["doc-alpha"],
                    strict_scope=True,
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT status, error
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            run_row = await cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT event_type
                FROM agent_run_events
                ORDER BY seq
                """
            )
            event_rows = await cursor.fetchall()

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == [
            "run_started",
            "run_failed",
        ]
        assert run_row == ("failed", "Unsupported agent event: content")
        assert [row[0] for row in event_rows] == ["run_started", "run_failed"]

    asyncio.run(run())
