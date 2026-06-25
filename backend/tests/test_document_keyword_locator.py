from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.document_keyword_locator import locate_keywords_in_index


def test_keyword_locator_prefers_exact_phrase_over_loose_terms() -> None:
    index = {
        "pages": [
            {"page": 1, "text": "华东收入增长来自渠道调整，复购率保持稳定。"},
            {"page": 2, "text": "收入稳定增长，但未提到华东这个地区。"},
        ],
        "structure": [],
    }

    result = locate_keywords_in_index(
        index_data=index,
        query="在哪一页提到了华东收入增长？",
        doc_id="doc-a",
        doc_name="sales.pdf",
    )

    assert result["search_method"] == "keyword_exact"
    assert result["matches"][0]["page"] == 1
    assert result["matches"][0]["matched_terms"]
    assert result["matches"][0]["match_type"] in {"exact_phrase", "keyword"}
    assert "华东收入增长" in result["matches"][0]["snippet"]


def test_keyword_locator_uses_ocr_text_for_matching_but_omits_visual_snippet() -> None:
    index = {
        "pages": [
            {
                "page": 3,
                "text": "OCR text: 华东收入增长 20%",
                "images": [{"image_path": "page://doc-a/3", "page": 3}],
                "ocr_used": True,
            }
        ],
        "page_text_map_ocr_pages": [3],
        "structure": [],
    }

    result = locate_keywords_in_index(
        index_data=index,
        query="华东收入增长",
        doc_id="doc-a",
        doc_name="scan.pdf",
    )

    match = result["matches"][0]
    assert match["page"] == 3
    assert match["match_type"] == "ocr_keyword"
    assert match["visual_evidence_required"] is True
    assert match["text_omitted_reason"] == "visual_evidence_required"
    assert "snippet" not in match
    assert "OCR text" not in str(result)
    assert match["image_refs"][0]["image_path"] == "page://doc-a/3"
    assert match["next_tool"] == "get_page_image"


def test_keyword_locator_returns_empty_matches_without_semantic_fallback() -> None:
    result = locate_keywords_in_index(
        index_data={"pages": [{"page": 1, "text": "完全无关"}], "structure": []},
        query="华东收入增长",
        doc_id="doc-a",
        doc_name="sales.pdf",
    )

    assert result["matches"] == []
    assert result["search_method"] == "keyword_exact"


def test_keyword_locator_uses_physical_page_when_logical_page_exceeds_pdf_page_count() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 44,
            "structure": [
                {
                    "title": "40 重庆银行数智员工重塑按揭贷款服务",
                    "page": 79,
                    "logical_page": 79,
                    "raw_page_label": 79,
                    "physical_index": 42,
                    "start_index": 42,
                    "text": "重庆银行数智员工重塑按揭贷款服务 使用数智员工处理按揭贷款。",
                    "children": [],
                }
            ],
        },
        query="重庆银行数智员工重塑按揭贷款服务",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert result["matches"][0]["page"] == 42
    assert result["matches"][0]["page_num"] == 42
    assert result["matches"][0]["source_anchor"]["start_page"] == 42
    assert result["matches"][0]["display_label"] == "cases.pdf p.42"


def test_keyword_locator_drops_structure_nodes_without_valid_physical_page() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 44,
            "structure": [
                {
                    "title": "40 重庆银行数智员工重塑按揭贷款服务",
                    "page": 79,
                    "logical_page": 79,
                    "text": "重庆银行数智员工重塑按揭贷款服务",
                    "children": [],
                }
            ],
        },
        query="重庆银行数智员工重塑按揭贷款服务",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert result["matches"] == []


def test_keyword_locator_does_not_treat_in_range_logical_page_as_physical_page() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 100,
            "structure": [
                {
                    "title": "05 逻辑页在范围内但没有物理映射",
                    "page": 5,
                    "logical_page": 5,
                    "raw_page_label": 5,
                    "text": "逻辑页在范围内但没有物理映射",
                    "children": [],
                }
            ],
        },
        query="逻辑页在范围内但没有物理映射",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert result["matches"] == []


def test_keyword_locator_does_not_map_child_text_to_parent_section_page() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 20,
            "structure": [
                {
                    "title": "AI+产业发展",
                    "physical_index": 3,
                    "start_index": 3,
                    "text": "AI+产业发展\n06 AI赋能规章制度管理及合同审核\n这里是子章节聚合文本。",
                    "children": [
                        {
                            "title": "06 AI赋能规章制度管理及合同审核",
                            "physical_index": 8,
                            "start_index": 8,
                            "text": "AI赋能规章制度管理及合同审核 介绍制度管理和合同审核。",
                            "children": [],
                        }
                    ],
                }
            ],
        },
        query="AI赋能规章制度管理及合同审核",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert [match["page"] for match in result["matches"]] == [8]


def test_keyword_locator_exact_phrase_ignores_inline_punctuation() -> None:
    result = locate_keywords_in_index(
        index_data={
            "pages": [
                {
                    "page": 31,
                    "text": '29 重庆大学AI辅导员"润欣" 面向学生服务。',
                }
            ],
            "structure": [],
        },
        query="重庆大学AI辅导员润欣",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert result["matches"][0]["page"] == 31
    assert result["matches"][0]["match_type"] == "exact_phrase"


def test_keyword_locator_prefers_substantive_pages_over_toc_pages() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 12,
            "structure": [
                {
                    "title": "Preface",
                    "physical_index": 1,
                    "start_index": 1,
                    "text": (
                        "目录 01 渝车出海——汽车全球化智慧交互体验与服务模式创新 01 "
                        "06 AI赋能规章制度管理及合同审核 11"
                    ),
                    "children": [],
                },
                {
                    "title": "06 AI赋能规章制度管理及合同审核",
                    "physical_index": 8,
                    "start_index": 8,
                    "text": "AI赋能规章制度管理及合同审核 介绍制度管理和合同审核。",
                    "children": [],
                },
            ],
        },
        query="AI赋能规章制度管理及合同审核",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert [match["page"] for match in result["matches"]] == [8]


def test_keyword_locator_suppresses_loose_keyword_matches_when_exact_phrase_exists() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 20,
            "structure": [
                {
                    "title": "39 全链路消费信贷协同决策与智能风控服务",
                    "physical_index": 12,
                    "start_index": 12,
                    "text": "全链路消费信贷协同决策与智能风控服务 提升风控效率。",
                    "children": [],
                },
                {
                    "title": "13 基于企业智脑的AI Agent数字员工",
                    "physical_index": 15,
                    "start_index": 15,
                    "text": "平台通过全链路协同决策与智能服务支撑其他业务。",
                    "children": [],
                },
            ],
        },
        query="全链路消费信贷协同决策与智能风控服务",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert [match["page"] for match in result["matches"]] == [12]


def test_keyword_locator_prefers_title_exact_hits_over_body_carryover() -> None:
    result = locate_keywords_in_index(
        index_data={
            "page_count": 20,
            "structure": [
                {
                    "title": "05 基于仿生运动与防爆技术的防爆四足机器人在高危领域的安全巡检应用",
                    "physical_index": 7,
                    "start_index": 7,
                    "text": "上一案例结尾。06 AI赋能规章制度管理及合同审核 长安汽车金融有限公司。",
                    "children": [],
                },
                {
                    "title": "06 AI赋能规章制度管理及合同审核",
                    "physical_index": 8,
                    "start_index": 8,
                    "text": "AI赋能规章制度管理及合同审核 介绍制度管理和合同审核。",
                    "children": [],
                },
            ],
        },
        query="AI赋能规章制度管理及合同审核",
        doc_id="doc-a",
        doc_name="cases.pdf",
    )

    assert [match["page"] for match in result["matches"]] == [8]
