import asyncio
from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import DocumentResponse
from app.services.tool_executor import ToolExecutor


def _doc(doc_id: str, user_id: str, name: str | None = None) -> DocumentResponse:
    return DocumentResponse(
        id=doc_id,
        name=name or f"{doc_id}.pdf",
        original_name=name or f"{doc_id}.pdf",
        file_path=f"/tmp/{doc_id}.pdf",
        file_size=10,
        file_type=".pdf",
        status="completed",
        page_count=1,
        processed_pages=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class FakeDocumentService:
    def __init__(self) -> None:
        self.owners = {"doc-a": "user-a", "doc-b": "user-b"}
        self.docs = {
            "doc-a": _doc("doc-a", "user-a", "alpha.pdf"),
            "doc-b": _doc("doc-b", "user-b", "beta.pdf"),
        }
        self.get_document_calls: list[tuple[str, str | None]] = []
        self.get_indexed_documents_calls: list[str | None] = []

    async def get_document(self, doc_id: str, user_id: str | None = None):
        self.get_document_calls.append((doc_id, user_id))
        if self.owners.get(doc_id) != user_id:
            return None
        return self.docs.get(doc_id)

    async def get_indexed_documents(self, user_id: str | None = None):
        self.get_indexed_documents_calls.append(user_id)
        return [
            doc
            for doc_id, doc in self.docs.items()
            if self.owners.get(doc_id) == user_id
        ]


class FakePageIndexService:
    def __init__(self) -> None:
        self.load_index_calls: list[str] = []

    async def load_index(self, doc_id: str):
        self.load_index_calls.append(doc_id)
        return {
            "structure": [
                {
                    "node_id": "n1",
                    "title": "Intro",
                    "start_index": 1,
                    "end_index": 1,
                    "summary": "Summary",
                }
            ]
        }


def test_tool_executor_requires_user_id() -> None:
    with pytest.raises(ValueError, match="user_id"):
        ToolExecutor(FakePageIndexService(), FakeDocumentService())


def test_get_document_structure_rejects_other_users_document() -> None:
    async def run() -> None:
        docs = FakeDocumentService()
        index = FakePageIndexService()
        executor = ToolExecutor(index, docs, user_id="user-a")

        result = await executor.execute(
            "get_document_structure", {"doc_id": "doc-b"}
        )

        assert "error" in result
        assert docs.get_document_calls == [("doc-b", "user-a")]
        assert index.load_index_calls == []

    asyncio.run(run())


def test_list_documents_returns_current_users_documents_only() -> None:
    async def run() -> None:
        docs = FakeDocumentService()
        executor = ToolExecutor(FakePageIndexService(), docs, user_id="user-a")

        result = await executor.execute("list_documents", {})

        assert [doc["id"] for doc in result["documents"]] == ["doc-a"]
        assert docs.get_indexed_documents_calls == ["user-a"]

    asyncio.run(run())


def test_allowed_doc_ids_empty_allows_no_documents() -> None:
    async def run() -> None:
        docs = FakeDocumentService()
        index = FakePageIndexService()
        executor = ToolExecutor(
            index,
            docs,
            user_id="user-a",
            allowed_doc_ids=[],
        )

        structure = await executor.execute(
            "get_document_structure", {"doc_id": "doc-a"}
        )
        listed = await executor.execute("list_documents", {})

        assert "error" in structure
        assert listed["documents"] == []
        assert index.load_index_calls == []

    asyncio.run(run())


def test_aggregate_tables_reports_rejected_document_ids() -> None:
    async def run() -> None:
        docs = FakeDocumentService()
        executor = ToolExecutor(
            FakePageIndexService(),
            docs,
            user_id="user-a",
            allowed_doc_ids=["doc-a"],
        )

        result = await executor.execute(
            "aggregate_tables",
            {
                "document_ids": ["doc-a", "doc-b", "missing-doc"],
                "operation_spec": {"operation": "count"},
            },
        )

        assert result["data"]["document_count"] == 1
        assert result["data"]["rejected_document_ids"] == ["doc-b", "missing-doc"]
        assert any(
            "not accessible" in note.lower()
            for note in result["data"]["quality_notes"]
        )

    asyncio.run(run())
