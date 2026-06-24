import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from app.services.web_search_settings_service import WebSearchSettingsService  # noqa: E402


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


async def _service() -> tuple[aiosqlite.Connection, WebSearchSettingsService]:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    try:
        await _create_bootstrap_schema(db)
        await run_migrations(db)
    except Exception:
        await db.close()
        raise
    return db, WebSearchSettingsService(db)


def test_defaults_without_saved_settings() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            settings = await service.get_settings("user-a")

            assert settings["provider"] == "anysearch"
            assert settings["mode"] == "on-demand"
            assert settings["zone"] == "cn"
            assert settings["language"] == "zh-CN"
            assert settings["max_results"] == 5
            assert settings["content_types"] == ["web", "news"]
            assert settings["api_key_mask"] == ""
            assert "api_key" not in settings
        finally:
            await db.close()

    asyncio.run(run())

def test_save_masks_optional_api_key() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_settings(
                user_id="user-a",
                mode="auto",
                provider="anysearch",
                api_key="as-secret-123456",
                zone="intl",
                language="en",
                max_results=8,
                content_types=["web"],
            )

            assert saved["api_key_mask"] == "as-...3456"
            assert saved["content_types"] == ["web"]
            assert "api_key" not in saved
            assert "as-secret-123456" not in str(saved)
            assert await service.get_secret("user-a") == "as-secret-123456"
        finally:
            await db.close()

    asyncio.run(run())


def test_users_are_isolated() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            await service.save_settings(user_id="user-a", api_key="as-secret-123456")

            user_b_settings = await service.get_settings("user-b")

            assert user_b_settings["api_key_mask"] == ""
            assert await service.get_secret("user-b") is None
        finally:
            await db.close()

    asyncio.run(run())


def test_resolve_for_request_applies_mode_gate() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            default = await service.resolve_for_request("user-a", requested=False)
            requested = await service.resolve_for_request("user-a", requested=True)
            await service.save_settings(user_id="user-a", mode="auto")
            auto = await service.resolve_for_request("user-a", requested=False)

            assert default["enabled"] is False
            assert requested["enabled"] is True
            assert auto["enabled"] is True
        finally:
            await db.close()

    asyncio.run(run())


def test_save_rejects_invalid_values() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            invalid_cases = [
                {"mode": "always"},
                {"provider": "other"},
                {"zone": "moon"},
                {"content_types": ["web", "video"]},
                {"content_types": []},
                {"max_results": 0},
                {"max_results": 11},
            ]
            for payload in invalid_cases:
                try:
                    await service.save_settings(user_id="user-a", **payload)
                    assert False, f"Expected invalid payload to fail: {payload}"
                except ValueError:
                    pass
        finally:
            await db.close()

    asyncio.run(run())
