import asyncio
import json
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from app.services.conversation_evidence_repository import (  # noqa: E402
    ConversationEvidenceRepository,
)
from phase0_chat_helpers import create_chat_history_schema  # noqa: E402


async def _setup_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    await create_chat_history_schema(db)
    await run_migrations(db)
    await db.execute(
        """
        INSERT INTO conversations (id, title, user_id)
        VALUES ('conv-evidence', 'Evidence', 'user-a')
        """
    )
    await db.execute(
        """
        INSERT INTO documents (
            id, name, original_name, file_path, file_type, status, updated_at, user_id
        )
        VALUES (
            'doc-alpha', 'alpha.pdf', 'alpha.pdf', '/tmp/alpha.pdf', 'pdf',
            'completed', '2026-06-26 10:00:00', 'user-a'
        )
        """
    )
    await db.commit()
    return db


def test_repository_records_compact_page_evidence_without_large_payloads() -> None:
    async def run() -> None:
        db = await _setup_db()
        try:
            repo = ConversationEvidenceRepository(db)
            await repo.record_tool_result(
                conversation_id="conv-evidence",
                run_id="run-alpha",
                tool_name="get_page_content",
                tool_arguments={"doc_id": "doc-alpha", "pages": "2"},
                compact_result={
                    "doc_id": "doc-alpha",
                    "doc_name": "alpha.pdf",
                    "items": [
                        {
                            "page": 2,
                            "text": "重庆师范大学创新实践证据。",
                            "page_image_base64": "must-not-store",
                        }
                    ],
                    "citations": [
                        {
                            "citation_key": "doc-alpha:p2",
                            "document_id": "doc-alpha",
                            "document_name": "alpha.pdf",
                            "source_anchor": {"format": "pdf", "start_page": 2},
                            "display_label": "alpha.pdf p.2",
                            "preview_kind": "pdf",
                        }
                    ],
                },
                scope_key="scope-alpha",
            )

            evidence = await repo.list_relevant(
                conversation_id="conv-evidence",
                scope_key="scope-alpha",
                question="有哪些创新实践？",
                limit=5,
            )
        finally:
            await db.close()

        serialized = json.dumps(evidence, ensure_ascii=False)
        assert len(evidence) == 1
        assert evidence[0]["tool_name"] == "get_page_content"
        assert evidence[0]["arguments"] == {"doc_id": "doc-alpha", "pages": "2"}
        assert evidence[0]["doc_id"] == "doc-alpha"
        assert evidence[0]["doc_name"] == "alpha.pdf"
        assert evidence[0]["page"] == 2
        assert evidence[0]["snippet"] == "重庆师范大学创新实践证据。"
        assert evidence[0]["citations"][0]["display_label"] == "alpha.pdf p.2"
        assert "must-not-store" not in serialized
        assert "page_image_base64" not in serialized

    asyncio.run(run())


def test_repository_invalidates_document_evidence_after_reparse() -> None:
    async def run() -> None:
        db = await _setup_db()
        try:
            repo = ConversationEvidenceRepository(db)
            await repo.record_tool_result(
                conversation_id="conv-evidence",
                run_id="run-alpha",
                tool_name="search_within_document",
                tool_arguments={"doc_id": "doc-alpha", "query": "创新"},
                compact_result={
                    "items": [
                        {
                            "doc_id": "doc-alpha",
                            "document_name": "alpha.pdf",
                            "page": 3,
                            "snippet": "旧索引中的命中。",
                        }
                    ]
                },
                scope_key="scope-alpha",
            )
            await db.execute(
                "UPDATE documents SET updated_at = '2026-06-26 11:00:00' WHERE id = 'doc-alpha'"
            )
            await db.commit()

            evidence = await repo.list_relevant(
                conversation_id="conv-evidence",
                scope_key="scope-alpha",
                question="创新",
                limit=5,
            )
        finally:
            await db.close()

        assert evidence == []

    asyncio.run(run())


def test_repository_deletes_evidence_for_removed_conversation() -> None:
    async def run() -> None:
        db = await _setup_db()
        try:
            repo = ConversationEvidenceRepository(db)
            await repo.record_tool_result(
                conversation_id="conv-evidence",
                run_id="run-alpha",
                tool_name="browse_documents",
                tool_arguments={"query": "创新"},
                compact_result={
                    "summary": "Found one document.",
                    "items": [{"document_id": "doc-alpha", "document_name": "alpha.pdf"}],
                },
                scope_key="scope-alpha",
            )
            await repo.delete_for_conversation("conv-evidence")
            cursor = await db.execute("SELECT COUNT(*) FROM conversation_evidence")
            row = await cursor.fetchone()
        finally:
            await db.close()

        assert row[0] == 0

    asyncio.run(run())
