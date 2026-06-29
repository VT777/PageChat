from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.toc_contracts import (
    TocContractError,
    assert_s4_draft_contract,
    normalize_mapped_toc,
    normalize_toc_draft,
)


def test_toc_draft_allows_raw_page_labels_but_not_final_pages() -> None:
    draft = normalize_toc_draft(
        {
            "source": "llm_toc_page",
            "toc_sections": [
                {
                    "kind": "main_toc",
                    "items": [
                        {"title": "Chapter 1", "level": 1, "raw_page_label": "5"},
                    ],
                }
            ],
        }
    )

    assert draft["type"] == "toc_draft"
    assert draft["toc_sections"][0]["items"][0]["raw_page_label"] == "5"
    assert_s4_draft_contract(draft)


@pytest.mark.parametrize("field", ["physical_index", "start_index", "end_index"])
def test_toc_draft_rejects_final_page_fields(field: str) -> None:
    draft = normalize_toc_draft(
        {
            "source": "bad_builder",
            "items": [
                {"title": "Chapter 1", "level": 1, field: 5},
            ],
        }
    )

    with pytest.raises(TocContractError):
        assert_s4_draft_contract(draft)


def test_mapped_toc_requires_final_page_fields() -> None:
    mapped = normalize_mapped_toc(
        {
            "source": "unified_s5",
            "items": [
                {"title": "Chapter 1", "physical_index": 3, "start_index": 3, "end_index": 8},
            ],
            "mapping_report": {"status": "ok"},
        }
    )

    assert mapped["type"] == "mapped_toc"
    assert mapped["items"][0]["start_index"] == 3


def test_mapped_toc_rejects_unmapped_items() -> None:
    with pytest.raises(TocContractError):
        normalize_mapped_toc(
            {
                "source": "unified_s5",
                "items": [{"title": "Chapter 1", "raw_page_label": "3"}],
                "mapping_report": {"status": "ok"},
            }
        )
