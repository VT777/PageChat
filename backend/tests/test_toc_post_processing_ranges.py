from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.utils import post_processing
from pageindex import post_processing as post_processing_module
from pageindex.post_processing import normalize_tree_page_ranges


def _flatten(nodes):
    out = []
    for node in nodes:
        out.append(node)
        children = node.get("nodes") or []
        out.extend(_flatten(children))
    return out


def test_post_processing_never_generates_negative_range_when_same_page_starts() -> None:
    flat = [
        {
            "structure": "4",
            "title": "第四章",
            "physical_index": 46,
            "appear_start": "yes",
        },
        {
            "structure": "4.1",
            "title": "引言",
            "physical_index": 46,
            "appear_start": "yes",
        },
        {
            "structure": "4.2",
            "title": "行业场景",
            "physical_index": 47,
            "appear_start": "yes",
        },
    ]

    tree = post_processing(flat, end_physical_index=50)
    all_nodes = _flatten(tree)

    assert all(
        node["end_index"] >= node["start_index"]
        for node in all_nodes
        if isinstance(node.get("start_index"), int)
        and isinstance(node.get("end_index"), int)
    )


def test_post_processing_repairs_numbered_structure_and_ignores_text_divider_noise() -> None:
    flat = [
        {"structure": "2", "title": "1.3 提升学生的AI应用体验", "physical_index": 12},
        {"structure": "2.1", "title": "1.4 优化学生智能素养发展路径", "physical_index": 17},
        {"structure": "3.1", "title": "1.5 优化学生人工智能素养发展环境", "physical_index": 30},
        {"structure": "13.1", "title": "第七章 人工智能应用体制机制与支撑保障", "physical_index": 116},
        {"structure": "13.2", "title": "7.1 人工智能应用规划和政策制定", "physical_index": 116},
        {"structure": "16", "title": "8.1 发展师生智能素养", "physical_index": 136},
        {"structure": "16.1", "title": "8.2 融合AI技术与教育", "physical_index": 142},
    ]

    tree, completeness = post_processing_module.post_process_toc(
        flat,
        page_count=170,
        analysis={
            "text_coverage": 1.0,
            "toc_frozen": True,
        },
        dividers=[25, 41, 65, 145, 153, 161],
        use_llm_grouping=True,
    )

    all_nodes = _flatten(tree)
    by_structure = {node["structure"]: node for node in all_nodes}
    titles = [node["title"] for node in all_nodes]

    assert "Chapter at page 25" not in titles
    assert by_structure["1.3"]["title"] == "1.3 提升学生的AI应用体验"
    assert by_structure["1.4"]["title"] == "1.4 优化学生智能素养发展路径"
    assert by_structure["7"]["title"] == "第七章 人工智能应用体制机制与支撑保障"
    assert by_structure["7.1"]["title"] == "7.1 人工智能应用规划和政策制定"
    assert by_structure["8.2"]["title"] == "8.2 融合AI技术与教育"
    assert completeness["reaches_end"] is True


def test_post_processing_preserves_slide_outline_internal_structures() -> None:
    flat = [
        {"structure": "1", "title": "AI驱动的第五科研范式", "physical_index": 4},
        {"structure": "1.1", "title": "1.1 第五范式-科学范式变迁", "physical_index": 4},
        {"structure": "1.2", "title": "1.1 第五范式-AI驱动的科学研究新范式", "physical_index": 5},
        {"structure": "1.3", "title": "1.2 典型案例-AI加速芯片设计", "physical_index": 7},
        {"structure": "1.4", "title": "1.2 典型案例-AI重塑生物医学研究", "physical_index": 8},
    ]

    tree, completeness = post_processing_module.post_process_toc(
        flat,
        page_count=12,
        analysis={
            "toc_frozen": True,
            "toc_frozen_source": "slide_outline",
        },
        use_llm_grouping=True,
    )

    all_nodes = _flatten(tree)
    by_title = {node["title"]: node for node in all_nodes}

    assert by_title["1.1 第五范式-AI驱动的科学研究新范式"]["structure"] == "1.2"
    assert by_title["1.2 典型案例-AI加速芯片设计"]["structure"] == "1.3"
    assert by_title["1.2 典型案例-AI重塑生物医学研究"]["structure"] == "1.4"
    assert completeness["needs_repair"] is False
