import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import page_index as page_index_module


class _Logger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


def test_detect_page_index_rejects_ambiguous_suffix_numbers(monkeypatch) -> None:
    sample = "目录 国外大厂AI应用落地01 国内大厂AI应用落地02 产业链梳理03 风险提示04"
    monkeypatch.setattr(page_index_module, "ChatGPT_API", lambda *_a, **_k: "{}")
    monkeypatch.setattr(
        page_index_module,
        "extract_json",
        lambda *_a, **_k: {"page_index_given_in_toc": "yes"},
    )

    result = page_index_module.detect_page_index(sample)
    assert result == "no"


def test_process_toc_with_page_numbers_requires_strong_page_anchor(monkeypatch) -> None:
    toc_items = [
        {"structure": "1", "title": "A", "page": 1},
        {"structure": "2", "title": "B", "page": 2},
        {"structure": "3", "title": "C", "page": 3},
        {"structure": "4", "title": "D", "page": 4},
    ]
    toc_with_only_one_anchor = [
        {"structure": "1", "title": "A", "physical_index": "<physical_index_4>"},
        {"structure": "2", "title": "B", "physical_index": None},
        {"structure": "3", "title": "C", "physical_index": None},
        {"structure": "4", "title": "D", "physical_index": None},
    ]
    page_list = [("正文", 10) for _ in range(12)]

    monkeypatch.setattr(
        page_index_module, "toc_transformer", lambda *_a, **_k: toc_items
    )
    monkeypatch.setattr(page_index_module, "remove_page_number", lambda x: x)
    monkeypatch.setattr(
        page_index_module,
        "toc_index_extractor",
        lambda *_a, **_k: toc_with_only_one_anchor,
    )
    monkeypatch.setattr(page_index_module, "convert_physical_index_to_int", lambda x: x)
    monkeypatch.setattr(
        page_index_module,
        "extract_matching_page_pairs",
        lambda *_a, **_k: [{"title": "A", "page": 1, "physical_index": 4}],
    )
    monkeypatch.setattr(page_index_module, "calculate_page_offset", lambda *_a, **_k: 3)
    monkeypatch.setattr(
        page_index_module, "add_page_offset_to_toc_json", lambda x, _o: x
    )
    monkeypatch.setattr(
        page_index_module, "process_none_page_numbers", lambda x, *_a, **_k: x
    )

    with pytest.raises(ValueError, match="TOC_PAGE_MAPPING_WEAK"):
        page_index_module.process_toc_with_page_numbers(
            toc_content="toc",
            toc_page_list=[2],
            page_list=page_list,
            toc_check_page_num=8,
            model="x",
            logger=_Logger(),
        )


def test_tree_parser_fast_rejects_toc_without_clear_page_numbers(monkeypatch) -> None:
    monkeypatch.setattr(
        page_index_module,
        "check_toc",
        lambda *_a, **_k: {
            "toc_content": "目录 ...",
            "toc_page_list": [2],
            "page_index_given_in_toc": "no",
        },
    )

    opt = SimpleNamespace(index_mode="fast", model="qwen3.6-flash")
    page_list = [("正文", 5), ("正文", 5)]

    with pytest.raises(ValueError, match="FAST_TOC_INCOMPLETE"):
        asyncio.run(page_index_module.tree_parser(page_list, opt, logger=_Logger()))


def test_assess_no_toc_range_quality_penalizes_single_page_collapse() -> None:
    toc = [
        {"title": "A", "physical_index": 3},
        {"title": "B", "physical_index": 3},
        {"title": "C", "physical_index": 3},
        {"title": "D", "physical_index": 3},
    ]
    q = page_index_module._assess_no_toc_range_quality(toc, page_count=21)
    assert q["score"] < 0.6
    assert "dominant_single_page" in "|".join(q["issues"])


def test_assess_no_toc_range_quality_accepts_well_spread_pages() -> None:
    toc = [
        {"title": "A", "physical_index": 3},
        {"title": "B", "physical_index": 7},
        {"title": "C", "physical_index": 12},
        {"title": "D", "physical_index": 16},
    ]
    q = page_index_module._assess_no_toc_range_quality(toc, page_count=21)
    assert q["score"] >= 0.8


def test_fix_incorrect_toc_tolerates_missing_physical_index_result(monkeypatch) -> None:
    toc = [{"title": "A", "physical_index": 1}]
    incorrect = [{"list_index": 0, "title": "A", "page_number": 1}]

    monkeypatch.setattr(page_index_module, "detect_divider_pages_robust", lambda *_a: [])

    async def _broken_fixer(*_args, **_kwargs):
        return None

    async def _missing_physical_index_check(*_args, **_kwargs):
        return {"answer": "yes"}

    monkeypatch.setattr(page_index_module, "single_toc_item_index_fixer", _broken_fixer)
    monkeypatch.setattr(page_index_module, "check_title_appearance", _missing_physical_index_check)

    fixed, invalid = asyncio.run(
        page_index_module.fix_incorrect_toc(
            toc,
            [("A body", 1)],
            incorrect,
            start_index=1,
            logger=_Logger(),
        )
    )

    assert fixed[0]["physical_index"] == 1
    assert invalid == [{"list_index": 0, "title": "A", "physical_index": 1}]
