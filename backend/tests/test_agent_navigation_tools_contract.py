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
    page_count: int = 3,
) -> DocumentResponse:
    return DocumentResponse(
        id=doc_id,
        name=name,
        original_name=name,
        file_path=file_path,
        file_size=10,
        file_type=file_type,
        status="completed",
        page_count=page_count,
        processed_pages=page_count,
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


class FakePageIndexByDocService:
    def __init__(self, indexes):
        self.indexes = indexes

    async def load_index(self, doc_id: str):
        return self.indexes.get(doc_id, {})


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
    assert {
        "find_related_documents",
        "list_folder_tree",
        "list_folder_contents",
        "list_documents",
    }.isdisjoint(names)
    assert _tool_schema("get_document_image")["parameters"]["required"] == ["image_path"]
    assert _tool_schema("get_page_image")["parameters"]["required"] == ["page"]


def test_legacy_document_tools_are_not_executable() -> None:
    async def run() -> None:
        executor = _executor({})

        for tool_name, args in [
            ("find_related_documents", {"query": "alpha"}),
            ("list_folder_tree", {}),
            ("list_folder_contents", {"folder_id": "folder-a"}),
            ("list_documents", {}),
        ]:
            result = await executor.execute(tool_name, args)
            assert result == {"error": f"未知工具: {tool_name}"}

    asyncio.run(run())


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


def test_get_document_image_reads_indexed_asset_by_image_path(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        asset_root = tmp_path / "assets"
        asset_root.mkdir()
        asset = asset_root / "img-1.jpeg"
        asset.write_bytes(b"fake-jpeg")
        monkeypatch.setattr(
            "app.services.tool_executor.INDEX_ASSET_ROOTS",
            (asset_root,),
            raising=False,
        )
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


def test_get_document_image_rejects_assets_outside_controlled_roots(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        asset_root = tmp_path / "assets"
        asset_root.mkdir()
        outside = tmp_path / "outside.jpeg"
        outside.write_bytes(b"not-an-index-asset")
        monkeypatch.setattr(
            "app.services.tool_executor.INDEX_ASSET_ROOTS",
            (asset_root,),
            raising=False,
        )
        index = {
            "assets": {
                "images": [
                    {
                        "image_path": "report.pdf/img-escape.jpeg",
                        "storage_path": str(outside),
                        "mimeType": "image/jpeg",
                        "page": 1,
                    }
                ]
            }
        }

        result = await _executor(index).execute(
            "get_document_image", {"image_path": "report.pdf/img-escape.jpeg"}
        )

        assert result["success"] is False
        assert "access denied" in result["error"].lower()

    asyncio.run(run())


def test_get_document_image_page_fallback_respects_allowed_doc_scope(monkeypatch) -> None:
    async def run() -> None:
        def fake_pdf_page_to_base64(file_path, page_num):
            return "encoded-page"

        monkeypatch.setattr("app.core.llm.pdf_page_to_base64", fake_pdf_page_to_base64)
        docs = [
            _doc(doc_id="doc-a", file_path="/tmp/a.pdf"),
            _doc(doc_id="doc-b", name="b.pdf", file_path="/tmp/b.pdf"),
        ]
        executor = ToolExecutor(
            FakePageIndexByDocService({}),
            FakeDocumentService(docs),
            user_id="user-a",
            allowed_doc_ids=["doc-a"],
        )

        page_ref = await executor.execute(
            "get_document_image", {"image_path": "page://doc-b/1"}
        )
        legacy_ref = await executor.execute(
            "get_document_image", {"doc_id": "doc-b", "page_num": 1}
        )

        assert page_ref["success"] is False
        assert "权限" in page_ref["error"]
        assert legacy_ref["success"] is False
        assert "权限" in legacy_ref["error"]

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


def test_browse_documents_query_filters_search_results_to_folder_scope(monkeypatch) -> None:
    async def run() -> None:
        captured = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                status="success",
                documents=[
                    SimpleNamespace(
                        doc_id="doc-a",
                        doc_name="report.pdf",
                        score=0.91,
                        reason="matched",
                        matched_segments=[],
                    ),
                    SimpleNamespace(
                        doc_id="doc-b",
                        doc_name="other.pdf",
                        score=0.89,
                        reason="matched",
                        matched_segments=[],
                    ),
                ],
                confidence="high",
                total_candidates=2,
                search_method="bm25_rerank",
            )

        docs = [
            _doc(doc_id="doc-a", folder_id="folder-a"),
            _doc(doc_id="doc-b", name="other.pdf", folder_id="folder-b"),
        ]
        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor({}, docs=docs).execute(
                "browse_documents",
                {"query": "report", "folder_id": "folder-a", "recursive": False},
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert captured["folder_id"] == "folder-a"
        assert captured["include_subfolders"] is False
        assert [doc["doc_id"] for doc in result["documents"]] == ["doc-a"]

    asyncio.run(run())


def test_browse_documents_no_query_uses_offset_for_pagination(monkeypatch) -> None:
    async def run() -> None:
        class FakeFolderService:
            def __init__(self):
                self.calls = []

            async def get_compact_folder_contents(
                self, folder_id, page=1, page_size=20, user_id=None
            ):
                self.calls.append((folder_id, page, page_size, user_id))
                return {
                    "child_folders": [],
                    "documents": [
                        {
                            "doc_id": f"doc-{page}",
                            "doc_name": f"doc-{page}.pdf",
                            "status": "completed",
                            "page_count": 1,
                            "folder_path": "root",
                            "description": "",
                            "created_at": None,
                        }
                    ],
                    "total_documents": 45,
                    "page": page,
                    "page_size": page_size,
                }

        fake = FakeFolderService()
        monkeypatch.setattr("app.services.tool_executor.FolderService", lambda: fake)

        first = await _executor({}).execute(
            "browse_documents", {"folder_id": "root"}
        )
        second = await _executor({}).execute(
            "browse_documents", {"folder_id": "root", "offset": first["next_offset"]}
        )

        assert fake.calls == [(None, 1, 20, "user-a"), (None, 2, 20, "user-a")]
        assert first["has_more"] is True
        assert first["next_offset"] == "2"
        assert second["documents"][0]["doc_id"] == "doc-2"

    asyncio.run(run())


def test_browse_documents_no_query_recursive_returns_descendant_documents(monkeypatch) -> None:
    async def run() -> None:
        class FakeFolderService:
            async def get_folder(self, folder_id, user_id=None):
                return SimpleNamespace(id=folder_id, path="Projects")

        monkeypatch.setattr("app.services.tool_executor.FolderService", FakeFolderService)
        docs = [
            _doc(doc_id="doc-a", folder_id="folder-a"),
            _doc(doc_id="doc-child", name="child.pdf", folder_id="folder-child"),
            _doc(doc_id="doc-other", name="other.pdf", folder_id="folder-other"),
        ]
        docs[0].folder_path = "Projects"
        docs[1].folder_path = "Projects/Child"
        docs[2].folder_path = "Archive"

        result = await _executor({}, docs=docs).execute(
            "browse_documents", {"folder_id": "folder-a", "recursive": True}
        )

        assert [doc["doc_id"] for doc in result["documents"]] == [
            "doc-a",
            "doc-child",
        ]
        assert result["has_more"] is False

    asyncio.run(run())


def test_get_document_structure_supports_doc_name_disambiguation_and_parts() -> None:
    async def run() -> None:
        docs = [
            _doc(doc_id="doc-a", name="same.pdf", folder_id="folder-a"),
            _doc(doc_id="doc-b", name="same.pdf", folder_id="folder-b"),
        ]
        structure = [
            {"node_id": f"n-{idx}", "title": f"Node {idx}", "start_index": idx}
            for idx in range(1, 86)
        ]
        executor = ToolExecutor(
            FakePageIndexByDocService({"doc-a": {"structure": structure}}),
            FakeDocumentService(docs),
            user_id="user-a",
        )

        ambiguous = await executor.execute(
            "get_document_structure", {"doc_name": "same.pdf"}
        )
        part1 = await executor.execute(
            "get_document_structure",
            {"doc_name": "same.pdf", "folder_id": "folder-a", "part": 1},
        )
        part2 = await executor.execute(
            "get_document_structure",
            {"doc_name": "same.pdf", "folder_id": "folder-a", "part": 2},
        )

        assert "candidates" in ambiguous
        assert part1["success"] is True
        assert part1["has_more_parts"] is True
        assert len(part1["structure"]) == 80
        assert part2["has_more_parts"] is False
        assert [node["node_id"] for node in part2["structure"]] == [
            "n-81",
            "n-82",
            "n-83",
            "n-84",
            "n-85",
        ]

    asyncio.run(run())


def test_get_page_content_reports_truncated_page_ranges() -> None:
    async def run() -> None:
        structure = [
            {
                "node_id": f"n-{idx}",
                "title": f"Page {idx}",
                "start_index": idx,
                "end_index": idx,
                "text": f"text {idx}",
            }
            for idx in range(1, 13)
        ]
        pages = [{"page": idx, "text": f"text {idx}", "images": []} for idx in range(1, 13)]
        result = await _executor(
            {"structure": structure, "pages": pages},
            docs=[_doc(page_count=12)],
        ).execute("get_page_content", {"doc_id": "doc-a", "pages": "1-12"})

        assert result["status"] == "success"
        assert result["data"]["requested_pages"] == "1-12"
        assert result["data"]["returned_pages"] == "1-10"
        assert result["data"]["request_truncated"] is True
        assert "继续" in str(result["next_steps"])

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
