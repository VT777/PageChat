from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.toc_contracts import (
    is_auxiliary_section_kind,
    normalize_toc_draft,
    normalize_toc_draft_item,
)


def test_normalize_toc_draft_item_preserves_raw_page_label_without_physical_page() -> None:
    item = normalize_toc_draft_item(
        {
            "title": "第一章 总则",
            "level": 1,
            "page": "I-3",
            "physical_index": 12,
        },
        default_section_kind="main_toc",
        source_page=2,
    )

    assert item["title"] == "第一章 总则"
    assert item["level"] == 1
    assert item["raw_page_label"] == "I-3"
    assert item["section_kind"] == "main_toc"
    assert item["source_page"] == 2
    assert "physical_index" not in item


@pytest.mark.parametrize(
    ("raw_kind", "expected"),
    [
        ("main", "main_toc"),
        ("figure", "figure_toc"),
        ("figures", "figure_toc"),
        ("table", "table_toc"),
        ("tables", "table_toc"),
        ("unknown", "other_toc"),
        ("", "main_toc"),
    ],
)
def test_normalize_toc_draft_item_normalizes_section_kind(raw_kind: str, expected: str) -> None:
    item = normalize_toc_draft_item(
        {"title": "示例", "section_kind": raw_kind},
        default_section_kind="main_toc",
    )

    assert item["section_kind"] == expected


def test_normalize_toc_draft_item_accepts_legacy_page_fields_as_raw_label() -> None:
    with_page = normalize_toc_draft_item(
        {"title": "图 1 架构图", "page": 23},
        default_section_kind="figure_toc",
    )
    with_raw = normalize_toc_draft_item(
        {"title": "表 1 参数表", "raw_page_label": "A-7"},
        default_section_kind="table_toc",
    )

    assert with_page["raw_page_label"] == 23
    assert with_page["section_kind"] == "figure_toc"
    assert with_raw["raw_page_label"] == "A-7"
    assert with_raw["section_kind"] == "table_toc"


def test_normalize_toc_draft_wraps_items_with_source_metadata() -> None:
    draft = normalize_toc_draft(
        [
            {"title": "一、背景", "page": "3"},
            {"title": "二、方法", "page": "8", "source_page": 4},
        ],
        section_kind="main_toc",
        source="visible_toc_rule",
    )

    assert draft["type"] == "toc_draft"
    assert draft["source"] == "visible_toc_rule"
    assert draft["section_kind"] == "main_toc"
    assert [item["raw_page_label"] for item in draft["items"]] == ["3", "8"]
    assert all("physical_index" not in item for item in draft["items"])


def test_is_auxiliary_section_kind() -> None:
    assert is_auxiliary_section_kind("figure_toc") is True
    assert is_auxiliary_section_kind("table_toc") is True
    assert is_auxiliary_section_kind("main_toc") is False
    assert is_auxiliary_section_kind("other_toc") is False
