from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.providers.code_toc_provider import CodeTocProvider


def test_bookmark_code_toc_provider_returns_frozen_skeleton():
    analysis = {
        "page_count": 30,
        "code_toc": {
            "source": "bookmarks",
            "items": [
                {"title": "1 Intro", "level": 1, "physical_index": 2},
                {"title": "1.1 Scope", "level": 2, "physical_index": 4},
                {"title": "2 Market", "level": 1, "physical_index": 10},
            ],
        },
    }

    result = CodeTocProvider().run(analysis)

    assert result["type"] == "toc_skeleton"
    assert result["source"] == "bookmarks"
    assert result["skeleton_valid"] is True
    assert result["page_mapping_valid"] is True
    assert result["authoritative_top_level"] is True


def test_regex_code_toc_provider_rejects_year_like_false_positive():
    analysis = {
        "page_count": 68,
        "code_toc": {
            "source": "regex",
            "items": [
                {"title": "AI in 2025", "level": 1, "physical_index": 2025},
                {"title": "AI in 2026", "level": 1, "physical_index": 2026},
                {"title": "AI in 2027", "level": 1, "physical_index": 2027},
            ],
        },
    }

    result = CodeTocProvider().run(analysis)

    assert result is None
    assert analysis["code_toc_reject_reason"] == "weak_regex_page_values"


def test_regex_code_toc_provider_accepts_reasonable_unique_mapping():
    analysis = {
        "page_count": 80,
        "code_toc": {
            "source": "regex",
            "items": [
                {"title": "1 Intro", "level": 1, "physical_index": 3},
                {"title": "2 Market", "level": 1, "physical_index": 12},
                {"title": "3 Models", "level": 1, "physical_index": 28},
                {"title": "4 Applications", "level": 1, "physical_index": 50},
            ],
        },
    }

    result = CodeTocProvider().run(analysis)

    assert result is not None
    assert result["source"] == "regex"
    assert result["page_mapping_valid"] is True


def test_code_toc_provider_rejects_slide_export_bookmarks():
    items = [
        {"title": "幻灯片 1", "level": 1, "physical_index": 1},
        {"title": "幻灯片 2", "level": 1, "physical_index": 2},
        {"title": "幻灯片 3", "level": 1, "physical_index": 3},
    ]
    analysis = {
        "page_count": 10,
        "text_coverage": 0.1,
        "image_coverage": 0.9,
        "code_toc": {"source": "bookmarks", "items": items},
    }

    result = CodeTocProvider().run(analysis)

    assert result is None
    assert analysis["code_toc_reject_reason"] == "weak_slide_bookmarks"
