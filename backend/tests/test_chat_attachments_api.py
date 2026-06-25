import asyncio
import base64
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
            status TEXT DEFAULT 'uploaded',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            folder_id TEXT,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            parent_id TEXT,
            path TEXT NOT NULL,
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
