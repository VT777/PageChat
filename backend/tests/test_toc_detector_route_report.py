import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_text_toc_report_marks_printed_page_numbers() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "Cover",
            "目录\n第一章 总则 ........ 5\n第二章 方法 ........ 12\n第三章 结果 ........ 20\n第四章 风险提示 ........ 25\n第五章 附录 ........ 30",
            "正文第一页",
        ]
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["has_page_numbers"] is True


def test_text_toc_report_marks_unpaged_toc() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "封面",
            "目录\n序言\n第一章：发展学生智能素养\n第二章：发展教师智能教学素养\n第三章：AI创新人才培养范式\n第四章：AI促进产教深度融合\n第五章：升级智慧校园与管理",
            "序言：研究背景\n时代浪潮",
        ]
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["has_page_numbers"] is False


def test_text_toc_report_allows_page_header_before_unpaged_toc_heading() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    report = detect_toc_pages_text_report(
        [
            "封面",
            "请务必阅读正文之后的免责声明及其项下所有内容\n国外大厂AI应用落地\n01\n国内大厂AI应用落地\n02\n目录\n产业链梳理\n03\n风险提示\n04",
            "国外大厂AI应用落地\nOpenAI发布健康应用",
        ]
    )

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["has_page_numbers"] is False


def test_text_toc_report_treats_dense_numbered_catalog_as_paged() -> None:
    from pageindex.toc_detector import detect_toc_pages_text_report

    catalog_lines = "\n".join(
        f"{idx:02d} Example catalog item {idx}" for idx in range(1, 13)
    )

    report = detect_toc_pages_text_report(["Cover", f"目录\n{catalog_lines}", "Body"])

    assert report["status"] == "detected"
    assert report["pages"] == [2]
    assert report["has_page_numbers"] is True


def test_find_toc_pages_stores_route_report_on_analysis() -> None:
    from pageindex.toc_detector import find_toc_pages

    analysis = {
        "page_texts": [
            "封面",
            "目录\n序言\n第一章：发展学生智能素养\n第二章：发展教师智能教学素养\n第三章：AI创新人才培养范式\n第四章：AI促进产教深度融合",
            "序言：研究背景",
        ]
    }

    pages = asyncio.run(find_toc_pages(analysis, "doc.pdf", model=None))

    assert pages == [2]
    assert analysis["toc_page_detection"]["pages"] == [2]
    assert analysis["toc_page_detection"]["has_page_numbers"] is False
