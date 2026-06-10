from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import page_index as page_index_module
from pageindex import toc_detector as toc_detector_module


def test_find_toc_pages_enriches_missing_contiguous_page(monkeypatch) -> None:
    page_list = [
        ("封面", 10),
        ("前言", 10),
        ("目录\n1.1 总览: 1\n1.2 方法: 3\n1.3 结果: 5", 10),
        ("目录\n2.1 框架: 8\n2.2 实现: 12\n2.3 评测: 14", 10),
        ("3.1 场景: 18 3.2 对比: 22 3.3 小结: 25", 10),
        ("正文第一页", 10),
    ]
    opt = SimpleNamespace(toc_check_page_num=6, model="dummy")

    monkeypatch.setattr(
        page_index_module, "toc_detector_batch", lambda *args, **kwargs: [2, 3]
    )

    toc_pages = page_index_module.find_toc_pages(0, page_list, opt)
    assert toc_pages == [2, 3, 4]


def test_find_toc_pages_does_not_append_non_toc_tail(monkeypatch) -> None:
    page_list = [
        ("封面", 10),
        ("目录\n1.1 总览: 1\n1.2 方法: 3\n1.3 结果: 5", 10),
        ("目录\n2.1 框架: 8\n2.2 实现: 12\n2.3 评测: 14", 10),
        ("这是正文，不是目录页", 10),
    ]
    opt = SimpleNamespace(toc_check_page_num=4, model="dummy")

    monkeypatch.setattr(
        page_index_module, "toc_detector_batch", lambda *args, **kwargs: [1, 2]
    )

    toc_pages = page_index_module.find_toc_pages(0, page_list, opt)
    assert toc_pages == [1, 2]


def test_find_toc_pages_prefers_text_detection_for_text_rich_docs(monkeypatch) -> None:
    called = {"text": False, "visual": False}

    def fake_text_detection(_page_texts):
        called["text"] = True
        return [2]

    async def fake_visual_detection(*_args, **_kwargs):
        called["visual"] = True
        return [99]

    monkeypatch.setattr(toc_detector_module, "detect_toc_pages_text", fake_text_detection)
    monkeypatch.setattr(toc_detector_module, "detect_toc_pages_visual", fake_visual_detection)

    result = __import__("asyncio").run(
        toc_detector_module.find_toc_pages(
            {
                "text_coverage": 1.0,
                "image_coverage": 0.8,
                "is_image_only_pdf": False,
                "page_texts": ["封面", "目录\n第一章\n第二章"],
            },
            "dummy.pdf",
            model=None,
        )
    )

    assert result == [2]
    assert called == {"text": True, "visual": False}


def test_find_toc_pages_uses_visual_when_structure_policy_requires_visual(monkeypatch) -> None:
    called = {"text": False, "visual": False}

    def fake_text_detection(_page_texts):
        called["text"] = True
        return [2]

    async def fake_visual_detection(*_args, **_kwargs):
        called["visual"] = True
        return [4]

    monkeypatch.setattr(toc_detector_module, "detect_toc_pages_text", fake_text_detection)
    monkeypatch.setattr(toc_detector_module, "detect_toc_pages_visual", fake_visual_detection)

    result = __import__("asyncio").run(
        toc_detector_module.find_toc_pages(
            {
                "text_coverage": 0.71,
                "image_coverage": 0.4,
                "is_image_only_pdf": False,
                "structure_policy": "visual_required",
                "layout_type": "visual_hybrid",
                "page_texts": ["cover", "toc"],
            },
            "dummy.pdf",
            model=None,
        )
    )

    assert result == [4]
    assert called == {"text": False, "visual": True}
