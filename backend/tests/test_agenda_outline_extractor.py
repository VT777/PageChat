from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pageindex.agenda_outline_extractor import (
    build_agenda_outline,
    extract_agenda_sections,
    extract_page_title,
    is_agenda_outline_document,
    is_agenda_page,
)


def _ai_application_pages():
    agenda = (
        "请务必阅读正文之后的免责声明及其项下所有内容\n"
        "国外大厂AI应用落地\n01\n"
        "国内大厂AI应用落地\n02\n"
        "目录\n"
        "产业链梳理\n03\n"
        "风险提示\n04"
    )
    return [
        "请务必阅读正文之后的免责声明及其项下所有内容\n2026年01月14日\nAI应用专题：\n各大厂新模型持续迭代，重视AI应用板块投资机会",
        "请务必阅读正文之后的免责声明及其项下所有内容\n摘要\n国外大厂AI应用落地，垂直场景深耕",
        agenda,
        "请务必阅读正文之后的免责声明及其项下所有内容\nOpen AI发布 ChatGPT Health 健康应用\nu ChatGPT Health正式落地医疗场景",
        "请务必阅读正文之后的免责声明及其项下所有内容\nAnthropic：Claude for Healthcare\nu 基于去年10月发布",
        "请务必阅读正文之后的免责声明及其项下所有内容\n亚马逊：推出AI退货看板\nu 推出针对跨境电商卖家",
        "请务必阅读正文之后的免责声明及其项下所有内容\n谷歌：AI模型最新迭代及场景化落地\n资料来源：CES大会",
        "请务必阅读正文之后的免责声明及其项下所有内容\n英伟达：推出全新Rubin平台及更新DLSS 4.5\nu 推出全新 AI 平台",
        agenda,
        "请务必阅读正文之后的免责声明及其项下所有内容\n阿里巴巴：AQ健康品牌升级为蚂蚁阿福\n资料来源：蚂蚁阿福官网",
        "请务必阅读正文之后的免责声明及其项下所有内容\n阿里巴巴：千问APP公测上线\nu 推出千问 App",
        "请务必阅读正文之后的免责声明及其项下所有内容\n表：字节春晚深度参与场景\n字节：官宣成为央视春晚独家AI伙伴\nu 春晚独家AI云合作伙伴",
        "请务必阅读正文之后的免责声明及其项下所有内容\nDeepseek：预计2月中旬发布V4旗舰模型\nu 发布全新训练架构",
        "请务必阅读正文之后的免责声明及其项下所有内容\n表：计划核心扶持内容\n腾讯：推出“AI应用及线上工具小程序成长计划”\nu 推出成长计划",
        "请务必阅读正文之后的免责声明及其项下所有内容\nMinimax智谱上市\n资料来源：Wind",
        agenda,
        "请务必阅读正文之后的免责声明及其项下所有内容\n应用方向\n标的\n多模态\n昆仑万维、万兴科技",
        agenda,
        "请务必阅读正文之后的免责声明及其项下所有内容\n风险提示\nØ 技术研发不及预期",
        "请务必阅读正文之后的免责声明及其项下所有内容\n免责声明\n分析师承诺\n作者保证报告所采用的数据",
        "请务必阅读正文之后的免责声明及其项下所有内容\n国信证券经济研究所\n深圳\n深圳市福田区福华一路125号",
    ]


def test_is_agenda_page_detects_numbered_menu_pages():
    pages = _ai_application_pages()

    assert is_agenda_page(pages[2]) is True
    assert is_agenda_page(pages[3]) is False


def test_extract_agenda_sections_from_menu_page():
    sections = extract_agenda_sections(_ai_application_pages()[2])

    assert sections == [
        {"number": 1, "title": "国外大厂AI应用落地"},
        {"number": 2, "title": "国内大厂AI应用落地"},
        {"number": 3, "title": "产业链梳理"},
        {"number": 4, "title": "风险提示"},
    ]


def test_extract_page_title_skips_header_and_table_titles():
    pages = _ai_application_pages()

    assert extract_page_title(pages[0]) == "AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会"
    assert extract_page_title(pages[3]) == "Open AI发布 ChatGPT Health 健康应用"
    assert extract_page_title(pages[11]) == "字节：官宣成为央视春晚独家AI伙伴"
    assert extract_page_title(pages[16]) is None


def test_build_agenda_outline_groups_page_titles_under_menu_sections():
    pages = _ai_application_pages()
    analysis = {
        "page_count": len(pages),
        "page_texts": pages,
        "text_coverage": 1.0,
    }

    assert is_agenda_outline_document(analysis) is True
    result = build_agenda_outline(analysis)

    assert result["source"] == "agenda_outline"
    titles = [item["title"] for item in result["toc_items"]]
    structures = [item["structure"] for item in result["toc_items"]]

    assert "目录" not in titles
    assert structures == [
        "0",
        "0.1",
        "0.2",
        "1",
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "2",
        "2.1",
        "2.2",
        "2.3",
        "2.4",
        "2.5",
        "2.6",
        "3",
        "4",
        "A",
        "A.1",
        "A.2",
    ]
    assert titles[3] == "国外大厂AI应用落地"
    assert titles[4] == "Open AI发布 ChatGPT Health 健康应用"
    assert titles[9] == "国内大厂AI应用落地"
    assert titles[16] == "产业链梳理"
    assert titles[18] == "Appendix"
