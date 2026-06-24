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


def test_get_web_search_settings_defaults(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/settings/web-search")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "anysearch"
    assert payload["mode"] == "on-demand"
    assert payload["zone"] == "cn"
    assert payload["language"] == "zh-CN"
    assert payload["max_results"] == 5
    assert payload["content_types"] == ["web", "news"]
    assert payload["api_key_mask"] == ""
    assert "api_key" not in payload


def test_save_web_search_settings_masks_key(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.put(
        "/api/settings/web-search",
        json={
            "provider": "anysearch",
            "mode": "auto",
            "api_key": "as-secret-123456",
            "zone": "intl",
            "language": "en",
            "max_results": 5,
            "content_types": ["web"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "auto"
    assert payload["api_key_mask"] == "as-...3456"
    assert "api_key" not in payload
    assert "as-secret-123456" not in response.text


def test_update_web_search_settings_without_key_preserves_mask(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client.put(
        "/api/settings/web-search",
        json={
            "provider": "anysearch",
            "mode": "on-demand",
            "api_key": "as-secret-123456",
            "zone": "cn",
            "language": "zh-CN",
            "max_results": 5,
            "content_types": ["web", "news"],
        },
    )

    response = client.put(
        "/api/settings/web-search",
        json={
            "provider": "anysearch",
            "mode": "auto",
            "zone": "intl",
            "language": "en",
            "max_results": 3,
            "content_types": ["news"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["api_key_mask"] == "as-...3456"
    assert payload["mode"] == "auto"
    assert payload["content_types"] == ["news"]


def test_web_search_settings_reject_invalid_payload(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.put(
        "/api/settings/web-search",
        json={
            "provider": "anysearch",
            "mode": "always",
            "zone": "cn",
            "language": "zh-CN",
            "max_results": 5,
            "content_types": ["web"],
        },
    )

    assert response.status_code == 400
    assert "mode" in response.text.lower()


def test_user_cannot_read_another_users_web_search_settings(tmp_path: Path) -> None:
    user_a = _client(tmp_path, user_id="user-a")
    user_a.put(
        "/api/settings/web-search",
        json={
            "provider": "anysearch",
            "mode": "auto",
            "api_key": "as-secret-123456",
            "zone": "intl",
            "language": "en",
            "max_results": 5,
            "content_types": ["web"],
        },
    )

    user_b = _client(tmp_path, user_id="user-b")

    payload = user_b.get("/api/settings/web-search").json()
    assert payload["mode"] == "on-demand"
    assert payload["api_key_mask"] == ""
    assert "as-secret-123456" not in str(payload)
