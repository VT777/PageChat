import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.search_service import DocumentSearchService, search_service
from app.services.tool_executor import ToolExecutor


def test_search_trace_infers_markdown_line_anchor_unit_type() -> None:
    meta = {
        "doc_name": "notes.md",
        "file_type": ".md",
        "source_anchor": {
            "format": "markdown",
            "start_line": 5,
            "end_line": 8,
        },
    }

    trace = DocumentSearchService._trace_for_segment(meta, 0.75)

    assert trace["source_anchor"] == {
        "format": "markdown",
        "unit_type": "line",
        "start_line": 5,
        "end_line": 8,
    }
    assert trace["display_label"] == "notes.md lines 5-8"
    assert trace["retrieval_source"] == "document_search"
    assert trace["confidence"] == 0.75


def test_search_trace_preserves_csv_row_range_anchor_and_display_label() -> None:
    meta = {
        "doc_name": "sales.csv",
        "file_type": ".csv",
        "start_index": 1,
        "end_index": 1,
        "source_anchor": {
            "format": "csv",
            "unit_type": "row_range",
            "start_row": 2,
            "end_row": 4,
        },
    }

    trace = DocumentSearchService._trace_for_segment(meta, 0.5)

    assert trace["source_anchor"]["unit_type"] == "row_range"
    assert trace["display_label"] == "sales.csv rows 2-4"


def test_find_related_documents_preserves_non_pdf_matched_segment_anchor() -> None:
    document_service = SimpleNamespace(
        get_indexed_documents=AsyncMock(return_value=[])
    )
    pageindex_service = SimpleNamespace(load_index=AsyncMock(return_value={}))
    executor = ToolExecutor(pageindex_service, document_service, user_id="user-1")

    async def fake_search(**kwargs):
        return SimpleNamespace(
            status="success",
            documents=[
                SimpleNamespace(
                    doc_id="doc-md",
                    doc_name="notes.md",
                    score=0.82,
                    reason="matched markdown",
                    matched_segments=[
                        {
                            "node_id": "node_1",
                            "title": "Intro",
                            "snippet": "alpha",
                            "start_index": 1,
                            "end_index": 1,
                            "source_anchor": {
                                "format": "markdown",
                                "unit_type": "line",
                                "start_line": 5,
                                "end_line": 8,
                            },
                            "display_label": "notes.md lines 5-8",
                            "retrieval_source": "document_search",
                            "confidence": 0.82,
                            "why_selected": "Matched document search index.",
                        }
                    ],
                    retrieval_source="document_search",
                    confidence=0.82,
                    why_selected="Matched document search index.",
                    source_anchor={
                        "format": "markdown",
                        "unit_type": "line",
                        "start_line": 5,
                        "end_line": 8,
                    },
                    display_label="notes.md lines 5-8",
                )
            ],
            confidence="high",
            total_candidates=1,
            search_method="bm25",
        )

    original_search = search_service.search
    search_service.search = fake_search  # type: ignore[method-assign]
    search_service.doc_corpus = ["alpha"]

    async def run_case() -> None:
        result = await executor._find_related_documents(query="alpha")
        segment = result["data"]["matched_segments"]["doc-md"][0]
        assert segment["start_index"] == 1
        assert segment["end_index"] == 1
        assert segment["source_anchor"]["unit_type"] == "line"
        assert segment["display_label"] == "notes.md lines 5-8"
        assert segment["retrieval_source"] == "document_search"

    try:
        asyncio.run(run_case())
    finally:
        search_service.search = original_search  # type: ignore[method-assign]
