import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService
from pageindex.quality_validation import build_index_quality_report


def _node(title, start, end, summary="summary", children=None):
    return {
        "title": title,
        "start_index": start,
        "end_index": end,
        "summary": summary,
        "nodes": children or [],
    }


def test_quality_report_marks_good_tree_completed() -> None:
    payload = {
        "structure": [
            _node("Overview", 1, 3),
            _node("Risk", 4, 6, children=[_node("Market Risk", 4, 5)]),
            _node("Appendix", 7, 10),
        ]
    }

    report = build_index_quality_report(payload, page_count=10)

    assert report["status"] == "completed"
    assert report["node_count"] == 4
    assert report["max_depth"] == 2
    assert report["page_range_coverage"] >= 0.9
    assert report["duplicate_title_ratio"] == 0.0
    assert report["empty_summary_ratio"] == 0.0
    assert report["unmapped_pages"] == []


def test_quality_report_marks_empty_tree_failed() -> None:
    report = build_index_quality_report({"structure": []}, page_count=5)

    assert report["status"] == "failed:indexing"
    assert report["node_count"] == 0
    assert "empty structure" in report["warnings"]


def test_quality_report_marks_low_page_coverage_needs_review() -> None:
    payload = {"structure": [_node("Only Beginning", 1, 2)]}

    report = build_index_quality_report(payload, page_count=10)

    assert report["status"] == "needs_review"
    assert report["page_range_coverage"] == 0.2
    assert 3 in report["unmapped_pages"]
    assert any("page range coverage" in warning for warning in report["warnings"])


def test_quality_report_marks_duplicate_titles_needs_review() -> None:
    payload = {
        "structure": [
            _node("Repeated", 1, 1),
            _node("Repeated", 2, 2),
            _node("Repeated", 3, 3),
            _node("Unique", 4, 4),
        ]
    }

    report = build_index_quality_report(payload, page_count=4)

    assert report["status"] == "needs_review"
    assert report["duplicate_title_ratio"] > 0.35
    assert any("duplicate title" in warning for warning in report["warnings"])


def test_quality_report_marks_empty_summaries_needs_review() -> None:
    payload = {
        "structure": [
            _node("A", 1, 1, summary=""),
            _node("B", 2, 2, summary=""),
            _node("C", 3, 3, summary="kept"),
        ]
    }

    report = build_index_quality_report(payload, page_count=3)

    assert report["status"] == "needs_review"
    assert report["empty_summary_ratio"] > 0.5
    assert any("empty summary" in warning for warning in report["warnings"])


def test_legacy_index_without_quality_report_still_loads(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.pageindex_service.INDEXES_DIR", tmp_path)
    service = PageIndexService()
    PageIndexService._save_index_payload(
        "legacy-doc",
        {"structure": [_node("Legacy", 1, 1)]},
    )

    loaded = asyncio.run(service.load_index("legacy-doc"))

    assert loaded is not None
    assert "quality_report" not in loaded
    assert loaded["structure"][0]["title"] == "Legacy"


def test_saved_pdf_index_payload_includes_quality_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.pageindex_service.INDEXES_DIR", tmp_path)

    PageIndexService._save_index_payload(
        "fresh-doc",
        {
            "format": "pdf",
            "page_count": 2,
            "structure": [
                _node("Overview", 1, 1),
                _node("Details", 2, 2),
            ],
        },
    )

    loaded = asyncio.run(PageIndexService().load_index("fresh-doc"))

    assert loaded is not None
    assert loaded["quality_report"]["status"] == "completed"
    assert loaded["quality_report"]["page_range_coverage"] == 1.0


def test_saved_pdf_index_payload_infers_pdf_from_doc_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.pageindex_service.INDEXES_DIR", tmp_path)

    PageIndexService._save_index_payload(
        "generated-pdf-doc",
        {
            "doc_name": "generated.pdf",
            "page_count": 2,
            "structure": [
                _node("Overview", 1, 1),
                _node("Details", 2, 2),
            ],
        },
    )

    loaded = asyncio.run(PageIndexService().load_index("generated-pdf-doc"))

    assert loaded is not None
    assert loaded["quality_report"]["status"] == "completed"
