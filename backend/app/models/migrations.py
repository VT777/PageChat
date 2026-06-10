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


MIGRATIONS: tuple[Migration, ...] = (
    ("20260610_001_add_documents_last_reindex_at", _add_documents_last_reindex_at),
    ("20260610_002_add_core_indexes", _add_core_indexes),
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
