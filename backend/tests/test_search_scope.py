import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.search_service import DocumentSearchService


class FakeBM25:
    def retrieve(self, queries, k):
        return (
            np.array([[0, 1, 2]], dtype=int),
            np.array([[1.0, 0.9, 0.8]], dtype=float),
        )


def _search_service() -> DocumentSearchService:
    service = DocumentSearchService()
    service._initialized = True
    service.bm25_index = FakeBM25()
    service.rerank_model = None
    service.doc_corpus = [
        "alpha revenue",
        "alpha private",
        "alpha scoped",
    ]
    service.segment_metadata = [
        {
            "doc_id": "doc-a",
            "doc_name": "A.pdf",
            "user_id": "user-a",
            "title": "A",
            "snippet": "alpha revenue",
        },
        {
            "doc_id": "doc-b",
            "doc_name": "B.pdf",
            "user_id": "user-b",
            "title": "B",
            "snippet": "alpha private",
        },
        {
            "doc_id": "doc-c",
            "doc_name": "C.pdf",
            "user_id": "user-a",
            "title": "C",
            "snippet": "alpha scoped",
        },
    ]
    service.doc_metadata = {
        "doc-a": {"name": "A.pdf", "user_id": "user-a"},
        "doc-b": {"name": "B.pdf", "user_id": "user-b"},
        "doc-c": {"name": "C.pdf", "user_id": "user-a"},
    }
    service.last_index_doc_count = 3
    return service


def test_search_requires_user_id() -> None:
    async def run() -> None:
        service = _search_service()
        service.ensure_index_fresh = AsyncNoop()

        with pytest.raises(ValueError, match="user_id"):
            await service.search(query="alpha", auto_expand=False)

    asyncio.run(run())


def test_search_filters_candidates_by_user_before_results() -> None:
    async def run() -> None:
        service = _search_service()
        service.ensure_index_fresh = AsyncNoop()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            auto_expand=False,
            recall_k=3,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == ["doc-a", "doc-c"]
        assert "doc-b" not in [doc.doc_id for doc in response.documents]

    asyncio.run(run())


def test_search_allowed_doc_ids_narrows_user_scope() -> None:
    async def run() -> None:
        service = _search_service()
        service.ensure_index_fresh = AsyncNoop()

        response = await service.search(
            query="alpha",
            user_id="user-a",
            allowed_doc_ids=["doc-c", "doc-b"],
            auto_expand=False,
            recall_k=3,
            top_k=5,
        )

        assert [doc.doc_id for doc in response.documents] == ["doc-c"]

    asyncio.run(run())


def test_query_expansion_cache_is_user_scoped(monkeypatch) -> None:
    async def run() -> None:
        service = DocumentSearchService()
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs["messages"][0]["content"])
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=f"expanded-{len(calls)}")
                    )
                ]
            )

        import app.core.llm as llm

        monkeypatch.setattr(llm, "async_chat_completion", fake_completion)

        first = await service._expand_query("短问", user_id="user-a")
        second = await service._expand_query("短问", user_id="user-a")
        third = await service._expand_query("短问", user_id="user-b")

        assert first == "expanded-1"
        assert second == "expanded-1"
        assert third == "expanded-2"
        assert len(calls) == 2

    asyncio.run(run())


def test_index_snapshot_reports_user_scoped_counts() -> None:
    service = _search_service()

    user_snapshot = service.get_index_snapshot(user_id="user-a")
    narrowed_snapshot = service.get_index_snapshot(
        user_id="user-a", allowed_doc_ids=["doc-b", "doc-c"]
    )

    assert user_snapshot["scope_doc_count"] == 2
    assert user_snapshot["scope_segment_count"] == 2
    assert user_snapshot["scope_ids"] == ["doc-a", "doc-c"]
    assert narrowed_snapshot["scope_doc_count"] == 1
    assert narrowed_snapshot["scope_segment_count"] == 1
    assert narrowed_snapshot["scope_ids"] == ["doc-c"]


class AsyncNoop:
    async def __call__(self):
        return None
