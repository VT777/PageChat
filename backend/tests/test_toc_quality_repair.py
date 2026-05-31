from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.pageindex_service import PageIndexService


def test_repair_structure_titles_replaces_generic_chapter() -> None:
    structure = [
        {
            "node_id": "0001",
            "title": "Chapter 1",
            "text": "第一章 AI发展总览\n本章讨论...",
            "nodes": [],
            "start_index": 1,
            "end_index": 3,
        }
    ]
    repaired = PageIndexService._repair_structure_titles(structure)
    assert repaired[0]["title"] != "Chapter 1"
    assert "AI发展总览" in repaired[0]["title"]


def test_build_segment_fallback_toc_for_large_doc() -> None:
    nodes = PageIndexService._build_segment_fallback_toc(20)
    assert len(nodes) >= 3
    assert nodes[0]["start_index"] == 1
    assert nodes[-1]["end_index"] == 20


def test_structure_quality_penalizes_single_bad_title() -> None:
    q = PageIndexService._compute_structure_quality(
        [{"node_id": "0001", "title": "2026.1", "nodes": []}]
    )
    assert q["score"] < 0.5


def test_noise_title_detects_short_acronym() -> None:
    assert PageIndexService._is_noise_title("IDCA") is True
    assert PageIndexService._is_noise_title("SCE") is True
    assert PageIndexService._is_noise_title("2026-01-14") is True


def test_normalize_title_strips_disclaimer_prefix() -> None:
    normalized = PageIndexService._normalize_title(
        "请务必阅读正文之后的免责声明及其项下所有内容 国外大厂AI应用落地"
    )
    assert normalized == "国外大厂AI应用落地"


def test_build_toc_outline_skips_noise_titles() -> None:
    structure = [
        {"node_id": "0001", "title": "Preface", "nodes": []},
        {"node_id": "0002", "title": "国内大厂AI应用落地", "nodes": []},
    ]
    outline = PageIndexService._build_toc_outline_text(structure)
    assert "Preface" not in outline
    assert "国内大厂AI应用落地" in outline
