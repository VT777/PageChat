from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _flatten(nodes):
    result = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten(node.get("nodes") or []))
    return result


def test_rule_extractor_builds_typed_catalog_roots_from_standard_toc_pages() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages

    page_texts = [
        "Cover",
        (
            "目录\n"
            "第一章 复盘：OpenAI 产品矩阵 ................ 4\n"
            "第二章 展望：模型能力持续提升 ................ 10\n"
            "第三章 愿景：AGI 平台入口 ................ 18\n"
            "第四章 风险提示 ................ 25\n"
            "图目录\n"
            "图1 OpenAI 产品时间线 ................ 5\n"
            "图2 ChatGPT 用户增长 ................ 12"
        ),
        (
            "图目录\n"
            "图3 Codex 能力演进 ................ 20\n"
            "表目录\n"
            "表1 OpenAI 融资情况梳理 ................ 8\n"
            "表2 关键模型迭代情况梳理 ................ 9"
        ),
        "第一章 复盘：OpenAI 产品矩阵\n正文",
        "图1 OpenAI 产品时间线\n正文",
        "更多正文",
        "更多正文",
        "表1 OpenAI 融资情况梳理\n正文",
        "表2 关键模型迭代情况梳理\n正文",
        "第二章 展望：模型能力持续提升\n正文",
        "更多正文",
        "图2 ChatGPT 用户增长\n正文",
        "更多正文",
        "更多正文",
        "更多正文",
        "更多正文",
        "更多正文",
        "第三章 愿景：AGI 平台入口\n正文",
        "更多正文",
        "图3 Codex 能力演进\n正文",
        "更多正文",
        "更多正文",
        "更多正文",
        "更多正文",
        "第四章 风险提示\n正文",
        "尾页",
    ]

    result = extract_visible_toc_with_pages(
        page_texts,
        toc_pages=[2, 3],
        page_count=len(page_texts),
    )

    assert result is not None
    assert result["source"] == "toc_page_text_rule"
    assert result["mapped"] is True
    assert [section["kind"] for section in result["toc_sections"]] == [
        "main_toc",
        "figure_toc",
        "table_toc",
    ]
    assert [node["title"] for node in result["items"]] == ["目录", "图目录", "表目录"]

    flat = _flatten(result["items"])
    by_title = {node["title"]: node for node in flat}
    assert by_title["第四章 风险提示"]["physical_index"] == 25
    assert by_title["图3 Codex 能力演进"]["physical_index"] == 20
    assert by_title["表2 关键模型迭代情况梳理"]["physical_index"] == 9
    assert result["mapping_report"]["status"] == "ok"


def test_paged_draft_extracts_pipe_table_rows_without_valid_markdown_separator() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages_draft

    page_texts = [
        "Cover",
        (
            "Contents\n"
            "| 01 | Alpha rollout | 01 |\n"
            "| --- | --- |\n"
            "| 02 | Beta launch | 03 |\n"
            "| 03 | Gamma operations | 05 |\n"
            "| 04 | Delta risk | 07 |\n"
        ),
        "01\nAlpha rollout\nBody",
        "02 Beta launch\nBody",
        "03 Gamma operations\nBody",
        "04 Delta risk\nBody",
    ]

    draft = extract_visible_toc_with_pages_draft(
        page_texts,
        toc_pages=[2],
        page_count=len(page_texts),
    )

    assert draft is not None
    assert [
        (item["title"], item["raw_page_label"], item["structure"])
        for item in draft["items"]
    ] == [
        ("01 Alpha rollout", 1, "01"),
        ("02 Beta launch", 3, "02"),
        ("03 Gamma operations", 5, "03"),
        ("04 Delta risk", 7, "04"),
    ]


def test_rule_extractor_rejects_ambiguous_chapter_numbers_as_page_numbers() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages

    result = extract_visible_toc_with_pages(
        [
            "Cover",
            (
                "目录\n"
                "国外大厂AI应用落地 01\n"
                "国内大厂AI应用落地 02\n"
                "产业链梳理 03\n"
                "风险提示 04"
            ),
            "国外大厂AI应用落地\n正文",
            "国内大厂AI应用落地\n正文",
        ],
        toc_pages=[2],
        page_count=4,
    )

    assert result is None


def test_rule_extractor_rejects_logical_pages_that_overflow_without_content_anchors() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages

    toc_lines = ["目录"]
    for index in range(1, 42):
        logical_page = index * 2 - 1
        toc_lines.append(f"{index:02d} 案例标题{index:02d} ................ {logical_page}")
    page_texts = [
        "封面",
        "\n".join(toc_lines),
    ] + [f"正文页 {page}" for page in range(3, 45)]

    result = extract_visible_toc_with_pages(
        page_texts,
        toc_pages=[2],
        page_count=44,
    )

    assert result is None


def test_rule_extractor_rejects_or_preserves_parenthetical_children_from_visible_toc() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages

    page_texts = [
        "封面",
        (
            "目 录\n"
            "一、AI 眼镜总体发展情况 .......................................................................................... 1\n"
            "（一）AI 眼镜开启信息增强新阶段 ................................................................. 2\n"
            "（二）三类产品呈现功能升维趋势 .................................................................. 3\n"
            "二、AI 眼镜关键技术 .................................................................................................. 6\n"
            "（一）硬件迭代使眼镜向轻量化发展 .............................................................. 6\n"
            "（二）软件算法与操作系统不断演进 ............................................................ 10"
        ),
        "正文",
        "正文",
        "正文",
        "一、AI 眼镜总体发展情况\n正文",
        "（一）AI 眼镜开启信息增强新阶段\n正文",
        "（二）三类产品呈现功能升维趋势\n正文",
        "正文",
        "正文",
        "二、AI 眼镜关键技术\n（一）硬件迭代使眼镜向轻量化发展\n正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "（二）软件算法与操作系统不断演进\n正文",
    ]

    result = extract_visible_toc_with_pages(
        page_texts,
        toc_pages=[2],
        page_count=len(page_texts),
    )

    if result is None:
        return

    flat = _flatten(result["items"])
    titles = {node["title"] for node in flat}
    assert "（一）AI 眼镜开启信息增强新阶段" in titles
    assert "（二）软件算法与操作系统不断演进" in titles
    assert result["allow_child_expansion"] is True


def test_rule_extractor_keeps_structured_main_entry_without_visible_page_number() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages

    page_texts = [
        "Cover",
        (
            "目录\n"
            "1. 复盘：AI 新物种 ................ 4\n"
            "2. 展望：模型为基 ................ 9\n"
            "3. 愿景：共赴 AGI 新时代 ................ 20\n"
            "4. 风险提示..................................."
        ),
        "正文",
        "1. 复盘：AI 新物种\n正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "2. 展望：模型为基\n正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "3. 愿景：共赴 AGI 新时代\n正文",
        "正文",
        "正文",
        "正文",
        "正文",
        "4. 风险提示\n正文",
    ]

    result = extract_visible_toc_with_pages(page_texts, toc_pages=[2], page_count=len(page_texts))

    assert result is not None
    main = next(section for section in result["toc_sections"] if section["kind"] == "main_toc")
    assert [item["title"] for item in main["items"]] == [
        "1. 复盘：AI 新物种",
        "2. 展望：模型为基",
        "3. 愿景：共赴 AGI 新时代",
        "4. 风险提示",
    ]
    assert main["items"][-1]["physical_index"] == 25
    assert main["items"][-1]["mapping_source"] == "title_search"


def test_no_page_rule_extractor_maps_adjacent_section_numbers_as_structure_only() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_no_pages

    page_texts = [
        "Cover",
        (
            "国外大厂AI应用落地\n"
            "01\n"
            "国内大厂AI应用落地\n"
            "02\n"
            "目录\n"
            "产业链梳理\n"
            "03\n"
            "风险提示\n"
            "04"
        ),
        "国外大厂AI应用落地\n正文",
        "正文",
        "国内大厂AI应用落地\n正文",
        "正文",
        "产业链梳理\n正文",
        "风险提示\n正文",
    ]

    result = extract_visible_toc_no_pages(page_texts, toc_pages=[2], page_count=len(page_texts))

    assert result is not None
    main = result["toc_sections"][0]
    assert main["kind"] == "main_toc"
    assert [(item["structure"], item["title"], item["physical_index"]) for item in main["items"]] == [
        ("01", "国外大厂AI应用落地", 3),
        ("02", "国内大厂AI应用落地", 5),
        ("03", "产业链梳理", 7),
        ("04", "风险提示", 8),
    ]
    assert all(item.get("page") is None for item in main["items"])
    assert result["mapping_report"]["status"] == "ok"


def test_no_page_rule_extractor_maps_chapter_catalog_titles() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_no_pages

    page_texts = [
        "封面",
        (
            "目录\n"
            "序言\n"
            "第一章：发展学生智能素养\n"
            "第二章：发展教师智能教学素养\n"
            "第三章：AI创新人才培养范式"
        ),
        "序言\n正文",
        "第一章：发展学生智能素养\n正文",
        "正文",
        "第二章：发展教师智能教学素养\n正文",
        "正文",
        "第三章：AI创新人才培养范式\n正文",
    ]

    result = extract_visible_toc_no_pages(page_texts, toc_pages=[2], page_count=len(page_texts))

    assert result is not None
    titles = [item["title"] for item in result["toc_sections"][0]["items"]]
    assert titles == [
        "序言",
        "第一章：发展学生智能素养",
        "第二章：发展教师智能教学素养",
        "第三章：AI创新人才培养范式",
    ]
    assert [item["physical_index"] for item in result["toc_sections"][0]["items"]] == [3, 4, 6, 8]


def test_no_page_rule_extractor_uses_repeated_catalog_dividers_as_boundaries() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_no_pages

    repeated_catalog = (
        "Overseas AI applications\n"
        "01\n"
        "Domestic AI applications\n"
        "02\n"
        "Contents\n"
        "AI supply chain\n"
        "03\n"
        "AI risk notice\n"
        "04"
    )
    page_texts = [
        "Cover",
        "Summary",
        repeated_catalog,
        "OpenAI launches a healthcare application\nBody",
        "More overseas application content",
        "More overseas application content",
        "More overseas application content",
        "More overseas application content",
        repeated_catalog,
        "Alibaba launches a domestic AI application\nBody",
        "More domestic application content",
        "More domestic application content",
        "More domestic application content",
        "More domestic application content",
        "More domestic application content",
        repeated_catalog,
        "AI supply chain overview\nBody",
        repeated_catalog,
        "AI risk details\nBody",
        "Disclaimer",
        "Back cover",
    ]

    result = extract_visible_toc_no_pages(page_texts, toc_pages=[3], page_count=len(page_texts))

    assert result is not None
    main = result["toc_sections"][0]["items"]
    assert [(item["structure"], item["title"], item["physical_index"]) for item in main] == [
        ("01", "Overseas AI applications", 3),
        ("02", "Domestic AI applications", 9),
        ("03", "AI supply chain", 16),
        ("04", "AI risk notice", 18),
    ]
    assert [item["mapping_source"] for item in main] == ["section_divider_sequence"] * 4
    assert result["mapping_report"]["strategy"] == "section_divider_sequence"


def test_printed_mapping_is_not_overridden_by_weak_outline_marker() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    items = [
        {"title": "1. Business overview", "level": 1, "page": 4, "logical_page": 4},
        {
            "title": "1.3 Valuation remains high with a 750B latest estimate",
            "level": 2,
            "page": 7,
            "logical_page": 7,
        },
    ]
    page_texts = [
        "Cover",
        "Contents\n1. Business overview 4\n1.3 Valuation remains high with a 750B latest estimate 7",
        "More contents",
        "1. Business overview\n1.3 unrelated appendix teaser\nBody",
        "Body",
        "Body",
        "Latest valuation estimate reaches 750B\nBody",
        "Body",
        "Body",
        "Body",
    ]

    mapped, report = map_toc_items_to_physical_pages(
        items,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2, 3],
        min_title_match_rate=0.0,
        prefer_printed_page_numbers=True,
    )

    assert report["status"] == "ok"
    assert mapped[1]["physical_index"] == 7
    assert mapped[1]["mapping_source"] == "printed_page_offset"


def test_printed_mapping_uses_ordinal_pages_when_logical_step_exceeds_physical_range() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    items = [
        {"title": f"Case {index:02d}", "level": 2, "page": logical_page}
        for index, logical_page in enumerate([1, 3, 5, 7, 9, 11], start=1)
    ]
    page_texts = [
        "Cover",
        "Contents\nCase 01 01\nCase 02 03\nCase 03 05\nCase 04 07\nCase 05 09\nCase 06 11",
        "Case 01\nBody",
        "Case 02\nBody",
        "Body without a clean heading",
        "Case 04\nBody",
        "Body without a clean heading",
        "Case 06\nBody",
    ]

    mapped, report = map_toc_items_to_physical_pages(
        items,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        prefer_printed_page_numbers=True,
    )

    assert report["status"] == "ok"
    assert report["strategy"] == "printed_page_offset"
    assert [item["physical_index"] for item in mapped] == [3, 4, 5, 6, 7, 8]


def test_visible_toc_with_pages_preserves_unpaged_group_headings_with_regular_overflow_pages() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages

    page_texts = [
        "Cover",
        "\n".join(
            [
                "目录",
                "AI+产业发展",
                "01 Case Alpha 01",
                "02 Case Beta 03",
                "目录",
                "Sample report title",
                "03 Case Gamma 05",
                "AI+消费提质",
                "04 Case Delta 07",
                "05 Case Epsilon 09",
                "06 Case Zeta 11",
            ]
        ),
        "01 Case Alpha\nBody",
        "02 Case Beta\nBody",
        "Body without a clean heading",
        "04 Case Delta\nBody",
        "Body without a clean heading",
        "06 Case Zeta\nBody",
    ]

    result = extract_visible_toc_with_pages(page_texts, toc_pages=[2], page_count=len(page_texts))

    assert result is not None
    main_root = result["items"][0]
    assert main_root["title"] == "目录"
    assert [node["title"] for node in main_root["nodes"]] == ["AI+产业发展", "AI+消费提质"]
    assert [child["physical_index"] for child in main_root["nodes"][0]["nodes"]] == [3, 4, 5]
    assert [child["physical_index"] for child in main_root["nodes"][1]["nodes"]] == [6, 7, 8]


def test_outline_marker_is_not_counted_as_strong_title_anchor() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    mapped, report = map_toc_items_to_physical_pages(
        [{"title": "Chapter 8: AI education outlook", "level": 1, "source_page": 2}],
        page_texts=[
            "Cover",
            "Contents\nChapter 8: AI education outlook",
            "Chapter 8 Rebuilding the education ecosystem\nBody",
        ],
        page_count=3,
        toc_pages=[2],
    )

    assert mapped[0]["mapping_source"] == "outline_marker"
    assert report["strong_anchor_count"] == 0
    assert report["title_match_rate"] == 0.0
    assert report["status"] == "failed"
    assert "title_match_rate_below_threshold" in report["reasons"]


def test_printed_page_mapping_reports_main_title_match_rate_separately() -> None:
    from pageindex.catalog_classifier import CATALOG_FIGURE, CATALOG_MAIN, CATALOG_TABLE
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    page_texts = [
        "目录\n1.1 Main Alpha 2\n图1 Figure Alpha 2\n表1 Table Alpha 3\n1.2 Main Beta 4",
        "1.1 Main Alpha\nbody",
        "body without auxiliary title",
        "1.2 Main Beta\nbody",
    ]
    items = [
        {"title": "1.1 Main Alpha", "page": 2, "catalog_type": CATALOG_MAIN},
        {"title": "图1 Figure Alpha", "page": 2, "catalog_type": CATALOG_FIGURE},
        {"title": "表1 Table Alpha", "page": 3, "catalog_type": CATALOG_TABLE},
        {"title": "1.2 Main Beta", "page": 4, "catalog_type": CATALOG_MAIN},
    ]

    _, report = map_toc_items_to_physical_pages(
        items,
        page_texts=page_texts,
        page_count=4,
        toc_pages=[1],
        min_title_match_rate=0.0,
        prefer_printed_page_numbers=True,
    )

    assert report["title_match_rate"] < 0.6
    assert report["main_title_match_rate"] == 1.0
    assert report["main_strong_anchor_count"] == 2
    assert report["main_sample_checked_count"] == 2


def test_no_page_rule_extractor_prefers_early_fuzzy_heading_over_late_exact_reference() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_no_pages

    page_texts = [
        "Cover",
        (
            "Contents\n"
            "Preface\n"
            "Chapter 1: Developing student skills\n"
            "Chapter 2: Developing teacher skills\n"
            "Chapter 3: AI innovation training"
        ),
        "Preface: research background\nBody",
        "Chapter 1 Developing student AI skills\nBody",
        "Chapter 2 Developing teacher AI skills\nBody",
        "Chapter 3 AI innovation training\nBody",
        (
            "Appendix case distribution\n"
            "Chapter 1: Developing student skills\n"
            "Chapter 2: Developing teacher skills\n"
            "Chapter 3: AI innovation training"
        ),
    ]

    result = extract_visible_toc_no_pages(page_texts, toc_pages=[2], page_count=len(page_texts))

    assert result is not None
    main = result["toc_sections"][0]["items"]
    assert [(item["title"], item["physical_index"]) for item in main] == [
        ("Preface", 3),
        ("Chapter 1: Developing student skills", 4),
        ("Chapter 2: Developing teacher skills", 5),
        ("Chapter 3: AI innovation training", 6),
    ]


def test_mapper_keeps_search_start_after_toc_when_extra_pages_are_excluded() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    items = [{"title": "Chapter 1: Reliable heading", "level": 1, "source_page": 2}]
    page_texts = [
        "Cover",
        "Contents\nChapter 1: Reliable heading",
        "Chapter 1 Reliable heading\nBody",
        "Body",
        "Body",
        "Body",
        "Appendix\nChapter 1: Reliable heading",
    ]

    mapped, report = map_toc_items_to_physical_pages(
        items,
        page_texts=page_texts,
        page_count=len(page_texts),
        toc_pages=[2],
        excluded_pages=[7],
        min_title_match_rate=0.0,
    )

    assert report["status"] == "ok"
    assert mapped[0]["physical_index"] == 3


def test_mapper_fails_when_no_items_can_be_mapped() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    mapped, report = map_toc_items_to_physical_pages(
        [{"title": "Missing heading", "level": 1, "source_page": 2}],
        page_texts=["Cover", "Contents\nMissing heading", "Body without the title"],
        page_count=3,
        toc_pages=[2],
        min_title_match_rate=0.0,
    )

    assert mapped[0]["mapping_source"] == "unmapped"
    assert report["status"] == "failed"
    assert "no_content_anchors" in report["reasons"]


def test_mapper_uses_chapter_marker_when_title_words_change() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    mapped, report = map_toc_items_to_physical_pages(
        [{"title": "Chapter 8: AI education outlook", "level": 1, "source_page": 2}],
        page_texts=[
            "Cover",
            "Contents\nChapter 8: AI education outlook",
            "Chapter 8 Rebuilding the education ecosystem\nBody",
        ],
        page_count=3,
        toc_pages=[2],
        min_title_match_rate=0.0,
    )

    assert report["status"] == "ok"
    assert mapped[0]["physical_index"] == 3
    assert mapped[0]["mapping_source"] == "outline_marker"


def test_mapper_does_not_match_numbered_title_to_unnumbered_document_header() -> None:
    from pageindex.judge.content_page_mapper import map_toc_items_to_physical_pages

    mapped, report = map_toc_items_to_physical_pages(
        [{"title": "2. AI glasses key technology", "level": 1, "source_page": 2}],
        page_texts=[
            "Cover",
            "Contents\n2. AI glasses key technology",
            "AI glasses key technology and ecosystem report\nBody for chapter one",
            "More chapter one body",
            "2. AI glasses key technology\nBody",
        ],
        page_count=5,
        toc_pages=[2],
        min_title_match_rate=0.0,
    )

    assert report["status"] == "ok"
    assert mapped[0]["physical_index"] == 5


def test_score_title_on_page_bounds_fuzzy_scanning(monkeypatch) -> None:
    import pageindex.judge.content_page_mapper as mapper

    calls = {"count": 0}

    class CountingSequenceMatcher:
        def __init__(self, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] > 300:
                raise AssertionError("fuzzy title matching must stay bounded")

        def ratio(self) -> float:
            return 0.0

    monkeypatch.setattr(mapper, "SequenceMatcher", CountingSequenceMatcher)

    page_text = "\n".join(
        f"Body paragraph {index} with unrelated OCR text and repeated filler"
        for index in range(120)
    )

    scored = mapper.score_title_on_page(
        "AI driven city governance scenario with multimodal decision platform",
        page_text,
    )

    assert scored["score"] == 0.0
    assert calls["count"] <= 300


def test_visible_toc_rule_can_return_draft_without_physical_mapping() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages_draft

    page_texts = [
        "Cover",
        "Contents\nChapter 1 Alpha ........ 4\nChapter 2 Beta ........ 6\nChapter 3 Gamma ........ 8",
        "Preface",
        "Chapter 1 Alpha\nBody",
        "More A",
        "Chapter 2 Beta\nBody",
        "More A",
        "More B",
        "Chapter 3 Gamma\nBody",
    ]

    draft = extract_visible_toc_with_pages_draft(
        page_texts,
        toc_pages=[2],
        page_count=len(page_texts),
    )

    assert draft is not None
    assert draft["type"] == "toc_draft"
    assert draft["source"] == "toc_page_text_rule"
    assert draft["toc_sections"][0]["kind"] == "main_toc"
    items = draft["toc_sections"][0]["items"]
    assert [item["raw_page_label"] for item in items] == [4, 6, 8]
    assert all("physical_index" not in item for item in items)
    assert all("end_index" not in item for item in items)


def test_visible_toc_with_pages_draft_accepts_truncated_pdf_overflow_labels() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages_draft

    page_texts = [
        "Cover",
        "Blank",
        (
            "Contents\n"
            "About the Federal Reserve ........................................................................................... iii\n"
            "1 Overview ....................................................................................................................... 1\n"
            "2 Monetary Policy and Economic Developments ..................................................... 3\n"
            "3 Financial Stability ..................................................................................................... 15\n"
            "4 Supervision and Regulation .................................................................................... 25\n"
            "5 Payment System and Reserve Bank Oversight ................................................... 53\n"
            "6 Consumer and Community Affairs ......................................................................... 83"
        ),
    ] + ["Body"] * 47

    draft = extract_visible_toc_with_pages_draft(
        page_texts,
        toc_pages=[3],
        page_count=50,
    )

    assert draft is not None
    items = draft["toc_sections"][0]["items"]
    assert items[0]["title"] == "About the Federal Reserve"
    assert items[0]["raw_page_label"] == "iii"
    assert [item["title"] for item in items[1:5]] == [
        "1 Overview",
        "2 Monetary Policy and Economic Developments",
        "3 Financial Stability",
        "4 Supervision and Regulation",
    ]
    assert [item["raw_page_label"] for item in items[1:]] == [1, 3, 15, 25, 53, 83]


def test_visible_toc_with_pages_draft_rejects_running_header_as_group_heading() -> None:
    from pageindex.visible_toc_rule_extractor import extract_visible_toc_with_pages_draft

    page_texts = [
        "Cover",
        (
            "行业深度报告|\n"
            "1. 复盘：AI 新物种，大模型时代的全球领航者 ........ 4\n"
            "1.1、概况：十年磨剑，引领全球大模型产业 ........ 4\n"
            "2. 展望：模型为基，多模态、AI 应用全面发力 ........ 9\n"
            "4. 风险提示 ........ 25\n"
            "图1、OpenAI 与微软公司的合作机制 ........ 4\n"
            "图2、OpenAI 发起人及创始人 ........ 4"
        ),
        "Figure catalog tail",
        "1. 复盘：AI 新物种，大模型时代的全球领航者\nBody",
        "Body",
        "Body",
        "Body",
        "Body",
        "2. 展望：模型为基，多模态、AI 应用全面发力\nBody",
    ] + ["Body"] * 16 + ["4. 风险提示\nBody"]

    draft = extract_visible_toc_with_pages_draft(
        page_texts,
        toc_pages=[2, 3],
        page_count=len(page_texts),
    )

    assert draft is not None
    titles = [item["title"] for item in draft["toc_sections"][0]["items"]]
    assert "行业深度报告|" not in titles
    assert titles[0].startswith("1. 复盘")
