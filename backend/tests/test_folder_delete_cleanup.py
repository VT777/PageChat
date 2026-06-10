import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.cache_service import cache_service
from app.services.folder_service import FolderService


async def _bootstrap_db(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE folders (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                parent_id TEXT,
                path TEXT NOT NULL,
                user_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
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
        await db.commit()


async def _insert_folder(
    db_path: Path, folder_id: str, path: str, user_id: str
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO folders (id, name, parent_id, path, user_id)
            VALUES (?, ?, NULL, ?, ?)
            """,
            (folder_id, path, path, user_id),
        )
        await db.commit()


async def _insert_document(
    db_path: Path,
    doc_id: str,
    folder_id: str,
    folder_path: str,
    user_id: str,
    source_path: Path,
    index_path: Path,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO documents (
                id, name, original_name, file_path, index_path, file_size,
                file_type, status, page_count, processed_pages, folder_id,
                folder_path, user_id
            )
            VALUES (?, ?, ?, ?, ?, 1, '.pdf', 'completed', 1, 1, ?, ?, ?)
            """,
            (
                doc_id,
                f"{doc_id}.pdf",
                f"{doc_id}.pdf",
                str(source_path),
                str(index_path),
                folder_id,
                folder_path,
                user_id,
            ),
        )
        await db.commit()


def test_delete_folder_cleans_documents_files_indexes_and_caches(
    tmp_path, monkeypatch
) -> None:
    async def run() -> None:
        db_path = tmp_path / "app.db"
        documents_dir = tmp_path / "documents"
        indexes_dir = tmp_path / "indexes"
        documents_dir.mkdir()
        indexes_dir.mkdir()
        await _bootstrap_db(db_path)

        user_a_source = documents_dir / "doc-a.pdf"
        user_a_index = indexes_dir / "doc-a-explicit.json"
        user_a_default_index = indexes_dir / "doc-a.json"
        user_b_source = documents_dir / "doc-b.pdf"
        user_b_index = indexes_dir / "doc-b.json"
        for path in [
            user_a_source,
            user_a_index,
            user_a_default_index,
            user_b_source,
            user_b_index,
        ]:
            path.write_text("x", encoding="utf-8")

        await _insert_folder(db_path, "folder-a", "Projects", "user-a")
        await _insert_folder(db_path, "folder-b", "Projects", "user-b")
        await _insert_document(
            db_path,
            "doc-a",
            "folder-a",
            "Projects",
            "user-a",
            user_a_source,
            user_a_index,
        )
        await _insert_document(
            db_path,
            "doc-b",
            "folder-b",
            "Projects",
            "user-b",
            user_b_source,
            user_b_index,
        )

        import app.services.document_service as document_service_module

        monkeypatch.setattr(document_service_module, "DOCUMENTS_DIR", documents_dir)
        monkeypatch.setattr(
            document_service_module, "INDEXES_DIR", indexes_dir, raising=False
        )

        cache_service.clear_all()
        cache_service.set_structure("user-a", "doc-a", {"cached": "structure"})
        cache_service.set_page_content("user-a", "doc-a", 1, False, {"cached": "page"})
        cache_service.set_search_result("user-a", "alpha", ["doc-a"], [{"doc": "a"}])

        service = FolderService()
        service._db_path = str(db_path)

        assert await service.delete_folder("folder-a", user_id="user-a") is True

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("SELECT id FROM documents WHERE id = 'doc-a'")
            assert await cursor.fetchone() is None
            cursor = await db.execute("SELECT id FROM folders WHERE id = 'folder-a'")
            assert await cursor.fetchone() is None
            cursor = await db.execute("SELECT id FROM documents WHERE id = 'doc-b'")
            assert await cursor.fetchone() == ("doc-b",)

        assert not user_a_source.exists()
        assert not user_a_index.exists()
        assert not user_a_default_index.exists()
        assert user_b_source.exists()
        assert user_b_index.exists()
        assert cache_service.get_structure("user-a", "doc-a") is None
        assert cache_service.get_page_content("user-a", "doc-a", 1, False) is None
        assert cache_service.get_search_result("user-a", "alpha", ["doc-a"]) is None

    asyncio.run(run())
