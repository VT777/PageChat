"""TOC 目录页检测模块 — 文本检测 + VLM视觉检测。

职责：
1. 从文本中检测目录页（代码扫描，低成本）
2. 从视觉中检测目录页（VLM，高成本但更准确）
3. 统一入口，智能选择检测方式
"""

import asyncio
import base64
import io
import math
import re
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

MAX_SCAN_PAGES = 20  # 扫描前N页
TOC_SCORE_THRESHOLD = 60  # 目录页及格线

# ---------------------------------------------------------------------------
# 文本目录检测
# ---------------------------------------------------------------------------

def detect_toc_pages_text(page_texts: List[str], max_scan_pages: int = MAX_SCAN_PAGES) -> Optional[List[int]]:
    """从文本中检测目录页。
    
    Args:
        page_texts: 所有页面的文本列表
        max_scan_pages: 最大扫描页数
        
    Returns:
        目录页物理页码列表（1-indexed），未找到返回 None
    """
    if not page_texts:
        return None
    
    # 复用 pdf_analyzer 中的 _detect_toc_pages 逻辑
    from pageindex.pdf_analyzer import _detect_toc_pages
    
    has_toc, toc_indices, confidence, _ = _detect_toc_pages(page_texts, max_scan_pages)
    
    if has_toc and confidence >= 0.5:
        # 转换 0-indexed 到 1-indexed
        return [idx + 1 for idx in toc_indices]
    
    return None


# ---------------------------------------------------------------------------
# VLM 视觉目录检测
# ---------------------------------------------------------------------------

VLM_TOC_DETECTION_PROMPT = """你是 PDF 文档分析专家。这些是文档前20页的缩略图网格。

## 任务
找出哪些页面是"目录页"。

## 目录页的判断标准（满足任意一项即可）
1. 页面顶部有"目录"、"Contents"、"目次"、"Table of Contents"等标题
2. 页面上有多个条目，每个条目带有页码数字（通常用点线"...."连接）
3. 条目通常有层级结构（如"第一章"、"1.1"、"一、"等编号）

## 注意
- "图目录"/"表目录"/"插图目录"也是目录页的一种
- 目录页通常连续出现（2-5页）
- 目录页之后的第一页通常是正文开始

## 图像说明
每张图的左上角标注了页码范围（如 p.1-p.8）。

## 输出格式（严格JSON，不要markdown代码块）
{
  "toc_pages": [3, 4, 5],
  "confidence": "high",
  "reasoning": "第3页有'目录'标题和多个带页码的条目；第4-5页是目录的延续，包含表目录和图目录..."
}

如果没有找到目录页：
{
  "toc_pages": [],
  "confidence": "low",
  "reasoning": "前20页中没有符合目录页特征的页面。第1页是封面，第2页是前言..."
}"""


def render_toc_detection_grids(
    file_path: str,
    max_pages: int = 20,
    thumb_width: int = 400,
    thumb_height: int = 560,
    pages_per_grid: int = 8,
    cols: int = 4,
    padding: int = 12,
    label_height: int = 22,
) -> List[Dict[str, Any]]:
    """渲染前N页为多页网格图，用于VLM目录检测。
    
    相比现有缩略图：
    - 单页更大（400x560 vs 250x350）
    - 每页数量更少（8页/张 vs 12页/张）
    - 确保目录条目和页码可读
    """
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont
    
    doc = pymupdf.open(file_path)
    page_count = min(len(doc), max_pages)
    
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    
    grids = []
    
    for start in range(0, page_count, pages_per_grid):
        end = min(start + pages_per_grid, page_count)
        n_pages = end - start
        rows = math.ceil(n_pages / cols)
        
        canvas_width = cols * (thumb_width + padding) + padding
        canvas_height = rows * (thumb_height + label_height + padding) + padding
        
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(canvas)
        
        for i in range(n_pages):
            page_num = start + i
            row = i // cols
            col = i % cols
            
            x = padding + col * (thumb_width + padding)
            y = padding + row * (thumb_height + label_height + padding)
            
            page = doc[page_num]
            page_rect = page.rect
            scale = min(thumb_width / page_rect.width, thumb_height / page_rect.height)
            mat = pymupdf.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            
            thumb_img = Image.open(io.BytesIO(pix.tobytes("png")))
            offset_x = (thumb_width - thumb_img.width) // 2
            offset_y = (thumb_height - thumb_img.height) // 2
            canvas.paste(thumb_img, (x + offset_x, y + label_height + offset_y))
            
            draw.rectangle(
                [x, y + label_height, x + thumb_width, y + label_height + thumb_height],
                outline="#999999",
                width=1,
            )
            draw.text((x + 4, y + 2), f"p.{page_num + 1}", fill="black", font=font)
        
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        grids.append({
            "start_page": start,
            "end_page": end - 1,
            "image_base64": b64,
        })
    
    doc.close()
    return grids


async def detect_toc_pages_visual(file_path: str, model: Optional[str] = None) -> Optional[List[int]]:
    """用VLM从视觉中检测目录页。
    
    Args:
        file_path: PDF文件路径
        model: VLM模型
        
    Returns:
        目录页物理页码列表（1-indexed），未找到返回 None
    """
    from pageindex.vlm_utils import vlm_call_with_images, parse_vlm_json
    
    print(f"[TOC-DETECT] VLM visual detection for {file_path}")
    
    # 渲染网格图
    grids = render_toc_detection_grids(file_path, max_pages=20)
    if not grids:
        return None
    
    grid_images = [{"page_index": 0, "image_base64": g["image_base64"]} for g in grids]
    
    # 调用VLM
    try:
        raw = await vlm_call_with_images(
            grid_images, VLM_TOC_DETECTION_PROMPT, model=model, max_tokens=3000
        )
        result = parse_vlm_json(raw)
        
        if not isinstance(result, dict):
            return None
        
        toc_pages = result.get("toc_pages", [])
        confidence = result.get("confidence", "low")
        
        if toc_pages and len(toc_pages) >= 1 and confidence in ("high", "medium"):
            print(f"[TOC-DETECT] VLM found toc pages: {toc_pages} (confidence={confidence})")
            return toc_pages
        else:
            print(f"[TOC-DETECT] VLM no toc found (confidence={confidence})")
            return None
            
    except Exception as e:
        print(f"[TOC-DETECT] VLM detection failed: {e}")
        return None


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

async def find_toc_pages(
    analysis: Dict[str, Any],
    file_path: str,
    model: Optional[str] = None,
) -> Optional[List[int]]:
    """查找目录页统一入口。
    
    策略：
    1. 图片型文档 → 直接用VLM视觉检测
    2. 文本型文档 → 先文本检测，失败再降级到VLM
    
    Args:
        analysis: pdf_analyzer 的分析结果
        file_path: PDF文件路径
        model: VLM模型
        
    Returns:
        目录页物理页码列表（1-indexed），未找到返回 None
    """
    # Prefer text detection when extracted text is usable. Many text PDFs embed
    # images on most pages; image_coverage alone should not make them visual docs.
    text_coverage = float(analysis.get("text_coverage") or 0.0)
    image_coverage = float(analysis.get("image_coverage") or 0.0)
    structure_policy = str(analysis.get("structure_policy") or "").lower()
    layout_type = str(analysis.get("layout_type") or "").lower()
    if structure_policy == "visual_required":
        print(
            f"[TOC-DETECT] profile={layout_type or 'unknown'} "
            f"policy=visual_required, using VLM visual detection"
        )
        return await detect_toc_pages_visual(file_path, model)

    is_image_doc = bool(analysis.get("is_image_only_pdf", False)) or (
        text_coverage < 0.3 and image_coverage >= 0.3
    )
    
    page_texts = analysis.get("page_texts", [])
    
    if is_image_doc:
        # 图片型 → 直接用VLM
        print("[TOC-DETECT] Image-type document, using VLM visual detection")
        return await detect_toc_pages_visual(file_path, model)
    else:
        # 文本型 → 先文本检测
        print("[TOC-DETECT] Text-type document, trying text detection first")
        toc_pages = detect_toc_pages_text(page_texts)
        
        if toc_pages:
            print(f"[TOC-DETECT] Text detection found toc pages: {toc_pages}")
            return toc_pages
        else:
            # 文本方法没找到，降级到VLM
            print("[TOC-DETECT] Text detection failed, falling back to VLM")
            return await detect_toc_pages_visual(file_path, model)
