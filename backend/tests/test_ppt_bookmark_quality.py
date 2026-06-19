from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_slide_export_bookmarks_do_not_make_fast_reliable() -> None:
    analysis = {
        "page_count": 43,
        "text_coverage": 0.3,
        "image_coverage": 1.0,
        "garbled_pages": list(range(43)),
        "code_toc": {
            "source": "bookmarks",
            "items": [
                {"structure": "1", "title": "默认节", "physical_index": 1},
                {"structure": "1.1", "title": "幻灯片 1: 报告封面", "physical_index": 1},
                {"structure": "2", "title": "第一章", "physical_index": 4},
                {"structure": "2.1", "title": "幻灯片 5: 全球人工智能基础能力与市场规模", "physical_index": 5},
                {"structure": "2.2", "title": "幻灯片 6: 美国人工智能基础能力特点分析", "physical_index": 6},
            ],
        },
    }

    assert PageIndexService._has_reliable_code_toc(analysis) is False
    assert PageIndexService._select_initial_execution_mode("smart", analysis) == "balanced"


def test_normal_bookmarks_remain_fast_reliable() -> None:
    analysis = {
        "page_count": 100,
        "text_coverage": 1.0,
        "image_coverage": 0.1,
        "garbled_pages": [],
        "code_toc": {
            "source": "bookmarks",
            "items": [
                {"structure": str(idx), "title": f"Section {idx:02d}", "physical_index": idx + 2}
                for idx in range(1, 81)
            ],
        },
    }

    assert PageIndexService._has_reliable_code_toc(analysis) is True
