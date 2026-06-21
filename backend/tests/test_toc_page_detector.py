from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_text_detector_reports_mixed_figure_and_table_sections() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            (
                "图目录\n"
                "图 1 AI 眼镜系统架构 ........ 12\n"
                "图 2 光学方案对比 ........ 18\n"
                "表目录\n"
                "表 1 供应链公司清单 ........ 28\n"
                "表 2 关键参数对比 ........ 35"
            ),
            "正文第一页",
        ],
        max_scan_pages=5,
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["sections"] == [
        {"kind": "figure_toc", "pages": [2]},
        {"kind": "table_toc", "pages": [2]},
    ]
    detected_candidate = next(candidate for candidate in report["candidates"] if candidate["page"] == 2)
    assert detected_candidate["primary_kind"] == "mixed_toc"


def test_text_detector_continues_when_batch_tail_is_toc_page() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            "目录\n第一章 总则 ........ 5\n第二章 方法 ........ 12\n第三章 结果 ........ 20",
            "目录\n第四章 应用 ........ 30\n第五章 风险 ........ 40\n第六章 附录 ........ 50",
            "图目录\n图 1 架构图 ........ 16\n图 2 流程图 ........ 22\n表目录\n表 1 参数表 ........ 24",
            "正文第一页",
        ],
        max_scan_pages=5,
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2, 3, 4]


def test_text_detector_rejects_body_disclaimer_and_references() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            "第一章 风险提示\n本章对政策、市场、技术与商业化风险进行详细说明，以下内容为正文段落。",
            "免责声明\n本报告仅供参考，不构成任何投资建议。请务必阅读正文之后的免责声明。",
            "参考文献\n[1] Research paper title\n[2] Another paper title",
        ],
        max_scan_pages=4,
    )

    assert report["status"] == "not_found"
    assert report["pages"] == []


def test_text_detector_accepts_split_main_toc_heading() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            (
                "\u76ee\n"
                "\u5f55\n"
                "\u7b2c\u4e00\u7ae0\u603b\u5219 ........ 1\n"
                "\u4e00\u3001\u6307\u5357\u76ee\u7684\u53ca\u57fa\u672c\u539f\u5219 ........ 1\n"
                "\u4e8c\u3001\u76f8\u5173\u672f\u8bed\u754c\u5b9a ........ 3\n"
                "\u7b2c\u4e8c\u7ae0\u5907\u6848\u53d1\u5c55\u73b0\u72b6 ........ 5\n"
                "\u7b2c\u4e09\u7ae0\u5907\u6848\u6d41\u7a0b\u89e3\u6790 ........ 27"
            ),
            "Body",
        ],
        max_scan_pages=5,
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["sections"] == [{"kind": "main_toc", "pages": [2]}]


def test_split_main_toc_heading_survives_long_catalog_lines() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    long_dots = "." * 110
    report = detect_toc_pages_text_report(
        [
            "Cover",
            (
                "\u76ee\n"
                "\u5f55\n"
                f"\u7b2c\u4e00\u7ae0\u603b\u5219{long_dots}1\n"
                f"\u4e00\u3001\u6307\u5357\u76ee\u7684\u53ca\u57fa\u672c\u539f\u5219{long_dots}1\n"
                f"\u4e8c\u3001\u76f8\u5173\u672f\u8bed\u754c\u5b9a{long_dots}3\n"
                f"\u7b2c\u4e8c\u7ae0\u5907\u6848\u53d1\u5c55\u73b0\u72b6{long_dots}5\n"
                f"\u7b2c\u4e09\u7ae0\u5907\u6848\u6d41\u7a0b\u89e3\u6790{long_dots}27"
            ),
            "Body",
        ],
        max_scan_pages=5,
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["sections"] == [{"kind": "main_toc", "pages": [2]}]


def test_auxiliary_catalog_heading_does_not_imply_main_toc_section() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            (
                "\u8868\u76ee\u5f55\n"
                "\u88681\n"
                "\u4e2d\u592e\u5c42\u9762\u4eba\u5de5\u667a\u80fd\u5907\u6848\u653f\u7b56\u6587\u4ef6 ........ 5\n"
                "\u88682\n"
                "\u5317\u4eac\u5e02\u751f\u6210\u5f0f\u4eba\u5de5\u667a\u80fd\u5907\u6848\u653f\u7b56\u6587\u4ef6 ........ 7\n"
                "\u88683\n"
                "\u5e7f\u4e1c\u7701\u751f\u6210\u5f0f\u4eba\u5de5\u667a\u80fd\u5907\u6848\u653f\u7b56\u6587\u4ef6 ........ 10"
            ),
            "Body",
        ],
        max_scan_pages=5,
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["sections"] == [{"kind": "table_toc", "pages": [2]}]


def test_auxiliary_catalog_continuation_does_not_imply_main_toc_section() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            (
                "\u56fe29\u3001ChatGPT Atlas \u6d4f\u89c8\u5668\u9875\u9762 ........ 18\n"
                "\u56fe30\u3001Codex \u6c34\u5e73\u9886\u5148 ........ 19\n"
                "\u56fe31\u3001Codex \u652f\u6301\u591a\u79cd\u62d3\u5c55\u5f62\u5f0f ........ 19\n"
                "\u88681\u3001OpenAI \u6838\u5fc3\u5458\u5de5\u79bb\u804c\u540e\u7684\u521b\u4e1a\u60c5\u51b5 ........ 6\n"
                "\u88682\u3001OpenAI \u5386\u6b21\u878d\u8d44\u60c5\u51b5\u68b3\u7406 ........ 8\n"
                "\u88683\u3001OpenAI \u7684\u5173\u952e\u6a21\u578b\u8fed\u4ee3\u60c5\u51b5\u68b3\u7406 ........ 9"
            ),
            "Body",
        ],
        max_scan_pages=5,
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["sections"] == [
        {"kind": "figure_toc", "pages": [2]},
        {"kind": "table_toc", "pages": [2]},
    ]


def test_text_detector_rejects_dense_body_table_page_without_toc_heading() -> None:
    from pageindex.toc_detector import classify_toc_page_text

    body_table_page = "\n".join(
        [
            "4 8",
            "16",
            "32",
            "64",
            "k",
            "0.0",
            "0.5",
            "1.0",
            "1.5",
            "2.0",
            "Query time (s)",
            "CAP",
            "COS",
            "NET",
            "SSP",
            "TRA",
            "SIA",
            "(a) RETINA",
            "4 8",
            "16",
            "32",
            "64",
            "k",
            "0",
            "5",
            "10",
            "15",
            "Query time (s)",
            "CAP",
            "COS",
            "NET",
            "SSP",
            "TRA",
            "SIA",
            "(b) IRMA",
            "4 8",
            "16",
            "32",
            "64",
            "k",
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "Query time (x103 s)",
            "CAP",
            "COS",
            "NET",
            "SSP",
            "TRA",
            "SIA",
            "(c) PANORAMIO",
            "4 8",
            "16",
            "32",
            "64",
            "k",
            "0",
            "5",
            "10",
            "15",
            "20",
            "Query time (x103 s)",
            "CAP",
            "COS",
            "NET",
            "SSP",
            "TRA",
            "SIA",
            "(d) FRIENDS",
            "Figure 9: Query time comparison.",
        ]
    )

    candidate = classify_toc_page_text(body_table_page, page=10)

    assert candidate["is_toc"] is False


def test_llm_toc_page_payload_normalizes_typed_sections() -> None:
    from pageindex.toc_detector import normalize_llm_toc_page_payload

    candidate = normalize_llm_toc_page_payload(
        {
            "is_toc": True,
            "primary_kind": "mixed_toc",
            "sections": [
                {"kind": "figure_toc", "confidence": 0.91},
                {"kind": "table_toc", "confidence": 0.86},
            ],
            "confidence": 0.9,
        },
        page=5,
        batch_index=2,
        batch_size=5,
    )

    assert candidate["is_toc"] is True
    assert candidate["primary_kind"] == "mixed_toc"
    assert candidate["sections"] == [
        {"kind": "figure_toc", "confidence": 0.91},
        {"kind": "table_toc", "confidence": 0.86},
    ]
    assert candidate["score"] == 0.9
