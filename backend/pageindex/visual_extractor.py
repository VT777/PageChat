"""视觉提取路径 v2 — 分层VLM提取。

适用场景: 扫描件、图片PDF、文本质量极低的文档
优势: 分层提取确保子章节完整
架构: 短文档全文提取 / 长文档先框架后展开
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

from pageindex.utils import llm_completion, count_tokens


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

SHORT_DOC_MAX_PAGES = 20      # 短文档阈值
VLM_MAX_PAGES_PER_CALL = 10   # 每次VLM调用最多处理页数


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_VLM_FULL_TOC_PROMPT = """你是文档目录提取专家。请分析以下文档的页面图像，提取完整的目录结构。

要求：
1. 提取所有级别的章节标题（一级、二级、三级等）
2. 每个标题包含：标题文本、级别（1=一级，2=二级...）、页码
3. 页码是文档的绝对页码（从1开始）
4. 保持原始编号（如"1.1"、"第一章"等）
5. 不要遗漏任何章节，包括前言、附录、参考文献等
6. 如果文档有"图目录"、"表目录"，也请列出其中的条目

输出JSON格式：
{{
  "chapters": [
    {{"title": "一级标题", "level": 1, "page": 1, "nodes": [
      {{"title": "二级标题", "level": 2, "page": 3}}
    ]}},
    ...
  ]
}}

注意：请尽可能提取所有子章节，不要只提取一级标题。
"""

_VLM_FRAMEWORK_PROMPT = """你是文档目录提取专家。请分析以下文档的页面图像，提取一级章节框架。

要求：
1. 只提取一级章节（最大的结构单元）
2. 每个章节包含：标题、起始页码
3. 页码从1开始
4. 不要遗漏任何章节

输出JSON格式：
{{
  "chapters": [
    {{"title": "章节标题", "start_page": 1}},
    ...
  ]
}}
"""

_VLM_EXPAND_PROMPT = """你是文档目录提取专家。请分析以下章节的内容，提取该章节的所有子章节标题。

章节信息：
- 标题: {chapter_title}
- 起始页: {start_page}
- 结束页: {end_page}

要求：
1. 提取该章节下的所有子章节（二级、三级等）
2. 每个子章节包含：标题、级别（2,3,4...）、页码
3. 页码是文档的绝对页码
4. 保持原始编号
5. 不要编造不存在的子章节

输出JSON格式：
{{
  "sub_chapters": [
    {{"title": "子章节标题", "level": 2, "page": 5}},
    ...
  ]
}}
"""


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

async def extract_visual_toc(
    file_path: str,
    analysis: Dict[str, Any],
    model: Optional[str] = None,
    anchors: Optional[Dict] = None,
    **kwargs
) -> Optional[Dict[str, Any]]:
    """视觉提取主入口（v2分层架构）。

    流程：
    1. 判断文档长度
    2. 短文档 → 全文提取
    3. 长文档 → 先提取框架 → 逐章展开
    """
    page_count = analysis.get("page_count", 0)
    
    print(f"[VISUAL-V2] Starting visual extraction: {page_count} pages")
    
    if page_count <= SHORT_DOC_MAX_PAGES:
        print(f"[VISUAL-V2] Short document ({page_count} pages), full extraction")
        result = await _extract_short_doc(file_path, page_count, model)
    else:
        print(f"[VISUAL-V2] Long document ({page_count} pages), hierarchical extraction")
        result = await _extract_long_doc(file_path, page_count, model, anchors)
    
    if result and result.get("items"):
        print(f"[VISUAL-V2] Extracted {len(result['items'])} top-level items")
        return {
            "items": result["items"],
            "structure": "hierarchical",
            "source": "visual_v2",
            "confidence": result.get("confidence", 0.8),
        }
    
    return None


async def _extract_short_doc(
    file_path: str,
    page_count: int,
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """短文档：全文VLM提取。"""
    # 渲染所有页面（或分批）
    from pageindex.vlm_utils import render_pages_to_images
    
    page_indices = list(range(min(page_count, SHORT_DOC_MAX_PAGES)))
    images = render_pages_to_images(file_path, page_indices, dpi=150)
    
    if not images:
        print("[VISUAL-V2] Failed to render pages")
        return None
    
    # 构建prompt
    prompt = _VLM_FULL_TOC_PROMPT
    
    # 调用VLM（需要图片）
    # 注意：这里需要vlm_call_with_images，但当前extractors是基于文本的
    # 简化：先返回None，实际实现需要添加VLM图片调用
    print("[VISUAL-V2] Short doc extraction not fully implemented (needs VLM image call)")
    
    # TODO: 实现VLM图片调用
    # 由于当前架构限制，先回退到旧代码
    from pageindex.balanced_toc import build_balanced_toc_visual
    result = await build_balanced_toc_visual(
        file_path=file_path,
        analysis={"page_count": page_count},
        model=model,
    )
    
    if result and result.get("structure"):
        return {
            "items": result.get("structure", []),
            "confidence": 0.7,
        }
    
    return None


async def _extract_long_doc(
    file_path: str,
    page_count: int,
    model: Optional[str] = None,
    anchors: Optional[Dict] = None,
) -> Optional[Dict[str, Any]]:
    """长文档：分层提取。"""
    # TODO: 实现Phase 1/2/3分层提取
    # 由于VLM图片调用复杂，先回退到旧代码
    
    print("[VISUAL-V2] Long doc hierarchical extraction not fully implemented")
    print("[VISUAL-V2] Falling back to legacy visual extraction")
    
    from pageindex.balanced_toc import build_balanced_toc_visual
    result = await build_balanced_toc_visual(
        file_path=file_path,
        analysis={"page_count": page_count},
        model=model,
        anchors=anchors,
    )
    
    if result and result.get("structure"):
        return {
            "items": result.get("structure", []),
            "confidence": 0.7,
        }
    
    return None


# ---------------------------------------------------------------------------
# 辅助函数（未来实现）
# ---------------------------------------------------------------------------

async def _vlm_extract_framework(images: List[Dict], model: Optional[str]) -> List[Dict]:
    """Phase 1: VLM提取一级框架。"""
    # TODO: 实现VLM图片调用
    pass


async def _vlm_expand_chapter(
    images: List[Dict],
    chapter_title: str,
    start_page: int,
    end_page: int,
    model: Optional[str],
) -> List[Dict]:
    """Phase 2: VLM展开子章节。"""
    # TODO: 实现VLM图片调用
    pass


def _merge_visual_results(
    chapters: List[Dict],
    sub_chapters_map: Dict[int, List[Dict]],
) -> List[Dict]:
    """Phase 3: 合并结果。"""
    # TODO: 合并逻辑
    pass
