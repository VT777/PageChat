import asyncio
import aiosqlite
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import DocumentResponse
from app.services.folder_service import FolderService
from app.services.tool_executor import AGENT_TOOLS, ToolExecutor


def _doc(doc_id: str, name: str, folder_id: str | None = None) -> DocumentResponse:
    return DocumentResponse(
        id=doc_id,
        name=name,
        original_name=name,
        file_path=f"/tmp/{name}",
        file_size=10,
        file_type=".pdf",
        status="completed",
        page_count=3,
        processed_pages=3,
        folder_id=folder_id,
        folder_path="Projects",
        description="brief",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class FakePageIndexService:
    pass


class FakeDocumentService:
    pass


class FakeFolderService:
    def __init__(self) -> None:
        self.tree_calls: list[str | None] = []
        self.contents_calls: list[tuple[str | None, int, int, str | None]] = []

    async def get_compact_folder_tree(self, user_id: str | None = None):
        self.tree_calls.append(user_id)
        return [
            {
                "id": "folder-a",
                "name": "Projects",
                "path": "Projects",
                "parent_id": None,
                "child_count": 1,
                "document_count": 2,
                "children": [
                    {
                        "id": "folder-child",
                        "name": "Child",
                        "path": "Projects/Child",
                        "parent_id": "folder-a",
                        "child_count": 0,
                        "document_count": 1,
                        "children": [],
                    }
                ],
            }
        ]

    async def get_compact_folder_contents(
        self,
        folder_id: str | None,
        page: int = 1,
        page_size: int = 20,
        user_id: str | None = None,
    ):
        self.contents_calls.append((folder_id, page, page_size, user_id))
        return {
            "folder_id": folder_id,
            "page": page,
            "page_size": page_size,
            "total_documents": 2,
            "child_folders": [
                {
                    "id": "folder-child",
                    "name": "Child",
                    "path": "Projects/Child",
                    "parent_id": folder_id,
                    "child_count": 0,
                    "document_count": 1,
                }
            ],
            "documents": [
                {
                    "doc_id": "doc-a",
                    "doc_name": "a.pdf",
                    "file_type": ".pdf",
                    "status": "completed",
                    "page_count": 3,
                    "folder_path": "Projects",
                    "description": "brief",
                    "updated_at": "2026-06-10T00:00:00",
                }
            ],
        }


class MissingFolderService(FakeFolderService):
    async def get_compact_folder_contents(
        self,
        folder_id: str | None,
        page: int = 1,
        page_size: int = 20,
        user_id: str | None = None,
    ):
        raise ValueError("Folder not found or access denied")


def _tool_schema(name: str) -> dict:
    for tool in AGENT_TOOLS:
        if tool["function"]["name"] == name:
            return tool["function"]
    raise AssertionError(f"tool {name} not found")


def test_folder_tool_descriptions_are_readable() -> None:
    tree = _tool_schema("list_folder_tree")
    contents = _tool_schema("list_folder_contents")

    assert "current user's folder tree" in tree["description"]
    assert "compact child folders and documents" in contents["description"]
    assert "鑾" not in tree["description"]
    assert "鑾" not in contents["description"]


def test_list_folder_tree_tool_returns_current_user_tree(monkeypatch) -> None:
    async def run() -> None:
        fake = FakeFolderService()
        monkeypatch.setattr(
            "app.services.tool_executor.FolderService", lambda: fake
        )
        executor = ToolExecutor(
            FakePageIndexService(), FakeDocumentService(), user_id="user-a"
        )

        result = await executor.execute("list_folder_tree", {})

        assert result["status"] == "success"
        assert fake.tree_calls == ["user-a"]
        assert result["data"]["folders"][0]["id"] == "folder-a"
        assert result["data"]["folders"][0]["children"][0]["id"] == "folder-child"

    asyncio.run(run())


def test_list_folder_contents_tool_returns_compact_documents_and_pagination(
    monkeypatch,
) -> None:
    async def run() -> None:
        fake = FakeFolderService()
        monkeypatch.setattr(
            "app.services.tool_executor.FolderService", lambda: fake
        )
        executor = ToolExecutor(
            FakePageIndexService(), FakeDocumentService(), user_id="user-a"
        )

        result = await executor.execute(
            "list_folder_contents",
            {"folder_id": "folder-a", "page": 2, "page_size": 1},
        )

        assert result["status"] == "success"
        assert fake.contents_calls == [("folder-a", 2, 1, "user-a")]
        assert result["data"]["page"] == 2
        assert result["data"]["documents"] == [
            {
                "doc_id": "doc-a",
                "doc_name": "a.pdf",
                "file_type": ".pdf",
                "status": "completed",
                "page_count": 3,
                "folder_path": "Projects",
                "description": "brief",
                "updated_at": "2026-06-10T00:00:00",
            }
        ]

    asyncio.run(run())


def test_list_folder_contents_returns_clear_error_for_invalid_scope(
    monkeypatch,
) -> None:
    async def run() -> None:
        fake = MissingFolderService()
        monkeypatch.setattr(
            "app.services.tool_executor.FolderService", lambda: fake
        )
        executor = ToolExecutor(
            FakePageIndexService(), FakeDocumentService(), user_id="user-a"
        )

        result = await executor.execute(
            "list_folder_contents",
            {"folder_id": "missing-folder"},
        )

        assert result == {
            "error": "工具 list_folder_contents 执行失败: Folder not found or access denied"
        }

    asyncio.run(run())


def test_folder_service_rejects_missing_folder_scope(tmp_path) -> None:
    async def run() -> None:
        db_path = tmp_path / "folders.db"
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
                    original_name TEXT NOT NULL,
                    file_type TEXT,
                    status TEXT,
                    page_count INTEGER,
                    folder_id TEXT,
                    folder_path TEXT,
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_id TEXT
                )
                """
            )
            await db.execute(
                """
                INSERT INTO folders (id, name, parent_id, path, user_id)
                VALUES ('folder-a', 'Projects', NULL, 'Projects', 'user-a')
                """
            )
            await db.commit()

        service = FolderService()
        service._db_path = str(db_path)

        try:
            await service.get_compact_folder_contents(
                folder_id="folder-a",
                user_id="user-b",
            )
        except ValueError as exc:
            assert str(exc) == "Folder not found or access denied"
        else:
            raise AssertionError("expected invalid folder scope to raise")

    asyncio.run(run())
