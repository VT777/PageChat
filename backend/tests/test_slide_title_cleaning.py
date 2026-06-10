from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.slide_outline_extractor import clean_slide_bookmark_title


def test_clean_slide_bookmark_title_removes_slide_prefix() -> None:
    assert (
        clean_slide_bookmark_title("幻灯片 13: 全球重点行业人工智能渗透率")
        == "全球重点行业人工智能渗透率"
    )
    assert clean_slide_bookmark_title("Slide 7: Market Overview") == "Market Overview"


def test_clean_slide_bookmark_title_returns_empty_for_bare_slide_label() -> None:
    assert clean_slide_bookmark_title("幻灯片 2") == ""
    assert clean_slide_bookmark_title("默认节") == ""
