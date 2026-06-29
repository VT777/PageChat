import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_garbled_detector_catches_rare_cjk_mojibake() -> None:
    from pageindex.pdf_analyzer import _classify_page, _is_garbled_text

    text = (
        "2025 妘AI 熎絔悞鶯\n"
        "隠㚵蔠裮䅳熱閔\n"
        "䖇栕鵾腬 藗譛紨矈 蒫闎熏\n"
    ) * 3

    assert _is_garbled_text(text) is True
    assert _classify_page(text, image_count=0) == "garbled"


def test_garbled_detector_keeps_normal_chinese_text() -> None:
    from pageindex.pdf_analyzer import _classify_page, _is_garbled_text

    text = (
        "2025年人工智能治理报告：回归现实主义。\n"
        "本报告分析大模型产业、政策监管、风险治理与企业应用趋势，"
        "并结合国内外案例提出可执行建议。\n"
    ) * 3

    assert _is_garbled_text(text) is False
    assert _classify_page(text, image_count=0) == "text"
