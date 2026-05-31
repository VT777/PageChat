"""Tests for fast three-level TOC extraction."""

import os
import re
import json
import pytest
import sys

sys.path.insert(0, "E:/projects/knowclaw_v2_mvp_refactor/backend")

from pageindex.page_index import (
    extract_toc_from_pdf_bookmarks,
    extract_toc_from_link_annotations,
    find_toc_pages_by_rules,
    _levels_to_structure,
    _parse_toc_text_to_items,
    _infer_structure_from_titles,
)

DOC_DIR = "E:/projects/knowclaw_v2_mvp_refactor/backend/data/documents"


class TestLevel1Bookmarks:
    """Level 1: PDF native bookmarks."""

    def test_pdf_with_bookmarks_returns_structured_toc(self):
        """PDF with /Outlines bookmarks should return items with structure/title/physical_index."""
        path = os.path.join(DOC_DIR, "b35ca90f_2025年AI治理报告：回归现实主义.pdf")
        if not os.path.exists(path):
            pytest.skip("Test PDF not available")
        result = extract_toc_from_pdf_bookmarks(path)
        assert result is not None
        assert len(result) >= 3
        assert all(
            "structure" in item and "title" in item and "physical_index" in item
            for item in result
        )

    def test_pdf_without_bookmarks_returns_none(self):
        """PDF without bookmarks should return None."""
        path = os.path.join(
            DOC_DIR,
            "816bdeff_2026年AI Agent智能体技术发展报告.pdf",
        )
        if not os.path.exists(path):
            pytest.skip("Test PDF not available")
        result = extract_toc_from_pdf_bookmarks(path)
        # This PDF has no /Outlines, only link annotations
        assert result is None

    def test_nonexistent_file_returns_none(self):
        result = extract_toc_from_pdf_bookmarks("/nonexistent/path.pdf")
        assert result is None


class TestLevel2LinkAnnotations:
    """Level 2: Link annotation extraction."""

    def test_pdf_with_link_annotations_returns_complete_toc(self):
        """AI Agent report should extract 50+ items via link annotations."""
        path = os.path.join(
            DOC_DIR,
            "816bdeff_2026年AI Agent智能体技术发展报告.pdf",
        )
        if not os.path.exists(path):
            pytest.skip("Test PDF not available")
        result = extract_toc_from_link_annotations(path)
        assert result is not None
        assert len(result) >= 50, f"Expected >= 50 items, got {len(result)}"
        # Should NOT be truncated — last entry should point to late pages
        last_page = max(item["physical_index"] for item in result)
        assert last_page >= 70, (
            f"Expected last page >= 70, got {last_page} (truncated?)"
        )

    def test_nonexistent_file_returns_none(self):
        result = extract_toc_from_link_annotations("/nonexistent/path.pdf")
        assert result is None


class TestLevel3Regex:
    """Level 3: Regex-based TOC page detection."""

    def test_detects_toc_pages_with_standard_format(self):
        toc_page = (
            "第一章 概述..........1\n"
            "1.1 背景..........3\n"
            "1.2 方法..........5\n"
            "第二章 分析..........10\n",
            100,
        )
        non_toc = ("这是正文内容，没有目录格式。", 50)
        page_list = [non_toc, toc_page, toc_page, non_toc, non_toc]
        result = find_toc_pages_by_rules(page_list)
        assert result == [1, 2]

    def test_empty_pages_return_no_toc(self):
        page_list = [("", 0), ("正文内容", 50)]
        result = find_toc_pages_by_rules(page_list)
        assert result == []

    def test_parse_toc_text_extracts_items(self):
        toc_text = "第一章 概述: 1\n1.1 背景介绍: 3\n1.2 研究方法: 5\n第二章 分析: 10\n"
        items = _parse_toc_text_to_items(toc_text)
        assert items is not None
        assert len(items) >= 3


class TestHelpers:
    """Helper functions."""

    def test_levels_to_structure(self):
        items = [
            {"level": 1, "title": "Ch1", "physical_index": 1},
            {"level": 2, "title": "Sec1.1", "physical_index": 2},
            {"level": 2, "title": "Sec1.2", "physical_index": 4},
            {"level": 1, "title": "Ch2", "physical_index": 6},
        ]
        result = _levels_to_structure(items)
        assert result[0]["structure"] == "1"
        assert result[1]["structure"] == "1.1"
        assert result[2]["structure"] == "1.2"
        assert result[3]["structure"] == "2"

    def test_infer_structure_from_numbered_titles(self):
        items = [
            {"title": "1.1 背景", "physical_index": 3},
            {"title": "1.2 方法", "physical_index": 5},
            {"title": "2.1 结果", "physical_index": 10},
        ]
        result = _infer_structure_from_titles(items)
        assert result[0]["structure"] == "1.1"
        assert result[1]["structure"] == "1.2"
        assert result[2]["structure"] == "2.1"
