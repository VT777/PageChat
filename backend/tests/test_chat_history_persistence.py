import asyncio
import json
from pathlib import Path
import sys

import aiosqlite
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import chat  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema  # noqa: E402


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


def test_conversation_messages_endpoint_returns_sequence_order_and_run_metadata(tmp_path: Path) -> None:
    db_path = tmp_path / "chat-history.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-phase0-history', 'History regression', 'user-a')
                """
            )
            await db.executemany(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    created_at, status, sequence, run_id
                )
                VALUES (?, 'conv-phase0-history', ?, ?, '[]', '[]',
                        '2026-06-26 10:00:00', 'completed', ?, ?)
                """,
                [
                    ("msg-20-user", "user", "What does the document say?", 1, None),
                    ("msg-10-assistant", "assistant", "It says alpha.", 2, "run-alpha"),
                    ("msg-30-user", "user", "Thanks", 3, None),
                ],
            )
            await db.execute(
                """
                INSERT INTO message_citations (
                    id, message_id, citation_key, document_id, document_name,
                    source_anchor_json, display_label, preview_kind
                )
                VALUES (
                    'cit-alpha', 'msg-10-assistant', 'c1', 'doc-alpha',
                    'alpha.pdf', ?, 'alpha.pdf p.2', 'pdf'
                )
                """,
                (json.dumps({"format": "pdf", "start_page": 2}),),
            )
            await db.commit()

    asyncio.run(run())

    response = _client(db_path).get("/api/chat/conversations/conv-phase0-history/messages")

    assert response.status_code == 200
    messages = response.json()
    actual_contract = [
        {
            "id": message.get("id"),
            "sequence": message.get("sequence"),
            "run_id": message.get("run_id"),
            "citations": message.get("citations"),
        }
        for message in messages
    ]
    assert actual_contract == [
        {
            "id": "msg-20-user",
            "sequence": 1,
            "run_id": None,
            "citations": [],
        },
        {
            "id": "msg-10-assistant",
            "sequence": 2,
            "run_id": "run-alpha",
            "citations": [
                {
                    "citation_key": "c1",
                    "document_id": "doc-alpha",
                    "document_name": "alpha.pdf",
                    "source_anchor": {"format": "pdf", "start_page": 2},
                    "display_label": "alpha.pdf p.2",
                    "preview_kind": "pdf",
                }
            ],
        },
        {
            "id": "msg-30-user",
            "sequence": 3,
            "run_id": None,
            "citations": [],
        },
    ]


def test_delete_conversation_removes_owned_messages_runs_events_and_citations(tmp_path: Path) -> None:
    db_path = tmp_path / "chat-delete.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-delete', 'Delete me', 'user-a')
                """
            )
            await db.executemany(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES (?, 'conv-delete', ?, ?, '[]', '[]', ?, ?, ?)
                """,
                [
                    ("msg-delete-user", "user", "Question?", "completed", 1, None),
                    ("msg-delete-assistant", "assistant", "Answer.", "completed", 2, "run-delete"),
                ],
            )
            await db.execute(
                """
                INSERT INTO agent_runs (
                    id, conversation_id, user_message_id, assistant_message_id,
                    status, protocol
                )
                VALUES (
                    'run-delete', 'conv-delete', 'msg-delete-user',
                    'msg-delete-assistant', 'completed', 'chat_completions'
                )
                """
            )
            await db.execute(
                """
                INSERT INTO agent_run_events (run_id, seq, event_type, payload_json)
                VALUES ('run-delete', 1, 'run_completed', '{}')
                """
            )
            await db.execute(
                """
                INSERT INTO message_citations (
                    id, message_id, citation_key, document_id, document_name,
                    source_anchor_json, display_label, preview_kind
                )
                VALUES (
                    'cit-delete', 'msg-delete-assistant', 'c1', 'doc-alpha',
                    'alpha.pdf', '{}', 'alpha p.1', 'pdf'
                )
                """
            )
            await db.commit()

    asyncio.run(run())

    response = _client(db_path).delete("/api/chat/conversations/conv-delete")

    assert response.status_code == 200
    assert response.json() == {"success": True}

    async def assert_deleted() -> None:
        async with aiosqlite.connect(db_path) as db:
            counts = []
            for table in [
                "conversations",
                "messages",
                "agent_runs",
                "agent_run_events",
                "message_citations",
            ]:
                cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")
                counts.append((table, (await cursor.fetchone())[0]))
        assert counts == [
            ("conversations", 0),
            ("messages", 0),
            ("agent_runs", 0),
            ("agent_run_events", 0),
            ("message_citations", 0),
        ]

    asyncio.run(assert_deleted())


def test_export_conversation_returns_metadata_and_ordered_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "chat-export.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-export', 'Export me', 'user-a')
                """
            )
            await db.executemany(
                """
                INSERT INTO messages (
                    id, conversation_id, role, content, sources, agent_steps,
                    status, sequence, run_id
                )
                VALUES (?, 'conv-export', ?, ?, '[]', '[]', 'completed', ?, ?)
                """,
                [
                    ("msg-export-2", "assistant", "Answer.", 2, "run-export"),
                    ("msg-export-1", "user", "Question?", 1, None),
                ],
            )
            await db.commit()

    asyncio.run(run())

    response = _client(db_path).get("/api/chat/conversations/conv-export/export")

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation"]["id"] == "conv-export"
    assert payload["conversation"]["title"] == "Export me"
    assert [message["id"] for message in payload["messages"]] == [
        "msg-export-1",
        "msg-export-2",
    ]
