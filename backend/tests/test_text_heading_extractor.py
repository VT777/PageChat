from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.text_heading_extractor import (
    extract_text_headings,
    is_chapter_skeleton_toc,
    merge_chapter_skeleton_with_headings,
    repair_numbered_structures,
)


def test_detects_chapter_skeleton_toc_without_page_numbers():
    toc_text = "\n".join(
        [
            "目录",
            "序言",
            "第一章：发展学生智能素养",
            "第二章：发展教师智能教学素养",
            "第三章：AI创新人才培养范式",
            "第四章：AI促进产教深度融合",
            "第五章：升级智慧校园与管理",
            "第六章：应对人工智能伦理与安全挑战",
            "第七章：强化人工智能应用体制机制与支撑保障",
            "第八章：人工智能重塑职业教育生态：困境与展望",
        ]
    )

    result = is_chapter_skeleton_toc(toc_text)

    assert result["is_skeleton"] is True
    assert result["has_page_numbers"] is False
    assert [item["title"] for item in result["items"][:3]] == [
        "序言",
        "第一章：发展学生智能素养",
        "第二章：发展教师智能教学素养",
    ]


def test_extracts_numbered_headings_from_text_pages():
    page_texts = [
        "目录\n序言\n第一章：发展学生智能素养",
        "序言：研究背景\n时代浪潮\n正文",
        "第一章 发展学生人工智能素养\nn 本章概览\n1.1 紧跟技能人才需求的变化",
        "1.1 紧跟技能人才需求的变化\nn 正文",
        "1.2 精准评估学生人工智能素养水平\nn 正文",
        "1.2 学生智能工具的应用情况\nn 重复编号内页，不应新增结构节点",
        "1.3 提升学生的AI应用体验\nn 正文",
        "1.4 优化学生智能素养发展路径\nn 正文",
        "1.5 优化学生人工智能素养发展环境\n正文",
        "第七章 人工智能应用体制机制与支撑保障\nn 本章概览",
        "7.1 人工智能应用规划和政策制定\nn 正文",
        "8.1 发展师生智能素养\n正文",
        "8.2 融合AI技术与教育\n正文",
        "2.22 2.22 2.22 2.22 2.22",
        "附录一 报告研究方法和过程\n正文",
    ]

    items = extract_text_headings(page_texts, start_page=1)
    by_structure = {item["structure"]: item for item in items}

    assert by_structure["1"]["title"] == "第一章 发展学生人工智能素养"
    assert by_structure["1.3"]["physical_index"] == 7
    assert by_structure["1.4"]["physical_index"] == 8
    assert by_structure["1.5"]["physical_index"] == 9
    assert by_structure["7"]["physical_index"] == 10
    assert by_structure["7.1"]["physical_index"] == 11
    assert by_structure["8.1"]["physical_index"] == 12
    assert by_structure["8.2"]["physical_index"] == 13
    assert by_structure["A1"]["physical_index"] == 15
    assert "2.22" not in by_structure


def test_extracts_english_article_headings_from_body_pages():
    page_texts = [
        "Paper Title\nAuthors\nABSTRACT\nThis paper introduces a method.",
        "Body text\n1.\nINTRODUCTION\nThe problem is important.",
        "2.1\nComputing the EMD\nDetailed method text.",
        "Algorithm 1 FILTER-AND-REFINEMENT FOR k-NN\n1: while ...",
        "5.\nEXPERIMENTAL EVALUATION\nTable 3: Dataset statistics",
        "7.\nCONCLUSION\nWe conclude.",
        "REFERENCES\n[1] Example",
    ]

    items = extract_text_headings(page_texts, start_page=1)
    by_title = {item["title"]: item for item in items}

    assert by_title["ABSTRACT"]["physical_index"] == 1
    assert by_title["1 INTRODUCTION"]["physical_index"] == 2
    assert by_title["2.1 Computing the EMD"]["level"] == 2
    assert "Algorithm 1 FILTER-AND-REFINEMENT FOR k-NN" not in by_title
    assert by_title["5 EXPERIMENTAL EVALUATION"]["physical_index"] == 5
    assert by_title["7 CONCLUSION"]["physical_index"] == 6
    assert by_title["REFERENCES"]["physical_index"] == 7


def test_extracts_multiple_english_headings_from_one_page():
    page_texts = [
        "\n".join(
            [
                "Paper Title",
                "Authors",
                "ABSTRACT",
                "This paper introduces a method.",
                "1.",
                "INTRODUCTION",
                "The problem is important.",
            ]
        ),
        "2.\nPRELIMINARIES\nBody",
        "2.1\nComputing the EMD\nDetailed method text.",
    ]

    items = extract_text_headings(page_texts, start_page=1)
    by_title = {item["title"]: item for item in items}

    assert by_title["ABSTRACT"]["physical_index"] == 1
    assert by_title["1 INTRODUCTION"]["physical_index"] == 1
    assert by_title["2 PRELIMINARIES"]["physical_index"] == 2
    assert by_title["2.1 Computing the EMD"]["level"] == 2


def test_english_heading_extractor_filters_numeric_and_definition_noise():
    page_texts = [
        "178 million Disney+ and Hulu subscriptions, an increase of 0.9 million",
        "0.1 + (-0.6) + 0.9 = 0.4. SSP selects the feasible path",
        "DEFINITION 1\nA technical definition follows.",
        "LEMMA 1 (COST MONOTONICITY OF FEASIBLE PATHS).\nProof follows.",
        "100K 200K 300K 400K 500K",
        "SIA / SSP",
        "PL := PL \u222ap",
        "RETINA, IRMA, PANORAMIO, FRIENDS, and WORLD.11 SIA",
    ]

    items = extract_text_headings(page_texts, start_page=1)

    assert items == []


def test_extracts_late_numbered_english_heading_on_dense_pages():
    page_texts = [
        "\n".join(
            ["Body line"] * 135
            + [
                "5.",
                "EXPERIMENTAL EVALUATION",
                "Body starts here.",
            ]
        ),
        "\n".join(
            ["More body"] * 180
            + [
                "6.",
                "RELATED WORK",
                "Body starts here.",
            ]
        ),
    ]

    items = extract_text_headings(page_texts, start_page=1)
    titles = [item["title"] for item in items]

    assert "5 EXPERIMENTAL EVALUATION" in titles
    assert "6 RELATED WORK" in titles


def test_extracts_financial_release_section_headings():
    page_texts = [
        "February 5, 2025\nTHE WALT DISNEY COMPANY REPORTS\nFIRST QUARTER EARNINGS FOR FISCAL 2025\nBody",
        "Guidance and Outlook:\nBody",
        "SUMMARIZED FINANCIAL RESULTS\nThe following table summarizes results.",
        "DISCUSSION OF FIRST QUARTER SEGMENT RESULTS\nStar India\nBody",
        "OTHER FINANCIAL INFORMATION\nCash flow details",
        "THE WALT DISNEY COMPANY CONDENSED CONSOLIDATED STATEMENTS OF INCOME\nTable",
        "NON-GAAP FINANCIAL MEASURES\nBody",
        "FORWARD-LOOKING STATEMENTS\nBody",
    ]

    items = extract_text_headings(page_texts, start_page=1)
    titles = [item["title"] for item in items]

    assert "THE WALT DISNEY COMPANY REPORTS FIRST QUARTER EARNINGS FOR FISCAL 2025" in titles
    assert "SUMMARIZED FINANCIAL RESULTS" in titles
    assert "DISCUSSION OF FIRST QUARTER SEGMENT RESULTS" in titles
    assert "OTHER FINANCIAL INFORMATION" in titles
    assert "NON-GAAP FINANCIAL MEASURES" in titles
    assert "FORWARD-LOOKING STATEMENTS" in titles


def test_extracts_annual_report_number_line_headings():
    page_texts = [
        "REPORT TO CONGRESS\nAnnual Report",
        "About the Federal Reserve\nThe Federal Reserve was created.",
        "1\nOverview\nThis report covers operations.",
        "2\nMonetary Policy and Economic\nDevelopments\nThe Federal Reserve conducts policy.",
        "3\nFinancial Stability\nMonitoring vulnerabilities.",
        "4\nSupervision and Regulation\nSupervised institutions.",
    ]

    items = extract_text_headings(page_texts, start_page=1)
    by_structure = {item["structure"]: item for item in items}

    assert by_structure["front-2"]["title"] == "About the Federal Reserve"
    assert by_structure["1"]["title"] == "1 Overview"
    assert by_structure["2"]["title"] == "2 Monetary Policy and Economic Developments"
    assert by_structure["3"]["physical_index"] == 5


def test_repair_numbered_structures_uses_title_numbers():
    items = [
        {"structure": "2", "title": "1.3 提升学生的AI应用体验", "physical_index": 12},
        {"structure": "2.1", "title": "1.4 优化学生智能素养发展路径", "physical_index": 17},
        {"structure": "13.1", "title": "第七章 人工智能应用体制机制与支撑保障", "physical_index": 116},
        {"structure": "13.2", "title": "7.1 人工智能应用规划和政策制定", "physical_index": 116},
        {"structure": "16.1", "title": "8.2 融合AI技术与教育", "physical_index": 142},
    ]

    repaired = repair_numbered_structures(items)

    assert [item["structure"] for item in repaired] == [
        "1.3",
        "1.4",
        "7",
        "7.1",
        "8.2",
    ]


def test_merge_chapter_skeleton_with_body_headings_keeps_body_pages():
    skeleton = {
        "is_skeleton": True,
        "items": [
            {"title": "序言", "level": 1},
            {"title": "第一章：发展学生智能素养", "level": 1},
            {"title": "第二章：发展教师智能教学素养", "level": 1},
        ],
    }
    headings = [
        {"structure": "P", "title": "序言：研究背景", "physical_index": 3, "level": 1},
        {"structure": "1", "title": "第一章 发展学生人工智能素养", "physical_index": 5, "level": 1},
        {"structure": "1.1", "title": "1.1 紧跟技能人才需求的变化", "physical_index": 6, "level": 2},
        {"structure": "2.1", "title": "2.1 把握技术创新教学的发展趋势", "physical_index": 35, "level": 2},
    ]

    merged = merge_chapter_skeleton_with_headings(skeleton, headings)
    by_structure = {item["structure"]: item for item in merged}

    assert by_structure["P"]["physical_index"] == 3
    assert by_structure["1"]["title"] == "第一章 发展学生人工智能素养"
    assert by_structure["1.1"]["physical_index"] == 6
    assert by_structure["2"]["title"] == "第二章：发展教师智能教学素养"
    assert by_structure["2"]["physical_index"] == 35
    assert by_structure["2.1"]["physical_index"] == 35
