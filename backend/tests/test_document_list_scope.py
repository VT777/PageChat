import asyncio
import inspect
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_service import DocumentService
from app.api.documents import list_documents


async def _bootstrap_documents_db(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                index_path TEXT,
                file_size INTEGER,
                file_type TEXT,
                status TEXT DEFAULT 'completed',
                page_count INTEGER,
                error_message TEXT,
                folder_id TEXT,
                folder_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_pages INTEGER DEFAULT 0,
                description TEXT,
                user_id TEXT,
                last_reindex_at TIMESTAMP
            )
            """
        )
        await db.executemany(
            """
            INSERT INTO documents (
                id, name, original_name, file_path, file_size, file_type, status,
                folder_id, folder_path, user_id, updated_at
            )
            VALUES (?, ?, ?, ?, 1024, '.pdf', 'completed', ?, ?, ?, ?)
            """,
            [
                (
                    "doc-root",
                    "root.pdf",
                    "root.pdf",
                    "root.pdf",
                    None,
                    None,
                    "user-a",
                    "2026-06-25T12:00:00",
                ),
                (
                    "doc-child",
                    "child.pdf",
                    "child.pdf",
                    "child.pdf",
                    "folder-child",
                    "Projects/Child",
                    "user-a",
                    "2026-06-25T11:00:00",
                ),
                (
                    "doc-other-user",
                    "other.pdf",
                    "other.pdf",
                    "other.pdf",
                    None,
                    None,
                    "user-b",
                    "2026-06-25T10:00:00",
                ),
            ],
        )
        await db.commit()


def test_root_document_list_is_not_recursive_by_default(tmp_path) -> None:
    async def run() -> None:
        db_path = tmp_path / "documents.db"
        await _bootstrap_documents_db(db_path)
        async with aiosqlite.connect(db_path) as db:
            service = DocumentService(db)

            documents, total = await service.list_documents(
                folder_id=None,
                include_subfolders=False,
                user_id="user-a",
            )

        assert total == 1
        assert [doc.id for doc in documents] == ["doc-root"]

    asyncio.run(run())


def test_root_document_list_can_be_recursive_when_explicit(tmp_path) -> None:
    async def run() -> None:
        db_path = tmp_path / "documents.db"
        await _bootstrap_documents_db(db_path)
        async with aiosqlite.connect(db_path) as db:
            service = DocumentService(db)

            documents, total = await service.list_documents(
                folder_id=None,
                include_subfolders=True,
                user_id="user-a",
            )

        assert total == 2
        assert [doc.id for doc in documents] == ["doc-root", "doc-child"]

    asyncio.run(run())


def test_document_list_api_defaults_to_non_recursive_root_scope() -> None:
    parameter = inspect.signature(list_documents).parameters["include_subfolders"]

    assert parameter.default.default is False
