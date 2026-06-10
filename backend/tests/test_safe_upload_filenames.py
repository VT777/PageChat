import asyncio
from pathlib import Path
import shutil
import sys
import uuid

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import document_service as document_service_module
from app.services.document_service import DocumentService


async def _create_documents_table(db: aiosqlite.Connection) -> None:
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


def _test_documents_dir() -> Path:
    root = Path(__file__).resolve().parent / "tmp_upload_documents" / uuid.uuid4().hex
    root.mkdir(exist_ok=True)
    return root


def test_validate_file_rejects_path_like_or_reserved_names() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            service = DocumentService(db)

            bad_names = [
                "../secret.pdf",
                r"folder\secret.pdf",
                "folder/secret.pdf",
                "bad\x00name.pdf",
                "bad\nname.pdf",
                "CON.pdf",
                "NUL.txt",
            ]

            for filename in bad_names:
                is_valid, message = service.validate_file(filename, 10)
                assert not is_valid, filename
                assert message

    asyncio.run(run())


def test_validate_file_accepts_normal_unicode_display_name() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            service = DocumentService(db)

            is_valid, message = service.validate_file("项目计划.pdf", 10)

            assert is_valid
            assert message == ""

    asyncio.run(run())


def test_save_document_uses_generated_storage_name_and_keeps_display_name(
    monkeypatch,
) -> None:
    async def run() -> None:
        documents_dir = _test_documents_dir()
        try:
            monkeypatch.setattr(document_service_module, "DOCUMENTS_DIR", documents_dir)

            async with aiosqlite.connect(":memory:") as db:
                await _create_documents_table(db)
                service = DocumentService(db)
                monkeypatch.setattr(service, "generate_doc_id", lambda: "doc12345")

                saved = await service.save_document(
                    file_content=b"hello",
                    filename="项目计划.pdf",
                    file_size=5,
                    file_type=".pdf",
                    user_id="user-1",
                )

                expected_path = documents_dir / "doc12345.pdf"
                unsafe_path = documents_dir / "doc12345_项目计划.pdf"

                assert saved.name == "项目计划.pdf"
                assert saved.original_name == "项目计划.pdf"
                assert Path(saved.file_path) == expected_path
                assert expected_path.read_bytes() == b"hello"
                assert not unsafe_path.exists()
        finally:
            shutil.rmtree(documents_dir.parent, ignore_errors=True)

    asyncio.run(run())
