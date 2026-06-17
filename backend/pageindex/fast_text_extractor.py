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

_FAST_PROMPT = """You are a document structure analyst. Analyze the full document excerpts below and extract a complete table-of-contents tree.

Requirements:
1. Extract headings at all hierarchy levels.
2. For each heading, return title text, level (1 for top-level, 2 for child, etc.), and 1-based physical PDF page number.
3. Page numbers start at 1.
4. Keep original numbering when present.
5. Do not omit visible sections, appendices, references, or other structural headings.
6. Ignore headers, footers, page numbers, table cells, and decorative text.

Return JSON only:
{{
  "chapters": [
    {{"title": "Top-level heading", "level": 1, "page": 1, "nodes": [
      {{"title": "Child heading", "level": 2, "page": 3}}
    ]}}
  ]
}}

Document excerpts:
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

    print(f"[TOC-CANDIDATE] provider=fast_text action=extract status=started pages={len(page_texts)}")

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

                print(f"[TOC-CANDIDATE] provider=fast_text action=extract status=ok chapters={len(chapters)}")
                return {
                    "items": tree,
                    "structure": "hierarchical",
                    "source": "fast_text",
                    "confidence": min(confidence, 1.0),
                }

    except Exception as e:
        print(f"[TOC-CANDIDATE] provider=fast_text action=extract status=error error={e}")

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
