"""快速文本提取路径 — 短文档单次LLM提取。

适用场景: ≤20页的短文档，文本质量高
优势: 最快，仅1次LLM调用
成本: 最低
"""

import re
from typing import Any, Dict, List, Optional

from pageindex.utils import llm_completion, count_tokens


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

MAX_TOKENS = 12000        # 最大输入token
MAX_PAGES = 20            # 最大页数


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_FAST_PROMPT = """你是文档结构分析专家。请分析以下文档的完整内容，提取完整的目录结构。

要求：
1. 提取所有级别的章节标题
2. 每个标题包含：标题文本、级别（1=一级，2=二级...）、页码
3. 页码从1开始
4. 保持原始编号
5. 不要遗漏任何章节

输出JSON格式：
{{
  "chapters": [
    {{"title": "一级标题", "level": 1, "page": 1, "nodes": [
      {{"title": "二级标题", "level": 2, "page": 3}}
    ]}},
    ...
  ]
}}

文档内容：
{content}
"""


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def extract_fast_text_toc(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """快速文本提取主入口。

    Args:
        page_texts: 所有页面文本
        model: LLM模型

    Returns:
        {
            "items": List[Dict],
            "structure": "hierarchical",
            "source": "fast_text",
            "confidence": float,
        }
    """
    if not page_texts or len(page_texts) > MAX_PAGES:
        return None

    print(f"[FAST-TEXT] Starting fast extraction: {len(page_texts)} pages")

    # 构建内容
    content_lines = []
    for i, text in enumerate(page_texts):
        summary = text[:600].replace('\n', ' ').strip()
        content_lines.append(f"[Page {i+1}] {summary}")

    content = '\n'.join(content_lines)

    # 截断
    tokens = count_tokens(content)
    if tokens > MAX_TOKENS:
        # 保留每页前400字
        content_lines = []
        for i, text in enumerate(page_texts):
            summary = text[:400].replace('\n', ' ').strip()
            content_lines.append(f"[Page {i+1}] {summary}")
        content = '\n'.join(content_lines)

    prompt = _FAST_PROMPT.format(content=content)

    try:
        response = llm_completion(model, prompt)
        if not response:
            return None

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            import json
            data = json.loads(json_match.group())
            chapters = data.get("chapters", [])

            if len(chapters) >= 2:
                tree = _normalize_tree(chapters)
                confidence = 0.7
                if len(chapters) >= 3:
                    confidence += 0.1
                if len(page_texts) <= 10:
                    confidence += 0.1

                print(f"[FAST-TEXT] Extracted {len(chapters)} chapters")
                return {
                    "items": tree,
                    "structure": "hierarchical",
                    "source": "fast_text",
                    "confidence": min(confidence, 1.0),
                }

    except Exception as e:
        print(f"[FAST-TEXT] Extraction failed: {e}")

    return None


def _normalize_tree(nodes: List[Dict], parent_structure: str = "") -> List[Dict]:
    """规范化树结构，确保每个节点有 structure 和 nodes。"""
    result = []

    for i, node in enumerate(nodes):
        title = node.get("title", "").strip()
        level = node.get("level", 1)
        page = node.get("page", 0)

        if not title or page <= 0:
            continue

        # 构建structure
        if parent_structure:
            structure = f"{parent_structure}.{i+1}"
        else:
            structure = str(i + 1)

        normalized = {
            "title": title,
            "structure": structure,
            "physical_index": page,
            "nodes": [],
        }

        # 递归处理子节点
        children = node.get("nodes", [])
        if children:
            normalized["nodes"] = _normalize_tree(children, structure)

        result.append(normalized)

    return result
