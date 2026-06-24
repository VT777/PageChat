import asyncio
from pathlib import Path
import sys

import aiosqlite
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import settings  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402


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
    db_path = tmp_path / "settings.db"

    async def init() -> None:
        async with aiosqlite.connect(db_path) as db:
            await _create_bootstrap_schema(db)
            await run_migrations(db)

    asyncio.run(init())

    app = FastAPI()
    app.include_router(settings.router)

    async def override_auth() -> dict:
        return {"id": user_id, "email": f"{user_id}@example.test"}

    async def override_db():
        db = await aiosqlite.connect(db_path)
        db.row_factory = aiosqlite.Row
        try:
            yield db
        finally:
            await db.close()

    app.dependency_overrides[settings.require_auth] = override_auth
    app.dependency_overrides[settings.get_db] = override_db
    return TestClient(app)


def _profile_payload(api_key: str = "dash-secret-123456") -> dict:
    return {
        "name": "DashScope OCR",
        "engine_type": "openai_compatible_ocr",
        "provider": "dashscope",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-ocr-2025-11-20",
        "api_key": api_key,
        "capabilities": ["page_text"],
        "options": {"temperature": 0},
        "is_default": True,
    }


def test_ocr_profile_crud_and_write_only_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)

    saved = client.post("/api/settings/ocr-engines", json=_profile_payload())
    profile_id = saved.json()["profile_id"]
    listed = client.get("/api/settings/ocr-engines")
    updated = client.patch(
        f"/api/settings/ocr-engines/{profile_id}",
        json={**_profile_payload(api_key=""), "name": "Updated OCR"},
    )

    assert saved.status_code == 200
    assert listed.json()[0]["api_key_mask"] == "das...3456"
    assert "api_key" not in listed.json()[0]
    assert "dash-secret-123456" not in listed.text
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated OCR"
    assert updated.json()["api_key_mask"] == "das...3456"

    deleted = client.delete(f"/api/settings/ocr-engines/{profile_id}")
    assert deleted.status_code == 200
    assert client.get("/api/settings/ocr-engines").json() == []


def test_ocr_routes_get_and_save(tmp_path: Path) -> None:
    client = _client(tmp_path)
    profile = client.post("/api/settings/ocr-engines", json=_profile_payload()).json()

    response = client.put(
        "/api/settings/ocr-routes",
        json={"routes": {"page_text": profile["profile_id"]}},
    )

    assert response.status_code == 200
    assert response.json()[0]["task"] == "page_text"
    routes = client.get("/api/settings/ocr-routes")
    assert routes.status_code == 200
    assert routes.json()[0]["profile_id"] == profile["profile_id"]


def test_ocr_connection_test_uses_adapter(monkeypatch, tmp_path: Path) -> None:
    calls = []

    class FakeAdapter:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        async def recognize(self, image_url, *, task, options=None):
            calls.append({"image_url": image_url, "task": task, "options": options})
            return object()

    monkeypatch.setattr(settings, "OpenAICompatibleOCRAdapter", FakeAdapter)
    client = _client(tmp_path)
    profile = client.post("/api/settings/ocr-engines", json=_profile_payload()).json()

    response = client.post(
        f"/api/settings/ocr-engines/{profile['profile_id']}/test",
        json={"task": "page_text", "image_url": "data:image/png;base64,abc"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls[0]["api_key"] == "dash-secret-123456"
    assert calls[1]["task"] == "page_text"
    assert "dash-secret-123456" not in response.text


def test_user_cannot_read_another_users_ocr_settings(tmp_path: Path) -> None:
    user_a = _client(tmp_path, user_id="user-a")
    user_a.post("/api/settings/ocr-engines", json=_profile_payload())

    user_b = _client(tmp_path, user_id="user-b")

    assert user_b.get("/api/settings/ocr-engines").json() == []
    assert user_b.get("/api/settings/ocr-routes").json() == []
