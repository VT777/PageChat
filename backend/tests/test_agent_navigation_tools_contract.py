import asyncio
import base64
from datetime import datetime
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.schemas import DocumentResponse
from app.services.search_service import search_service
from app.services.tool_executor import AGENT_TOOLS, ToolExecutor


def _doc(
    doc_id: str = "doc-a",
    name: str = "report.pdf",
    file_path: str = "/tmp/report.pdf",
    file_type: str = ".pdf",
    folder_id: str | None = "folder-a",
) -> DocumentResponse:
    return DocumentResponse(
        id=doc_id,
        name=name,
        original_name=name,
        file_path=file_path,
        file_size=10,
        file_type=file_type,
        status="completed",
        page_count=3,
        processed_pages=3,
        folder_id=folder_id,
        folder_path="root/reports" if folder_id else "",
        description="A compact report description.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class FakeDocumentService:
    def __init__(self, docs=None):
        self.docs = docs or [_doc()]
        self.by_id = {doc.id: doc for doc in self.docs}

    async def get_document(self, doc_id: str, user_id: str | None = None):
        return self.by_id.get(doc_id)

    async def get_indexed_documents(self, user_id: str | None = None):
        return list(self.docs)


class FakePageIndexService:
    def __init__(self, index):
        self.index = index

    async def load_index(self, doc_id: str):
        return self.index


def _executor(index, docs=None) -> ToolExecutor:
    return ToolExecutor(
        FakePageIndexService(index),
        FakeDocumentService(docs),
        user_id="user-a",
    )


def _tool_schema(name: str) -> dict:
    for tool in AGENT_TOOLS:
        if tool["function"]["name"] == name:
            return tool["function"]
    raise AssertionError(f"tool {name} not found")


def test_navigation_tool_catalog_exposes_official_style_tools() -> None:
    names = {tool["function"]["name"] for tool in AGENT_TOOLS}

    assert {
        "view_folder_structure",
        "browse_documents",
        "get_document_structure",
        "get_page_content",
        "get_document_image",
        "get_page_image",
        "search_within_document",
    }.issubset(names)
    assert _tool_schema("get_document_image")["parameters"]["required"] == ["image_path"]
    assert _tool_schema("get_page_image")["parameters"]["required"] == [
        "doc_id",
        "page",
    ]


def test_visual_page_content_returns_image_refs_without_ocr_text() -> None:
    async def run() -> None:
        index = {
            "structure": [
                {
                    "node_id": "n1",
                    "title": "Figure page",
                    "start_index": 1,
                    "end_index": 1,
                    "text": "OCR text that should not enter model context",
                    "has_visual_content": True,
                    "images": [
                        {
                            "image_path": "report.pdf/img-1.jpeg",
                            "mimeType": "image/jpeg",
                            "page": 1,
                        }
                    ],
                }
            ],
            "pages": [
                {
                    "page": 1,
                    "text": "page OCR text that should also be omitted",
                    "images": [
                        {
                            "image_path": "report.pdf/img-1.jpeg",
                            "mimeType": "image/jpeg",
                            "page": 1,
                        }
                    ],
                }
            ],
        }
        result = await _executor(index).execute(
            "get_page_content", {"doc_id": "doc-a", "pages": "1"}
        )

        assert result["status"] == "success"
        page = result["data"]["content"][0]
        assert page["page"] == 1
        assert page["text"] == ""
        assert page["text_omitted_reason"] == "visual_evidence_required"
        assert page["visual_evidence_required"] is True
        assert page["images"] == [
            {
                "image_path": "report.pdf/img-1.jpeg",
                "alt": "img-1.jpeg",
                "mimeType": "image/jpeg",
                "page": 1,
            }
        ]
        assert "OCR text" not in str(result)
        assert "text_content" not in page

    asyncio.run(run())


def test_get_document_image_reads_indexed_asset_by_image_path(tmp_path: Path) -> None:
    async def run() -> None:
        asset = tmp_path / "img-1.jpeg"
        asset.write_bytes(b"fake-jpeg")
        index = {
            "assets": {
                "images": [
                    {
                        "image_path": "report.pdf/img-1.jpeg",
                        "storage_path": str(asset),
                        "mimeType": "image/jpeg",
                        "page": 1,
                    }
                ]
            }
        }

        result = await _executor(index).execute(
            "get_document_image", {"image_path": "report.pdf/img-1.jpeg"}
        )

        assert result["success"] is True
        assert result["type"] == "image"
        assert result["mimeType"] == "image/jpeg"
        assert result["image_path"] == "report.pdf/img-1.jpeg"
        assert result["page"] == 1
        assert base64.b64decode(result["data"]) == b"fake-jpeg"

    asyncio.run(run())


def test_get_page_image_keeps_full_page_render_as_fallback(monkeypatch) -> None:
    async def run() -> None:
        def fake_pdf_page_to_base64(file_path, page_num):
            assert file_path == "/tmp/report.pdf"
            assert page_num == 2
            return "encoded-page"

        monkeypatch.setattr("app.core.llm.pdf_page_to_base64", fake_pdf_page_to_base64)
        result = await _executor({}).execute(
            "get_page_image", {"doc_id": "doc-a", "page": 2}
        )

        assert result["status"] == "success"
        assert result["data"]["image_base64"] == "encoded-page"
        assert result["data"]["type"] == "image"
        assert result["data"]["mimeType"] == "image/jpeg"

    asyncio.run(run())


def test_browse_documents_query_returns_compact_document_items(monkeypatch) -> None:
    async def run() -> None:
        async def fake_search(**kwargs):
            return SimpleNamespace(
                status="success",
                documents=[
                    SimpleNamespace(
                        doc_id="doc-a",
                        doc_name="report.pdf",
                        score=0.91,
                        reason="matched",
                        matched_segments=[
                            {
                                "snippet": "this internal segment should not leak",
                                "text": "full text should not leak",
                            }
                        ],
                    )
                ],
                confidence="high",
                total_candidates=1,
                search_method="bm25_rerank",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor({}).execute(
                "browse_documents", {"query": "report", "folder_id": "folder-a"}
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert result["success"] is True
        assert result["documents"] == [
            {
                "doc_id": "doc-a",
                "name": "report.pdf",
                "path": "root/reports",
                "folder_id": "folder-a",
                "status": "completed",
                "created_at": result["documents"][0]["created_at"],
                "description": "A compact report description.",
                "page_count": 3,
            }
        ]
        assert "matched_segments" not in result["documents"][0]
        assert "snippet" not in str(result)
        assert "full text" not in str(result)

    asyncio.run(run())


def test_search_within_document_requires_document_scope(monkeypatch) -> None:
    async def run() -> None:
        executor = _executor({})

        missing_scope = await executor.execute(
            "search_within_document", {"query": "alpha"}
        )
        assert missing_scope["success"] is False
        assert "doc_id" in missing_scope["error"]

        async def fake_search(**kwargs):
            assert kwargs["document_ids"] == ["doc-a"]
            return SimpleNamespace(
                status="success",
                documents=[
                    SimpleNamespace(
                        doc_id="doc-a",
                        doc_name="report.pdf",
                        score=0.88,
                        reason="matched",
                        matched_segments=[
                            {
                                "node_id": "n1",
                                "title": "Alpha",
                                "snippet": "alpha appears here",
                                "start_index": 2,
                                "end_index": 2,
                            }
                        ],
                    )
                ],
                confidence="high",
                total_candidates=1,
                search_method="bm25",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await executor.execute(
                "search_within_document", {"doc_id": "doc-a", "query": "alpha"}
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert result["success"] is True
        assert result["doc_id"] == "doc-a"
        assert result["matches"] == [
            {
                "node_id": "n1",
                "title": "Alpha",
                "snippet": "alpha appears here",
                "page_range": "2",
            }
        ]

    asyncio.run(run())
