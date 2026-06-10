from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.retrieval import RetrievalScope, build_source_display_label


def test_retrieval_scope_requires_user_id() -> None:
    with pytest.raises(ValueError, match="user_id"):
        RetrievalScope(user_id="")


def test_retrieval_scope_distinguishes_user_wide_and_empty_subset() -> None:
    user_wide = RetrievalScope(user_id="user-1")
    empty_subset = RetrievalScope(user_id="user-1", allowed_doc_ids=())

    assert user_wide.allowed_doc_ids is None
    assert empty_subset.allowed_doc_ids == ()
    assert user_wide.cache_key != empty_subset.cache_key


def test_retrieval_scope_cache_key_includes_user_and_sorted_doc_ids() -> None:
    first = RetrievalScope(user_id="user-1", allowed_doc_ids=("b", "a"))
    second = RetrievalScope(user_id="user-1", allowed_doc_ids=("a", "b"))
    other_user = RetrievalScope(user_id="user-2", allowed_doc_ids=("a", "b"))

    assert first.cache_key == second.cache_key
    assert first.cache_key != other_user.cache_key


@pytest.mark.parametrize(
    ("document_name", "anchor", "expected"),
    [
        (
            "report.pdf",
            {"format": "pdf", "unit_type": "page", "start_page": 12, "end_page": 15},
            "report.pdf p.12-15",
        ),
        (
            "notes.md",
            {
                "format": "markdown",
                "unit_type": "line",
                "start_line": 20,
                "end_line": 42,
            },
            "notes.md lines 20-42",
        ),
        (
            "contract.docx",
            {
                "format": "docx",
                "unit_type": "paragraph",
                "start_paragraph": 10,
                "end_paragraph": 18,
            },
            "contract.docx paragraphs 10-18",
        ),
        (
            "sales.xlsx",
            {
                "format": "xlsx",
                "unit_type": "row_range",
                "sheet": "Sheet1",
                "start_row": 2,
                "end_row": 80,
            },
            "sales.xlsx Sheet1 rows 2-80",
        ),
        (
            "deck.pptx",
            {"format": "pptx", "unit_type": "slide", "start_slide": 7, "end_slide": 7},
            "deck.pptx slide 7",
        ),
    ],
)
def test_build_source_display_label(document_name: str, anchor: dict, expected: str) -> None:
    assert build_source_display_label(document_name, anchor) == expected


def test_build_source_display_label_handles_incomplete_anchor() -> None:
    assert build_source_display_label("report.pdf", {"unit_type": "page"}) == (
        "report.pdf source unavailable"
    )
