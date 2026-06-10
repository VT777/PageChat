import asyncio
from pathlib import Path
import sys

import aiosqlite
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.folder_service import FolderService
from app.services.search_service import DocumentSearchService


class AsyncNoop:
    async def __call__(self):
        return None


class FakeBM25:
    def retrieve(self, queries, k):
        indices = list(range(5))
        scores = [1.0 - (i * 0.05) for i in indices]
        return (
            np.array([indices], dtype=int),
            np.array([scores], dtype=float),
        )


def _folder_search_service() -> DocumentSearchService:
    service = DocumentSearchService()
    service._initialized = True
    service.bm25_index = FakeBM25()
    service.rerank_model = None
    service.doc_corpus = [
        "alpha parent",
        "alpha child",
        "alpha sibling",
        "alpha root",
        "alpha other user",
    ]
    service.segment_metadata = [
        {
            "doc_id": "doc-parent",
            "doc_name": "parent.pdf",
            "user_id": "user-a",
            "folder_id": "folder-parent",
            "folder_path": "Projects",
            "title": "Parent",
            "snippet": "alpha parent",
        },
        {
            "doc_id": "doc-child",
            "doc_name": "child.pdf",
            "user_id": "user-a",
            "folder_id": "folder-child",
            "folder_path": "Projects/Child",
            "title": "Child",
            "snippet": "alpha child",
        },
        {
            "doc_id": "doc-sibling",
            "doc_name": "sibling.pdf",
            "user_id": "user-a",
            "folder_id": "folder-sibling",
            "folder_path": "Archive",
            "title": "Sibling",
            "snippet": "alpha sibling",
        },
        {
            "doc_id": "doc-root",
            "doc_name": "root.pdf",
            "user_id": "user-a",
            "folder_id": None,
            "folder_path": None,
            "title": "Root",
            "snippet": "alpha root",
        },
        {
            "doc_id": "doc-other",
            "doc_name": "other.pdf",
            "user_id": "user-b",
            "folder_id": "folder-parent",
            "folder_path": "Projects",
            "title": "Other",
            "snippet": "alpha other user",
        },
    ]
    service.doc_metadata = {
        meta["doc_id"]: {
            "name": meta["doc_name"],
            "user_id": meta["user_id"],
            "folder_id": meta["folder_id"],
            "folder_path": meta["folder_path"],
        }
        for meta in service.segment_metadata
    }
    service.last_index_doc_count = len(service.doc_metadata)
    service.ensure_index_fresh = AsyncNoop()
    return service


def test_search_with_folder_id_excludes_sibling_and_child_by_default() -> None:
    async def run() -> None:
        service = _folder_search_service()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            folder_id="folder-parent",
            include_subfolders=False,
            auto_expand=False,
            recall_k=5,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == ["doc-parent"]

    asyncio.run(run())


def test_search_with_folder_id_can_include_descendants() -> None:
    async def run() -> None:
        service = _folder_search_service()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            folder_id="folder-parent",
            include_subfolders=True,
            auto_expand=False,
            recall_k=5,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == [
            "doc-parent",
            "doc-child",
        ]

    asyncio.run(run())


def test_search_with_folder_path_can_include_descendants() -> None:
    async def run() -> None:
        service = _folder_search_service()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            folder_path="Projects",
            include_subfolders=True,
            auto_expand=False,
            recall_k=5,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == [
            "doc-parent",
            "doc-child",
        ]

    asyncio.run(run())


def test_allowed_doc_ids_still_narrows_folder_results() -> None:
    async def run() -> None:
        service = _folder_search_service()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            folder_id="folder-parent",
            include_subfolders=True,
            allowed_doc_ids=["doc-child", "doc-sibling"],
            auto_expand=False,
            recall_k=5,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == ["doc-child"]

    asyncio.run(run())


def test_document_ids_and_folder_scope_are_intersected() -> None:
    async def run() -> None:
        service = _folder_search_service()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            folder_id="folder-parent",
            include_subfolders=True,
            document_ids=["doc-child", "doc-sibling"],
            auto_expand=False,
            recall_k=5,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == ["doc-child"]

    asyncio.run(run())


async def _bootstrap_folder_db(db_path: Path) -> None:
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
                status TEXT DEFAULT 'completed',
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
        await db.executemany(
            """
            INSERT INTO folders (id, name, parent_id, path, user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("parent", "Projects", None, "Projects", "user-a"),
                ("child", "Child", "parent", "Projects/Child", "user-a"),
                ("target", "Target", None, "Target", "user-a"),
            ],
        )
        await db.executemany(
            """
            INSERT INTO documents (
                id, name, original_name, file_path, file_type, status,
                folder_id, folder_path, user_id
            )
            VALUES (?, ?, ?, ?, '.pdf', 'completed', ?, ?, ?)
            """,
            [
                ("doc-parent", "p.pdf", "p.pdf", "p.pdf", "parent", "Projects", "user-a"),
                (
                    "doc-child",
                    "c.pdf",
                    "c.pdf",
                    "c.pdf",
                    "child",
                    "Projects/Child",
                    "user-a",
                ),
            ],
        )
        await db.commit()


def test_rename_folder_updates_direct_and_descendant_document_paths(tmp_path) -> None:
    async def run() -> None:
        db_path = tmp_path / "folder.db"
        await _bootstrap_folder_db(db_path)
        service = FolderService()
        service._db_path = str(db_path)

        await service.rename_folder("parent", "Renamed", user_id="user-a")

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT id, folder_path FROM documents ORDER BY id"
            )
            rows = await cursor.fetchall()

        assert rows == [
            ("doc-child", "Renamed/Child"),
            ("doc-parent", "Renamed"),
        ]

    asyncio.run(run())


def test_move_folder_updates_direct_and_descendant_document_paths(tmp_path) -> None:
    async def run() -> None:
        db_path = tmp_path / "folder.db"
        await _bootstrap_folder_db(db_path)
        service = FolderService()
        service._db_path = str(db_path)

        await service.move_folder("parent", "target", user_id="user-a")

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT id, folder_path FROM documents ORDER BY id"
            )
            rows = await cursor.fetchall()

        assert rows == [
            ("doc-child", "Target/Projects/Child"),
            ("doc-parent", "Target/Projects"),
        ]

    asyncio.run(run())
