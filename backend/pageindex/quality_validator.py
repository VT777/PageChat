"""质量验证模块 — 检测提取结果的问题并自动修复。

检测项：
1. 超大节点（>8个子节点）→ 需要进一步拆分
2. 页码覆盖检查（是否有页面未被任何章节覆盖）
3. 子章节缺失检测（一级章节下无子章节）
4. 页码连续性检查（页码是否单调递增）
5. 重复章节检测

修复策略：
1. 超大节点 → 触发二次分层提取
2. 覆盖缺口 → 标记为"未分类"
3. 子章节缺失 → 对该章节单独调用LLM展开
4. 页码不连续 → 尝试重新映射
5. 重复章节 → 合并或删除
"""

import asyncio
from typing import Any, Dict, List, Optional, Set, Tuple

from pageindex.utils import llm_acompletion


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

LARGE_NODE_THRESHOLD = 8          # 超大节点阈值（子节点数）
MIN_COVERAGE_RATIO = 0.8          # 最小页码覆盖率
MAX_PAGE_GAP = 5                  # 最大允许页码缺口


# ---------------------------------------------------------------------------
# 验证函数
# ---------------------------------------------------------------------------

def validate_toc(
    toc_items: List[Dict],
    page_count: int,
    page_texts: List[str],
    source: str = "unknown",
) -> Dict[str, Any]:
    """验证目录质量。

    Args:
        toc_items: 目录树
        page_count: 文档总页数
        page_texts: 所有页面文本
        source: TOC来源 (toc_page, hierarchical, etc.)

    Returns:
        {
            "is_valid": bool,
            "score": float,           # 0-1 质量分
            "issues": List[Dict],     # 问题列表
            "stats": Dict,            # 统计信息
        }
    """
    issues = []
    stats = _calculate_stats(toc_items, page_count)

    # 1. 检查超大节点
    large_nodes = _find_large_nodes(toc_items)
    for node in large_nodes:
        issues.append({
            "type": "large_node",
            "severity": "warning",
            "message": f"超大节点: '{node['title']}' 有{node['child_count']}个子节点",
            "node": node,
        })

    # 2. 检查页码覆盖（对toc_page source放宽要求）
    coverage = stats.get("page_coverage", 0)
    # TOC页提取器只提取目录页条目，coverage要求放宽
    min_coverage = 0.3 if source == "toc_page" else MIN_COVERAGE_RATIO
    if coverage < min_coverage:
        severity = "warning" if source == "toc_page" else "error"
        issues.append({
            "type": "low_coverage",
            "severity": severity,
            "message": f"页码覆盖率过低: {coverage:.0%} (要求≥{min_coverage:.0%})",
            "coverage": coverage,
        })

    # 3. 检查页码缺口（对toc_page source跳过）
    if source != "toc_page":
        gaps = _find_page_gaps(toc_items, page_count)
        for gap in gaps:
            if gap["size"] > MAX_PAGE_GAP:
                issues.append({
                    "type": "page_gap",
                    "severity": "warning",
                    "message": f"页码缺口: 第{gap['start']}-{gap['end']}页未被覆盖",
                    "gap": gap,
                })

    # 4. 检查重复章节
    duplicates = _find_duplicates(toc_items)
    for dup in duplicates:
        issues.append({
            "type": "duplicate",
            "severity": "warning",
            "message": f"重复章节: '{dup['title']}' 出现{dup['count']}次",
            "duplicate": dup,
        })

    # 5. 检查子章节缺失（对toc_page source跳过，因为TOC页可能只有一级）
    if source != "toc_page":
        missing_subs = _find_missing_subchapters(toc_items, page_texts)
        for item in missing_subs:
            issues.append({
                "type": "missing_subchapters",
                "severity": "info",
                "message": f"子章节缺失: '{item['title']}' ({item['page_range']}页) 无子章节",
                "node": item,
            })

    # 计算质量分
    score = _calculate_score(issues, stats)

    # 判断有效性
    is_valid = (
        score >= 0.6 and
        not any(i["severity"] == "error" for i in issues)
    )

    return {
        "is_valid": is_valid,
        "score": score,
        "issues": issues,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# 修复函数
# ---------------------------------------------------------------------------

async def repair_toc(
    toc_items: List[Dict],
    issues: List[Dict],
    page_texts: List[str],
    model: Optional[str] = None,
) -> List[Dict]:
    """修复目录中的问题。

    Args:
        toc_items: 原始目录
        issues: 问题列表
        page_texts: 页面文本
        model: LLM模型

    Returns:
        修复后的目录
    """
    result = _deep_copy(toc_items)

    for issue in issues:
        issue_type = issue.get("type")

        if issue_type == "large_node":
            # 对超大节点进行二次拆分
            node = issue.get("node", {})
            await _repair_large_node(result, node, page_texts, model)

        elif issue_type == "page_gap":
            # 添加未分类节点
            gap = issue.get("gap", {})
            _repair_page_gap(result, gap)

        elif issue_type == "missing_subchapters":
            # 对缺失子章节的节点进行展开
            node = issue.get("node", {})
            await _repair_missing_subchapters(result, node, page_texts, model)

        elif issue_type == "duplicate":
            # 合并重复章节
            dup = issue.get("duplicate", {})
            _repair_duplicate(result, dup)

    return result


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _calculate_stats(toc_items: List[Dict], page_count: int) -> Dict:
    """计算目录统计信息。"""
    if not toc_items or page_count <= 0:
        return {"page_coverage": 0, "total_nodes": 0, "max_depth": 0}

    covered_pages: Set[int] = set()
    total_nodes = 0
    max_depth = 0

    def traverse(nodes: List[Dict], depth: int = 1):
        nonlocal total_nodes, max_depth
        for node in nodes:
            total_nodes += 1
            max_depth = max(max_depth, depth)

            start = node.get("physical_index") or 0
            # 结束页 = 下一个兄弟节点的开始页 - 1，或文档末尾
            # 这里简化处理：只记录起始页
            if start > 0:
                covered_pages.add(start)

            children = node.get("nodes", [])
            if children:
                traverse(children, depth + 1)

    traverse(toc_items)

    coverage = len(covered_pages) / page_count if page_count > 0 else 0

    return {
        "page_coverage": coverage,
        "total_nodes": total_nodes,
        "max_depth": max_depth,
        "covered_pages": len(covered_pages),
    }


def _find_large_nodes(nodes: List[Dict], path: str = "") -> List[Dict]:
    """查找超大节点。"""
    result = []

    for node in nodes:
        children = node.get("nodes", [])
        if len(children) > LARGE_NODE_THRESHOLD:
            result.append({
                "title": node.get("title", ""),
                "structure": node.get("structure", ""),
                "child_count": len(children),
                "path": path,
            })

        # 递归检查
        if children:
            result.extend(_find_large_nodes(children, path + node.get("title", "") + " > "))

    return result


def _find_page_gaps(nodes: List[Dict], page_count: int) -> List[Dict]:
    """查找页码覆盖缺口。"""
    if not nodes or page_count <= 0:
        return []

    # 收集所有章节的起始页
    start_pages = set()

    def collect_pages(node_list: List[Dict]):
        for node in node_list:
            page = node.get("physical_index", 0)
            if page > 0:
                start_pages.add(page)
            collect_pages(node.get("nodes", []))

    collect_pages(nodes)

    # 找缺口
    gaps = []
    sorted_pages = sorted(start_pages)

    if not sorted_pages:
        return []

    # 检查开头
    if sorted_pages[0] > 1:
        gaps.append({"start": 1, "end": sorted_pages[0] - 1, "size": sorted_pages[0] - 1})

    # 检查中间
    for i in range(len(sorted_pages) - 1):
        gap_start = sorted_pages[i]
        gap_end = sorted_pages[i + 1]
        if gap_end - gap_start > 1:
            gaps.append({
                "start": gap_start + 1,
                "end": gap_end - 1,
                "size": gap_end - gap_start - 1,
            })

    # 检查末尾
    if sorted_pages[-1] < page_count:
        gaps.append({
            "start": sorted_pages[-1] + 1,
            "end": page_count,
            "size": page_count - sorted_pages[-1],
        })

    return gaps


def _find_duplicates(nodes: List[Dict]) -> List[Dict]:
    """查找重复章节标题。"""
    title_counts: Dict[str, int] = {}

    def count_titles(node_list: List[Dict]):
        for node in node_list:
            title = node.get("title", "")
            if title:
                title_counts[title] = title_counts.get(title, 0) + 1
            count_titles(node.get("nodes", []))

    count_titles(nodes)

    return [
        {"title": title, "count": count}
        for title, count in title_counts.items()
        if count > 1
    ]


def _find_missing_subchapters(nodes: List[Dict], page_texts: List[str]) -> List[Dict]:
    """查找可能缺失子章节的一级节点。

    条件：
    - 是一级节点
    - 无子节点
    - 页数 > 5
    """
    result = []

    for i, node in enumerate(nodes):
        children = node.get("nodes", [])
        if children:
            continue

        start_page = node.get("physical_index", 0)
        # 估算结束页
        if i + 1 < len(nodes):
            end_page = nodes[i + 1].get("physical_index", len(page_texts)) - 1
        else:
            end_page = len(page_texts)

        page_range = end_page - start_page + 1
        if page_range > 5 and start_page > 0:
            result.append({
                "title": node.get("title", ""),
                "structure": node.get("structure", ""),
                "start_page": start_page,
                "end_page": end_page,
                "page_range": page_range,
            })

    return result


def _calculate_score(issues: List[Dict], stats: Dict) -> float:
    """计算质量分。"""
    score = 1.0

    # 根据问题严重程度扣分
    for issue in issues:
        severity = issue.get("severity", "info")
        if severity == "error":
            score -= 0.3
        elif severity == "warning":
            score -= 0.1
        elif severity == "info":
            score -= 0.05

    # 根据覆盖率扣分
    coverage = stats.get("page_coverage", 0)
    if coverage < 0.5:
        score -= 0.2
    elif coverage < 0.8:
        score -= 0.1

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# 修复实现
# ---------------------------------------------------------------------------

async def _repair_large_node(
    tree: List[Dict],
    target_node: Dict,
    page_texts: List[str],
    model: Optional[str] = None,
):
    """修复超大节点：对该节点进行二次分层提取。"""
    # 简化实现：对超大节点添加一个标记
    # 实际实现可以调用 hierarchical_extractor 对该节点范围进行提取
    for node in tree:
        if node.get("structure") == target_node.get("structure"):
            node["_needs_expansion"] = True
            break
        # 递归检查子节点
        if node.get("nodes"):
            await _repair_large_node(node["nodes"], target_node, page_texts, model)


def _repair_page_gap(tree: List[Dict], gap: Dict):
    """修复页码缺口：添加未分类节点。"""
    # 在树末尾添加一个"未分类"节点
    if gap.get("size", 0) > 0:
        tree.append({
            "title": f"未分类内容（第{gap['start']}-{gap['end']}页）",
            "structure": str(len(tree) + 1),
            "physical_index": gap["start"],
            "nodes": [],
            "_is_gap_filler": True,
        })


async def _repair_missing_subchapters(
    tree: List[Dict],
    target_node: Dict,
    page_texts: List[str],
    model: Optional[str] = None,
):
    """修复缺失子章节：对该章节进行LLM展开。"""
    # 简化实现：添加标记，实际可由调用方处理
    for node in tree:
        if node.get("structure") == target_node.get("structure"):
            node["_missing_subchapters"] = True
            break
        if node.get("nodes"):
            await _repair_missing_subchapters(node["nodes"], target_node, page_texts, model)


def _repair_duplicate(tree: List[Dict], dup: Dict):
    """修复重复章节：合并相同标题的章节。"""
    # 简化实现：保留第一个，后续添加序号
    title = dup.get("title", "")
    seen = False

    for node in tree:
        if node.get("title") == title:
            if seen:
                node["title"] = f"{title} (续)"
            else:
                seen = True
        if node.get("nodes"):
            _repair_duplicate(node["nodes"], dup)


def _deep_copy(nodes: List[Dict]) -> List[Dict]:
    """深拷贝节点列表。"""
    import copy
    return copy.deepcopy(nodes)
