from pathlib import Path
import inspect
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.fast_path.code_toc_fast_path import CodeTOCFastPath
from app.services.pageindex_service import PageIndexService
import app.services.pageindex_service as pageindex_service_module


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")


class FakeHTTPSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse(payload={"data": {"jobId": "job-1"}})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if url.endswith("/job-1"):
            return FakeResponse(
                payload={
                    "data": {
                        "state": "done",
                        "extractProgress": {"extractedPages": 1},
                        "resultUrl": {"jsonUrl": "https://example.test/result.jsonl"},
                    }
                }
            )
        return FakeResponse(
            text='{"result":{"ocrResults":[{"prunedResult":{"rec_texts":["目录","第一章 绪论 1"],"rec_scores":[0.99,0.98],"rec_boxes":[[80,80,180,120],[100,160,680,200]]}}]}}'
        )


def test_new_architecture_service_path_has_no_visual_fallback() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService._generate_pdf_index)

    assert "extract_visual_toc" not in source
    assert "falling back to targeted visual/legacy" not in source
    assert "build_balanced_toc_visual" not in source
    assert "_vlm_detect_anchors" not in source
    assert "_run_unified_toc_controller" not in source
    assert "segment_fallback" not in source
    assert "page_heading_outline" not in source


def test_new_architecture_service_uses_page_text_ocr_only() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService)

    assert '_resolve_ocr_engine("toc_page")' not in source
    assert 'task="toc_page"' not in source


def test_pageindex_service_does_not_keep_legacy_candidate_lifecycle() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService)

    forbidden = [
        "_collect_text_toc_candidates",
        "_run_unified_toc_controller",
        "_build_segment_fallback_toc",
        "_looks_like_segment_fallback_toc",
        "_is_segment_fallback_judgment",
        "_build_page_heading_outline_candidate_from_page_list",
        "segment_fallback",
        "page_heading_outline",
    ]
    for token in forbidden:
        assert token not in source


def test_pdf_main_flow_keeps_s5_as_single_page_mapping_owner() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService._generate_pdf_index)

    assert "_should_run_final_content_mapping" not in source
    assert "_map_toc_items_after_content_ocr" not in source
    assert "normalize_tree_page_ranges" not in source
    assert "post_process_toc(" not in source


def test_pdf_main_flow_does_not_rebuild_page_text_map_after_s5() -> None:
    source = inspect.getsource(pageindex_service_module.PageIndexService._generate_pdf_index)
    route_accept_index = source.index("decision=accept")

    assert "_run_pdf_ocr_pages_by_images" not in source[route_accept_index:]
    assert "preprocess_page_text_map(" not in source[route_accept_index:]


def test_s5_tree_builder_preserves_mapped_boundary_overlap() -> None:
    items = [
        {
            "title": "Chapter 1",
            "level": 1,
            "structure": "1",
            "physical_index": 3,
            "start_index": 3,
            "mapping_evidence": {"near_page_top": True},
        },
        {
            "title": "Chapter 2",
            "level": 1,
            "structure": "2",
            "physical_index": 10,
            "start_index": 10,
            "mapping_evidence": {"near_page_top": False},
        },
        {
            "title": "Chapter 3",
            "level": 1,
            "structure": "3",
            "physical_index": 15,
            "start_index": 15,
            "mapping_evidence": {"near_page_top": True},
        },
    ]

    tree, completeness = PageIndexService._build_s5_toc_tree(
        items,
        page_count=20,
        analysis={"top_level_frozen": True},
    )

    assert completeness["needs_repair"] is False
    chapters = [node for node in tree if str(node.get("title") or "").startswith("Chapter")]
    assert [node["end_index"] for node in chapters] == [10, 14, 20]
    assert chapters[0]["range_boundary"] == "overlap_with_next_start"


def test_s5_tree_builder_preserves_multicatalog_main_coverage() -> None:
    items = [
        {"title": "Chapter 1", "level": 1, "structure": "1", "physical_index": 6},
        {"title": "Chapter 2", "level": 1, "structure": "2", "physical_index": 12},
        {"title": "Figure 1 architecture", "level": 1, "structure": "F1", "physical_index": 20, "catalog_type": "figure"},
        {"title": "Table 1 benchmark", "level": 1, "structure": "T1", "physical_index": 22, "catalog_type": "table"},
    ]

    tree, completeness = PageIndexService._build_s5_toc_tree(
        items,
        page_count=30,
        analysis={"page_texts": [""] * 30},
    )

    assert completeness["needs_repair"] is False
    assert [node["title"] for node in tree] == ["目录", "图目录", "表目录"]
    main_root = tree[0]
    assert main_root["start_index"] == 1
    assert main_root["end_index"] == 30
    assert [child["title"] for child in main_root["nodes"]] == ["Preface", "Chapter 1", "Chapter 2"]
    assert main_root["nodes"][-1]["end_index"] == 30
    assert tree[1]["exclude_from_coverage"] is True
    assert tree[2]["exclude_from_coverage"] is True


def test_s5_tree_builder_adds_front_matter_inside_prebuilt_main_catalog() -> None:
    items = [
        {
            "title": "目录",
            "node_type": "catalog_group",
            "catalog_type": "main",
            "nodes": [
                {"title": "Chapter 1", "level": 1, "structure": "1", "physical_index": 6},
                {"title": "Chapter 2", "level": 1, "structure": "2", "physical_index": 12},
            ],
        },
        {
            "title": "图目录",
            "node_type": "auxiliary_catalog",
            "catalog_type": "figure",
            "is_auxiliary": True,
            "exclude_from_coverage": True,
            "nodes": [
                {"title": "Figure 1 architecture", "level": 1, "physical_index": 20, "catalog_type": "figure"}
            ],
        },
    ]

    tree, completeness = PageIndexService._build_s5_toc_tree(
        items,
        page_count=30,
        analysis={"page_texts": [""] * 30},
    )

    assert completeness["needs_repair"] is False
    main_root = tree[0]
    assert main_root["title"] == "目录"
    assert main_root["nodes"][0]["title"] == "Preface"
    assert main_root["nodes"][0]["start_index"] == 1
    assert main_root["nodes"][0]["end_index"] == 5
    assert main_root["nodes"][-1]["end_index"] == 30


def test_completeness_ignores_auxiliary_catalog_coverage() -> None:
    from pageindex.post_processing import check_completeness

    tree = [
        {"title": "Body", "start_index": 1, "end_index": 6, "nodes": []},
        {
            "title": "Figure catalog",
            "node_type": "auxiliary_catalog",
            "is_auxiliary": True,
            "exclude_from_coverage": True,
            "start_index": 7,
            "end_index": 20,
            "nodes": [
                {
                    "title": "Figure 1",
                    "node_type": "auxiliary_catalog_item",
                    "is_auxiliary": True,
                    "exclude_from_coverage": True,
                    "start_index": 7,
                    "end_index": 20,
                }
            ],
        },
    ]

    completeness = check_completeness(tree, page_count=20)

    assert completeness["needs_repair"] is True
    assert completeness["coverage"] == 0.3
    assert completeness["gaps"] == [(7, 20)]


def test_completeness_does_not_use_catalog_group_range_as_body_coverage() -> None:
    from pageindex.post_processing import check_completeness

    tree = [
        {
            "title": "Contents",
            "node_type": "catalog_group",
            "start_index": 1,
            "end_index": 20,
            "nodes": [
                {"title": "Preface", "start_index": 1, "end_index": 5, "nodes": []},
                {"title": "Chapter 2", "start_index": 10, "end_index": 20, "nodes": []},
            ],
        }
    ]

    completeness = check_completeness(tree, page_count=20)

    assert completeness["needs_repair"] is True
    assert completeness["gaps"] == [(6, 9)]


def test_build_tree_treats_chinese_decimal_structures_as_siblings() -> None:
    from pageindex.post_processing import build_tree

    tree = build_tree(
        [
            {"title": "第一节", "structure": "一.1", "nodes": []},
            {"title": "第二节", "structure": "一.2", "nodes": []},
            {"title": "第三节", "structure": "一.3", "nodes": []},
        ]
    )

    assert [node["title"] for node in tree] == ["第一节", "第二节", "第三节"]
    assert all(not node.get("nodes") for node in tree)


def test_code_toc_fast_path_allows_verified_bookmark_early_return() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 20,
            "code_toc": {
                "source": "bookmarks",
                "items": [
                    {"title": "第一章 绪论", "level": 1, "physical_index": 3},
                    {"title": "第二章 方法", "level": 1, "physical_index": 8},
                    {"title": "第三章 结论", "level": 1, "physical_index": 14},
                ],
            },
        }
    )

    assert result is not None
    assert result["source"] == "code_toc"
    assert result["early_return_allowed"] is True
    assert result["evidence"]["pages_monotonic"] is True


def test_code_toc_fast_path_does_not_early_return_when_visible_auxiliary_catalog_is_missing() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 50,
            "toc_page_detection": {
                "status": "detected",
                "pages": [2],
                "has_page_numbers": True,
                "sections": [
                    {"kind": "main_toc", "pages": [2]},
                    {"kind": "figure_toc", "pages": [2]},
                ],
            },
            "code_toc": {
                "source": "bookmarks",
                "toc_sections": [
                    {
                        "kind": "main_toc",
                        "source": "bookmarks",
                        "items": [
                            {"title": "Overview", "level": 1, "physical_index": 7},
                            {"title": "Current State", "level": 1, "physical_index": 10},
                            {"title": "Challenges", "level": 1, "physical_index": 16},
                            {"title": "Framework", "level": 1, "physical_index": 25},
                            {"title": "Practice", "level": 1, "physical_index": 40},
                            {"title": "Outlook", "level": 1, "physical_index": 47},
                        ],
                    }
                ],
                "items": [
                    {"title": "Overview", "level": 1, "physical_index": 7},
                    {"title": "Current State", "level": 1, "physical_index": 10},
                    {"title": "Challenges", "level": 1, "physical_index": 16},
                    {"title": "Framework", "level": 1, "physical_index": 25},
                    {"title": "Practice", "level": 1, "physical_index": 40},
                    {"title": "Outlook", "level": 1, "physical_index": 47},
                ],
            },
        }
    )

    assert result is not None
    assert result["early_return_allowed"] is False
    assert "missing_visible_auxiliary_catalog:figure_toc" in result["reasons"]


def test_code_toc_fast_path_never_early_returns_weak_regex() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 100,
            "code_toc": {
                "source": "regex",
                "items": [
                    {"title": "2024", "level": 1, "physical_index": 2024},
                    {"title": "2025", "level": 1, "physical_index": 2025},
                    {"title": "2026", "level": 1, "physical_index": 2026},
                ],
            },
        }
    )

    assert result is None


def test_code_toc_fast_path_rejects_unverified_regex_candidate() -> None:
    result = CodeTOCFastPath().run(
        {
            "page_count": 20,
            "code_toc": {
                "source": "regex",
                "items": [
                    {"title": "第一章 绪论", "level": 1, "physical_index": 3},
                    {"title": "第二章 方法", "level": 1, "physical_index": 8},
                ],
                "quality": {"verified": False, "score": 0.2},
            },
        }
    )

    assert result is None


def test_page_mapping_verifier_penalizes_many_items_collapsed_to_one_page() -> None:
    from pageindex.judge.page_mapping_verifier import PageMappingVerifier

    items = [
        {"title": f"Section {index}", "physical_index": 1}
        for index in range(12)
    ]

    report = PageMappingVerifier().verify({"source": "code_toc", "items": items}, page_count=50)

    assert report["page_collapse"] is True
    assert report["page_mapping_score"] < 0.5
