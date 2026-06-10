from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.slide_outline_extractor import (
    build_slide_outline,
    is_agenda_page,
    is_slide_like_document,
)


def _fifth_paradigm_pages():
    return [
        "",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成\n三\n未来科研范式展望\n五\n大模型辅助的论文与项目\n四",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成\n三\n未来科研范式展望\n五\n大模型辅助的论文与项目\n四",
        "1.1 第五范式-科学范式变迁\n第1范式：经验科学",
        "1.2 第五范式-AI驱动的科学研究新范式\n新科研范式以数据智能为核心",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成\n三\n未来科研范式展望\n五\n大模型辅助的论文与项目\n四",
        "2.1 三起两落：人工智能发展史\n人工智能经历了半个多世纪的发展历程",
        "2.2 大模型发展历程\n生成式AI迅速发展",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成\n三\n未来科研范式展望\n五\n大模型辅助的论文与项目\n四",
        "3.1 科学假设生成的原理\n创造力研究表明",
        "3.2 科学假设生成的流程\n第1步：问题定义",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成\n三\n未来科研范式展望\n五\n大模型辅助的论文与项目\n四",
        "4.1 大模型辅助的论文与项目\n智能写作与评审",
        "4.2 申请书撰写\n挖掘基础科学问题",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成\n三\n未来科研范式展望\n五\n大模型辅助的论文与项目\n四",
        "5.1 AI研究新范式的浪潮前夜\nAI技术将在未来科研领域扮演重要角色",
        "5.2 AI研究新范式展望\n人类专家与AI协同科研",
    ]


def test_is_agenda_page_detects_repeated_slide_agenda():
    assert is_agenda_page(_fifth_paradigm_pages()[1]) is True
    assert is_agenda_page(_fifth_paradigm_pages()[3]) is False


def test_is_slide_like_document_detects_fifth_paradigm_pattern():
    analysis = {
        "page_count": len(_fifth_paradigm_pages()),
        "page_texts": _fifth_paradigm_pages(),
        "text_coverage": 0.97,
        "code_toc": {"items": None},
        "chapter_dividers": [2, 3, 6, 9, 12, 15],
    }

    assert is_slide_like_document(analysis) is True


def test_build_slide_outline_skips_agenda_and_groups_numbered_slides():
    result = build_slide_outline(
        {
            "page_count": len(_fifth_paradigm_pages()),
            "page_texts": _fifth_paradigm_pages(),
            "text_coverage": 0.97,
            "chapter_dividers": [2, 3, 6, 9, 12, 15],
        }
    )

    titles = [item["title"] for item in result["toc_items"]]
    structures = [item["structure"] for item in result["toc_items"]]

    assert result["source"] == "slide_outline"
    assert "汇报提纲" not in titles
    assert structures == [
        "1",
        "1.1",
        "1.2",
        "2",
        "2.1",
        "2.2",
        "3",
        "3.1",
        "3.2",
        "4",
        "4.1",
        "4.2",
        "5",
        "5.1",
        "5.2",
    ]
    assert titles[0] == "AI驱动的第五科研范式"
    assert titles[3] == "百花齐放的大模型时代"
    assert titles[9] == "大模型辅助的论文与项目"
    assert titles[12] == "未来科研范式展望"


def test_build_slide_outline_uses_unique_internal_structures_for_repeated_display_numbers():
    pages = [
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成",
        "汇报提纲\nAI驱动的第五科研范式\n一\n百花齐放的大模型时代\n二\n大模型辅助的科学假设生成",
        "1.1 第五范式-科学范式变迁\n正文",
        "1.2 典型案例-AI加速芯片设计\n正文",
        "1.2 典型案例-AI重塑生物医学研究\n正文",
        "1.2 典型案例-AI驱动材料科学研究\n正文",
        "2.1 三起两落：人工智能发展史\n正文",
        "2.2 大模型发展历程\n正文",
    ]

    result = build_slide_outline(
        {
            "page_count": len(pages),
            "page_texts": pages,
            "text_coverage": 1.0,
            "chapter_dividers": [1, 2],
        }
    )

    assert [item["structure"] for item in result["toc_items"]] == [
        "1",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "2",
        "2.1",
        "2.2",
    ]
