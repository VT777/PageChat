from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.balanced_quality_gate import run_balanced_quality_gate
from pageindex.visual_page_outline_extractor import (
    build_page_title_candidates,
    expand_flat_toc_with_page_titles,
)


def test_global_ai_insight_keeps_four_top_chapters_and_expands_long_chapters():
    skeleton = {
        "items": [
            {"title": "全球人工智能技术发展洞察", "level": 1},
            {"title": "AI十大行业技术应用需求洞察", "level": 1},
            {"title": "全球人工智能技术应用突破奖", "level": 1},
            {"title": "全球人工智能技术应用未来趋势", "level": 1},
        ]
    }
    tree = [
        {"title": "全球人工智能技术发展洞察", "level": 1, "structure": "1", "start_index": 4, "end_index": 10, "nodes": []},
        {"title": "AI十大行业技术应用需求洞察", "level": 1, "structure": "2", "start_index": 11, "end_index": 23, "nodes": []},
        {"title": "全球人工智能技术应用突破奖", "level": 1, "structure": "3", "start_index": 24, "end_index": 37, "nodes": []},
        {"title": "全球人工智能技术应用未来趋势", "level": 1, "structure": "4", "start_index": 38, "end_index": 43, "nodes": []},
    ]
    page_texts = [""] * 43
    page_texts[11] = "AI垂类行业技术应用价值分析框架"
    page_texts[12] = "全球重点行业人工智能渗透率"
    page_texts[13] = "互联网：以内容为核心的行业典型应用"
    page_texts[24] = "全球人工智能技术应用突破奖介绍"
    page_texts[25] = "SCE评估模型"
    page_texts[26] = "十大领域应用突破奖"
    page_texts[27] = "Google AI Overviews"

    expansion = expand_flat_toc_with_page_titles(tree, page_texts, page_count=43)
    fixed, quality = run_balanced_quality_gate(
        tree,
        {"top_level_frozen": True, "allow_child_expansion": True},
        skeleton,
        page_count=43,
    )

    assert [node["title"] for node in fixed] == [
        "全球人工智能技术发展洞察",
        "AI十大行业技术应用需求洞察",
        "全球人工智能技术应用突破奖",
        "全球人工智能技术应用未来趋势",
    ]
    assert expansion["added_children"] >= 6
    assert len(fixed[1]["nodes"]) >= 3
    assert len(fixed[2]["nodes"]) >= 3
    assert quality["top_level_exact_match"] is True
    assert quality["long_chapter_completeness"] is True


def test_structured_page_title_candidates_do_not_modify_top_level():
    parent = {
        "title": "AI十大行业技术应用需求洞察",
        "structure": "2",
        "start_index": 11,
        "end_index": 23,
    }
    evidence = [
        {
            "page": 14,
            "primary_role": "content_slide",
            "evidence_spans": [{"role": "page_title", "text": "互联网行业应用", "confidence": 0.9}],
        }
    ]

    candidates = build_page_title_candidates(evidence, parent, page_count=43)

    assert candidates[0]["title"] == "互联网行业应用"
    assert parent["title"] == "AI十大行业技术应用需求洞察"
