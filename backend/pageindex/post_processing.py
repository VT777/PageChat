"""后处理模块：将 TOC 扁平列表转换为完整的、页码正确的树结构。

确保：
1. TOC 完整（覆盖文档大部分页面）
2. 页码正确（start_index/end_index 在有效范围内）
3. 层级正确（structure 编号对应正确的父子关系）
4. 无遗漏（Preface 补充、大节点拆分）
"""

import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Step 1: 数据清洗
# ---------------------------------------------------------------------------


def clean_toc_items(toc_items: List[Dict]) -> List[Dict]:
    """清洗 TOC 条目：转 int、去重、排序、过滤无效。"""
    cleaned = []
    for item in toc_items:
        pi = item.get("physical_index")

        # 转 int
        if isinstance(pi, str):
            m = re.search(r"\d+", pi)
            pi = int(m.group()) if m else None
        elif isinstance(pi, float):
            pi = int(pi)

        if pi is None or pi < 1:
            continue

        cleaned_item = {
            "structure": str(item.get("structure", "")).strip(),
            "title": str(item.get("title", "")).strip(),
            "physical_index": pi,
        }
        # 保留 number 字段（用于图表分类）
        number = item.get("number")
        if number is not None:
            cleaned_item["number"] = str(number).strip()
        cleaned.append(cleaned_item)

    if not cleaned:
        return []

    # 按 physical_index 排序（稳定排序，保留原始顺序）
    cleaned.sort(key=lambda x: x["physical_index"])

    # 去重：相同标题 + 相近页码（±1）
    deduped = [cleaned[0]]
    for item in cleaned[1:]:
        last = deduped[-1]
        same_title = item["title"][:20] == last["title"][:20]
        close_page = abs(item["physical_index"] - last["physical_index"]) <= 1
        if same_title and close_page:
            continue
        deduped.append(item)

    # 检查单调递增，移除回退的条目
    result = [deduped[0]]
    for item in deduped[1:]:
        if item["physical_index"] >= result[-1]["physical_index"]:
            result.append(item)
        else:
            print(
                f"[POST] Removed non-monotonic item: {item['title'][:30]} p.{item['physical_index']}"
            )

    return result


# ---------------------------------------------------------------------------
# Step 2: 边界校验
# ---------------------------------------------------------------------------


def filter_figure_catalogs(toc_items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """过滤纯图录/表录目录节点，保留具体图表条目。
    
    检测规则：
    1. 标题匹配 "图目录" 或 "表目录" —— 这些是纯目录页，过滤掉
    2. 标题匹配 "图 N..." 或 "表 N..." —— 这些是具体图表条目，保留但标记
    """
    catalog_pattern = re.compile(r'^[图表]目录')
    
    normal = []
    figures = []
    
    for item in toc_items:
        title = item.get("title", "")
        if catalog_pattern.match(title):
            # 纯目录节点（如"图目录"）—— 过滤
            figures.append(item)
            print(f"[POST] Filtered figure/table catalog: {title[:50]}")
        else:
            normal.append(item)
    
    if figures:
        print(f"[POST] Filtered {len(figures)} figure/table catalog entries")
    
    return normal, figures


def validate_indices(toc_items: List[Dict], page_count: int) -> List[Dict]:
    """校验 physical_index 在 [1, page_count] 范围内。"""
    valid = []
    for item in toc_items:
        pi = item["physical_index"]
        if 1 <= pi <= page_count:
            valid.append(item)
        else:
            print(
                f"[POST] Out of range: {item['title'][:30]} p.{pi} (max={page_count})"
            )
    return valid


# ---------------------------------------------------------------------------
# Step 3: 补充 Preface
# ---------------------------------------------------------------------------


def add_preface(toc_items: List[Dict]) -> List[Dict]:
    """如果第一个条目不在第 1 页，插入 Preface 节点。"""
    if not toc_items:
        return toc_items

    if toc_items[0]["physical_index"] > 1:
        preface = {
            "structure": "0",
            "title": "Preface",
            "physical_index": 1,
        }
        toc_items = [preface] + toc_items

    return toc_items


# ---------------------------------------------------------------------------
# Step 4: 设置 start_index / end_index
# ---------------------------------------------------------------------------


def assign_page_ranges(toc_items: List[Dict], page_count: int) -> List[Dict]:
    """为每个条目设置 start_index 和 end_index。"""
    for i, item in enumerate(toc_items):
        item["start_index"] = item["physical_index"]

        if i < len(toc_items) - 1:
            next_start = toc_items[i + 1]["physical_index"]
            item["end_index"] = max(next_start - 1, item["start_index"])
        else:
            item["end_index"] = page_count

    return toc_items


# ---------------------------------------------------------------------------
# Step 5: 扁平列表 → 树结构
# ---------------------------------------------------------------------------


def build_tree(toc_items: List[Dict]) -> List[Dict]:
    """用 structure 字段构建层级树。"""
    if not toc_items:
        return []

    # 为每个节点初始化 nodes
    for item in toc_items:
        item["nodes"] = []

    # 用栈构建父子关系
    root_nodes = []
    stack: List[Dict] = []  # 当前路径上的父节点栈

    for item in toc_items:
        structure = item["structure"]

        # Preface (structure="0") 始终是独立的顶级节点，不做父节点
        if structure == "0":
            root_nodes.append(item)
            stack = []  # 清空栈，Preface 不是后续节点的父
            continue

        # P5-fix: 空 structure 的节点（如图表条目）作为独立根节点
        if not structure:
            root_nodes.append(item)
            stack = []  # 清空栈，空 structure 节点不做父节点
            continue

        depth = structure.count(".") + 1

        # 找到正确的父节点
        while len(stack) > 0 and _get_depth(stack[-1]["structure"]) >= depth:
            stack.pop()

        if stack:
            stack[-1]["nodes"].append(item)
        else:
            root_nodes.append(item)

        stack.append(item)

    return root_nodes


def _get_depth(structure: str) -> int:
    """获取 structure 的层级深度。

    P2-9: 支持多种编号格式：
    - 阿拉伯数字："1", "1.1", "1.2.3" → depth = count(".") + 1
    - 中文编号："一", "（一）", "1"（混合）→ depth = 1（顶级）
    """
    if not structure or structure == "0":
        return 0

    # 标准阿拉伯数字层级（1, 1.1, 1.2.3）
    if re.match(r"^[\d.]+", structure):
        return structure.count(".") + 1

    # 中文编号（一、二、三...）→ 顶级
    if re.match(r"^[一二三四五六七八九十百千零]+", structure):
        return 1

    # 带括号的中文（（一）、（二）...）→ 子级
    if re.match(r"^[（(][一二三四五六七八九十]+[）)]", structure):
        return 2

    # 默认：没有 "." 的视为顶级，有 "." 的按点数计算
    return structure.count(".") + 1


# ---------------------------------------------------------------------------
# Step 6: 修复父节点 end_index
# ---------------------------------------------------------------------------


def fix_parent_ranges(tree: List[Dict]) -> None:
    """递归修复：父节点 end_index 至少覆盖到最后一个子节点的 end_index。"""
    for node in tree:
        children = node.get("nodes", [])
        if children:
            fix_parent_ranges(children)
            last_child_end = children[-1].get("end_index", 0)
            if last_child_end > node.get("end_index", 0):
                node["end_index"] = last_child_end


# ---------------------------------------------------------------------------
# Step 7: 完整性检查
# ---------------------------------------------------------------------------


def check_completeness(tree: List[Dict], page_count: int) -> Dict[str, Any]:
    """检查 TOC 树的完整性。"""
    # 收集所有叶节点的页面范围
    ranges = []
    _collect_ranges(tree, ranges)

    if not ranges:
        return {"coverage": 0, "gaps": [], "ok": False}

    # 计算覆盖的页面集合
    covered_pages = set()
    for start, end in ranges:
        for p in range(start, end + 1):
            covered_pages.add(p)

    coverage = len(covered_pages) / page_count if page_count > 0 else 0

    # 检查空洞
    gaps = []
    all_pages = set(range(1, page_count + 1))
    uncovered = sorted(all_pages - covered_pages)
    if uncovered:
        # 合并连续的未覆盖页面
        gap_start = uncovered[0]
        for i in range(1, len(uncovered)):
            if uncovered[i] != uncovered[i - 1] + 1:
                gaps.append((gap_start, uncovered[i - 1]))
                gap_start = uncovered[i]
        gaps.append((gap_start, uncovered[-1]))

    # 检查最后一个节点是否到达文档末尾
    last_end = max((r[1] for r in ranges), default=0)
    reaches_end = last_end >= page_count - 2  # 允许末尾 1-2 页空白

    # 分层阈值：允许漏页 = min(max(2, ceil(5%)), 10)
    import math

    max_uncovered = min(max(2, math.ceil(page_count * 0.05)), 10)
    uncovered_count = page_count - len(covered_pages)

    if uncovered_count <= 3 and coverage >= 0.95:
        quality = "good"
    elif uncovered_count <= max_uncovered and reaches_end:
        quality = "ok"
    elif uncovered_count <= max_uncovered * 2:
        quality = "warning"  # 需要修复
    else:
        quality = "bad"  # 需要修复

    ok = quality in ("good", "ok")
    needs_repair = quality in ("warning", "bad")

    if not ok:
        print(
            f"[POST] Completeness: quality={quality}, coverage={coverage:.0%}, "
            f"uncovered={uncovered_count}/{max_uncovered} allowed, "
            f"last_end={last_end}/{page_count}, gaps={len(gaps)}"
        )

    return {
        "quality": quality,
        "coverage": coverage,
        "gaps": gaps,
        "reaches_end": reaches_end,
        "ok": ok,
        "needs_repair": needs_repair,
        "uncovered_count": uncovered_count,
        "max_uncovered": max_uncovered,
    }


def _collect_ranges(tree: List[Dict], ranges: List[Tuple[int, int]]) -> None:
    """递归收集所有节点的 [start_index, end_index]。"""
    for node in tree:
        s = node.get("start_index")
        e = node.get("end_index")
        if s is not None and e is not None:
            ranges.append((s, e))
        children = node.get("nodes", [])
        if children:
            _collect_ranges(children, ranges)


# ---------------------------------------------------------------------------
# Step 8: 格式化输出
# ---------------------------------------------------------------------------


def format_tree(tree: List[Dict]) -> List[Dict]:
    """清理树结构，只保留需要的字段。"""
    result = []
    for node in tree:
        formatted = {
            "title": node.get("title", ""),
            "start_index": node.get("start_index"),
            "end_index": node.get("end_index"),
            "summary": node.get("summary", ""),
            "text": node.get("text", ""),
            "nodes": format_tree(node.get("nodes", [])),
        }
        # 可选字段
        if "node_id" in node:
            formatted["node_id"] = node["node_id"]
        if "structure" in node:
            formatted["structure"] = node["structure"]
        result.append(formatted)
    return result


# ---------------------------------------------------------------------------
# P3: Unified Refinement Layer (dividers-based cross-validation)
# ---------------------------------------------------------------------------


def refine_toc_with_dividers(
    toc_items: List[Dict],
    dividers: List[int],
    page_count: int,
) -> List[Dict]:
    """Unified refinement: cross-validate TOC against divider positions.
    
    Fixes:
    1. Duplicate physical_index → merge or adjust
    2. Missing chapters for dividers → insert synthetic items
    3. Wrong chapter assignments → reassign to nearest divider
    4. Empty structure fields → infer from position
    """
    if not dividers or not toc_items:
        return toc_items
    
    items = list(toc_items)
    
    # 1. Fix duplicate physical_index
    # P4-fix: 不再按 physical_index 合并，因为一页可以有多个条目（如图表）
    # 只去重真正的重复（相同标题+相同页码）
    seen = set()
    deduped = []
    for item in items:
        key = (item.get("title", "")[:30], item["physical_index"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    
    items = deduped
    items.sort(key=lambda x: x["physical_index"])
    
    # 2. Ensure each divider has a corresponding top-level item
    # Find items that are "close" to dividers (±1 page)
    divider_items = {}  # divider -> item
    for item in items:
        pi = item["physical_index"]
        for d in dividers:
            if abs(pi - d) <= 1:
                divider_items[d] = item
                break
    
    # 3. Insert missing chapter items for dividers without matches
    # FIX: Skip page 1 - it's usually cover/toc, not a chapter divider
    for d in dividers:
        if d == 1:
            continue  # Skip page 1 (cover page)
        if d not in divider_items and d <= page_count:
            # Find insertion point
            insert_idx = len(items)
            for i, item in enumerate(items):
                if item["physical_index"] > d:
                    insert_idx = i
                    break
            
            synthetic = {
                "structure": "",
                "title": f"Chapter at page {d}",
                "physical_index": d,
            }
            items.insert(insert_idx, synthetic)
            print(f"[POST-REFINE] Inserted synthetic chapter at p.{d}")
    
    # 4. Re-sort after insertions
    items.sort(key=lambda x: x["physical_index"])
    
    # 5. Fix empty structures: infer chapter numbers
    chapter_num = 1
    for i, item in enumerate(items):
        if not item.get("structure"):
            # Check if this looks like a main chapter
            is_main = False
            if i < len(items) - 1:
                next_struct = str(items[i + 1].get("structure", ""))
                if "." in next_struct:
                    is_main = True
            
            if is_main:
                item["structure"] = str(chapter_num)
                chapter_num += 1
            else:
                # Sub-chapter: find parent
                parent_num = None
                for j in range(i - 1, -1, -1):
                    prev_struct = str(items[j].get("structure", ""))
                    if prev_struct and "." not in prev_struct:
                        parent_num = prev_struct
                        break
                if parent_num:
                    item["structure"] = f"{parent_num}.1"
    
    return items


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def post_process_toc(
    toc_items: List[Dict],
    page_count: int,
    dividers: Optional[List[int]] = None,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """TOC 后处理主入口。

    Args:
        toc_items: TOC 扁平条目列表
        page_count: 文档总页数
        dividers: 可选的章节分隔页列表，用于统一修正

    Returns:
        (tree, completeness_info)
    """
    # Step 1: 清洗
    items = clean_toc_items(toc_items)
    if not items:
        print("[POST] No valid items after cleaning")
        items = [{"structure": "1", "title": "Document Content", "physical_index": 1}]

    # Step 1.2: 过滤图录/表录节点
    items, _ = filter_figure_catalogs(items)
    if not items:
        print("[POST] No valid items after filtering figure catalogs")
        items = [{"structure": "1", "title": "Document Content", "physical_index": 1}]

    # Step 1.5: P3 Unified Refinement (dividers-based)
    if dividers:
        items = refine_toc_with_dividers(items, dividers, page_count)

    # Step 2: 边界校验
    items = validate_indices(items, page_count)
    if not items:
        print("[POST] No valid items after validation")
        items = [{"structure": "1", "title": "Document Content", "physical_index": 1}]

    # Step 3: 补充 Preface
    items = add_preface(items)

    # Step 4: 设置页面范围
    items = assign_page_ranges(items, page_count)

    # Step 5: 构建树
    tree = build_tree(items)
    
    # Step 5.5: 移除空结构的合成根节点，提升直接子节点
    def remove_synthetic_roots(nodes):
        result = []
        for node in nodes:
            if node.get("structure") == "" and "Chapter at page" in node.get("title", ""):
                # 提升直接子节点到当前层级
                children = node.get("nodes", [])
                if children:
                    print(f"[POST] Removed synthetic root '{node['title']}', promoted {len(children)} children")
                    # 递归处理子节点（它们可能也是合成根节点）
                    result.extend(remove_synthetic_roots(children))
                else:
                    print(f"[POST] Removed synthetic root '{node['title']}' (no children)")
            else:
                # 保留节点，但递归处理其子节点
                if node.get("nodes"):
                    node["nodes"] = remove_synthetic_roots(node["nodes"])
                result.append(node)
        return result
    
    tree = remove_synthetic_roots(tree)
    
    # Step 5.6: 移除所有"Chapter at page"合成节点
    def remove_all_synthetic_nodes(nodes):
        result = []
        for node in nodes:
            if "Chapter at page" in node.get("title", ""):
                # 移除合成节点，但保留其子节点
                children = node.get("nodes", [])
                if children:
                    print(f"[POST] Removed synthetic chapter '{node['title']}', promoted {len(children)} children")
                    result.extend(remove_all_synthetic_nodes(children))
                else:
                    print(f"[POST] Removed synthetic chapter '{node['title']}' (no children)")
            else:
                # 保留节点，但递归处理其子节点
                if node.get("nodes"):
                    node["nodes"] = remove_all_synthetic_nodes(node["nodes"])
                result.append(node)
        return result
    
    tree = remove_all_synthetic_nodes(tree)
    
    # Step 5.7: 使用structure重建正确的父子关系
    def rebuild_tree_by_structure(nodes):
        """根据structure字段重建父子关系，确保子节点在正确的父节点下"""
        if not nodes:
            return []
        
        # 按start_index排序
        nodes_sorted = sorted(nodes, key=lambda x: x.get("start_index", 0) or x.get("physical_index", 0))
        
        # 创建节点映射（structure -> node）
        node_map = {}
        for node in nodes_sorted:
            s = node.get("structure", "")
            if s:
                node_map[s] = node
        
        # 构建父子关系
        roots = []
        for node in nodes_sorted:
            s = node.get("structure", "")
            if not s or s == "0":
                # Preface或空structure，作为根节点
                roots.append(node)
                continue
            
            parent_found = False
            if "." in s:
                # 子章节，找到父节点
                parent_s = ".".join(s.split(".")[:-1])
                if parent_s in node_map:
                    parent = node_map[parent_s]
                    if "nodes" not in parent:
                        parent["nodes"] = []
                    # 避免重复添加
                    if node not in parent["nodes"]:
                        parent["nodes"].append(node)
                    parent_found = True
            
            if not parent_found:
                # 没有父节点，作为根节点
                roots.append(node)
        
        return roots
    
    tree = rebuild_tree_by_structure(tree)

    # Step 6: 修复父节点范围
    fix_parent_ranges(tree)

    # Step 6.5: P4-fix —— 按类型分组，构建三个独立的目录
    def flatten_tree(nodes):
        """展平树结构，返回所有节点"""
        result = []
        for node in nodes:
            result.append(node)
            children = node.get("nodes", [])
            if children:
                result.extend(flatten_tree(children))
        return result
    
    def classify_node_type(node):
        """分类节点类型：chapter / figure / table / other"""
        title = str(node.get("title", "")).lower()
        number = str(node.get("number", "")).lower()
        text = f"{number} {title}"
        
        if "图目录" in text or "表目录" in text:
            return "other"  # 过滤掉目录节点
        if any(k in text for k in ['图', 'figure', 'fig.']):
            return "figure"
        if any(k in text for k in ['表', 'table']):
            return "table"
        return "chapter"
    
    # 展平并分类
    all_nodes = flatten_tree(tree)
    chapters = [n for n in all_nodes if classify_node_type(n) == "chapter"]
    figures = [n for n in all_nodes if classify_node_type(n) == "figure"]
    tables = [n for n in all_nodes if classify_node_type(n) == "table"]
    
    print(f"[POST] Grouped: {len(chapters)} chapters, {len(figures)} figures, {len(tables)} tables")
    
    # 构建三个独立的树
    grouped_tree = []
    
    if chapters:
        # 清理子节点引用，避免重复
        for n in chapters:
            n["nodes"] = []
        chapter_tree = build_tree(chapters)
        grouped_tree.append({
            "title": "目录",
            "physical_index": chapters[0].get("physical_index", 1),
            "start_index": chapters[0].get("start_index", 1),
            "end_index": chapters[-1].get("end_index", page_count),
            "nodes": chapter_tree,
            "node_type": "catalog_group",
        })
    
    if figures:
        for n in figures:
            n["nodes"] = []
        figure_tree = build_tree(figures)
        grouped_tree.append({
            "title": "图目录",
            "physical_index": figures[0].get("physical_index", 1),
            "start_index": figures[0].get("start_index", 1),
            "end_index": figures[-1].get("end_index", page_count),
            "nodes": figure_tree,
            "node_type": "catalog_group",
        })
    
    if tables:
        for n in tables:
            n["nodes"] = []
        table_tree = build_tree(tables)
        grouped_tree.append({
            "title": "表目录",
            "physical_index": tables[0].get("physical_index", 1),
            "start_index": tables[0].get("start_index", 1),
            "end_index": tables[-1].get("end_index", page_count),
            "nodes": table_tree,
            "node_type": "catalog_group",
        })
    
    # 使用分组后的树
    if grouped_tree:
        tree = grouped_tree

    # Step 7: 完整性检查
    completeness = check_completeness(tree, page_count)

    print(
        f"[POST] Done: {len(items)} items → tree with {len(tree)} top-level groups, "
        f"coverage={completeness['coverage']:.0%}"
    )
    return tree, completeness


async def llm_quality_check(
    tree: List[Dict],
    toc_items: List[Dict],
    page_count: int,
    source: str = "unknown",
    has_dividers: bool = False,
    divider_count: int = 0,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """LLM 最终质检：评估 TOC 结构质量并给出修复建议。
    
    Args:
        tree: TOC 树结构
        toc_items: 原始 TOC 条目
        page_count: 文档总页数
        source: TOC 来源 (bookmarks/regex/vlm)
        has_dividers: 是否有章节分隔页
        divider_count: 章节分隔页数量
        model: LLM 模型名称
    
    Returns:
        {
            "structure_score": int,
            "large_nodes": list,
            "missing_chapters": list,
            "overall_score": int,
            "suggestions": list,
            "needs_repair": bool,
        }
    """
    try:
        from pageindex.vlm_utils import parse_vlm_json
        from pageindex.utils import ChatGPT_API_async
        from app.prompts.pageindex_prompts import TOC_QUALITY_CHECK_PROMPT
    except ImportError:
        # 如果导入失败，返回基础质检结果
        return {
            "structure_score": 50,
            "large_nodes": [],
            "missing_chapters": [],
            "overall_score": 50,
            "suggestions": [],
            "needs_repair": False,
            "error": "Import failed",
        }
    
    # 格式化 TOC 树
    def format_tree(nodes: List[Dict], indent: int = 0) -> str:
        lines = []
        for node in nodes:
            prefix = "  " * indent
            start = node.get("start_index", "?")
            end = node.get("end_index", "?")
            title = node.get("title", "")
            lines.append(f"{prefix}[{start}-{end}] {title}")
            children = node.get("nodes", [])
            if children:
                lines.append(format_tree(children, indent + 1))
        return "\n".join(lines)
    
    toc_tree_formatted = format_tree(tree)
    
    # 格式化原始条目
    toc_items_formatted = "\n".join(
        f"  [{it.get('structure', '?')}] p.{it.get('physical_index', '?')} {it.get('title', '')}"
        for it in toc_items[:20]  # 只取前 20 个避免过长
    )
    
    prompt = TOC_QUALITY_CHECK_PROMPT.format(
        page_count=page_count,
        source=source,
        has_dividers="是" if has_dividers else "否",
        divider_count=divider_count,
        toc_tree_formatted=toc_tree_formatted,
        toc_items_formatted=toc_items_formatted,
    )
    
    try:
        response = await ChatGPT_API_async(model=model or "qwen3.6-flash", prompt=prompt)
        result = parse_vlm_json(response)
        
        if isinstance(result, dict):
            print(f"[LLM-QC] Quality check: overall_score={result.get('overall_score', 'N/A')}, "
                  f"needs_repair={result.get('needs_repair', False)}")
            if result.get("needs_repair"):
                print(f"[LLM-QC] Suggestions: {result.get('suggestions', [])}")
            return result
    except Exception as e:
        print(f"[LLM-QC] Failed: {e}")
    
    # 失败时返回默认结果
    return {
        "structure_score": 50,
        "large_nodes": [],
        "missing_chapters": [],
        "overall_score": 50,
        "suggestions": [],
        "needs_repair": False,
    }
