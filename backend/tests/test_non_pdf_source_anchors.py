from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.search_service import DocumentSearchService


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


