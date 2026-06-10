from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.balanced_toc import _map_toc_physical_pages
from pageindex.quality_validation import TocQualityChecker, decide_extraction_path


def _chongqing_case_toc_items():
    categories = [
        ("category industry", 1),
        ("category governance", 15),
        ("category livelihood", 26),
        ("category science", 34),
        ("category consumption", 38),
        ("category cooperation", 41),
    ]
    items = []
    category_iter = iter(categories)
    next_category, next_case = next(category_iter)

    for case_no, logical_page in zip(range(1, 42), range(1, 82, 2)):
        if case_no == next_case:
            items.append({"title": next_category, "level": 1})
            try:
                next_category, next_case = next(category_iter)
            except StopIteration:
                next_category, next_case = None, None
        items.append(
            {
                "title": f"{case_no:02d} case",
                "level": 2,
                # Mirrors the old quick VLM payload shape: TOC logical page
                # numbers were mislabeled as physical_index.
                "physical_index": logical_page,
            }
        )
    return items


def _chongqing_toc_with_synthetic_root():
    items = [{"title": "目录", "level": 1}]
    categories = [
        ("AI+产业发展", 1),
        ("AI+超大城市现代化治理", 15),
        ("AI+民生福祉", 26),
        ("AI+科学技术", 34),
        ("AI+消费提质", 38),
        ("AI+开放合作", 41),
    ]
    category_iter = iter(categories)
    next_category, next_case = next(category_iter)

    for case_no, logical_page in zip(range(1, 42), range(1, 82, 2)):
        if case_no == next_case:
            items.append({"title": next_category, "level": 2})
            try:
                next_category, next_case = next(category_iter)
            except StopIteration:
                next_category, next_case = None, None
        items.append(
            {
                "title": f"{case_no:02d} case",
                "level": 3,
                "page": logical_page,
            }
        )
    return items


def _chongqing_toc_with_document_title_root():
    items = [
        {
            "title": "2025年度重庆市人工智能应用场景典型案例集",
            "level": 1,
        }
    ]
    categories = [
        ("AI+产业发展", 1),
        ("AI+超大城市现代化治理", 15),
        ("AI+民生福祉", 26),
        ("AI+科学技术", 34),
        ("AI+消费提质", 38),
        ("AI+开放合作", 41),
    ]
    category_iter = iter(categories)
    next_category, next_case = next(category_iter)

    for case_no, logical_page in zip(range(1, 42), range(1, 82, 2)):
        if case_no == next_case:
            items.append({"title": next_category, "level": 2})
            try:
                next_category, next_case = next(category_iter)
            except StopIteration:
                next_category, next_case = None, None
        items.append(
            {
                "title": f"{case_no:02d} case",
                "level": 3,
                "page": logical_page,
            }
        )
    return items


def test_quality_checker_accepts_high_quality_toc_with_mislabeled_logical_pages():
    toc_items = _chongqing_case_toc_items()

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["is_valid"] is True
    assert qc["has_hierarchy"] is True
    assert qc["top_level_count"] == 6
    assert qc["valid_page_field"] == "physical_index"
    assert qc["valid_page_count"] == 41
    assert qc["page_monotonic"] is True
    assert decide_extraction_path(qc, {"is_valid": False})["path"] == "BRANCH_A"


def test_toc_mapping_treats_out_of_range_physical_index_as_logical_page():
    toc_items = [
        {"title": f"{case_no:02d} case", "physical_index": logical_page}
        for case_no, logical_page in zip(range(1, 42), range(1, 82, 2))
    ]

    _map_toc_physical_pages(
        toc_items,
        page_count=44,
        first_content_page=3,
        last_toc_page=2,
        ocr_text_map=None,
        dividers=[],
    )

    assert [(item["page"], item["physical_index"]) for item in toc_items[:5]] == [
        (1, 3),
        (3, 4),
        (5, 5),
        (7, 6),
        (9, 7),
    ]
    assert [(item["page"], item["physical_index"]) for item in toc_items[-5:]] == [
        (73, 39),
        (75, 40),
        (77, 41),
        (79, 42),
        (81, 43),
    ]


def test_quality_checker_accepts_toc_with_synthetic_root_and_shifted_levels():
    toc_items = _chongqing_toc_with_synthetic_root()

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["is_valid"] is True
    assert qc["has_hierarchy"] is True
    assert qc["top_level_count"] == 6
    assert qc["valid_page_field"] == "page"
    assert qc["valid_page_count"] == 41
    assert decide_extraction_path(qc, {"is_valid": False})["path"] == "BRANCH_A"


def test_quality_checker_accepts_toc_with_document_title_root():
    toc_items = _chongqing_toc_with_document_title_root()

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["is_valid"] is True
    assert qc["has_hierarchy"] is True
    assert qc["top_level_count"] == 6
    assert qc["valid_page_field"] == "page"
    assert qc["valid_page_count"] == 41
    assert qc["page_monotonic"] is True
    assert qc["page_unique_ratio"] == 1.0
    assert qc["common_page_step"] == 2
    assert qc["synthetic_root_detected"] is True
    assert decide_extraction_path(qc, {"is_valid": False})["path"] == "BRANCH_A"


def test_quality_checker_preserves_no_page_toc_skeleton_for_later_mapping():
    toc_items = [
        {"title": "Market overview", "level": 1},
        {"title": "Model landscape", "level": 1},
        {"title": "Application opportunities", "level": 1},
        {"title": "Investment suggestions", "level": 1},
    ]

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["skeleton_valid"] is True
    assert qc["page_mapping_valid"] is False
    assert qc["hierarchy_valid"] is False
    assert qc["decision"] == "USE_SKELETON_MAP_LATER"


def test_quality_checker_rejects_hallucinated_same_page_mapping_but_keeps_skeleton():
    toc_items = [
        {"title": "Market overview", "level": 1, "page": 1},
        {"title": "Model landscape", "level": 1, "page": 1},
        {"title": "Application opportunities", "level": 1, "page": 1},
        {"title": "Investment suggestions", "level": 1, "page": 1},
    ]

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["skeleton_valid"] is True
    assert qc["page_mapping_valid"] is False
    assert qc["page_unique_ratio"] == 0.25
    assert qc["common_page_step"] == 0
    assert qc["decision"] == "USE_SKELETON_MAP_LATER"
    assert qc["is_valid"] is False
    assert decide_extraction_path(qc, {"is_valid": False})["path"] == "BRANCH_A"


def test_quality_checker_accepts_direct_toc_when_skeleton_and_mapping_are_valid():
    toc_items = [
        {"title": "Market overview", "level": 1, "page": 1},
        {"title": "Model landscape", "level": 1, "page": 8},
        {"title": "Application opportunities", "level": 1, "page": 15},
        {"title": "Investment suggestions", "level": 1, "page": 24},
    ]

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["skeleton_valid"] is True
    assert qc["page_mapping_valid"] is True
    assert qc["decision"] == "USE_DIRECT"
    assert qc["is_valid"] is True


def test_decision_uses_hierarchical_skeleton_even_when_mapping_needs_repair():
    toc_items = [
        {"title": "Category A", "level": 1, "page": 1},
        {"title": "Case A", "level": 2, "page": 1},
        {"title": "Category B", "level": 1, "page": 3},
        {"title": "Case B", "level": 2, "page": 3},
    ]

    qc = TocQualityChecker().check(toc_items, toc_pages=[2])

    assert qc["skeleton_valid"] is True
    assert qc["page_mapping_valid"] is False
    assert decide_extraction_path(qc, {"is_valid": False})["path"] == "BRANCH_A"


def test_toc_mapping_does_not_let_category_headings_consume_content_pages():
    toc_items = _chongqing_toc_with_synthetic_root()[1:]

    _map_toc_physical_pages(
        toc_items,
        page_count=44,
        first_content_page=3,
        last_toc_page=2,
        ocr_text_map=None,
        dividers=[],
    )

    by_title = {item["title"]: item for item in toc_items}

    assert by_title["AI+产业发展"]["physical_index"] == 3
    assert by_title["01 case"]["physical_index"] == 3
    assert by_title["AI+消费提质"]["physical_index"] == 40
    assert by_title["38 case"]["physical_index"] == 40
    assert by_title["AI+开放合作"]["physical_index"] == 43
    assert by_title["41 case"]["physical_index"] == 43
