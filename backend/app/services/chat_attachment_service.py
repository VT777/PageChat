from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import re
import uuid
from typing import Any

import aiofiles
import aiosqlite
from PIL import Image, UnidentifiedImageError

from app.core.config import (
    CHAT_ATTACHMENT_ALLOWED_MIME_TYPES,
    CHAT_ATTACHMENT_MAX_BYTES,
    CHAT_ATTACHMENT_MAX_PER_MESSAGE,
    CHAT_ATTACHMENTS_DIR,
)


_MIME_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class ChatAttachmentService:
    def __init__(
        self,
        db: aiosqlite.Connection,
        storage_dir: Path | str = CHAT_ATTACHMENTS_DIR,
    ) -> None:
        self.db = db
        self.storage_dir = Path(storage_dir)

    async def save_upload(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> dict[str, Any]:
        user_id = self._require_user_id(user_id)
        mime_type = self._validate_mime_type(content_type)
        self._validate_size(data)
        width, height = self._validate_image(data)

        attachment_id = uuid.uuid4().hex
        original_name = Path(filename or "image").name or "image"
        stored_path = self._storage_path(user_id, attachment_id, mime_type)
        stored_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(stored_path, "wb") as handle:
            await handle.write(data)

        await self.db.execute(
            """
            INSERT INTO chat_attachments (
                attachment_id,
                user_id,
                original_name,
                stored_path,
                mime_type,
                size_bytes,
                width,
                height,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'uploaded')
            """,
            (
                attachment_id,
                user_id,
                original_name,
                str(stored_path),
                mime_type,
                len(data),
                width,
                height,
            ),
        )
        await self.db.commit()

        return await self.get_attachment(user_id, attachment_id)

    async def get_attachment(self, user_id: str, attachment_id: str) -> dict[str, Any]:
        row = await self._fetch_owned_row(user_id, attachment_id)
        return self._public_metadata(row)

    async def content_path_for_user(self, user_id: str, attachment_id: str) -> Path:
        row = await self._fetch_owned_row(user_id, attachment_id)
        path = Path(row["stored_path"])
        if not path.exists():
            raise ValueError("attachment content not found")
        return path

    async def delete_unbound_attachment(self, user_id: str, attachment_id: str) -> bool:
        row = await self._fetch_owned_row(user_id, attachment_id)
        if row["status"] != "uploaded" or row["message_id"]:
            return False

        path = Path(row["stored_path"])
        await self.db.execute(
            """
            DELETE FROM chat_attachments
            WHERE attachment_id = ? AND user_id = ? AND status = 'uploaded'
            """,
            (attachment_id, user_id),
        )
        await self.db.commit()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return True

    async def bind_to_message(
        self,
        user_id: str,
        attachment_ids: list[str] | None,
        conversation_id: str,
        message_id: str,
    ) -> list[dict[str, Any]]:
        rows = await self._fetch_rows_for_request(user_id, attachment_ids)
        if not rows:
            return []

        now_sql = "CURRENT_TIMESTAMP"
        for row in rows:
            if row["status"] != "uploaded" and row["message_id"] != message_id:
                raise ValueError("attachment is already bound")
            await self.db.execute(
                f"""
                UPDATE chat_attachments
                SET conversation_id = ?,
                    message_id = ?,
                    status = 'bound',
                    updated_at = {now_sql}
                WHERE attachment_id = ? AND user_id = ?
                """,
                (conversation_id, message_id, row["attachment_id"], user_id),
            )
        await self.db.commit()

        rebound = []
        for row in rows:
            rebound.append(await self.get_attachment(user_id, row["attachment_id"]))
        return rebound

    async def attachments_for_model(
        self,
        user_id: str,
        attachment_ids: list[str] | None,
    ) -> list[dict[str, Any]]:
        rows = await self._fetch_rows_for_request(user_id, attachment_ids)
        payloads: list[dict[str, Any]] = []
        for row in rows:
            path = Path(row["stored_path"])
            if not path.exists():
                raise ValueError("attachment content not found")
            async with aiofiles.open(path, "rb") as handle:
                data = await handle.read()
            payloads.append(
                {
                    "attachment_id": row["attachment_id"],
                    "original_name": row["original_name"],
                    "mime_type": row["mime_type"],
                    "data_base64": base64.b64encode(data).decode("ascii"),
                    "width": row["width"],
                    "height": row["height"],
                }
            )
        return payloads

    async def _fetch_rows_for_request(
        self,
        user_id: str,
        attachment_ids: list[str] | None,
    ) -> list[aiosqlite.Row]:
        user_id = self._require_user_id(user_id)
        clean_ids = list(dict.fromkeys(attachment_ids or []))
        if len(clean_ids) > CHAT_ATTACHMENT_MAX_PER_MESSAGE:
            raise ValueError("too many attachments")
        if not clean_ids:
            return []

        rows = [await self._fetch_owned_row(user_id, item) for item in clean_ids]
        return rows

    async def _fetch_owned_row(
        self,
        user_id: str,
        attachment_id: str,
    ) -> aiosqlite.Row:
        user_id = self._require_user_id(user_id)
        if not attachment_id:
            raise ValueError("attachment_id is required")
        cursor = await self.db.execute(
            """
            SELECT
                attachment_id,
                user_id,
                conversation_id,
                message_id,
                original_name,
                stored_path,
                mime_type,
                size_bytes,
                width,
                height,
                status,
                created_at,
                updated_at
            FROM chat_attachments
            WHERE attachment_id = ? AND user_id = ?
            """,
            (attachment_id, user_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ValueError("attachment not found")
        return row

    def _storage_path(self, user_id: str, attachment_id: str, mime_type: str) -> Path:
        extension = _MIME_EXTENSIONS[mime_type]
        return self.storage_dir / self._safe_user_dir(user_id) / f"{attachment_id}{extension}"

    @staticmethod
    def _public_metadata(row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "attachment_id": row["attachment_id"],
            "original_name": row["original_name"],
            "mime_type": row["mime_type"],
            "size_bytes": row["size_bytes"],
            "width": row["width"],
            "height": row["height"],
            "status": row["status"],
            "conversation_id": row["conversation_id"],
            "message_id": row["message_id"],
            "content_url": f"/api/chat/attachments/{row['attachment_id']}/content",
        }

    @staticmethod
    def _require_user_id(user_id: str) -> str:
        if not user_id or not str(user_id).strip():
            raise ValueError("user_id is required")
        return str(user_id)

    @staticmethod
    def _validate_mime_type(content_type: str) -> str:
        mime_type = (content_type or "").split(";")[0].strip().lower()
        if mime_type not in CHAT_ATTACHMENT_ALLOWED_MIME_TYPES:
            raise ValueError("unsupported image type")
        return mime_type

    @staticmethod
    def _validate_size(data: bytes) -> None:
        if not data:
            raise ValueError("attachment is empty")
        if len(data) > CHAT_ATTACHMENT_MAX_BYTES:
            raise ValueError("attachment is too large")

    @staticmethod
    def _validate_image(data: bytes) -> tuple[int, int]:
        try:
            with Image.open(BytesIO(data)) as image:
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("invalid image data") from exc
        return width, height

    @staticmethod
    def _safe_user_dir(user_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", user_id).strip("._")
        return safe or "user"
