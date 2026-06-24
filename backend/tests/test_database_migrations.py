import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations


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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        )
        """
    )
    await db.commit()


async def _column_names(db: aiosqlite.Connection, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in await cursor.fetchall()}


async def _index_names(db: aiosqlite.Connection, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA index_list({table_name})")
    return {row[1] for row in await cursor.fetchall()}


def test_migrations_create_history_and_are_idempotent() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await _create_bootstrap_schema(db)

            await run_migrations(db)
            await run_migrations(db)

            columns = await _column_names(db, "schema_migrations")
            assert {"id", "applied_at"}.issubset(columns)

            cursor = await db.execute("SELECT id FROM schema_migrations ORDER BY id")
            migration_ids = [row[0] for row in await cursor.fetchall()]

            assert migration_ids == [
                "20260610_001_add_documents_last_reindex_at",
                "20260610_002_add_core_indexes",
                "20260611_003_add_model_settings_tables",
                "20260615_004_add_ocr_settings_tables",
                "20260625_005_add_web_search_settings_table",
            ]

    asyncio.run(run())


def test_migrations_add_ocr_settings_tables() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await _create_bootstrap_schema(db)

            await run_migrations(db)

            profile_columns = await _column_names(db, "ocr_engine_profiles")
            override_columns = await _column_names(db, "ocr_task_overrides")

            assert {
                "profile_id",
                "user_id",
                "engine_type",
                "endpoint",
                "model",
                "api_key_ciphertext",
                "api_key_mask",
                "profile_version",
                "is_default",
            }.issubset(profile_columns)
            assert {"user_id", "task", "profile_id"}.issubset(override_columns)

    asyncio.run(run())


def test_migrations_add_web_search_settings_table() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await _create_bootstrap_schema(db)

            await run_migrations(db)

            columns = await _column_names(db, "web_search_settings")

            assert {
                "user_id",
                "provider",
                "mode",
                "api_key_ciphertext",
                "api_key_mask",
                "zone",
                "language",
                "max_results",
                "content_types_json",
            }.issubset(columns)

    asyncio.run(run())


def test_migrations_add_documents_last_reindex_at() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await _create_bootstrap_schema(db)

            before_columns = await _column_names(db, "documents")
            assert "last_reindex_at" not in before_columns

            await run_migrations(db)

            after_columns = await _column_names(db, "documents")
            assert "last_reindex_at" in after_columns

    asyncio.run(run())


def test_migrations_add_core_indexes() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await _create_bootstrap_schema(db)

            await run_migrations(db)

            assert "idx_documents_user_status_updated" in await _index_names(
                db, "documents"
            )
            assert "idx_documents_user_folder_updated" in await _index_names(
                db, "documents"
            )
            assert "idx_folders_user_parent" in await _index_names(db, "folders")
            assert "idx_folders_user_path" in await _index_names(db, "folders")
            assert "idx_conversations_user_created" in await _index_names(
                db, "conversations"
            )
            assert "idx_messages_conversation_created" in await _index_names(
                db, "messages"
            )

    asyncio.run(run())


def test_migrations_add_model_settings_tables() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await _create_bootstrap_schema(db)

            await run_migrations(db)

            provider_columns = await _column_names(db, "model_provider_configs")
            route_columns = await _column_names(db, "model_route_mappings")

            assert {
                "provider_id",
                "user_id",
                "provider",
                "base_url",
                "api_key_ciphertext",
                "api_key_mask",
            }.issubset(provider_columns)
            assert {
                "user_id",
                "route_slot",
                "provider_id",
                "model",
                "route_version",
            }.issubset(route_columns)

    asyncio.run(run())
