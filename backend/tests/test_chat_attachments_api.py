import asyncio
import base64
import json
from pathlib import Path
import sys

import aiosqlite
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import chat  # noqa: E402
from app.core.config import CHAT_ATTACHMENT_MAX_BYTES  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402


def _tiny_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
    )


async def _create_bootstrap_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            original_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            index_path TEXT,
            file_size INTEGER,
            file_type TEXT,
            status TEXT DEFAULT 'uploaded',
            page_count INTEGER,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_pages INTEGER DEFAULT 0,
            folder_id TEXT,
            folder_path TEXT,
            description TEXT,
            user_id TEXT
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            sources TEXT,
            agent_steps TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            thinking_content TEXT,
            status TEXT DEFAULT 'completed',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            parent_id TEXT,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        )
        """
    )
    await db.commit()


def _client(tmp_path: Path, user_id: str = "user-a") -> TestClient:
    db_path = tmp_path / "chat-attachments.db"

    async def init() -> None:
        async with aiosqlite.connect(db_path) as db:
            await _create_bootstrap_schema(db)
            await run_migrations(db)

    asyncio.run(init())

    chat.DB_PATH = db_path
    chat.CHAT_ATTACHMENTS_DIR = tmp_path / "attachments"

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


def test_upload_chat_attachment_returns_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["attachment_id"]
    assert payload["original_name"] == "screen.png"
    assert payload["mime_type"] == "image/png"
    assert payload["size_bytes"] == len(_tiny_png_bytes())
    assert payload["content_url"].endswith(f"/{payload['attachment_id']}/content")
    assert "stored_path" not in payload
    assert "data:image" not in response.text


def test_fetch_attachment_content_requires_owner(tmp_path: Path) -> None:
    user_a = _client(tmp_path, user_id="user-a")
    uploaded = user_a.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    )
    attachment_id = uploaded.json()["attachment_id"]

    owner_response = user_a.get(f"/api/chat/attachments/{attachment_id}/content")
    user_b = _client(tmp_path, user_id="user-b")
    denied_response = user_b.get(f"/api/chat/attachments/{attachment_id}/content")

    assert owner_response.status_code == 200
    assert owner_response.content == _tiny_png_bytes()
    assert owner_response.headers["content-type"] == "image/png"
    assert denied_response.status_code in {403, 404}


def test_upload_rejects_invalid_mime_and_oversize(tmp_path: Path) -> None:
    client = _client(tmp_path)

    invalid = client.post(
        "/api/chat/attachments",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    huge = client.post(
        "/api/chat/attachments",
        files={"file": ("huge.png", b"x" * (CHAT_ATTACHMENT_MAX_BYTES + 1), "image/png")},
    )

    assert invalid.status_code == 400
    assert huge.status_code == 400


def test_delete_unbound_attachment_removes_draft_file(tmp_path: Path) -> None:
    client = _client(tmp_path, user_id="user-a")
    uploaded = client.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    ).json()

    deleted = client.delete(f"/api/chat/attachments/{uploaded['attachment_id']}")
    content = client.get(f"/api/chat/attachments/{uploaded['attachment_id']}/content")

    assert deleted.status_code == 200
    assert deleted.json() == {"success": True}
    assert content.status_code == 404


def test_delete_bound_attachment_returns_conflict(tmp_path: Path) -> None:
    client = _client(tmp_path, user_id="user-a")
    uploaded = client.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    ).json()

    async def bind_attachment() -> None:
        async with aiosqlite.connect(tmp_path / "chat-attachments.db") as db:
            await db.execute(
                """
                UPDATE chat_attachments
                SET conversation_id = ?,
                    message_id = ?,
                    status = 'bound'
                WHERE attachment_id = ?
                """,
                ("conv-a", "msg-a", uploaded["attachment_id"]),
            )
            await db.commit()

    asyncio.run(bind_attachment())

    deleted = client.delete(f"/api/chat/attachments/{uploaded['attachment_id']}")

    assert deleted.status_code == 409


def test_conversation_messages_include_attachment_metadata(tmp_path: Path) -> None:
    client = _client(tmp_path, user_id="user-a")
    uploaded = client.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    ).json()

    async def insert_message() -> None:
        async with aiosqlite.connect(tmp_path / "chat-attachments.db") as db:
            await db.execute(
                "INSERT INTO conversations (id, title, user_id) VALUES (?, ?, ?)",
                ("conv-a", "截图对话", "user-a"),
            )
            await db.execute(
                """
                INSERT INTO messages (
                    id,
                    conversation_id,
                    role,
                    content,
                    sources,
                    agent_steps,
                    status,
                    attachments_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "msg-a",
                    "conv-a",
                    "user",
                    "看这张截图",
                    "[]",
                    "[]",
                    "completed",
                    json.dumps([uploaded], ensure_ascii=False),
                ),
            )
            await db.commit()

    asyncio.run(insert_message())

    response = client.get("/api/chat/conversations/conv-a/messages")

    assert response.status_code == 200
    assert response.json()[0]["attachments"][0]["attachment_id"] == uploaded[
        "attachment_id"
    ]


def test_chat_stream_never_emits_base64_attachment_payload(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeAgentService:
        def __init__(self, db):
            self.db = db

        async def run_agent_stream(self, **kwargs):
            assert kwargs["request_attachments"][0]["data_base64"]
            yield 'event: answer_delta\ndata: {"content":"我看到了截图。"}\n\n'

    monkeypatch.setattr("app.services.agent_service.AgentService", FakeAgentService)
    client = _client(tmp_path, user_id="user-a")
    uploaded = client.post(
        "/api/chat/attachments",
        files={"file": ("screen.png", _tiny_png_bytes(), "image/png")},
    ).json()
    raw_base64 = base64.b64encode(_tiny_png_bytes()).decode("ascii")

    response = client.post(
        "/api/chat/stream",
        json={
            "question": "看这张截图",
            "attachment_ids": [uploaded["attachment_id"]],
        },
    )

    assert response.status_code == 200
    assert "我看到了截图" in response.text
    assert raw_base64 not in response.text
    assert "data:image" not in response.text
