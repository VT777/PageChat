import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
from app.services.search_service import DocumentSearchService
from app.services.tool_executor import ToolExecutor
from app.services.search_service import search_service


class FakeBM25:
    def retrieve(self, queries, k):
        return (
            np.array([[0]], dtype=int),
            np.array([[1.0]], dtype=float),
        )


class AsyncNoop:
    async def __call__(self):
        return None


def test_document_search_results_include_retrieval_trace_metadata() -> None:
    async def run() -> None:
        service = DocumentSearchService()
        service._initialized = True
        service.ensure_index_fresh = AsyncNoop()
        service.bm25_index = FakeBM25()
        service.rerank_model = None
        service.doc_corpus = ["alpha revenue"]
        service.segment_metadata = [
            {
                "doc_id": "doc-a",
                "doc_name": "report.pdf",
                "user_id": "user-a",
                "file_type": ".pdf",
                "title": "Revenue",
                "snippet": "alpha revenue",
                "start_index": 12,
                "end_index": 15,
                "source_anchor": None,
            }
        ]
        service.doc_metadata = {
            "doc-a": {"name": "report.pdf", "user_id": "user-a"}
        }
        service.last_index_doc_count = 1

        response = await service.search(
            query="alpha", user_id="user-a", auto_expand=False
        )

        doc = response.documents[0]
        segment = doc.matched_segments[0]
        assert doc.retrieval_source == "document_search"
        assert doc.confidence == doc.score
        assert doc.why_selected
        assert doc.source_anchor == {
            "format": "pdf",
            "unit_type": "page",
            "start_page": 12,
            "end_page": 15,
        }
        assert doc.display_label == "report.pdf p.12-15"
        assert segment["retrieval_source"] == "document_search"
        assert segment["confidence"] == segment["score"]
        assert segment["display_label"] == "report.pdf p.12-15"

    asyncio.run(run())


def test_tool_executor_propagates_retrieval_trace_metadata() -> None:
    docs = [SimpleNamespace(id="doc-a", original_name="report.pdf")]
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=docs)
    )
    executor = ToolExecutor(
        SimpleNamespace(load_index=AsyncMock(return_value={})),
        document_service,
        user_id="user-a",
    )

    async def fake_search(**kwargs):
        return SimpleNamespace(
            status="success",
            documents=[
                SimpleNamespace(
                    doc_id="doc-a",
                    doc_name="report.pdf",
                    score=0.82,
                    reason="matched",
                    retrieval_source="document_search",
                    confidence=0.82,
                    why_selected="Matched document search index.",
                    source_anchor={
                        "format": "pdf",
                        "unit_type": "page",
                        "start_page": 12,
                        "end_page": 15,
                    },
                    display_label="report.pdf p.12-15",
                    matched_segments=[
                        {
                            "node_id": "n1",
                            "retrieval_source": "document_search",
                            "confidence": 0.82,
                            "why_selected": "Matched document search index.",
                            "source_anchor": {
                                "format": "pdf",
                                "unit_type": "page",
                                "start_page": 12,
                                "end_page": 15,
                            },
                            "display_label": "report.pdf p.12-15",
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
    search_service.doc_corpus = ["alpha"]

    async def run() -> None:
        result = await executor._find_related_documents(query="alpha")
        related = result["related_documents"][0]
        assert related["retrieval_source"] == "document_search"
        assert related["confidence"] == 0.82
        assert related["why_selected"] == "Matched document search index."
        assert related["source_anchor"]["start_page"] == 12
        assert related["display_label"] == "report.pdf p.12-15"
        assert result["data"]["matched_segments"]["doc-a"][0]["display_label"] == (
            "report.pdf p.12-15"
        )

    try:
        asyncio.run(run())
    finally:
        search_service.search = original_search  # type: ignore


def test_keyword_fallback_results_include_retrieval_trace_metadata() -> None:
    pageindex = PageIndexService()
    results = pageindex._simple_search(
        [
            {
                "node_id": "n1",
                "title": "Alpha",
                "text": "alpha revenue",
                "start_index": 3,
                "end_index": 3,
            }
        ],
        query="alpha",
        doc_id="doc-a",
        doc_name="report.pdf",
    )

    result = results[0]
    assert result["retrieval_source"] == "keyword_fallback"
    assert result["confidence"] == result["relevance"]
    assert result["why_selected"] == "Matched fallback keyword search."
    assert result["source_anchor"] == {
        "format": "pdf",
        "unit_type": "page",
        "start_page": 3,
        "end_page": 3,
    }
    assert result["display_label"] == "report.pdf p.3"


def test_tree_reasoning_results_include_retrieval_trace_metadata(monkeypatch) -> None:
    async def fake_chat_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            '[{"node_id": "n1", "reasoning": "matched section", '
                            '"relevance_score": 0.83}]'
                        )
                    )
                )
            ]
        )

    async def fake_verify_candidate_nodes(**kwargs):
        return kwargs["candidates"]

    monkeypatch.setattr("app.core.llm.async_chat_completion", fake_chat_completion)
    monkeypatch.setattr(
        "app.services.pageindex_service.verify_candidate_nodes",
        fake_verify_candidate_nodes,
    )

    async def run() -> None:
        pageindex = PageIndexService()
        results = await pageindex.search_in_structure_async(
            {
                "structure": [
                    {
                        "node_id": "n1",
                        "title": "Alpha",
                        "text": "alpha revenue",
                        "start_index": 4,
                        "end_index": 5,
                    }
                ]
            },
            query="alpha",
            doc_id="doc-a",
            doc_name="report.pdf",
            user_id="trace-tree-user",
        )

        result = results[0]
        assert result["retrieval_source"] == "tree_reasoning"
        assert result["confidence"] == result["relevance"]
        assert result["why_selected"] == result["reasoning"]
        assert result["source_anchor"]["unit_type"] == "page"
        assert result["display_label"]

    asyncio.run(run())
