from collections.abc import Awaitable, Callable

import aiosqlite


Migration = tuple[str, Callable[[aiosqlite.Connection], Awaitable[None]]]


async def _column_exists(
    db: aiosqlite.Connection, table_name: str, column_name: str
) -> bool:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    return any(row[1] == column_name for row in await cursor.fetchall())


async def _add_documents_last_reindex_at(db: aiosqlite.Connection) -> None:
    if not await _column_exists(db, "documents", "last_reindex_at"):
        await db.execute("ALTER TABLE documents ADD COLUMN last_reindex_at TIMESTAMP")


async def _add_core_indexes(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_user_status_updated
        ON documents(user_id, status, updated_at)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_user_folder_updated
        ON documents(user_id, folder_id, updated_at)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_folders_user_parent
        ON folders(user_id, parent_id)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_folders_user_path
        ON folders(user_id, path)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_conversations_user_created
        ON conversations(user_id, created_at)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
        ON messages(conversation_id, created_at)
        """
    )


async def _add_model_settings_tables(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS model_provider_configs (
            provider_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            base_url TEXT NOT NULL,
            api_key_ciphertext TEXT NOT NULL,
            api_key_mask TEXT NOT NULL,
            validation_status TEXT NOT NULL DEFAULT 'untested',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_model_provider_configs_user
        ON model_provider_configs(user_id, updated_at)
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS model_route_mappings (
            user_id TEXT NOT NULL,
            route_slot TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            model TEXT NOT NULL,
            supports_streaming INTEGER NOT NULL DEFAULT 1,
            supports_tool_calling INTEGER NOT NULL DEFAULT 1,
            supports_vision INTEGER NOT NULL DEFAULT 0,
            supports_structured_output INTEGER NOT NULL DEFAULT 0,
            supports_responses_api INTEGER NOT NULL DEFAULT 0,
            route_version TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, route_slot),
            FOREIGN KEY (provider_id) REFERENCES model_provider_configs(provider_id)
                ON DELETE CASCADE
        )
        """
    )


async def _add_model_route_capabilities(db: aiosqlite.Connection) -> None:
    capability_columns = {
        "supports_streaming": "INTEGER NOT NULL DEFAULT 1",
        "supports_tool_calling": "INTEGER NOT NULL DEFAULT 1",
        "supports_structured_output": "INTEGER NOT NULL DEFAULT 0",
        "supports_responses_api": "INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, definition in capability_columns.items():
        if not await _column_exists(db, "model_route_mappings", column_name):
            await db.execute(
                f"ALTER TABLE model_route_mappings ADD COLUMN {column_name} {definition}"
            )


async def _add_ocr_settings_tables(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS ocr_engine_profiles (
            profile_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            engine_type TEXT NOT NULL,
            provider TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            model TEXT NOT NULL,
            api_key_ciphertext TEXT NOT NULL,
            api_key_mask TEXT NOT NULL,
            capabilities_json TEXT NOT NULL,
            options_json TEXT NOT NULL,
            profile_version TEXT NOT NULL,
            is_default INTEGER NOT NULL DEFAULT 0,
            validation_status TEXT NOT NULL DEFAULT 'untested',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ocr_engine_profiles_user
        ON ocr_engine_profiles(user_id, updated_at)
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS ocr_task_overrides (
            user_id TEXT NOT NULL,
            task TEXT NOT NULL,
            profile_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, task),
            FOREIGN KEY (profile_id) REFERENCES ocr_engine_profiles(profile_id)
                ON DELETE CASCADE
        )
        """
    )

async def _add_web_search_settings_table(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS web_search_settings (
            user_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'anysearch',
            mode TEXT NOT NULL DEFAULT 'on-demand',
            api_key_ciphertext TEXT,
            api_key_mask TEXT,
            zone TEXT NOT NULL DEFAULT 'cn',
            language TEXT NOT NULL DEFAULT 'zh-CN',
            max_results INTEGER NOT NULL DEFAULT 5,
            content_types_json TEXT NOT NULL DEFAULT '["web","news"]',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def _add_chat_attachments(db: aiosqlite.Connection) -> None:
    if not await _column_exists(db, "messages", "attachments_json"):
        await db.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT")
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_attachments (
            attachment_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT,
            message_id TEXT,
            original_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            width INTEGER,
            height INTEGER,
            status TEXT NOT NULL DEFAULT 'uploaded',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_attachments_user_created
        ON chat_attachments(user_id, created_at)
        """
    )


async def _add_model_provider_response_capabilities(db: aiosqlite.Connection) -> None:
    for column_name in (
        "supports_responses_api",
        "supports_reasoning_effort",
        "supports_reasoning_summary",
    ):
        if not await _column_exists(db, "model_provider_configs", column_name):
            await db.execute(
                f"ALTER TABLE model_provider_configs ADD COLUMN {column_name} "
                "INTEGER NOT NULL DEFAULT 0"
            )


async def _add_agent_run_storage(db: aiosqlite.Connection) -> None:
    if not await _column_exists(db, "messages", "sequence"):
        await db.execute("ALTER TABLE messages ADD COLUMN sequence INTEGER")
    if not await _column_exists(db, "messages", "run_id"):
        await db.execute("ALTER TABLE messages ADD COLUMN run_id TEXT")

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            assistant_message_id TEXT NOT NULL,
            status TEXT NOT NULL,
            provider_id TEXT,
            model TEXT,
            protocol TEXT NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            error TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (user_message_id) REFERENCES messages(id),
            FOREIGN KEY (assistant_message_id) REFERENCES messages(id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id, seq),
            FOREIGN KEY (run_id) REFERENCES agent_runs(id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS message_citations (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            citation_key TEXT NOT NULL,
            document_id TEXT,
            document_name TEXT NOT NULL,
            source_anchor_json TEXT NOT NULL,
            display_label TEXT NOT NULL,
            preview_kind TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (message_id) REFERENCES messages(id)
        )
        """
    )

    await db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_conversation_sequence
        ON messages(conversation_id, sequence)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_started
        ON agent_runs(conversation_id, started_at)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_seq
        ON agent_run_events(run_id, seq)
        """
    )
    await db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_message_citations_message
        ON message_citations(message_id)
        """
    )

    cursor = await db.execute(
        """
        SELECT DISTINCT conversation_id
        FROM messages
        WHERE sequence IS NULL
        """
    )
    conversation_ids = [row[0] for row in await cursor.fetchall()]
    for conversation_id in conversation_ids:
        cursor = await db.execute(
            """
            SELECT id
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at, id
            """,
            (conversation_id,),
        )
        for index, row in enumerate(await cursor.fetchall(), start=1):
            await db.execute(
                "UPDATE messages SET sequence = ? WHERE id = ? AND sequence IS NULL",
                (index, row[0]),
            )


MIGRATIONS: tuple[Migration, ...] = (
    ("20260610_001_add_documents_last_reindex_at", _add_documents_last_reindex_at),
    ("20260610_002_add_core_indexes", _add_core_indexes),
    ("20260611_003_add_model_settings_tables", _add_model_settings_tables),
    ("20260615_004_add_ocr_settings_tables", _add_ocr_settings_tables),
    ("20260625_005_add_web_search_settings_table", _add_web_search_settings_table),
    ("20260625_006_add_chat_attachments", _add_chat_attachments),
    (
        "20260626_007_add_model_provider_response_capabilities",
        _add_model_provider_response_capabilities,
    ),
    ("20260626_008_add_agent_runs_events_citations", _add_agent_run_storage),
    ("20260626_009_add_model_route_capabilities", _add_model_route_capabilities),
)


async def run_migrations(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor = await db.execute("SELECT id FROM schema_migrations")
    applied = {row[0] for row in await cursor.fetchall()}

    for migration_id, migration in MIGRATIONS:
        if migration_id in applied:
            continue
        await migration(db)
        await db.execute(
            "INSERT INTO schema_migrations (id) VALUES (?)", (migration_id,)
        )

    await db.commit()
