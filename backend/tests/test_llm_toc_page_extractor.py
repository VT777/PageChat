from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_normalize_llm_toc_payload_merges_standalone_markers_with_titles() -> None:
    from pageindex.candidates.llm_toc_page_extractor import normalize_llm_toc_payload

    extraction = normalize_llm_toc_payload(
        {
            "toc_items": [
                {"title": "汇报提纲", "level": 1, "page": None},
                {"title": "AI驱动的第五科研范式", "level": 1, "page": None},
                {"title": "一", "level": 1, "page": None},
                {"title": "百花齐放的大模型时代", "level": 1, "page": None},
                {"title": "二", "level": 1, "page": None},
                {"title": "大模型辅助的科学假设生成", "level": 1, "page": None},
                {"title": "三", "level": 1, "page": None},
                {"title": "未来科研范式展望", "level": 1, "page": None},
                {"title": "五", "level": 1, "page": None},
                {"title": "大模型辅助的论文与项目", "level": 1, "page": None},
                {"title": "四", "level": 1, "page": None},
            ]
        }
    )

    assert [item["title"] for item in extraction.items] == [
        "一 AI驱动的第五科研范式",
        "二 百花齐放的大模型时代",
        "三 大模型辅助的科学假设生成",
        "四 大模型辅助的论文与项目",
        "五 未来科研范式展望",
    ]
    assert [item["structure"] for item in extraction.items] == ["一", "二", "三", "四", "五"]
    assert extraction.has_printed_page_numbers is False


def test_normalize_llm_toc_payload_preserves_typed_toc_sections() -> None:
    from pageindex.candidates.llm_toc_page_extractor import (
        build_llm_toc_prompt,
        normalize_llm_toc_payload,
    )

    prompt = build_llm_toc_prompt([{"page": 2, "text": "目录\nChapter A 4\n图目录\nFigure 1 5"}])
    assert "toc_sections" in prompt
    assert "figure_toc" in prompt
    assert "toc_items" not in prompt

    extraction = normalize_llm_toc_payload(
        {
            "toc_sections": [
                {
                    "kind": "main_toc",
                    "title": "目录",
                    "items": [{"title": "Chapter A", "level": 1, "page": 4}],
                },
                {
                    "kind": "figure_toc",
                    "title": "图目录",
                    "items": [{"title": "Figure 1", "level": 1, "page": 5}],
                },
            ]
        }
    )

    assert [section["kind"] for section in extraction.toc_sections] == ["main_toc", "figure_toc"]
    assert [item["section_kind"] for item in extraction.items] == ["main_toc", "figure_toc"]
    assert extraction.has_printed_page_numbers is True


def test_normalize_llm_toc_payload_dedupes_repeated_marker_sections() -> None:
    from pageindex.candidates.llm_toc_page_extractor import normalize_llm_toc_payload

    extraction = normalize_llm_toc_payload(
        {
            "toc_items": [
                {"title": "AI驱动的第五科研范式", "level": 1},
                {"title": "一", "level": 1},
                {"title": "百花齐放的大模型时代", "level": 1},
                {"title": "二", "level": 1},
                {"title": "未来科研范式展望", "level": 1},
                {"title": "五", "level": 1},
                {"title": "大模型辅助的论文与项目", "level": 1},
                {"title": "四", "level": 1},
                {"title": "AI驱动的第五科研范式", "level": 1},
                {"title": "一", "level": 1},
                {"title": "百花齐放的大模型时代", "level": 1},
                {"title": "二", "level": 1},
                {"title": "未来科研范式展望", "level": 1},
                {"title": "五", "level": 1},
                {"title": "大模型辅助的论文与项目", "level": 1},
                {"title": "四", "level": 1},
            ]
        }
    )

    assert [item["title"] for item in extraction.items] == [
        "一 AI驱动的第五科研范式",
        "二 百花齐放的大模型时代",
        "四 大模型辅助的论文与项目",
        "五 未来科研范式展望",
    ]


def test_normalize_llm_toc_payload_drops_short_fragments_between_numbered_sections() -> None:
    from pageindex.candidates.llm_toc_page_extractor import normalize_llm_toc_payload

    extraction = normalize_llm_toc_payload(
        {
            "toc_items": [
                {"title": "Part01: 市场分析：消费趋势与获客挑战", "level": 1},
                {"title": "增长引擎一·", "level": 1},
                {"title": "Part02: AI心智占位：预测式社交生态实战指南", "level": 1},
                {"title": "增长引擎二·", "level": 1},
                {"title": "Part03: 内容营销工业化：标签思维驱动工业化增长", "level": 1},
                {"title": "增长引擎三·", "level": 1},
                {"title": "Part04: 数据基建：驱动端到端进化的数字底座", "level": 1},
                {"title": "Part05: AI变革落地：快消品牌AI营销案例", "level": 1},
            ]
        }
    )

    assert [item["title"] for item in extraction.items] == [
        "Part01: 市场分析：消费趋势与获客挑战",
        "Part02: AI心智占位：预测式社交生态实战指南",
        "Part03: 内容营销工业化：标签思维驱动工业化增长",
        "Part04: 数据基建：驱动端到端进化的数字底座",
        "Part05: AI变革落地：快消品牌AI营销案例",
    ]
