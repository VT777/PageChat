from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex import page_index as page_index_module


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
