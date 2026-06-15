import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from app.services.ocr_settings_service import OCRSettingsService  # noqa: E402


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


async def _service() -> tuple[aiosqlite.Connection, OCRSettingsService]:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    try:
        await _create_bootstrap_schema(db)
        await run_migrations(db)
    except Exception:
        await db.close()
        raise
    return db, OCRSettingsService(db)


def test_save_list_update_and_delete_profile_masks_secret() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_profile(
                user_id="user-a",
                name="DashScope OCR",
                engine_type="openai_compatible_ocr",
                provider="dashscope",
                endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen-vl-ocr-2025-11-20",
                api_key="dash-secret-123456",
                capabilities=["toc_page", "page_text"],
                options={"temperature": 0},
                is_default=True,
            )

            listed = await service.list_profiles("user-a")
            updated = await service.update_profile(
                user_id="user-a",
                profile_id=saved["profile_id"],
                name="Updated OCR",
                engine_type="openai_compatible_ocr",
                provider="dashscope",
                endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen-vl-ocr-2025-11-20",
                capabilities=["toc_page"],
                options={"temperature": 0},
                is_default=False,
            )

            assert listed[0]["api_key_mask"] == "das...3456"
            assert "api_key" not in listed[0]
            assert "dash-secret-123456" not in str(listed[0])
            assert updated["name"] == "Updated OCR"
            assert updated["capabilities"] == ["toc_page"]
            assert await service.delete_profile("user-a", saved["profile_id"]) is True
            assert await service.list_profiles("user-a") == []
        finally:
            await db.close()

    asyncio.run(run())


def test_profiles_are_user_scoped() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            saved = await service.save_profile(
                user_id="user-a",
                name="A",
                engine_type="paddleocr_job",
                provider="aistudio",
                endpoint="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
                model="PP-OCRv6",
                api_key="paddle-secret",
                capabilities=["toc_page", "page_text"],
            )

            assert await service.list_profiles("user-b") == []
            assert await service.delete_profile("user-b", saved["profile_id"]) is False
            try:
                await service.save_profile(
                    user_id="user-b",
                    name="B",
                    engine_type="paddleocr_job",
                    provider="aistudio",
                    endpoint="https://evil.test/jobs",
                    model="PP-OCRv6",
                    api_key="evil-secret",
                    capabilities=["toc_page"],
                    profile_id=saved["profile_id"],
                )
                assert False, "Expected cross-user overwrite to fail"
            except ValueError as exc:
                assert "profile" in str(exc).lower()
        finally:
            await db.close()

    asyncio.run(run())


def test_task_override_resolution_prefers_override_then_default() -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            default = await service.save_profile(
                user_id="user-a",
                name="Default",
                engine_type="paddleocr_job",
                provider="aistudio",
                endpoint="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
                model="PP-OCRv6",
                api_key="paddle-secret",
                capabilities=["toc_page", "page_text"],
                is_default=True,
            )
            toc = await service.save_profile(
                user_id="user-a",
                name="TOC",
                engine_type="openai_compatible_ocr",
                provider="dashscope",
                endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model="qwen-vl-ocr-2025-11-20",
                api_key="dash-secret",
                capabilities=["toc_page"],
            )

            await service.save_task_overrides("user-a", {"toc_page": toc["profile_id"]})

            toc_route = await service.resolve_task("user-a", "toc_page")
            text_route = await service.resolve_task("user-a", "page_text")

            assert toc_route["profile_id"] == toc["profile_id"]
            assert toc_route["source"] == "task_override"
            assert text_route["profile_id"] == default["profile_id"]
            assert text_route["source"] == "default_profile"
            assert toc_route["api_key"] == "dash-secret"
        finally:
            await db.close()

    asyncio.run(run())


def test_env_fallback_when_no_user_profile(monkeypatch) -> None:
    async def run() -> None:
        db, service = await _service()
        try:
            monkeypatch.setattr(
                "app.services.ocr_settings_service.config.OCR_DEFAULT_ENGINE_TYPE",
                "openai_compatible_ocr",
                raising=False,
            )
            monkeypatch.setattr(
                "app.services.ocr_settings_service.config.OCR_BASE_URL",
                "https://env.example/v1",
                raising=False,
            )
            monkeypatch.setattr(
                "app.services.ocr_settings_service.config.OCR_MODEL",
                "env-ocr-model",
                raising=False,
            )
            monkeypatch.setattr(
                "app.services.ocr_settings_service.config.OCR_API_KEY",
                "env-secret",
                raising=False,
            )

            resolved = await service.resolve_task("user-a", "page_text")

            assert resolved["source"] == "environment"
            assert resolved["engine_type"] == "openai_compatible_ocr"
            assert resolved["endpoint"] == "https://env.example/v1"
            assert resolved["model"] == "env-ocr-model"
            assert resolved["api_key"] == "env-secret"
        finally:
            await db.close()

    asyncio.run(run())
