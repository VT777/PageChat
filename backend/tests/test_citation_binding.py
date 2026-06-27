import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.citations import (
    citation_events_from_tool_result,
    dedupe_citations,
    normalize_citation,
)


def test_citation_events_from_tool_result_deduplicates_nested_citations() -> None:
    result = {
        "citations": [
            {
                "citation_key": "c1",
                "document_id": "doc-1",
                "document_name": "alpha.pdf",
                "source_anchor": {"format": "pdf", "start_page": 2},
                "display_label": "alpha.pdf p.2",
                "preview_kind": "pdf",
            },
            {
                "citation_key": "c1",
                "document_id": "doc-1",
                "document_name": "alpha.pdf",
                "source_anchor": {"format": "pdf", "start_page": 2},
                "display_label": "alpha.pdf p.2",
                "preview_kind": "pdf",
            },
        ],
        "nested": {
            "source": {
                "citation_key": "c2",
                "document_id": "doc-2",
                "document_name": "beta.txt",
                "source_anchor": {"format": "txt", "start_line": 4},
                "display_label": "beta.txt line 4",
                "preview_kind": "text",
            }
        },
    }

    citations = citation_events_from_tool_result(result)

    assert [citation["citation_key"] for citation in citations] == ["c1", "c2"]
    assert citations[0]["source_anchor"] == {"format": "pdf", "start_page": 2}
    assert citations[1]["preview_kind"] == "text"


def test_dedupe_citations_keeps_same_key_on_different_anchors() -> None:
    citations = [
        {
            "citation_key": "coarse-key",
            "document_id": "doc-a",
            "document_name": "alpha.pdf",
            "source_anchor": {"format": "pdf", "start_page": 1},
            "display_label": "alpha.pdf p.1",
            "preview_kind": "pdf",
        },
        {
            "citation_key": "coarse-key",
            "document_id": "doc-a",
            "document_name": "alpha.pdf",
            "source_anchor": {"format": "pdf", "start_page": 2},
            "display_label": "alpha.pdf p.2",
            "preview_kind": "pdf",
        },
    ]

    assert [item["display_label"] for item in dedupe_citations(citations)] == [
        "alpha.pdf p.1",
        "alpha.pdf p.2",
    ]


def test_citation_events_keep_same_key_on_different_anchors() -> None:
    result = {
        "citations": [
            {
                "citation_key": "coarse-key",
                "document_id": "doc-a",
                "document_name": "alpha.pdf",
                "source_anchor": {"format": "pdf", "start_page": 1},
                "display_label": "alpha.pdf p.1",
                "preview_kind": "pdf",
            },
            {
                "citation_key": "coarse-key",
                "document_id": "doc-a",
                "document_name": "alpha.pdf",
                "source_anchor": {"format": "pdf", "start_page": 2},
                "display_label": "alpha.pdf p.2",
                "preview_kind": "pdf",
            },
        ]
    }

    assert [
        item["display_label"] for item in citation_events_from_tool_result(result)
    ] == ["alpha.pdf p.1", "alpha.pdf p.2"]


def test_dedupe_citations_ignores_display_label_when_anchor_matches() -> None:
    citations = [
        {
            "citation_key": "c-alpha",
            "document_id": "doc-a",
            "document_name": "alpha.pdf",
            "source_anchor": {"format": "pdf", "start_page": 1},
            "display_label": "alpha.pdf p.1",
            "preview_kind": "pdf",
        },
        {
            "citation_key": "c-alpha",
            "document_id": "doc-a",
            "document_name": "alpha.pdf",
            "source_anchor": {"format": "pdf", "start_page": 1},
            "display_label": "Alpha page one",
            "preview_kind": "pdf",
        },
    ]

    assert [item["display_label"] for item in dedupe_citations(citations)] == [
        "alpha.pdf p.1"
    ]


def test_dedupe_citations_uses_document_id_anchor_when_document_name_varies() -> None:
    citations = [
        {
            "citation_key": "c-alpha-a",
            "document_id": "doc-a",
            "document_name": "alpha.pdf",
            "source_anchor": {"format": "pdf", "start_page": 1},
            "display_label": "alpha.pdf p.1",
            "preview_kind": "pdf",
        },
        {
            "citation_key": "c-alpha-b",
            "document_id": "doc-a",
            "document_name": "Alpha Report",
            "source_anchor": {"format": "pdf", "start_page": 1},
            "display_label": "Alpha Report page one",
            "preview_kind": "pdf",
        },
    ]

    assert [item["display_label"] for item in dedupe_citations(citations)] == [
        "alpha.pdf p.1"
    ]


def test_citation_events_dedupes_explicit_and_candidate_for_same_anchor() -> None:
    result = {
        "matches": [
            {
                "citation_key": "explicit-key",
                "doc_id": "doc-a",
                "doc_name": "alpha.pdf",
                "source_anchor": {"format": "pdf", "start_page": 3},
                "display_label": "alpha.pdf p.3",
                "preview_kind": "pdf",
                "snippet": "same source",
            }
        ]
    }

    citations = citation_events_from_tool_result(result)

    assert [
        (item["citation_key"], item["document_id"], item["source_anchor"])
        for item in citations
    ] == [
        ("explicit-key", "doc-a", {"format": "pdf", "start_page": 3})
    ]


def test_dedupe_citations_keeps_xlsx_rows_on_different_sheets() -> None:
    citations = [
        {
            "citation_key": "sales-row",
            "document_id": "doc-sales",
            "document_name": "sales.xlsx",
            "source_anchor": {
                "format": "xlsx",
                "unit_type": "row_range",
                "sheet": "North",
                "start_row": 1,
                "end_row": 2,
            },
            "display_label": "North rows 1-2",
            "preview_kind": "xlsx",
        },
        {
            "citation_key": "sales-row",
            "document_id": "doc-sales",
            "document_name": "sales.xlsx",
            "source_anchor": {
                "format": "xlsx",
                "unit_type": "row_range",
                "sheet": "South",
                "start_row": 1,
                "end_row": 2,
            },
            "display_label": "South rows 1-2",
            "preview_kind": "xlsx",
        },
    ]

    assert [item["display_label"] for item in dedupe_citations(citations)] == [
        "North rows 1-2",
        "South rows 1-2",
    ]


def test_normalize_citation_preserves_anchor_and_preview_kind() -> None:
    citation = normalize_citation(
        {
            "citation_key": "c3",
            "document_id": "doc-3",
            "document_name": "gamma.docx",
            "source_anchor": {"format": "docx", "start_paragraph": 8},
            "display_label": "gamma.docx paragraph 8",
            "preview_kind": "docx",
        }
    )

    assert citation["citation_key"] == "c3"
    assert citation["document_id"] == "doc-3"
    assert citation["source_anchor"] == {"format": "docx", "start_paragraph": 8}
    assert citation["preview_kind"] == "docx"
    assert citation["display_label"] == "gamma.docx paragraph 8"


def test_normalize_citation_accepts_tool_result_aliases() -> None:
    citation = normalize_citation(
        {
            "doc_id": "doc-4",
            "doc_name": "orders.xlsx",
            "source_anchor": {
                "format": "xlsx",
                "unit_type": "row_range",
                "start_row": 12,
                "end_row": 14,
            },
            "display_label": "orders.xlsx rows 12-14",
        }
    )

    assert citation["document_id"] == "doc-4"
    assert citation["document_name"] == "orders.xlsx"
    assert citation["preview_kind"] == "xlsx"
    assert citation["display_label"] == "orders.xlsx rows 12-14"


def test_citation_events_from_document_tool_shapes() -> None:
    result = {
        "documents": [
            {
                "doc_id": "doc-1",
                "name": "alpha.pdf",
                "file_type": ".pdf",
                "page_count": 12,
            }
        ],
        "data": {
            "doc_id": "doc-2",
            "doc_name": "beta.pdf",
            "pages": [
                {
                    "page_num": 3,
                    "node_title": "Budget",
                    "source_anchor": {
                        "format": "pdf",
                        "unit_type": "page",
                        "start_page": 3,
                        "end_page": 3,
                    },
                }
            ],
        },
        "matches": [
            {
                "doc_id": "doc-3",
                "doc_name": "gamma.md",
                "title": "Install",
                "snippet": "Run the installer.",
                "source_anchor": {
                    "format": "markdown",
                    "unit_type": "line",
                    "start_line": 8,
                    "end_line": 12,
                },
                "display_label": "gamma.md lines 8-12",
            }
        ],
    }

    citations = citation_events_from_tool_result(result)

    assert [
        (citation["document_id"], citation["document_name"], citation["preview_kind"])
        for citation in citations
    ] == [
        ("doc-2", "beta.pdf", "pdf"),
        ("doc-3", "gamma.md", "markdown"),
    ]
    assert citations[0]["source_anchor"]["start_page"] == 3
    assert citations[1]["display_label"] == "gamma.md lines 8-12"


def test_citation_events_from_web_search_results() -> None:
    result = {
        "results": [
            {
                "title": "Beijing weather forecast",
                "url": "https://weather.example/beijing",
                "snippet": "Sunny and warm.",
            }
        ]
    }

    citations = citation_events_from_tool_result(result)

    assert len(citations) == 1
    assert citations[0]["preview_kind"] == "web"
    assert citations[0]["document_id"] == "https://weather.example/beijing"
    assert citations[0]["document_name"] == "Beijing weather forecast"
    assert citations[0]["source_anchor"] == {
        "format": "web",
        "url": "https://weather.example/beijing",
    }


def test_citation_events_dedupes_web_sources_by_url_identity() -> None:
    result = {
        "results": [
            {
                "title": "Beijing weather forecast",
                "url": "https://weather.example/beijing",
                "snippet": "Sunny and warm.",
            },
            {
                "title": "Weather in Beijing today",
                "url": "https://weather.example/beijing",
                "snippet": "Same URL from another result block.",
            },
        ]
    }

    citations = citation_events_from_tool_result(result)

    assert [(item["document_name"], item["document_id"]) for item in citations] == [
        ("Beijing weather forecast", "https://weather.example/beijing")
    ]


def test_citation_events_rejects_unsafe_web_urls() -> None:
    result = {
        "results": [
            {
                "title": "Unsafe",
                "url": "javascript:alert(1)",
            },
            {
                "title": "Data URL",
                "url": "data:text/html,<script>alert(1)</script>",
            },
        ]
    }

    assert citation_events_from_tool_result(result) == []


def test_citation_events_rejects_unsafe_nested_web_citations() -> None:
    result = {
        "citations": [
            {
                "citation_key": "bad-web",
                "document_name": "Unsafe",
                "document_id": "javascript:alert(1)",
                "source_anchor": {
                    "format": "web",
                    "url": "javascript:alert(1)",
                },
                "display_label": "Unsafe",
                "preview_kind": "web",
            }
        ]
    }

    assert citation_events_from_tool_result(result) == []


def test_citation_events_rejects_unsafe_nested_web_citations_case_insensitive() -> None:
    result = {
        "citations": [
            {
                "citation_key": "bad-web-uppercase",
                "document_name": "Unsafe",
                "document_id": "javascript:alert(1)",
                "source_anchor": {
                    "format": "WEB",
                    "url": "javascript:alert(1)",
                },
                "display_label": "Unsafe",
                "preview_kind": "WEB",
            }
        ]
    }

    assert citation_events_from_tool_result(result) == []
