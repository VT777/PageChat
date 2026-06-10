import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.search_service import search_service
from app.services.tool_executor import ToolExecutor


def _executor(allowed_doc_ids=None) -> ToolExecutor:
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=[])
    )
    pageindex_service = SimpleNamespace(load_index=AsyncMock(return_value={}))
    return ToolExecutor(
        pageindex_service,
        document_service,
        user_id="user-1",
        allowed_doc_ids=allowed_doc_ids,
    )


def _doc(doc_id: str, score: float = 0.8, segment=None):
    return SimpleNamespace(
        doc_id=doc_id,
        doc_name=f"{doc_id}.pdf",
        score=score,
        reason="matched",
        matched_segments=segment
        if segment is not None
        else [
            {
                "node_id": "n1",
                "title": "Hit",
                "score": score,
                "source_anchor": {
                    "format": "pdf",
                    "unit_type": "page",
                    "start_page": 2,
                    "end_page": 2,
                },
                "display_label": f"{doc_id}.pdf p.2",
            }
        ],
    )


def test_explicit_document_ids_default_to_strict_scope() -> None:
    async def run() -> None:
        calls = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                status="success",
                documents=[_doc("doc-a")],
                confidence="high",
                total_candidates=1,
                search_method="bm25",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor()._find_related_documents(
                query="alpha",
                document_ids=["doc-a"],
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert calls[0]["document_ids"] == ["doc-a"]
        assert calls[0]["allowed_doc_ids"] is None
        assert result["data"]["retrieval_mode"] == "strict_scope"
        assert result["data"]["scope"]["strict_scope"] is True

    asyncio.run(run())


def test_explicit_folder_id_default_to_strict_scope() -> None:
    async def run() -> None:
        calls = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                status="success",
                documents=[_doc("doc-a")],
                confidence="high",
                total_candidates=1,
                search_method="bm25",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor()._find_related_documents(
                query="alpha",
                folder_id="folder-a",
                include_subfolders=True,
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert calls[0]["folder_id"] == "folder-a"
        assert calls[0]["include_subfolders"] is True
        assert result["data"]["retrieval_mode"] == "strict_scope"
        assert result["data"]["scope"]["requested_folder_id"] == "folder-a"

    asyncio.run(run())


def test_strict_scope_false_expands_to_current_user_library_with_trace() -> None:
    async def run() -> None:
        calls = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                status="success",
                documents=[_doc("doc-b", 0.72)],
                confidence="high",
                total_candidates=1,
                search_method="bm25",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor()._find_related_documents(
                query="alpha",
                document_ids=["doc-a"],
                strict_scope=False,
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert calls[0]["document_ids"] is None
        assert result["data"]["retrieval_mode"] == "selected_then_user_library"
        assert result["data"]["scope"]["expanded_to_user_library"] is True
        assert result["data"]["recommended_document_ids"] == ["doc-b"]

    asyncio.run(run())


def test_allowed_doc_ids_cannot_be_widened_by_expansion() -> None:
    async def run() -> None:
        calls = []

        async def fake_search(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                status="success",
                documents=[_doc("doc-allowed", 0.8)],
                confidence="high",
                total_candidates=1,
                search_method="bm25",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor(allowed_doc_ids=["doc-allowed"])._find_related_documents(
                query="alpha",
                document_ids=["doc-selected"],
                strict_scope=False,
            )
        finally:
            search_service.search = original_search  # type: ignore

        assert calls[0]["allowed_doc_ids"] == ["doc-allowed"]
        assert result["data"]["recommended_document_ids"] == ["doc-allowed"]

    asyncio.run(run())


def test_result_contains_actionable_segments_and_recommended_next_action() -> None:
    async def run() -> None:
        async def fake_search(**kwargs):
            return SimpleNamespace(
                status="success",
                documents=[_doc("doc-a", 0.9)],
                confidence="high",
                total_candidates=1,
                search_method="bm25",
            )

        original_search = search_service.search
        search_service.search = fake_search  # type: ignore
        search_service.doc_corpus = ["x"]
        try:
            result = await _executor()._find_related_documents(query="alpha")
        finally:
            search_service.search = original_search  # type: ignore

        assert result["data"]["matched_segments"]["doc-a"][0]["source_anchor"]
        assert result["data"]["recommended_next_action"] == "get_page_content"

    asyncio.run(run())
