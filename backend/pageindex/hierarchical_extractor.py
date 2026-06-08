"""分层提取路径 — 先提取一级框架，再逐章展开子章节。

适用场景: 长文档(>50页)，结构复杂，有明确章节层次
优势: 子章节完整，页码边界准确，支持多级嵌套
成本: ~5-10次LLM调用（1次框架+每章1次展开）
"""

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

from pageindex.utils import llm_completion, llm_acompletion, count_tokens
from pageindex.fast_toc import verify_content_match, apply_offset


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

MAX_TOKENS_PER_PHASE1 = 8000      # Phase 1 最大token数
MAX_TOKENS_PER_PHASE2 = 6000      # Phase 2 每章最大token数
CHAPTER_BATCH_SIZE = 3            # Phase 2 并发章节数
MIN_CHAPTER_PAGES = 2             # 章节最小页数


# ---------------------------------------------------------------------------
# Phase 1: 提取一级框架
# ---------------------------------------------------------------------------

_PHASE1_PROMPT = """你是文档结构分析专家。请分析以下文档的内容，提取所有一级章节标题。

要求：
1. 只提取一级章节（最大的结构单元，如"第一章"、"1. 引言"等）
2. 每个章节包含：标题、起始页码
3. 页码从1开始计数
4. 不要遗漏任何章节，包括附录、参考文献等
5. 如果文档有"目录"、"图目录"、"表目录"等前置部分，也请列出

输出JSON格式：
{
  "chapters": [
    {"title": "章节标题", "start_page": 1},
    ...
  ]
}

文档内容（每页前300字）：
{content}
"""


async def phase1_extract_framework(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[List[Dict]]:
    """Phase 1: 提取一级章节框架。

    Args:
        page_texts: 所有页面的文本列表（0-indexed）
        model: LLM模型名称

    Returns:
        章节列表，每项包含 title 和 start_page
        失败返回 None
    """
    if not page_texts:
        return None

    # 构建摘要：每页取前300字符
    summaries = []
    for i, text in enumerate(page_texts):
        summary = text[:300].replace('\n', ' ').strip()
        if summary:
            summaries.append(f"[Page {i+1}] {summary}")

    content = '\n'.join(summaries)

    # 如果内容太长，截断
    tokens = count_tokens(content)
    if tokens > MAX_TOKENS_PER_PHASE1:
        # 保留首尾，中间采样
        keep_pages = max(3, len(page_texts) // 10)
        head = summaries[:keep_pages]
        tail = summaries[-keep_pages:]
        # 中间每隔N页取一页
        step = max(1, (len(summaries) - 2 * keep_pages) // 20)
        middle = summaries[keep_pages:len(summaries)-keep_pages:step]
        content = '\n'.join(head + middle + tail)

    prompt = _PHASE1_PROMPT.format(content=content)

    try:
        response = await llm_acompletion(model, prompt)
        if not response:
            return None

        # 解析JSON - 使用更健壮的extract_json
        from pageindex.utils import extract_json
        data = extract_json(response)
        if not data:
            print(f"[HIERARCHICAL] Failed to parse JSON from response")
            return None
        
        chapters = data.get("chapters", [])

        # 验证
        valid_chapters = []
        for ch in chapters:
            title = ch.get("title", "").strip()
            start_page = ch.get("start_page", 0)
            if title and start_page > 0:
                valid_chapters.append({
                    "title": title,
                    "start_page": start_page,
                })

        if len(valid_chapters) >= 2:
            print(f"[HIERARCHICAL] Phase 1: Extracted {len(valid_chapters)} chapters")
            return valid_chapters

    except Exception as e:
        print(f"[HIERARCHICAL] Phase 1 failed: {e}")

    return None


# ---------------------------------------------------------------------------
# Phase 2: 逐章展开子章节
# ---------------------------------------------------------------------------

_PHASE2_PROMPT = """你是文档结构分析专家。请分析以下章节的内容，提取该章节的所有子章节标题。

章节信息：
- 标题: {chapter_title}
- 起始页: {start_page}
- 结束页: {end_page}

要求：
1. 提取该章节下的所有子章节（二级、三级等）
2. 每个子章节包含：标题、级别（2,3,4...）、页码
3. 页码是文档的绝对页码（从1开始）
4. 保持原始编号（如"1.1"、"（一）"等）
5. 不要编造不存在的子章节

输出JSON格式：
{
  "sub_chapters": [
    {"title": "子章节标题", "level": 2, "page": 5},
    {"title": "子子章节", "level": 3, "page": 7},
    ...
  ]
}

章节内容：
{content}
"""


async def phase2_expand_chapter(
    chapter_title: str,
    start_page: int,
    end_page: int,
    page_texts: List[str],
    model: Optional[str] = None,
) -> List[Dict]:
    """Phase 2: 展开单个章节的子章节。

    Args:
        chapter_title: 章节标题
        start_page: 起始页码（1-indexed）
        end_page: 结束页码（1-indexed）
        page_texts: 所有页面文本
        model: LLM模型

    Returns:
        子章节列表
    """
    if start_page < 1 or start_page > len(page_texts):
        return []

    end_page = min(end_page, len(page_texts))

    # 提取章节文本
    chapter_texts = page_texts[start_page-1:end_page]
    content = '\n'.join(f"[Page {i+start_page}] {t[:500]}" 
                        for i, t in enumerate(chapter_texts))

    # 截断过长内容
    tokens = count_tokens(content)
    if tokens > MAX_TOKENS_PER_PHASE2:
        # 保留每页前300字
        content = '\n'.join(f"[Page {i+start_page}] {t[:300]}" 
                            for i, t in enumerate(chapter_texts))
        tokens = count_tokens(content)
        if tokens > MAX_TOKENS_PER_PHASE2:
            # 进一步采样：只取奇数页
            content = '\n'.join(f"[Page {i+start_page}] {t[:300]}" 
                                for i, t in enumerate(chapter_texts) if i % 2 == 0)

    prompt = _PHASE2_PROMPT.format(
        chapter_title=chapter_title,
        start_page=start_page,
        end_page=end_page,
        content=content,
    )

    try:
        response = await llm_acompletion(model, prompt)
        if not response:
            return []

        # 使用更健壮的extract_json
        from pageindex.utils import extract_json
        data = extract_json(response)
        if not data:
            print(f"[HIERARCHICAL] Failed to parse JSON for '{chapter_title}'")
            return []
        
        sub_chapters = data.get("sub_chapters", [])

        # 验证和清理
        valid = []
        for sub in sub_chapters:
            title = sub.get("title", "").strip()
            level = sub.get("level", 2)
            page = sub.get("page", 0)

            if title and page >= start_page and page <= end_page:
                valid.append({
                    "title": title,
                    "level": level,
                    "page": page,
                })

        print(f"[HIERARCHICAL] Phase 2: '{chapter_title}' -> {len(valid)} sub-chapters")
        return valid

    except Exception as e:
        print(f"[HIERARCHICAL] Phase 2 failed for '{chapter_title}': {e}")

    return []


async def phase2_expand_all_chapters(
    chapters: List[Dict],
    page_texts: List[str],
    model: Optional[str] = None,
) -> Dict[int, List[Dict]]:
    """Phase 2: 并发展开所有章节的子章节。

    Args:
        chapters: Phase 1 提取的章节列表
        page_texts: 所有页面文本
        model: LLM模型

    Returns:
        {章节索引: 子章节列表}
    """
    if not chapters:
        return {}

    # 计算每个章节的结束页
    results = {}
    for i, ch in enumerate(chapters):
        start_page = ch["start_page"]
        if i + 1 < len(chapters):
            end_page = chapters[i + 1]["start_page"] - 1
        else:
            end_page = len(page_texts)

        # 确保最小页数
        if end_page - start_page + 1 < MIN_CHAPTER_PAGES:
            end_page = min(start_page + MIN_CHAPTER_PAGES - 1, len(page_texts))

        results[i] = {
            "title": ch["title"],
            "start_page": start_page,
            "end_page": end_page,
            "sub_chapters": [],
        }

    # 分批并发处理
    async def process_batch(batch_indices: List[int]) -> None:
        tasks = []
        for idx in batch_indices:
            info = results[idx]
            task = phase2_expand_chapter(
                info["title"],
                info["start_page"],
                info["end_page"],
                page_texts,
                model,
            )
            tasks.append((idx, task))

        # 并发执行
        coros = [t[1] for t in tasks]
        sub_results = await asyncio.gather(*coros, return_exceptions=True)

        for (idx, _), sub_chapters in zip(tasks, sub_results):
            if isinstance(sub_chapters, list):
                results[idx]["sub_chapters"] = sub_chapters

    # 按批次处理
    indices = list(results.keys())
    for i in range(0, len(indices), CHAPTER_BATCH_SIZE):
        batch = indices[i:i + CHAPTER_BATCH_SIZE]
        await process_batch(batch)

    # 转换为返回格式
    return {idx: results[idx]["sub_chapters"] for idx in results}


# ---------------------------------------------------------------------------
# Phase 3: 合并结果
# ---------------------------------------------------------------------------

def phase3_merge_results(
    chapters: List[Dict],
    sub_chapters_map: Dict[int, List[Dict]],
) -> List[Dict]:
    """Phase 3: 将一级章节和子章节合并为完整目录树。

    Args:
        chapters: Phase 1 的一级章节
        sub_chapters_map: Phase 2 的子章节 {章节索引: 子章节列表}

    Returns:
        完整的目录树结构
    """
    if not chapters:
        return []

    result = []

    for i, ch in enumerate(chapters):
        # 一级章节节点
        chapter_node = {
            "title": ch["title"],
            "structure": str(i + 1),
            "physical_index": ch["start_page"],
            "nodes": [],
        }

        # 添加子章节
        subs = sub_chapters_map.get(i, [])
        if subs:
            # 构建子章节树
            sub_tree = _build_sub_tree(subs, i + 1)
            chapter_node["nodes"] = sub_tree

        result.append(chapter_node)

    return result


def _build_sub_tree(sub_chapters: List[Dict], parent_structure: str) -> List[Dict]:
    """根据子章节的 level 构建树形结构。

    Args:
        sub_chapters: 子章节列表，每项包含 title, level, page
        parent_structure: 父章节的structure编号（如 "1"）

    Returns:
        子章节树
    """
    if not sub_chapters:
        return []

    # 按页码排序
    sub_chapters = sorted(sub_chapters, key=lambda x: x.get("page", 0))

    result = []
    stack = []  # (level, node)

    # 子章节计数器
    level_counters: Dict[int, int] = {}

    for sub in sub_chapters:
        level = sub.get("level", 2)
        title = sub.get("title", "")
        page = sub.get("page", 0)

        if not title or page <= 0:
            continue

        # 生成structure
        level_counters[level] = level_counters.get(level, 0) + 1
        # 重置更深级别的计数器
        for l in list(level_counters.keys()):
            if l > level:
                del level_counters[l]

        # 构建structure路径
        parts = [parent_structure]
        for l in sorted(level_counters.keys()):
            if l >= 2:
                parts.append(str(level_counters[l]))
        structure = '.'.join(parts)

        node = {
            "title": title,
            "structure": structure,
            "physical_index": page,
            "nodes": [],
        }

        # 找到父节点
        if level <= 2:
            # 二级章节，直接挂到一级下
            result.append(node)
            stack = [(level, node)]
        else:
            # 找合适的父节点
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


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def extract_hierarchical_toc(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """分层提取主入口。

    执行完整的 Phase 1 → Phase 2 → Phase 3 流程。

    Args:
        page_texts: 所有页面的文本列表
        model: LLM模型名称

    Returns:
        {
            "items": List[Dict],      # 完整目录树
            "structure": "hierarchical",
            "source": "hierarchical",
            "confidence": float,
            "phases": {
                "phase1_chapters": int,
                "phase2_expanded": int,
                "total_sub_chapters": int,
            }
        }
    """
    print("[HIERARCHICAL] Starting Phase 1: Framework extraction...")

    # Phase 1
    chapters = await phase1_extract_framework(page_texts, model)
    if not chapters:
        print("[HIERARCHICAL] Phase 1 failed, aborting")
        return None

    print(f"[HIERARCHICAL] Phase 1 complete: {len(chapters)} chapters")

    # Phase 2
    print("[HIERARCHICAL] Starting Phase 2: Chapter expansion...")
    sub_chapters_map = await phase2_expand_all_chapters(chapters, page_texts, model)

    total_subs = sum(len(subs) for subs in sub_chapters_map.values())
    expanded_count = sum(1 for subs in sub_chapters_map.values() if subs)
    print(f"[HIERARCHICAL] Phase 2 complete: {expanded_count}/{len(chapters)} chapters expanded, {total_subs} sub-chapters")

    # Phase 3
    print("[HIERARCHICAL] Starting Phase 3: Merge results...")
    tree = phase3_merge_results(chapters, sub_chapters_map)

    # 计算置信度
    confidence = 0.5
    if len(chapters) >= 3:
        confidence += 0.2
    if expanded_count >= len(chapters) * 0.5:
        confidence += 0.2
    if total_subs >= len(chapters):
        confidence += 0.1

    return {
        "items": tree,
        "structure": "hierarchical",
        "source": "hierarchical",
        "confidence": min(confidence, 1.0),
        "phases": {
            "phase1_chapters": len(chapters),
            "phase2_expanded": expanded_count,
            "total_sub_chapters": total_subs,
        },
    }
