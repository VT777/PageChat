from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.visual_page_outline_extractor import (
    build_page_title_candidates,
    expand_flat_toc_with_page_titles,
    extract_page_title_candidates,
)


def test_extract_page_title_candidates_filters_footer_noise() -> None:
    page_texts = [
        "",
        "获取更多维度报告数据，请访问亿欧网 www.iyiou.com\n5\n全球人工智能基础能力与市场规模\n数据来源：公开资料",
    ]

    candidates = extract_page_title_candidates(page_texts, start_page=2, end_page=2)

    assert candidates == [
        {
            "title": "全球人工智能基础能力与市场规模",
            "page": 2,
            "physical_index": 2,
            "source": "flat_text_fallback",
            "confidence": 0.45,
            "page_type": "content_slide",
            "reason": "fallback_text_line",
        }
    ]


def test_build_page_title_candidates_uses_structured_evidence() -> None:
    parent = {
        "structure": "2",
        "title": "第二章 AI十大行业技术应用需求洞察",
        "start_index": 11,
        "end_index": 23,
    }
    evidence = [
        {
            "page": 12,
            "primary_role": "content_slide",
            "evidence_spans": [
                {
                    "role": "page_title",
                    "text": "AI垂类行业技术应用价值分析框架",
                    "confidence": 0.88,
                }
            ],
        },
        {
            "page": 13,
            "primary_role": "content_slide",
            "evidence_spans": [
                {
                    "role": "page_title",
                    "text": "全球重点行业人工智能渗透率",
                    "confidence": 0.86,
                }
            ],
        },
    ]

    candidates = build_page_title_candidates(evidence, parent, page_count=43)

    assert [candidate["title"] for candidate in candidates] == [
        "AI垂类行业技术应用价值分析框架",
        "全球重点行业人工智能渗透率",
    ]
    assert candidates[0]["source"] == "structured_evidence"
    assert candidates[0]["page"] == 12
    assert candidates[0]["page_type"] == "content_slide"


def test_expand_flat_toc_with_page_titles_attaches_children_by_range() -> None:
    tree = [
        {
            "structure": "0",
            "title": "Preface",
            "start_index": 1,
            "end_index": 3,
            "nodes": [],
        },
        {
            "structure": "1",
            "title": "第一章 全球人工智能技术发展洞察",
            "start_index": 4,
            "end_index": 10,
            "nodes": [],
        },
        {
            "structure": "2",
            "title": "第二章 AI十大行业技术应用需求洞察",
            "start_index": 11,
            "end_index": 23,
            "nodes": [],
        },
    ]
    page_texts = [""] * 23
    page_texts[3] = "Chapter 1\n第一章 全球人工智能技术发展洞察"
    page_texts[4] = "全球人工智能基础能力与市场规模"
    page_texts[5] = "核心技术演进与融合发展趋势"
    page_texts[10] = "Chapter 2\n第二章 AI十大行业技术应用需求洞察"
    page_texts[11] = "AI垂类行业技术应用价值分析框架"
    page_texts[12] = "全球重点行业人工智能渗透率"
    page_texts[13] = "互联网：以内容为核心的行业典型应用"

    result = expand_flat_toc_with_page_titles(tree, page_texts, page_count=23)

    assert result["added_children"] == 5
    assert result["quality"] == "good"
    assert [child["title"] for child in tree[1]["nodes"]] == [
        "全球人工智能基础能力与市场规模",
        "核心技术演进与融合发展趋势",
    ]
    assert [child["title"] for child in tree[2]["nodes"]] == [
        "AI垂类行业技术应用价值分析框架",
        "全球重点行业人工智能渗透率",
        "互联网：以内容为核心的行业典型应用",
    ]
    assert [child["structure"] for child in tree[2]["nodes"]] == ["2.1", "2.2", "2.3"]
    assert tree[1]["start_index"] == 4
    assert tree[1]["end_index"] == 10


def test_expand_flat_toc_with_page_titles_skips_duplicate_chapter_cover() -> None:
    tree = [
        {
            "structure": "1",
            "title": "第一章 全球人工智能技术发展洞察",
            "start_index": 4,
            "end_index": 6,
            "nodes": [],
        }
    ]
    page_texts = [""] * 6
    page_texts[3] = "Chapter 1\n第一章 全球人工智能技术发展洞察"
    page_texts[4] = "全球人工智能基础能力与市场规模"

    result = expand_flat_toc_with_page_titles(tree, page_texts, page_count=6)

    assert result["added_children"] == 1
    assert [child["title"] for child in tree[0]["nodes"]] == [
        "全球人工智能基础能力与市场规模"
    ]


def test_expand_flat_toc_with_page_titles_reports_bad_quality_for_empty_long_chapter() -> None:
    tree = [
        {
            "structure": "3",
            "title": "第三章 全球人工智能技术应用突破奖",
            "start_index": 24,
            "end_index": 37,
            "nodes": [],
        }
    ]
    page_texts = [""] * 37

    result = expand_flat_toc_with_page_titles(tree, page_texts, page_count=37)

    assert result["added_children"] == 0
    assert result["quality"] == "bad"
    assert result["needs_repair"] is True
    assert result["expected_children"] > result["actual_children"]


def test_expand_flat_toc_with_page_titles_uses_appendix_markers_not_chart_labels() -> None:
    tree = [
        {
            "structure": "P",
            "title": "\u5e8f\u8a00",
            "start_index": 1,
            "end_index": 3,
            "nodes": [],
        },
        {
            "structure": "A1",
            "title": "\u9644\u5f55\u4e00 \u62a5\u544a\u7814\u7a76\u65b9\u6cd5\u548c\u8fc7\u7a0b",
            "start_index": 169,
            "end_index": 174,
            "nodes": [],
        },
    ]
    page_texts = [""] * 174
    page_texts[0] = "\u5e8f\u8a00\n\u804c\u4e1a\u6559\u80b2\u4eba\u5de5\u667a\u80fd"
    page_texts[168] = (
        "\u9644\u5f55\u4e00 \u62a5\u544a\u7814\u7a76\u65b9\u6cd5\u548c\u8fc7\u7a0b\n"
        "n \u6982\u5ff5\u5b9a\u4e49\u53ca\u7406\u8bba\u4f9d\u636e\n"
        "\u6280\u672f\u73af\u5883"
    )
    page_texts[171] = (
        "\u9644\u5f55\u4e00 \u62a5\u544a\u7814\u7a76\u65b9\u6cd5\u548c\u8fc7\u7a0b\n"
        "n \u5b66\u6821\u95ee\u5377\u7ed3\u6784\n"
        "\u6280\u672f\u73af\u5883\n"
        "\u7b97\u529b\u57fa\u7840\u8bbe\u65bd"
    )
    page_texts[172] = (
        "\u9644\u5f55\u4e00 \u62a5\u544a\u7814\u7a76\u65b9\u6cd5\u548c\u8fc7\u7a0b\n"
        "n \u5b66\u751f\u95ee\u5377\u7ed3\u6784\n"
        "\u6280\u672f\u73af\u5883\n"
        "\u77e5\u9053\u4e0e\u7406\u89e3"
    )
    page_texts[173] = (
        "\u9644\u5f55\u4e00 \u62a5\u544a\u7814\u7a76\u65b9\u6cd5\u548c\u8fc7\u7a0b\n"
        "n \u6559\u5e08\u95ee\u5377\u7ed3\u6784\n"
        "\u667a\u80fd\u7d20\u517b\n"
        "\u77e5\u9053\u4e0e\u7406\u89e3"
    )

    result = expand_flat_toc_with_page_titles(tree, page_texts, page_count=174)

    appendix_children = tree[1]["nodes"]
    assert tree[0]["nodes"] == []
    assert [child["title"] for child in appendix_children] == [
        "\u6982\u5ff5\u5b9a\u4e49\u53ca\u7406\u8bba\u4f9d\u636e",
        "\u5b66\u6821\u95ee\u5377\u7ed3\u6784",
        "\u5b66\u751f\u95ee\u5377\u7ed3\u6784",
        "\u6559\u5e08\u95ee\u5377\u7ed3\u6784",
    ]
    assert {child["source"] for child in appendix_children} == {"appendix_heading"}
    assert result["source_distribution"]["appendix_heading"] == 4


def test_expand_flat_toc_with_page_titles_skips_appendix_back_matter() -> None:
    tree = [
        {
            "structure": "A3",
            "title": "\u9644\u5f55\u4e09 \u804c\u4e1a\u9662\u6821\u4eba\u5de5\u667a\u80fd\u5e94\u7528\u5c31\u7eea\u5ea6\u6307\u6570\u62a5\u544a",
            "start_index": 200,
            "end_index": 201,
            "nodes": [],
        }
    ]
    page_texts = [""] * 201
    page_texts[199] = (
        "\u4e2d\u56fd\u667a\u6167\u6559\u80b2\u533a\u57df\u53d1\u5c55\u7814\u7a76\u62a5\u544a\n"
        "\u8c22\u8c22\u9605\u8bfb\uff01"
    )
    page_texts[200] = (
        "\u7f16\u5236\u5355\u4f4d\uff1a\u300a\u4e2d\u56fd\u6559\u80b2\u4fe1\u606f\u5316\u300b\u6742\u5fd7\u793e\n"
        "\u7f16\u5236\u6307\u5bfc\uff1a"
    )

    result = expand_flat_toc_with_page_titles(tree, page_texts, page_count=201)

    assert result["added_children"] == 0
    assert tree[0]["nodes"] == []
