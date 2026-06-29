from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_text_detector_includes_contiguous_toc_tail() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    page_texts = [
        "封面",
        "前言",
        "目录\n1.1 总览 ........ 1\n1.2 方法 ........ 3\n1.3 结果 ........ 5",
        "目录\n2.1 框架 ........ 8\n2.2 实现 ........ 12\n2.3 评测 ........ 14",
        "目录\n3.1 场景 ........ 18\n3.2 对比 ........ 22\n3.3 小结 ........ 25",
        "正文第一页",
    ]

    report = detect_toc_pages_text_report(page_texts, max_scan_pages=6)

    assert report["pages"] == [3, 4, 5]
    assert report["status"] == "detected"


def test_text_detector_does_not_append_non_toc_tail() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    page_texts = [
        "封面",
        "目录\n1.1 总览 ........ 1\n1.2 方法 ........ 3\n1.3 结果 ........ 5",
        "目录\n2.1 框架 ........ 8\n2.2 实现 ........ 12\n2.3 评测 ........ 14",
        "这是正文，不是目录页。这里开始介绍第一章的研究背景和主要观点。",
    ]

    report = detect_toc_pages_text_report(page_texts, max_scan_pages=4)

    assert report["pages"] == [2, 3]
    assert report["status"] == "detected"
