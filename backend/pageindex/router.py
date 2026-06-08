"""智能路由决策模块 — 根据文档画像选择最优提取路径。"""

import os
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

PATH_TOC_PAGE = "toc_page"           # TOC页提取（有目录页）
PATH_HIERARCHICAL = "hierarchical"   # 分层提取（长文档，默认）
PATH_BATCH = "batch"                 # 批量每页提取（PPT/汇报提纲）
PATH_VISUAL = "visual"               # 视觉提取（图片PDF）
PATH_FAST_TEXT = "fast_text"         # 快速文本提取（短文档）

ALL_PATHS = [PATH_TOC_PAGE, PATH_HIERARCHICAL, PATH_BATCH, PATH_VISUAL, PATH_FAST_TEXT]


# ---------------------------------------------------------------------------
# 路由决策
# ---------------------------------------------------------------------------

def decide_extraction_path(analysis: Dict[str, Any], mode: str = "smart") -> Dict[str, Any]:
    """根据文档分析结果，选择最优提取路径。

    5-path 决策逻辑（优先级从高到低）：
    1. TOC页路径: 检测到目录页且置信度>=0.6 → 直接提取
    2. 视觉路径: 图片PDF或文本质量极低 → OCR/VLM提取
    3. 批量路径: 章节分隔页>=5（PPT/汇报提纲模式）→ 逐页提取
    4. 快速文本: 短文档(<=20页)且文本质量高 → 单次LLM提取
    5. 分层提取: 默认路径，适合长文档

    Args:
        analysis: analyze_pdf_structure 的返回结果
        mode: 用户请求模式 ("smart", "fast", "balanced")

    Returns:
        {
            "path": str,           # 选择的路径
            "confidence": float,   # 决策置信度
            "reasons": List[str],  # 决策理由
            "alternatives": List[str],  # 备选路径
        }
    """
    page_count = analysis.get("page_count", 0)
    text_coverage = analysis.get("text_coverage", 0)
    is_image_only = analysis.get("is_image_only_pdf", False)
    is_garbled = analysis.get("is_garbled_pdf", False)
    quality = analysis.get("text_quality", {})
    chapter_dividers = analysis.get("chapter_dividers", [])
    toc_page_info = analysis.get("toc_page", {})

    reasons = []
    alternatives = []

    # --- 模式覆盖 ---
    if mode == "fast":
        # Fast 模式：尽可能使用快速路径
        if page_count <= 20 and text_coverage > 0.5 and not is_garbled:
            reasons.append("Fast mode: 短文档，使用快速文本路径")
            return _make_decision(PATH_FAST_TEXT, 0.9, reasons, [PATH_HIERARCHICAL])
        elif toc_page_info.get("has_toc_page") and toc_page_info.get("confidence", 0) >= 0.5:
            reasons.append("Fast mode: 检测到目录页，使用TOC页路径")
            return _make_decision(PATH_TOC_PAGE, 0.85, reasons, [PATH_FAST_TEXT])
        else:
            reasons.append("Fast mode: 回退到快速文本路径")
            return _make_decision(PATH_FAST_TEXT, 0.7, reasons, [PATH_HIERARCHICAL])

    if mode == "balanced":
        # Balanced 模式：优先TOC页，其次分层
        if toc_page_info.get("has_toc_page") and toc_page_info.get("confidence", 0) >= 0.5:
            reasons.append("Balanced mode: 检测到目录页")
            return _make_decision(PATH_TOC_PAGE, 0.8, reasons, [PATH_HIERARCHICAL])

    # --- 智能路由决策 ---

    # 1. 视觉路径（最高优先级，因为图片PDF几乎无法用文本提取）
    if is_image_only:
        reasons.append(f"图片PDF: {text_coverage:.0%} 页面无文本")
        return _make_decision(PATH_VISUAL, 0.95, reasons, [PATH_BATCH])

    if is_garbled or (quality.get("meaningful_ratio", 1) < 0.15 and text_coverage < 0.3):
        reasons.append(f"文本质量极低: meaningful={quality.get('meaningful_ratio', 0):.0%}")
        return _make_decision(PATH_VISUAL, 0.9, reasons, [PATH_BATCH])

    # 2. TOC页路径
    if toc_page_info.get("has_toc_page"):
        toc_conf = toc_page_info.get("confidence", 0)
        if toc_conf >= 0.6:
            reasons.append(f"检测到目录页 (confidence={toc_conf:.2f})")
            return _make_decision(PATH_TOC_PAGE, toc_conf, reasons, [PATH_HIERARCHICAL])
        elif toc_conf >= 0.4:
            alternatives.append(PATH_TOC_PAGE)
            reasons.append(f"疑似目录页 (confidence={toc_conf:.2f})，作为备选")

    # 3. 批量路径（章节分隔页模式）
    if len(chapter_dividers) >= 5:
        reasons.append(f"检测到{len(chapter_dividers)}个章节分隔页（PPT/汇报提纲模式）")
        return _make_decision(PATH_BATCH, 0.85, reasons, [PATH_HIERARCHICAL])

    # 4. 快速文本路径
    if page_count <= 20 and text_coverage > 0.5 and not is_garbled:
        heading_density = calculate_heading_density(analysis)
        if heading_density < 0.3:  # 标题密度低，结构简单
            reasons.append(f"短文档({page_count}页)，标题密度低({heading_density:.2f})，适合快速提取")
            return _make_decision(PATH_FAST_TEXT, 0.8, reasons, [PATH_HIERARCHICAL])
        else:
            alternatives.append(PATH_FAST_TEXT)
            reasons.append(f"短文档但标题密度高({heading_density:.2f})，分层提取更准确")

    # 5. 默认：分层提取
    reasons.append(f"长文档({page_count}页)，使用分层提取保证完整性")
    if alternatives:
        return _make_decision(PATH_HIERARCHICAL, 0.75, reasons, alternatives)
    return _make_decision(PATH_HIERARCHICAL, 0.75, reasons, [PATH_FAST_TEXT])


def _make_decision(path: str, confidence: float, reasons: List[str], alternatives: List[str]) -> Dict[str, Any]:
    """构造决策结果。"""
    return {
        "path": path,
        "confidence": confidence,
        "reasons": reasons,
        "alternatives": alternatives,
    }


# ---------------------------------------------------------------------------
# 辅助特征计算
# ---------------------------------------------------------------------------

def calculate_heading_density(analysis: Dict[str, Any]) -> float:
    """计算文档的标题密度（每页平均标题行数）。
    
    标题行特征：
    - 行首有编号（1.、1.1、第X章、（一）等）
    - 行长度适中（10-80字符）
    - 非页眉/页脚
    
    返回 0-1 的密度值。
    """
    import re
    page_texts = analysis.get("page_texts", [])
    if not page_texts:
        return 0.0

    heading_patterns = [
        r'^第[一二三四五六七八九十百零〇两\d]+[章节部分篇]',  # 第一章
        r'^\d{1,2}(?:\.\d{1,2}){0,2}\s+[^\s]',              # 1.1 标题
        r'^[一二三四五六七八九十]+、',                          # 一、
        r'^[（(][一二三四五六七八九十\d]+[)）]',                # （一）
        r'^\d+\.\s+[^\d]',                                   # 1. 标题
        r'^(?:Chapter|Section|Part)\s+\d+',                    # Chapter 1
    ]
    combined = re.compile('|'.join(f'({p})' for p in heading_patterns))

    total_headings = 0
    for text in page_texts:
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if 10 <= len(line) <= 80 and combined.match(line):
                total_headings += 1

    return total_headings / len(page_texts) if page_texts else 0.0


def get_path_description(path: str) -> str:
    """获取路径的中文描述。"""
    descriptions = {
        PATH_TOC_PAGE: "目录页提取（直接解析目录页）",
        PATH_HIERARCHICAL: "分层提取（先框架后展开）",
        PATH_BATCH: "批量提取（逐页提取，适合PPT）",
        PATH_VISUAL: "视觉提取（OCR/VLM，适合图片PDF）",
        PATH_FAST_TEXT: "快速文本提取（单次LLM，适合短文档）",
    }
    return descriptions.get(path, f"未知路径: {path}")
