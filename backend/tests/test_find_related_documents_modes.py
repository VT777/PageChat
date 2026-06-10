import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tool_executor import ToolExecutor
from app.services.search_service import search_service


def test_find_related_selected_only_mode() -> None:
    docs = [
        SimpleNamespace(id="d1", original_name="A.pdf"),
        SimpleNamespace(id="d2", original_name="B.pdf"),
    ]
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=docs)
    )
    pageindex_service = SimpleNamespace(load_index=AsyncMock(return_value={}))

    executor = ToolExecutor(pageindex_service, document_service, user_id="user-1")

    async def fake_search(**kwargs):
        return SimpleNamespace(
            status="success",
            documents=[
                SimpleNamespace(
                    doc_id="d1",
                    doc_name="A.pdf",
                    score=0.82,
                    reason="命中片段",
                    matched_segments=[
                        {
                            "node_id": "node_1",
                            "title": "章节1",
                            "snippet": "测试片段",
                            "source_anchor": {"format": "pdf", "page": 1},
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
    search_service.doc_corpus = [("d1", "desc"), ("d2", "desc")]

    async def run_case() -> None:
        result = await executor._find_related_documents(
            query="测试",
            user_selected_document_ids=["d1"],
            allow_global_expansion=True,
        )
        assert result["data"]["retrieval_mode"] == "selected_only"
        assert result["data"]["recommended_document_ids"] == ["d1"]
        assert result["next_steps"]["action"] == "call_tool"
        assert result["data"]["matched_segments"]["d1"][0]["node_id"] == "node_1"
        assert "index_snapshot" in result["data"]

    try:
        asyncio.run(run_case())
    finally:
        search_service.search = original_search  # type: ignore


def test_find_related_stats_query_prefers_aggregate_tables() -> None:
    docs = [SimpleNamespace(id="d1", original_name="list.xlsx")]
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=docs)
    )
    pageindex_service = SimpleNamespace(load_index=AsyncMock(return_value={}))

    executor = ToolExecutor(pageindex_service, document_service, user_id="user-1")

    async def fake_search(**kwargs):
        return SimpleNamespace(
            status="success",
            documents=[
                SimpleNamespace(
                    doc_id="d1",
                    doc_name="list.xlsx",
                    score=0.78,
                    reason="命中名单",
                    matched_segments=[],
                )
            ],
            confidence="high",
            total_candidates=1,
            search_method="bm25_rerank",
        )

    original_search = search_service.search
    search_service.search = fake_search  # type: ignore
    search_service.doc_corpus = ["名单"]

    async def run_case() -> None:
        result = await executor._find_related_documents(query="复试名单有多少人")
        assert result["next_steps"]["suggested_tool"] == "aggregate_tables"

    try:
        asyncio.run(run_case())
    finally:
        search_service.search = original_search  # type: ignore


def test_find_related_selected_then_global_mode() -> None:
    docs = [
        SimpleNamespace(id="d1", original_name="A.pdf"),
        SimpleNamespace(id="d2", original_name="B.pdf"),
    ]
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=docs)
    )
    pageindex_service = SimpleNamespace(load_index=AsyncMock(return_value={}))

    executor = ToolExecutor(pageindex_service, document_service, user_id="user-1")

    async def fake_search(**kwargs):
        return SimpleNamespace(
            status="partial",
            documents=[
                SimpleNamespace(
                    doc_id="d2", doc_name="B.pdf", score=0.66, reason="全局补充命中"
                )
            ],
            confidence="medium",
            total_candidates=1,
            search_method="bm25_rerank",
        )

    original_search = search_service.search
    search_service.search = fake_search  # type: ignore
    search_service.doc_corpus = [("d1", "desc"), ("d2", "desc")]

    async def run_case() -> None:
        result = await executor._find_related_documents(
            query="测试",
            user_selected_document_ids=["d1"],
            allow_global_expansion=True,
        )
        assert result["data"]["retrieval_mode"] == "selected_then_global"
        assert result["data"]["recommended_document_ids"] == ["d2"]
        assert result["data"]["fallback_suggested"] is False

    try:
        asyncio.run(run_case())
    finally:
        search_service.search = original_search  # type: ignore


def test_find_related_low_confidence_next_step_no_auto_legacy() -> None:
    docs = [SimpleNamespace(id="d1", original_name="A.pdf")]
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=docs)
    )
    pageindex_service = SimpleNamespace(load_index=AsyncMock(return_value={}))

    executor = ToolExecutor(pageindex_service, document_service, user_id="user-1")

    async def fake_search(**kwargs):
        return SimpleNamespace(
            status="none",
            documents=[],
            confidence="low",
            total_candidates=0,
            search_method="bm25",
        )

    original_search = search_service.search
    search_service.search = fake_search  # type: ignore
    search_service.doc_corpus = [("d1", "desc")]

    async def run_case() -> None:
        result = await executor._find_related_documents(query="完全无关")
        assert result["data"]["retrieval_mode"] == "selected_only"
        assert result["data"]["fallback_available"] is True
        assert result["next_steps"]["suggested_tool"] == "list_documents"
        assert "不自动回退" in result["next_steps"]["reason"]
        assert "index_snapshot" in result["data"]

    try:
        asyncio.run(run_case())
    finally:
        search_service.search = original_search  # type: ignore
