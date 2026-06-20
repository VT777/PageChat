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

MAX_TOKENS_FRAMEWORK = 8000      # stage=framework 最大token数
MAX_TOKENS_EXPAND = 6000      # stage=expand 每章最大token数
CHAPTER_BATCH_SIZE = 3            # stage=expand 并发章节数
MIN_CHAPTER_PAGES = 2             # 章节最小页数



def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_EXPLICIT_NUMBERING_RE = re.compile(
    r"^\s*(?P<number>\d{1,3}(?:[.]\d{1,3})+)\b"
)


def _explicit_numbering_key(title: str) -> Optional[str]:
    """Return a stable key for explicit section numbers such as 1.4 or 2.3.1."""
    normalized = (title or "").replace(chr(0xFF0E), ".")
    match = _EXPLICIT_NUMBERING_RE.match(normalized)
    if not match:
        return None
    return match.group("number")

# ---------------------------------------------------------------------------
# stage=framework: 提取一级框架
# ---------------------------------------------------------------------------

_FRAMEWORK_PROMPT = """You are a document structure analyst. Analyze the document excerpts below and extract all top-level chapter titles.

Requirements:
1. Extract only top-level chapters, meaning the largest structural units such as "Chapter 1" or "1. Introduction".
2. For each chapter, return the title and the starting physical page number.
3. Page numbers are 1-based physical PDF pages.
4. Do not omit appendices, references, or other top-level back matter.
5. If the document has front-matter sections such as Contents, Figure List, or Table List, include them only when they are top-level visible document sections.

Return JSON only:
{{
  "chapters": [
    {{"title": "Chapter title", "start_page": 1}}
  ]
}}

Document excerpts, up to the first 300 characters per page:
{content}
"""


async def extract_framework(
    page_texts: List[str],
    model: Optional[str] = None,
) -> Optional[List[Dict]]:
    """Extract the top-level framework for the hierarchical provider.

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
    if tokens > MAX_TOKENS_FRAMEWORK:
        # 保留首尾，中间采样
        keep_pages = max(3, len(page_texts) // 10)
        head = summaries[:keep_pages]
        tail = summaries[-keep_pages:]
        # 中间每隔N页取一页
        step = max(1, (len(summaries) - 2 * keep_pages) // 20)
        middle = summaries[keep_pages:len(summaries)-keep_pages:step]
        content = '\n'.join(head + middle + tail)

    prompt = _FRAMEWORK_PROMPT.format(content=content)

    try:
        response = await llm_acompletion(model, prompt)
        if not response:
            return None

        # 解析JSON - 使用更健壮的extract_json
        from pageindex.utils import extract_json
        data = extract_json(response)
        if not data:
            print(f"[TOC-CANDIDATE] provider=hierarchical Failed to parse JSON from response")
            return None
        
        chapters = data.get("chapters", [])

        # 验证
        valid_chapters = []
        for ch in chapters:
            title = _coerce_text(ch.get("title"))
            start_page = _coerce_int(ch.get("start_page"), 0)
            if title and start_page > 0:
                valid_chapters.append({
                    "title": title,
                    "start_page": start_page,
                })

        if len(valid_chapters) >= 2:
            print(f"[TOC-CANDIDATE] provider=hierarchical stage=framework status=ok chapters={len(valid_chapters)}")
            return valid_chapters

    except Exception as e:
        print(f"[TOC-CANDIDATE] provider=hierarchical stage=framework status=error error={e}")

    return None


# ---------------------------------------------------------------------------
# stage=expand status=ok chapter= 逐章展开子章节
# ---------------------------------------------------------------------------

_EXPAND_PROMPT = """You are a document structure analyst. Analyze the chapter excerpt below and extract all subsection titles inside that chapter.

Chapter metadata:
- Title: {chapter_title}
- Start page: {start_page}
- End page: {end_page}

Requirements:
1. Extract all second-level, third-level, and deeper section headings under this chapter.
2. For each subsection, return title, hierarchy level (2, 3, 4, ...), and 1-based physical PDF page number.
3. Keep original numbering when present, such as "1.1" or "(a)".
4. Titles must be concise headings, not paragraphs, table cells, or body text.
5. If unsure, return fewer items instead of guessing.
6. Ignore headers, footers, page numbers, table cells, and decorative text.

Return JSON only:
{{
  "sub_chapters": [
    {{"title": "Subsection title", "level": 2, "page": 5}}
  ]
}}

Chapter excerpt:
{content}
"""


async def expand_chapter(
    chapter_title: str,
    start_page: int,
    end_page: int,
    page_texts: List[str],
    model: Optional[str] = None,
) -> List[Dict]:
    """stage=expand status=ok chapter= 展开单个章节的子章节。

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
    if tokens > MAX_TOKENS_EXPAND:
        # 保留每页前300字
        content = '\n'.join(f"[Page {i+start_page}] {t[:300]}" 
                            for i, t in enumerate(chapter_texts))
        tokens = count_tokens(content)
        if tokens > MAX_TOKENS_EXPAND:
            # 进一步采样：只取奇数页
            content = '\n'.join(f"[Page {i+start_page}] {t[:300]}" 
                                for i, t in enumerate(chapter_texts) if i % 2 == 0)

    prompt = _EXPAND_PROMPT.format(
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
            print(f"[TOC-CANDIDATE] provider=hierarchical Failed to parse JSON for '{chapter_title}'")
            return []
        
        sub_chapters = data.get("sub_chapters", [])

        # 验证和清理
        valid = []
        for sub in sub_chapters:
            title = _coerce_text(sub.get("title"))
            level = max(2, _coerce_int(sub.get("level"), 2))
            page = _coerce_int(sub.get("page"), 0)

            if title and page >= start_page and page <= end_page:
                valid.append({
                    "title": title,
                    "level": level,
                    "page": page,
                })

        print(f"[TOC-CANDIDATE] provider=hierarchical stage=expand status=ok chapter='{chapter_title}' sub_chapters={len(valid)}")
        return valid

    except Exception as e:
        print(f"[TOC-CANDIDATE] provider=hierarchical stage=expand status=error chapter='{chapter_title}' error={e}")

    return []


async def expand_all_chapters(
    chapters: List[Dict],
    page_texts: List[str],
    model: Optional[str] = None,
) -> Dict[int, List[Dict]]:
    """stage=expand status=ok chapter= 并发展开所有章节的子章节。

    Args:
        chapters: chapters extracted by the framework stage
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
            task = expand_chapter(
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
# stage=merge: 合并结果
# ---------------------------------------------------------------------------

def merge_results(
    chapters: List[Dict],
    sub_chapters_map: Dict[int, List[Dict]],
) -> List[Dict]:
    """Merge top-level chapters and expanded children into a TOC tree.

    Args:
        chapters: chapters extracted by the framework stage
        sub_chapters_map: child chapters from the expand stage

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
            sub_tree = _build_sub_tree(subs, str(i + 1))
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
    sub_chapters = sorted(sub_chapters, key=lambda x: _coerce_int(x.get("page"), 0))

    parent_prefix = _coerce_text(parent_structure)
    result = []
    stack = []  # (level, node)

    # 子章节计数器
    level_counters: Dict[int, int] = {}
    seen_numbered_nodes: Dict[Tuple[int, str], Dict[str, Any]] = {}

    for sub in sub_chapters:
        level = max(2, _coerce_int(sub.get("level"), 2))
        title = _coerce_text(sub.get("title"))
        page = _coerce_int(sub.get("page"), 0)

        if not title or page <= 0:
            continue

        numbering_key = _explicit_numbering_key(title)
        if numbering_key:
            duplicate_node = seen_numbered_nodes.get((level, numbering_key))
            if duplicate_node is not None:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, duplicate_node))
                continue

        # 生成structure
        level_counters[level] = level_counters.get(level, 0) + 1
        # 重置更深级别的计数器
        for l in list(level_counters.keys()):
            if l > level:
                del level_counters[l]

        # 构建structure路径
        parts = [parent_prefix] if parent_prefix else []
        for l in sorted(level_counters.keys()):
            if l >= 2:
                parts.append(str(level_counters[l]))
        structure = '.'.join(str(part) for part in parts if str(part))

        node = {
            "title": title,
            "structure": structure,
            "physical_index": page,
            "nodes": [],
        }
        if numbering_key:
            seen_numbered_nodes[(level, numbering_key)] = node

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

    Runs the hierarchical provider framework -> expand -> merge flow.

    Args:
        page_texts: 所有页面的文本列表
        model: LLM模型名称

    Returns:
        {
            "items": List[Dict],      # 完整目录树
            "structure": "hierarchical",
            "source": "hierarchical",
            "confidence": float,
            "stages": {
                "framework_chapters": int,
                "expanded_chapters": int,
                "total_sub_chapters": int,
            }
        }
    """
    print("[TOC-CANDIDATE] provider=hierarchical stage=framework status=started")

    # stage=framework
    chapters = await extract_framework(page_texts, model)
    if not chapters:
        print("[TOC-CANDIDATE] provider=hierarchical stage=framework status=error action=abort")
        return None

    print(f"[TOC-CANDIDATE] provider=hierarchical stage=framework status=done chapters={len(chapters)}")

    # stage=expand
    print("[TOC-CANDIDATE] provider=hierarchical stage=expand status=started")
    sub_chapters_map = await expand_all_chapters(chapters, page_texts, model)

    total_subs = sum(len(subs) for subs in sub_chapters_map.values())
    expanded_count = sum(1 for subs in sub_chapters_map.values() if subs)
    print(f"[TOC-CANDIDATE] provider=hierarchical stage=expand status=done expanded={expanded_count}/{len(chapters)} sub_chapters={total_subs}")

    # stage=merge
    print("[TOC-CANDIDATE] provider=hierarchical stage=merge status=started")
    tree = merge_results(chapters, sub_chapters_map)

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
        "stages": {
            "framework_chapters": len(chapters),
            "expanded_chapters": expanded_count,
            "total_sub_chapters": total_subs,
        },
    }
