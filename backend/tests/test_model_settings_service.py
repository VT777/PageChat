import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations
from app.services.model_settings_service import ModelSettingsService


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


async def _service() -> tuple[aiosqlite.Connection, ModelSettingsService]:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    try:
        await _create_bootstrap_schema(db)
        await run_migrations(db)
    except Exception:
        await db.close()
        raise
    return db, ModelSettingsService(db)


def test_save_and_read_provider_config_masks_api_key() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            configs = await service.list_provider_configs("user-a")

            assert saved["provider_id"]
            assert configs[0]["api_key_mask"] == "sk-...3456"
            assert "api_key" not in configs[0]
            assert "sk-secret-123456" not in str(configs[0])
        finally:
            await db.close()

    asyncio.run(run())


def test_delete_provider_config_is_user_scoped() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            assert await service.delete_provider_config("user-b", saved["provider_id"]) is False
            assert await service.delete_provider_config("user-a", saved["provider_id"]) is True
            assert await service.list_provider_configs("user-a") == []
        finally:
            await db.close()

    asyncio.run(run())


def test_save_provider_config_cannot_overwrite_another_users_provider_id() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            try:
                await service.save_provider_config(
                    user_id="user-b",
                    provider="openai_compatible",
                    base_url="https://evil.test/v1",
                    api_key="sk-evil-123456",
                    provider_id=saved["provider_id"],
                )
                assert False, "Expected cross-user provider update to fail"
            except ValueError as exc:
                assert "provider" in str(exc).lower()

            configs = await service.list_provider_configs("user-a")
            assert configs[0]["base_url"] == "https://example.test/v1"
        finally:
            await db.close()

    asyncio.run(run())


def test_resolve_route_uses_environment_fallback_without_user_config(monkeypatch) -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            monkeypatch.setattr(
                "app.services.model_settings_service.config.LLM_BASE_URL",
                "https://env.example/v1",
            )
            monkeypatch.setattr(
                "app.services.model_settings_service.config.LLM_API_KEY",
                "env-secret",
            )
            monkeypatch.setattr(
                "app.services.model_settings_service.config.LLM_FLASH_MODEL",
                "env-flash",
            )

            resolved = await service.resolve_route("user-a", "general_chat")

            assert resolved["source"] == "environment"
            assert resolved["model"] == "env-flash"
            assert resolved["base_url"] == "https://env.example/v1"
            assert resolved["api_key"] == "env-secret"
        finally:
            await db.close()

    asyncio.run(run())


def test_save_route_mapping_rejects_missing_provider_or_model() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            try:
                await service.save_route_mapping(
                    user_id="user-a",
                    route_slot="general_chat",
                    provider_id="missing-provider",
                    model="model-a",
                )
                assert False, "Expected missing provider to fail"
            except ValueError as exc:
                assert "provider" in str(exc).lower()

            provider = await service.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )

            try:
                await service.save_route_mapping(
                    user_id="user-a",
                    route_slot="general_chat",
                    provider_id=provider["provider_id"],
                    model="",
                )
                assert False, "Expected missing model to fail"
            except ValueError as exc:
                assert "model" in str(exc).lower()
        finally:
            await db.close()

    asyncio.run(run())
