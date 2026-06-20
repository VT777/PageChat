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
        ("01", "Overseas AI applications", 4),
        ("02", "Domestic AI applications", 10),
        ("03", "AI supply chain", 17),
        ("04", "AI risk notice", 19),
    ]
    assert [item["mapping_source"] for item in main] == ["section_divider_sequence"] * 4
    assert result["mapping_report"]["strategy"] == "section_divider_sequence"


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
