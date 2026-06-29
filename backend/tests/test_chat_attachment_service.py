import asyncio
import base64
from pathlib import Path
import sys

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import CHAT_ATTACHMENT_MAX_BYTES
from app.models.migrations import run_migrations
from app.services.chat_attachment_service import ChatAttachmentService


def _tiny_png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
    )


async def _db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
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
    await run_migrations(db)
    return db


def test_upload_image_persists_metadata_without_base64(tmp_path: Path) -> None:
    async def run() -> None:
        db = await _db()
        try:
            service = ChatAttachmentService(db, storage_dir=tmp_path)
            data = _tiny_png_bytes()

            saved = await service.save_upload(
                user_id="user-a",
                filename="screen.png",
                content_type="image/png",
                data=data,
            )

            assert saved["attachment_id"]
            assert saved["original_name"] == "screen.png"
            assert saved["mime_type"] == "image/png"
            assert saved["size_bytes"] == len(data)
            assert saved["width"] == 1
            assert saved["height"] == 1
            assert "base64" not in str(saved).lower()
            assert "data:image" not in str(saved).lower()
        finally:
            await db.close()

    asyncio.run(run())


def test_rejects_non_image_or_oversized_upload(tmp_path: Path) -> None:
    async def run() -> None:
        db = await _db()
        try:
            service = ChatAttachmentService(db, storage_dir=tmp_path)

            with pytest.raises(ValueError):
                await service.save_upload("user-a", "notes.txt", "text/plain", b"hello")
            with pytest.raises(ValueError):
                await service.save_upload(
                    "user-a",
                    "huge.png",
                    "image/png",
                    b"x" * (CHAT_ATTACHMENT_MAX_BYTES + 1),
                )
        finally:
            await db.close()

    asyncio.run(run())


def test_user_cannot_resolve_another_users_attachment(tmp_path: Path) -> None:
    async def run() -> None:
        db = await _db()
        try:
            service = ChatAttachmentService(db, storage_dir=tmp_path)
            saved = await service.save_upload(
                "user-a", "screen.png", "image/png", _tiny_png_bytes()
            )

            with pytest.raises(ValueError):
                await service.attachments_for_model("user-b", [saved["attachment_id"]])
        finally:
            await db.close()

    asyncio.run(run())


def test_bind_to_message_updates_attachment_owner_scope(tmp_path: Path) -> None:
    async def run() -> None:
        db = await _db()
        try:
            service = ChatAttachmentService(db, storage_dir=tmp_path)
            saved = await service.save_upload(
                "user-a", "screen.png", "image/png", _tiny_png_bytes()
            )

            bound = await service.bind_to_message(
                "user-a",
                [saved["attachment_id"]],
                conversation_id="conversation-a",
                message_id="message-a",
            )

            assert bound[0]["attachment_id"] == saved["attachment_id"]
            assert bound[0]["status"] == "bound"
            cursor = await db.execute(
                """
                SELECT conversation_id, message_id, status
                FROM chat_attachments
                WHERE attachment_id = ?
                """,
                (saved["attachment_id"],),
            )
            row = await cursor.fetchone()
            assert dict(row) == {
                "conversation_id": "conversation-a",
                "message_id": "message-a",
                "status": "bound",
            }
        finally:
            await db.close()

    asyncio.run(run())
