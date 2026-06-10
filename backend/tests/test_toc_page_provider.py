from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.providers.toc_page_provider import TocPageTextProvider


def test_toc_page_text_provider_preserves_no_page_toc_skeleton():
    analysis = {
        "toc_pages": [2],
        "page_texts": [
            "Cover",
            "Contents\n1 Market overview\n2 Model landscape\n3 Application opportunities\n4 Investment suggestions",
            "Market overview body",
        ],
    }

    result = TocPageTextProvider().run(analysis)

    assert result["type"] == "toc_skeleton"
    assert result["source"] == "toc_page_text"
    assert result["skeleton_valid"] is True
    assert result["page_mapping_valid"] is False
    assert result["has_page_numbers"] is False
    assert result["authoritative_top_level"] is True
    assert [item["title"] for item in result["items"]] == [
        "Market overview",
        "Model landscape",
        "Application opportunities",
        "Investment suggestions",
    ]


def test_toc_page_text_provider_accepts_page_number_mapping_when_present():
    analysis = {
        "toc_pages": [2],
        "page_texts": [
            "Cover",
            "Contents\n1 Market overview .... 3\n2 Model landscape .... 12\n3 Applications .... 25",
        ],
    }

    result = TocPageTextProvider().run(analysis)

    assert result["page_mapping_valid"] is True
    assert [item["physical_index"] for item in result["items"]] == [3, 12, 25]


def test_toc_page_text_provider_ignores_agenda_page():
    analysis = {
        "toc_pages": [2],
        "page_texts": [
            "Cover",
            "Agenda\n01 Market overview\n02 Model landscape\n03 Applications",
        ],
    }

    assert TocPageTextProvider().run(analysis) is None
