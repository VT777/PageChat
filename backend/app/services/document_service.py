import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiosqlite

from app.core.config import (
    ALLOWED_EXTENSIONS,
    DOCUMENTS_DIR,
    INDEXES_DIR,
    MAX_FILE_SIZE,
)
from app.models.schemas import DocumentResponse


class DocumentService:
    """文档服务 - 处理文档上传、管理和索引"""

    WINDOWS_RESERVED_NAMES = {
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

    def __init__(
        self,
        db: aiosqlite.Connection,
    ):
        self.db = db

    def generate_doc_id(self) -> str:
        """生成文档 ID"""
        return str(uuid.uuid4())[:8]

    def _normalize_upload_display_name(self, filename: str) -> str:
        if not filename:
            raise ValueError("文件名不能为空")
        if "\x00" in filename or any(ord(ch) < 32 for ch in filename):
            raise ValueError("文件名包含非法控制字符")
        if "/" in filename or "\\" in filename:
            raise ValueError("文件名不能包含路径分隔符")

        name = Path(filename).name.strip()
        if not name or name in {".", ".."}:
            raise ValueError("文件名无效")

        stem = Path(name).stem.upper()
        if stem in self.WINDOWS_RESERVED_NAMES:
            raise ValueError("文件名为系统保留名称")

        return name

    def validate_file(self, filename: str, file_size: int) -> tuple[bool, str]:
        """验证文件"""
        try:
            display_name = self._normalize_upload_display_name(filename)
        except ValueError as exc:
            return False, str(exc)
        # 检查文件扩展名
        ext = Path(display_name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"不支持的文件格式: {ext}"

        # 检查文件大小
        if file_size > MAX_FILE_SIZE:
            return False, f"文件大小超过限制 ({MAX_FILE_SIZE // 1024 // 1024}MB)"

        return True, ""

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    async def cleanup_document_artifacts(self, doc: DocumentResponse) -> None:
        """Remove source and index files for a document without touching the DB."""
        candidates = []
        if doc.file_path:
            candidates.append((Path(doc.file_path), DOCUMENTS_DIR))
        if doc.index_path:
            candidates.append((Path(doc.index_path), INDEXES_DIR))
        candidates.append((INDEXES_DIR / f"{doc.id}.json", INDEXES_DIR))

        seen = set()
        for path, root in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if not self._is_within(path, root):
                continue
            if path.exists() and path.is_file():
                path.unlink()

    async def save_document(
        self,
        file_content: bytes,
        filename: str,
        file_size: int,
        file_type: str,
        folder_id: str = None,
        folder_path: str = "",
        user_id: str = None,
    ) -> DocumentResponse:
        """保存上传的文档到指定文件夹"""
        doc_id = self.generate_doc_id()
        display_name = self._normalize_upload_display_name(filename)
        ext = Path(display_name).suffix.lower()

        # 保存文件
        file_path = DOCUMENTS_DIR / f"{doc_id}{ext}"
        with open(file_path, "wb") as f:
            f.write(file_content)

        # 插入数据库（包含 user_id）
        await self.db.execute(
            """
            INSERT INTO documents (id, name, original_name, file_path, file_size, file_type, status, folder_id, folder_path, user_id)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                doc_id,
                display_name,
                display_name,
                str(file_path),
                file_size,
                file_type,
                folder_id,
                folder_path,
                user_id,
            ),
        )
        await self.db.commit()

        # 返回文档信息（包含数据库生成的 created_at/updated_at）
        saved_doc = await self.get_document(doc_id)
        if saved_doc is not None:
            return saved_doc

        # 防御性兜底：若查询失败，仍返回满足响应契约的数据
        now = datetime.utcnow()
        return DocumentResponse(
            id=doc_id,
            name=display_name,
            original_name=display_name,
            file_path=str(file_path),
            file_size=file_size,
            file_type=file_type,
            status="pending",
            folder_id=folder_id,
            folder_path=folder_path,
            created_at=now,
            updated_at=now,
        )

    async def get_document(
        self, doc_id: str, user_id: str = None
    ) -> Optional[DocumentResponse]:
        """获取单个文档（支持用户隔离）"""
        query = """SELECT id, name, original_name, file_path, index_path, file_size, 
                      file_type, status, page_count, error_message, folder_id, folder_path, 
                      created_at, updated_at, processed_pages, description
               FROM documents WHERE id = ?"""
        params = [doc_id]

        # 如果提供了 user_id，添加用户隔离条件
        if user_id:
            query = query.replace("WHERE id = ?", "WHERE id = ? AND user_id = ?")
            params.append(user_id)

        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()

        if row:
            return DocumentResponse(
                id=row[0],
                name=row[1],
                original_name=row[2],
                file_path=row[3],
                index_path=row[4],
                file_size=row[5],
                file_type=row[6],
                status=row[7],
                page_count=row[8],
                error_message=row[9],
                folder_id=row[10],
                folder_path=row[11],
                created_at=row[12],
                updated_at=row[13],
                processed_pages=row[14] if row[14] is not None else None,
                description=row[15] if row[15] is not None else None,
            )
        return None

    async def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str = None,
        folder_id: str = None,
        folder_path: str = None,
        include_subfolders: bool = False,
        user_id: str = None,
    ) -> tuple[List[DocumentResponse], int]:
        """获取文档列表（支持文件夹筛选，按用户隔离）"""

        # 构建 WHERE 子句
        conditions = []
        params = []

        # 用户隔离：只查询当前用户的文档
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)

        # 文件夹筛选
        # folder_id 可能是 None 或空字符串（取决于前端/网关如何传参）
        normalized_folder_id = (
            folder_id if folder_id not in ("", "null", "undefined") else None
        )

        if normalized_folder_id:
            conditions.append("folder_id = ?")
            params.append(normalized_folder_id)
        elif not include_subfolders:
            # 未指定文件夹且不包含子文件夹时，只查询根目录文档
            conditions.append("folder_id IS NULL")

        if include_subfolders and folder_path:
            # 包含子文件夹：使用路径前缀匹配
            conditions.append("(folder_path = ? OR folder_path LIKE ?)")
            params.extend([folder_path, f"{folder_path}/%"])

        # 搜索条件
        if search:
            conditions.append("(original_name LIKE ? OR name LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # 获取总数
        count_query = f"SELECT COUNT(*) FROM documents {where_clause}"
        cursor = await self.db.execute(count_query, params)
        total_row = await cursor.fetchone()
        total = total_row[0] if total_row else 0

        # 获取列表
        offset = (page - 1) * page_size
        query = f"""
            SELECT id, name, original_name, file_path, index_path, file_size, 
                   file_type, status, page_count, error_message, folder_id, folder_path, 
                   created_at, updated_at, processed_pages, description, last_reindex_at
            FROM documents 
            {where_clause}
            ORDER BY updated_at DESC 
            LIMIT ? OFFSET ?
        """
        params.extend([page_size, offset])

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()

        items = [
            DocumentResponse(
                id=row[0],
                name=row[1],
                original_name=row[2],
                file_path=row[3],
                index_path=row[4],
                file_size=row[5],
                file_type=row[6],
                status=row[7],
                page_count=row[8],
                error_message=row[9],
                folder_id=row[10],
                folder_path=row[11],
                created_at=row[12],
                updated_at=row[13],
                processed_pages=row[14] if row[14] is not None else None,
                description=row[15] if row[15] is not None else None,
                last_reindex_at=row[16] if row[16] is not None else None,
            )
            for row in rows
        ]

        return items, total

    async def update_document_status(
        self,
        doc_id: str,
        status: str,
        index_path: str = None,
        page_count: int = None,
        error_message: str = None,
    ):
        """更新文档状态"""
        query = "UPDATE documents SET status = ?, updated_at = CURRENT_TIMESTAMP"
        params = [status]

        if index_path:
            query += ", index_path = ?"
            params.append(index_path)

        if page_count is not None:
            query += ", page_count = ?"
            params.append(page_count)

        if error_message:
            query += ", error_message = ?"
            params.append(error_message)

        query += " WHERE id = ?"
        params.append(doc_id)

        await self.db.execute(query, params)
        await self.db.commit()

        # 文档元数据变更时清除所有会话缓存
        if status in ("completed", "failed:indexing", "deleted"):
            from app.services.agent_service import clear_conversation_cache

            clear_conversation_cache()

    async def move_document(
        self, doc_id: str, folder_id: Optional[str], user_id: str = None
    ) -> bool:
        """移动文档到指定文件夹（支持用户隔离）"""
        doc = await self.get_document(doc_id, user_id=user_id)
        if not doc:
            raise ValueError("文档不存在或无权访问")

        # 获取目标文件夹信息
        folder_path = ""
        if folder_id:
            from app.services.folder_service import FolderService

            folder_service = FolderService(self.db)
            folder = await folder_service.get_folder(folder_id, user_id=user_id)
            if not folder:
                raise ValueError("目标文件夹不存在")
            folder_path = folder.path

        try:
            query = "UPDATE documents SET folder_id = ?, folder_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
            params = [folder_id, folder_path, doc_id]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            await self.db.execute(query, params)
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            # 唯一约束冲突 - 目标文件夹中已存在同名文件
            raise ValueError("目标文件夹中已存在同名文件")

    async def rename_document(
        self, doc_id: str, new_name: str, user_id: str = None
    ) -> bool:
        """重命名文档（支持用户隔离）"""
        # 获取当前文档信息
        doc = await self.get_document(doc_id, user_id=user_id)
        if not doc:
            raise ValueError("文档不存在或无权访问")

        # 检查新名称是否合法
        if not new_name or not new_name.strip():
            raise ValueError("文档名称不能为空")

        # 检查是否包含非法字符
        if "/" in new_name or "\\" in new_name:
            raise ValueError("文档名称不能包含 / 或 \\")

        # 获取文件的扩展名
        original_name = doc.original_name
        if "." in original_name:
            ext = original_name.rsplit(".", 1)[1]
            # 确保新名称也有相同的扩展名
            if "." not in new_name:
                new_name = f"{new_name}.{ext}"

        try:
            query = "UPDATE documents SET original_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
            params = [new_name, doc_id]
            if user_id:
                query += " AND user_id = ?"
                params.append(user_id)
            await self.db.execute(query, params)
            await self.db.commit()
            return True
        except aiosqlite.IntegrityError:
            # 唯一约束冲突 - 同一文件夹中已存在同名文件
            raise ValueError("该文件夹中已存在同名文件")

    async def delete_document(self, doc_id: str, user_id: str = None) -> bool:
        """删除文档（支持用户隔离）"""
        # 检查文档是否存在（带用户权限验证）
        doc = await self.get_document(doc_id, user_id)
        if not doc:
            return False

        await self.cleanup_document_artifacts(doc)

        # 删除数据库记录（带用户权限验证）
        if user_id:
            cursor = await self.db.execute(
                "DELETE FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id)
            )
        else:
            cursor = await self.db.execute(
                "DELETE FROM documents WHERE id = ?", (doc_id,)
            )
        await self.db.commit()

        # 删除文档后清除所有会话缓存
        from app.services.agent_service import clear_conversation_cache
        from app.services.cache_service import cache_service

        cache_service.clear_document(user_id or "", doc_id)
        clear_conversation_cache()

        return cursor.rowcount > 0

    async def get_indexed_documents(
        self, user_id: str = None
    ) -> List[DocumentResponse]:
        """获取已索引的文档列表（支持用户隔离）"""
        query = "SELECT * FROM documents WHERE status = 'completed'"
        params = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        query += " ORDER BY created_at DESC"
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()

        return [
            DocumentResponse(
                id=row[0],
                name=row[1],
                original_name=row[2],
                file_path=row[3],
                index_path=row[4],
                file_size=row[5],
                file_type=row[6],
                status=row[7],
                page_count=row[8],
                error_message=row[9],
                created_at=row[10],
                updated_at=row[11],
                processed_pages=row[12] if row[12] is not None else None,
                folder_id=row[13],
                folder_path=row[14],
                description=row[15] if row[15] is not None else None,
            )
            for row in rows
        ]

