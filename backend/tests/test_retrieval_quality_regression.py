import asyncio
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.search_service import DocumentSearchService


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "evaluation"


class FixedBM25:
    def retrieve(self, queries, k):
        return (
            np.array([[0, 1]], dtype=int),
            np.array([[2.0, 0.1]], dtype=float),
        )


class AsyncNoop:
    async def __call__(self):
        return None


def _load_query() -> dict:
    return json.loads((FIXTURE_DIR / "queries.json").read_text(encoding="utf-8"))[0]


def test_retrieval_fixture_returns_expected_document_node_and_anchor() -> None:
    async def run() -> None:
        expected = _load_query()
        service = DocumentSearchService()
        service._initialized = True
        service.ensure_index_fresh = AsyncNoop()
        service.bm25_index = FixedBM25()
        service.rerank_model = None
        service.doc_corpus = [
            "Deployment Checklist Confirm environment variables Run smoke tests",
            "Unrelated billing appendix",
        ]
        service.segment_metadata = [
            {
                "doc_id": expected["document_id"],
                "doc_name": expected["document_name"],
                "user_id": "eval-user",
                "file_type": ".md",
                "title": "Deployment Checklist",
                "snippet": "Confirm environment variables. Run smoke tests.",
                "source_anchor": {
                    "format": "markdown",
                    "unit_type": "line",
                    "start_line": 5,
                    "end_line": 8,
                },
            },
            {
                "doc_id": "other-doc",
                "doc_name": "other.md",
                "user_id": "eval-user",
                "file_type": ".md",
                "title": "Billing",
                "snippet": "Unrelated billing appendix",
                "source_anchor": {
                    "format": "markdown",
                    "unit_type": "line",
                    "start_line": 1,
                    "end_line": 2,
                },
            },
        ]
        service.doc_metadata = {
            expected["document_id"]: {
                "name": expected["document_name"],
                "user_id": "eval-user",
            },
            "other-doc": {"name": "other.md", "user_id": "eval-user"},
        }
        service.last_index_doc_count = 2

        response = await service.search(
            expected["query"],
            user_id="eval-user",
            auto_expand=False,
        )

        assert response.documents
        top = response.documents[0]
        segment = top.matched_segments[0]
        assert top.doc_id == expected["document_id"]
        assert expected["expected_title_contains"] in segment["title"]
        assert segment["source_anchor"]["unit_type"] == expected["expected_unit_type"]
        assert segment["retrieval_source"] == "document_search"

        fallback_rate = sum(
            1
            for doc in response.documents
            for item in doc.matched_segments
            if item.get("retrieval_source") in {"keyword_fallback", "visual_summary"}
        ) / max(1, sum(len(doc.matched_segments) for doc in response.documents))
        assert fallback_rate == 0.0

    asyncio.run(run())
