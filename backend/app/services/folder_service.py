import aiosqlite
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Tuple
from app.core.config import DATA_DIR
from app.models.schemas import FolderResponse, FolderTreeResponse
from app.services.cache_service import cache_service
from app.services.document_service import DocumentService

DB_PATH = DATA_DIR / "knowclaw.db"


class FolderService:
    def __init__(self, db: aiosqlite.Connection = None):
        self.db = db
        self._db_path = str(DB_PATH)

    def _validate_folder_name(self, name: str) -> None:
        """验证文件夹名称（防御性检查）"""
        if not name or not name.strip():
            raise ValueError("文件夹名称不能为空")
        if len(name) > 255:
            raise ValueError("文件夹名称不能超过255个字符")
        if "/" in name or "\\" in name or "\x00" in name:
            raise ValueError("文件夹名称不能包含 /, \\ 或空字符")
        # Check for reserved names (Windows)
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        if name.upper() in reserved:
            raise ValueError(f'"{name}" 是保留名称，不能使用')

    def _generate_id(self) -> str:
        return str(uuid.uuid4())[:8]

    def _build_path(self, name: str, parent_path: str = "") -> str:
        """构建完整路径"""
        if parent_path:
            return f"{parent_path}/{name}"
        return name

    async def create_folder(
        self, name: str, parent_id: Optional[str] = None, user_id: str = None
    ) -> FolderResponse:
        """创建文件夹（关联到用户）"""
        self._validate_folder_name(name)
        folder_id = self._generate_id()

        async with aiosqlite.connect(self._db_path) as db:
            try:
                await db.execute("BEGIN")

                parent_path = ""
                if parent_id:
                    query = "SELECT path FROM folders WHERE id = ?"
                    params = [parent_id]
                    if user_id:
                        query += " AND user_id = ?"
                        params.append(user_id)
                    cursor = await db.execute(query, params)
                    row = await cursor.fetchone()
                    if row:
                        parent_path = row[0]
                    else:
                        await db.execute("ROLLBACK")
                        raise ValueError("父文件夹不存在或无权访问")

                path = self._build_path(name, parent_path)

                query = "SELECT id FROM folders WHERE path = ?"
                params = [path]
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                else:
                    query += " AND user_id IS NULL"
                cursor = await db.execute(query, params)
                if await cursor.fetchone():
                    await db.execute("ROLLBACK")
                    raise ValueError(f"Folder '{path}' already exists")

                await db.execute(
                    """INSERT INTO folders (id, name, parent_id, path, user_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                    (folder_id, name, parent_id, path, user_id),
                )
                await db.execute("COMMIT")
                return await self.get_folder(folder_id, user_id=user_id)
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def get_folder(
        self, folder_id: str, user_id: str = None
    ) -> Optional[FolderResponse]:
        """获取单个文件夹（可选按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            query = "SELECT id, name, parent_id, path, created_at, updated_at FROM folders WHERE id = ?"
            params = [folder_id]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            if row:
                return FolderResponse(
                    id=row[0],
                    name=row[1],
                    parent_id=row[2],
                    path=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                )
            return None

    async def list_folders(
        self, parent_id: Optional[str] = None, user_id: str = None
    ) -> List[FolderResponse]:
        """列出文件夹（平级，按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            if parent_id:
                query = (
                    "SELECT id, name, parent_id, path, created_at, updated_at "
                    "FROM folders WHERE parent_id = ?"
                )
                params = [parent_id]
            else:
                query = (
                    "SELECT id, name, parent_id, path, created_at, updated_at "
                    "FROM folders WHERE parent_id IS NULL"
                )
                params = []

            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            else:
                query += " AND user_id IS NULL"
            query += " ORDER BY name"

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [
                FolderResponse(
                    id=row[0],
                    name=row[1],
                    parent_id=row[2],
                    path=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                )
                for row in rows
            ]

    async def get_folder_tree(self, user_id: str = None) -> List[FolderTreeResponse]:
        """获取完整的文件夹树（按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            query = (
                "SELECT id, name, parent_id, path, created_at, updated_at FROM folders"
            )
            params = []
            if user_id:
                query += " WHERE user_id = ?"
                params.append(user_id)
            else:
                query += " WHERE user_id IS NULL"
            query += " ORDER BY path"

            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()

            folders = {}
            for row in rows:
                folder = FolderTreeResponse(
                    id=row[0],
                    name=row[1],
                    parent_id=row[2],
                    path=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    children=[],
                )
                folders[row[0]] = folder

            root_folders = []
            for folder in folders.values():
                if folder.parent_id and folder.parent_id in folders:
                    folders[folder.parent_id].children.append(folder)
                else:
                    root_folders.append(folder)
            return root_folders

    async def rename_folder(
        self, folder_id: str, new_name: str, user_id: str = None
    ) -> FolderResponse:
        """重命名文件夹（按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            try:
                await db.execute("BEGIN")

                query = "SELECT parent_id, path FROM folders WHERE id = ?"
                params = [folder_id]
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                cursor = await db.execute(query, params)
                row = await cursor.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    raise ValueError("Folder not found or access denied")

                parent_id, old_path = row
                if "/" in old_path:
                    parent_path = old_path.rsplit("/", 1)[0]
                    new_path = f"{parent_path}/{new_name}"
                else:
                    new_path = new_name

                check_query = "SELECT id FROM folders WHERE path = ? AND id != ?"
                check_params = [new_path, folder_id]
                if user_id:
                    check_query += " AND user_id = ?"
                    check_params.append(user_id)
                else:
                    check_query += " AND user_id IS NULL"
                cursor = await db.execute(check_query, check_params)
                if await cursor.fetchone():
                    await db.execute("ROLLBACK")
                    raise ValueError(f"Folder '{new_path}' already exists")

                update_query = (
                    "UPDATE folders SET name = ?, path = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?"
                )
                update_params = [new_name, new_path, folder_id]
                if user_id:
                    update_query += " AND user_id = ?"
                    update_params.append(user_id)
                await db.execute(update_query, update_params)

                await self._update_child_paths(db, old_path, new_path, user_id)

                doc_query = (
                    "UPDATE documents SET folder_path = ? || SUBSTR(folder_path, ?) "
                    "WHERE folder_path LIKE ?"
                )
                doc_params = [new_path, len(old_path) + 1, f"{old_path}/%"]
                if user_id:
                    doc_query += " AND user_id = ?"
                    doc_params.append(user_id)
                await db.execute(doc_query, doc_params)

                await db.execute("COMMIT")
                return await self.get_folder(folder_id, user_id=user_id)
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def _update_child_paths(
        self,
        db: aiosqlite.Connection,
        old_parent: str,
        new_parent: str,
        user_id: str = None,
    ):
        """递归更新子文件夹路径（按用户过滤）"""
        query = "SELECT id, path FROM folders WHERE path LIKE ?"
        params = [f"{old_parent}/%"]
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        else:
            query += " AND user_id IS NULL"
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        for row in rows:
            child_id, old_path = row
            new_path = new_parent + old_path[len(old_parent) :]
            await db.execute(
                "UPDATE folders SET path = ? WHERE id = ?", (new_path, child_id)
            )

    async def move_folder(
        self, folder_id: str, new_parent_id: Optional[str], user_id: str = None
    ) -> FolderResponse:
        """移动文件夹（按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            query = "SELECT name, path FROM folders WHERE id = ?"
            params = [folder_id]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            if not row:
                raise ValueError("Folder not found or access denied")

            name, old_path = row

            if new_parent_id and new_parent_id != "null":
                if await self._is_descendant(db, folder_id, new_parent_id, user_id):
                    raise ValueError("Cannot move folder into its own subfolder")

                parent_query = "SELECT path FROM folders WHERE id = ?"
                parent_params = [new_parent_id]
                if user_id:
                    parent_query += " AND user_id = ?"
                    parent_params.append(user_id)
                cursor = await db.execute(parent_query, parent_params)
                parent_row = await cursor.fetchone()
                if not parent_row:
                    raise ValueError("Parent folder not found or access denied")
                new_path = f"{parent_row[0]}/{name}"
            else:
                new_path = name

            check_query = "SELECT id FROM folders WHERE path = ? AND id != ?"
            check_params = [new_path, folder_id]
            if user_id:
                check_query += " AND user_id = ?"
                check_params.append(user_id)
            else:
                check_query += " AND user_id IS NULL"
            cursor = await db.execute(check_query, check_params)
            if await cursor.fetchone():
                raise ValueError(f"Folder '{new_path}' already exists")

            try:
                await db.execute("BEGIN")

                update_query = (
                    "UPDATE folders SET parent_id = ?, path = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?"
                )
                update_params = [new_parent_id, new_path, folder_id]
                if user_id:
                    update_query += " AND user_id = ?"
                    update_params.append(user_id)
                await db.execute(update_query, update_params)

                await self._update_child_paths(db, old_path, new_path, user_id)

                doc_query = (
                    "UPDATE documents SET folder_path = ? || SUBSTR(folder_path, ?) "
                    "WHERE folder_path LIKE ?"
                )
                doc_params = [new_path, len(old_path) + 1, f"{old_path}/%"]
                if user_id:
                    doc_query += " AND user_id = ?"
                    doc_params.append(user_id)
                await db.execute(doc_query, doc_params)

                await db.execute("COMMIT")
                return await self.get_folder(folder_id, user_id=user_id)
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def _is_descendant(
        self,
        db: aiosqlite.Connection,
        ancestor_id: str,
        descendant_id: str,
        user_id: str = None,
    ) -> bool:
        """检查 descendant_id 是否是 ancestor_id 的后代"""
        current_id = descendant_id
        while current_id:
            query = "SELECT parent_id FROM folders WHERE id = ?"
            params = [current_id]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
            if not row or not row[0]:
                return False
            if row[0] == ancestor_id:
                return True
            current_id = row[0]
        return False

    async def delete_folder(self, folder_id: str, user_id: str = None) -> bool:
        """删除文件夹（递归删除所有内容，按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            try:
                await db.execute("BEGIN")

                query = "SELECT path FROM folders WHERE id = ?"
                params = [folder_id]
                if user_id:
                    query += " AND user_id = ?"
                    params.append(user_id)
                cursor = await db.execute(query, params)
                row = await cursor.fetchone()
                if not row:
                    await db.execute("ROLLBACK")
                    return False

                path = row[0]

                child_query = "SELECT id FROM folders WHERE path LIKE ?"
                child_params = [f"{path}/%"]
                if user_id:
                    child_query += " AND user_id = ?"
                    child_params.append(user_id)
                else:
                    child_query += " AND user_id IS NULL"
                cursor = await db.execute(child_query, child_params)
                child_ids = [row[0] for row in await cursor.fetchall()]
                all_ids = [folder_id] + child_ids

                placeholders = ",".join("?" for _ in all_ids)
                docs_query = f"""
                    SELECT id, name, original_name, file_path, index_path, file_size,
                           file_type, status, page_count, processed_pages, error_message,
                           folder_id, folder_path, description, user_id, created_at, updated_at
                    FROM documents
                    WHERE folder_id IN ({placeholders})
                """
                docs_params = list(all_ids)
                if user_id:
                    docs_query += " AND user_id = ?"
                    docs_params.append(user_id)
                else:
                    docs_query += " AND user_id IS NULL"
                cursor = await db.execute(docs_query, docs_params)
                document_rows = await cursor.fetchall()
                documents = [
                    SimpleNamespace(
                        id=row[0],
                        name=row[1],
                        original_name=row[2],
                        file_path=row[3],
                        index_path=row[4],
                        file_size=row[5],
                        file_type=row[6],
                        status=row[7],
                        page_count=row[8],
                        processed_pages=row[9],
                        error_message=row[10],
                        folder_id=row[11],
                        folder_path=row[12],
                        description=row[13],
                        user_id=row[14],
                        created_at=row[15],
                        updated_at=row[16],
                    )
                    for row in document_rows
                ]

                document_service = DocumentService(db)
                for doc in documents:
                    await document_service.cleanup_document_artifacts(doc)
                    cache_service.clear_document(doc.user_id or user_id or "", doc.id)

                for fid in all_ids:
                    doc_query = "DELETE FROM documents WHERE folder_id = ?"
                    doc_params = [fid]
                    if user_id:
                        doc_query += " AND user_id = ?"
                        doc_params.append(user_id)
                    await db.execute(doc_query, doc_params)

                for fid in reversed(all_ids):
                    folder_query = "DELETE FROM folders WHERE id = ?"
                    folder_params = [fid]
                    if user_id:
                        folder_query += " AND user_id = ?"
                        folder_params.append(user_id)
                    await db.execute(folder_query, folder_params)

                await db.execute("COMMIT")
                from app.services.agent_service import clear_conversation_cache

                clear_conversation_cache()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def get_folder_contents(
        self,
        folder_id: Optional[str],
        page: int = 1,
        page_size: int = 20,
        user_id: str = None,
    ) -> Tuple[List[dict], int]:
        """获取文件夹内容（文档列表，按用户过滤）"""
        async with aiosqlite.connect(self._db_path) as db:
            if folder_id:
                folder_query = "SELECT id, name, path, created_at, updated_at FROM folders WHERE parent_id = ?"
                folder_params = [folder_id]
            else:
                folder_query = "SELECT id, name, path, created_at, updated_at FROM folders WHERE parent_id IS NULL"
                folder_params = []

            if user_id:
                folder_query += " AND user_id = ?"
                folder_params.append(user_id)
            else:
                folder_query += " AND user_id IS NULL"
            folder_query += " ORDER BY name"
            cursor = await db.execute(folder_query, folder_params)
            folders = await cursor.fetchall()

            offset = (page - 1) * page_size
            if folder_id:
                count_query = "SELECT COUNT(*) FROM documents WHERE folder_id = ?"
                count_params = [folder_id]
                doc_query = (
                    "SELECT id, name, original_name, file_path, index_path, file_size, "
                    "file_type, status, page_count, processed_pages, error_message, "
                    "created_at, updated_at FROM documents WHERE folder_id = ?"
                )
                doc_params = [folder_id]
            else:
                count_query = "SELECT COUNT(*) FROM documents WHERE folder_id IS NULL"
                count_params = []
                doc_query = (
                    "SELECT id, name, original_name, file_path, index_path, file_size, "
                    "file_type, status, page_count, processed_pages, error_message, "
                    "created_at, updated_at FROM documents WHERE folder_id IS NULL"
                )
                doc_params = []

            if user_id:
                count_query += " AND user_id = ?"
                count_params.append(user_id)
                doc_query += " AND user_id = ?"
                doc_params.append(user_id)
            else:
                count_query += " AND user_id IS NULL"
                doc_query += " AND user_id IS NULL"

            cursor = await db.execute(count_query, count_params)
            total = (await cursor.fetchone())[0]

            doc_query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            doc_params.extend([page_size, offset])
            cursor = await db.execute(doc_query, doc_params)
            documents = await cursor.fetchall()

            contents = []
            for row in folders:
                contents.append(
                    {
                        "type": "folder",
                        "id": row[0],
                        "name": row[1],
                        "path": row[2],
                        "created_at": row[3],
                        "updated_at": row[4],
                    }
                )

            for row in documents:
                contents.append(
                    {
                        "type": "document",
                        "id": row[0],
                        "name": row[1],
                        "original_name": row[2],
                        "file_path": row[3],
                        "index_path": row[4],
                        "file_size": row[5],
                        "file_type": row[6],
                        "status": row[7],
                        "page_count": row[8],
                        "processed_pages": row[9],
                        "error_message": row[10],
                        "created_at": row[11],
                        "updated_at": row[12],
                    }
                )

            return contents, total
