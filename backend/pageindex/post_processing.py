"""后处理模块：将 TOC 扁平列表转换为完整的、页码正确的树结构。

确保：
1. TOC 完整（覆盖文档大部分页面）
2. 页码正确（start_index/end_index 在有效范围内）
3. 层级正确（structure 编号对应正确的父子关系）
4. 无遗漏（Preface 补充、大节点拆分）
"""

import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from pageindex.catalog_classifier import (
    AUXILIARY_CATALOG_TYPES,
    CATALOG_FIGURE,
    CATALOG_MAIN,
    CATALOG_TABLE,
    catalog_group_title,
    detect_catalog_type,
)


def merge_toc_sources(
    file_path: str,
    toc_from_page: Optional[List[Dict]],
    toc_from_search: Optional[List[Dict]],
    dividers: Optional[List[int]],
    extracted_items: Optional[List[Dict]],
) -> List[Dict]:
    """Safely merge canonical TOC sources without dropping no-TOC extracted items."""
    base_items = toc_from_page or extracted_items or []
    merged: Dict[str, Dict] = {
        str(item.get("structure", index + 1)): dict(item)
        for index, item in enumerate(base_items)
    }

    for item in toc_from_search or []:
        structure = str(item.get("structure", ""))
        if structure in merged and item.get("physical_index") and not merged[structure].get("physical_index"):
            merged[structure]["physical_index"] = item["physical_index"]

    return sorted(
        merged.values(),
        key=lambda item: item.get("physical_index") or 10**9,
    )



def _to_positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        parsed = int(value)
        return parsed if parsed > 0 else None
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            parsed = int(match.group())
            return parsed if parsed > 0 else None
    return None


def _looks_like_toc_title(value: Any) -> bool:
    title = str(value or "").strip()
    if len(title) < 2 or len(title) > 240:
        return False
    compact = re.sub(r"\s+", "", title)
    if not compact:
        return False
    if re.fullmatch(r"[\d\W_]+", compact, flags=re.UNICODE):
        return False
    if re.match(r"^(?:level|page|logical_page|physical_index|source_page|confidence)\s*[:=]", title, re.IGNORECASE):
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", title))

# ---------------------------------------------------------------------------
# stage=clean: 数据清洗
# ---------------------------------------------------------------------------


def _is_catalog_group_item(item: Dict[str, Any]) -> bool:
    return item.get("page_type") == "catalog_group" or item.get("node_type") == "catalog_group"


def _toc_pages_from_analysis(analysis: Optional[Dict[str, Any]]) -> List[int]:
    if not isinstance(analysis, dict):
        return []

    sources = [
        analysis.get("toc_pages"),
        (analysis.get("toc_page") or {}).get("pages") if isinstance(analysis.get("toc_page"), dict) else None,
        (analysis.get("toc_page_detection") or {}).get("pages")
        if isinstance(analysis.get("toc_page_detection"), dict)
        else None,
    ]
    pages: List[int] = []
    for source in sources:
        if not isinstance(source, list):
            continue
        for value in source:
            parsed = _to_positive_int(value)
            if parsed is not None:
                pages.append(parsed)
    return sorted(set(pages))


def _should_preserve_unpaged_toc_skeleton(analysis: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(analysis, dict):
        return False
    source = str(analysis.get("toc_source") or analysis.get("toc_frozen_source") or "")
    if source not in {"llm_toc_page", "ocr_toc_page", "toc_page_layout"}:
        return False
    toc_page = analysis.get("toc_page") or {}
    has_toc_page = bool(toc_page.get("has_toc_page")) if isinstance(toc_page, dict) else False
    return has_toc_page or bool(_toc_pages_from_analysis(analysis))


def clean_toc_items(
    toc_items: List[Dict],
    page_count: Optional[int] = None,
    *,
    preserve_unpaged: bool = False,
    provisional_start_page: int = 1,
) -> List[Dict]:
    """清洗 TOC 条目：转 int、去重、排序、过滤无效。
    
    保留 catalog_group 节点（即使 physical_index 为 None）。
    """
    cleaned = []
    for item in toc_items:
        pi = _to_positive_int(item.get("physical_index"))
        logical_page = _to_positive_int(item.get("logical_page")) or _to_positive_int(item.get("page"))
        page_value = _to_positive_int(item.get("page"))
        source_page = _to_positive_int(item.get("source_page"))
        page_type = item.get("page_type", "")

        # catalog_group nodes may be structural and legitimately lack a page.
        is_catalog_group = _is_catalog_group_item(item)
        provisional_mapping = False

        if not is_catalog_group and pi is None:
            if not _looks_like_toc_title(item.get("title")):
                continue
            if logical_page is not None:
                pi = min(logical_page, page_count) if page_count and page_count > 0 else logical_page
            elif preserve_unpaged:
                upper = page_count if page_count and page_count > 0 else provisional_start_page
                pi = max(1, min(int(provisional_start_page or 1), int(upper)))
            else:
                continue
            provisional_mapping = True

        if not is_catalog_group and (pi is None or pi < 1):
            continue

        repair_reasons = [str(reason) for reason in (item.get("repair_reasons") or []) if str(reason).strip()]
        if provisional_mapping:
            if "mapping_pending" not in repair_reasons:
                repair_reasons.append("mapping_pending")
            provisional_reason = "provisional_logical_page" if logical_page is not None else "unpaged_toc_skeleton"
            if provisional_reason not in repair_reasons:
                repair_reasons.append(provisional_reason)
                repair_reasons.append("provisional_logical_page")

        cleaned_item = {
            "structure": str(item.get("structure", "")).strip(),
            "title": str(item.get("title", "")).strip(),
            "physical_index": pi,
            "page_type": page_type,
        }
        if page_value is not None:
            cleaned_item["page"] = page_value
        if logical_page is not None:
            cleaned_item["logical_page"] = logical_page
        if source_page is not None:
            cleaned_item["source_page"] = source_page
        catalog_type = item.get("catalog_type")
        if catalog_type is not None:
            cleaned_item["catalog_type"] = str(catalog_type).strip()
        if repair_reasons:
            cleaned_item["repair_reasons"] = repair_reasons
        if provisional_mapping:
            cleaned_item["needs_repair"] = True
            cleaned_item["mapping_source"] = item.get("mapping_source") or (
                "provisional_logical_page" if logical_page is not None else "unpaged_toc_skeleton"
            )
            cleaned_item["mapping_confidence"] = item.get("mapping_confidence") or 0.0
        if item.get("_fixed_range"):
            cleaned_item["_fixed_range"] = True
            if isinstance(item.get("start_index"), int):
                cleaned_item["start_index"] = item["start_index"]
            if isinstance(item.get("end_index"), int):
                cleaned_item["end_index"] = item["end_index"]
        level = item.get("level")
        if isinstance(level, int) and not isinstance(level, bool):
            cleaned_item["level"] = level
        # 保留 number 字段（用于图表分类）
        number = item.get("number")
        if number is not None:
            cleaned_item["number"] = str(number).strip()
        # 保留 nodes（子节点）用于 catalog_group
        nodes = item.get("nodes")
        if nodes:
            cleaned_item["nodes"] = clean_toc_items(
                nodes,
                page_count=page_count,
                preserve_unpaged=preserve_unpaged,
                provisional_start_page=provisional_start_page,
            )
        cleaned.append(cleaned_item)

    if not cleaned:
        return []

    # 按 physical_index 排序（稳定排序，保留原始顺序）
    # catalog_group 节点（physical_index 为 None）排在最前面，保持原始顺序
    catalog_groups = [x for x in cleaned if _is_catalog_group_item(x)]
    regular_items = [x for x in cleaned if not _is_catalog_group_item(x)]
    regular_items.sort(key=lambda x: x["physical_index"] or 0)
    cleaned = catalog_groups + regular_items

    # 去重：相同标题 + 相近页码（±1）
    deduped = [cleaned[0]]
    for item in cleaned[1:]:
        last = deduped[-1]
        same_title = item["title"][:20] == last["title"][:20]
        # catalog_group 节点不参与去重
        if _is_catalog_group_item(item):
            deduped.append(item)
            continue
        close_page = abs((item["physical_index"] or 0) - (last["physical_index"] or 0)) <= 1
        if same_title and close_page:
            continue
        deduped.append(item)

    # 检查单调递增，移除回退的条目
    result = [deduped[0]]
    for item in deduped[1:]:
        # catalog_group 节点直接保留，不参与单调性检查
        if _is_catalog_group_item(item):
            result.append(item)
            continue
        # 与前一个常规节点比较
        last_regular = [x for x in result if not _is_catalog_group_item(x)]
        if not last_regular:
            result.append(item)
            continue
        if (item["physical_index"] or 0) >= (last_regular[-1]["physical_index"] or 0):
            result.append(item)
        else:
            print(
                f"[TOC-POST] Removed non-monotonic item: {item['title'][:30]} p.{item['physical_index']}"
            )

    return result


# ---------------------------------------------------------------------------
# stage=validate: 边界校验
# ---------------------------------------------------------------------------


def filter_figure_catalogs(toc_items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """过滤纯图录/表录目录节点，保留具体图表条目。
    
    检测规则：
    1. 标题匹配 "图目录" 或 "表目录" —— 这些是纯目录页，过滤掉（但保留 catalog_group 节点）
    2. 标题匹配 "图 N..." 或 "表 N..." —— 这些是具体图表条目，保留但标记
    """
    catalog_pattern = re.compile(r'^[图表]目录')
    
    normal = []
    figures = []
    
    for item in toc_items:
        title = item.get("title", "")
        # 保留 catalog_group 节点（如 目录/表目录/图目录）
        if item.get("page_type") == "catalog_group" or item.get("node_type") == "catalog_group":
            normal.append(item)
            continue
        if catalog_pattern.match(title):
            # 纯目录节点（如"图目录"）—— 过滤
            figures.append(item)
            print(f"[TOC-POST] Filtered figure/table catalog: {title[:50]}")
        else:
            normal.append(item)
    
    return normal, figures


def validate_indices(toc_items: List[Dict], page_count: int) -> List[Dict]:
    """校验 physical_index 在 [1, page_count] 范围内。"""
    valid = []
    for item in toc_items:
        pi = item.get("physical_index")
        # catalog_group 节点跳过校验
        if item.get("page_type") == "catalog_group" or item.get("node_type") == "catalog_group":
            valid.append(item)
            continue
        if pi is not None and 1 <= pi <= page_count:
            valid.append(item)
        else:
            print(
                f"[TOC-POST] Out of range: {item['title'][:30]} p.{pi} (max={page_count})"
            )
    return valid


# ---------------------------------------------------------------------------
# stage=preface: 补充 Preface
# ---------------------------------------------------------------------------


def promote_single_catalog_root(tree: List[Dict], page_count: int) -> List[Dict]:
    """Promote children when a synthetic Contents root wraps the whole tree."""
    if len(tree) != 1:
        return tree
    root = tree[0]
    title = str(root.get("title", "")).strip()
    if title not in {"目录", "Contents", "Table of Contents"}:
        return tree
    children = root.get("nodes") or []
    if len(children) < 2:
        return tree
    start = root.get("start_index")
    end = root.get("end_index")
    covers_document = (
        isinstance(start, int)
        and isinstance(end, int)
        and start <= 2
        and end >= max(1, page_count - 1)
    )
    if not covers_document:
        return tree
    child_pages = [
        child.get("start_index")
        for child in children
        if isinstance(child.get("start_index"), int)
    ]
    if len(child_pages) < len(children):
        return tree
    if any(child_pages[i] > child_pages[i + 1] for i in range(len(child_pages) - 1)):
        return tree
    print(f"[TOC-POST] Promoted synthetic catalog root '{title}' with {len(children)} children")
    return children


def repair_case_continuation_roots(tree: List[Dict]) -> List[Dict]:
    """Move case continuation roots back under the preceding case/award chapter."""
    if len(tree) < 2:
        return tree

    repaired: List[Dict] = []
    for node in tree:
        title = str(node.get("title", "")).strip()
        previous = repaired[-1] if repaired else None
        previous_title = str(previous.get("title", "")).strip() if previous else ""
        is_case_continuation = bool(
            re.match(r"^[\u4e00-\u9fa5A-Za-z]+AI[:：]", title)
            and previous
            and any(keyword in previous_title for keyword in ("突破奖", "案例", "应用"))
        )
        if not is_case_continuation:
            repaired.append(node)
            continue

        previous.setdefault("nodes", [])
        moved = dict(node)
        moved["nodes"] = []
        previous["nodes"].append(moved)
        previous["nodes"].extend(node.get("nodes") or [])
        if isinstance(node.get("end_index"), int):
            previous["end_index"] = max(
                previous.get("end_index") or node["end_index"],
                node["end_index"],
            )
        print(f"[TOC-POST] Moved continuation case '{title[:30]}' under '{previous_title[:30]}'")

    return repaired


def repair_placeholder_chapter_titles(tree: List[Dict]) -> List[Dict]:
    """Replace bare Chapter labels with concise child-derived titles."""
    for node in tree:
        children = node.get("nodes") or []
        if children:
            node["nodes"] = repair_placeholder_chapter_titles(children)

        title = str(node.get("title", "")).strip()
        if not re.match(r"^第[一二三四五六七八九十]+章\s*Chapter\s*\d+$", title, re.IGNORECASE):
            continue
        child_titles = [str(child.get("title", "")).strip() for child in node.get("nodes") or []]
        prefixes = []
        for child_title in child_titles:
            match = re.match(r"^([^:：]{2,12})[:：]", child_title)
            if match:
                prefixes.append(match.group(1).strip())
        if len(prefixes) >= 2:
            node["original_title"] = title
            node["title"] = "与".join(prefixes[:2])
        elif child_titles:
            node["original_title"] = title
            node["title"] = child_titles[0]
    return tree


def add_preface(toc_items: List[Dict]) -> List[Dict]:
    """如果第一个条目不在第 1 页，插入 Preface 节点。"""
    if not toc_items:
        return toc_items

    # 跳过开头的 catalog_group 节点
    first_regular = None
    for item in toc_items:
        if not (item.get("page_type") == "catalog_group" or item.get("node_type") == "catalog_group"):
            first_regular = item
            break

    if first_regular and (first_regular.get("physical_index") or 0) > 1:
        preface = {
            "structure": "0",
            "title": "Preface",
            "physical_index": 1,
        }
        # 在 catalog_group 之后插入 Preface
        insert_idx = 0
        for i, item in enumerate(toc_items):
            if not (item.get("page_type") == "catalog_group" or item.get("node_type") == "catalog_group"):
                insert_idx = i
                break
        toc_items.insert(insert_idx, preface)

    return toc_items


def normalize_sibling_page_ranges(
    nodes: List[Dict],
    *,
    page_count: int,
    parent_start: Optional[int] = None,
    parent_end: Optional[int] = None,
    copy_nodes: bool = True,
) -> List[Dict]:
    """Normalize one sibling list using physical page boundaries."""
    normalized = deepcopy(nodes) if copy_nodes else nodes
    if not normalized:
        return normalized
    max_page = max(1, int(page_count or 1))
    lower = _clamp_page(parent_start or 1, max_page)
    upper = _clamp_page(parent_end or max_page, max_page)
    if upper < lower:
        upper = lower

    for node in normalized:
        start = _node_start_page(node)
        start = _clamp_page(start or lower, max_page)
        start = max(lower, min(start, upper))
        end = _node_end_page(node)
        end = _clamp_page(end or upper, max_page)
        end = max(start, min(end, upper))
        node["start_index"] = start
        node["end_index"] = end
        if not _to_positive_int(node.get("physical_index")):
            node["physical_index"] = start

    for index, node in enumerate(normalized):
        start = node["start_index"]
        if index < len(normalized) - 1:
            next_start = normalized[index + 1]["start_index"]
            current_end = node.get("end_index") or upper
            end = next_start if next_start == current_end else next_start - 1
            node["end_index"] = max(start, min(end, upper))
        else:
            node["end_index"] = max(start, upper)

        children = node.get("nodes") or []
        if children:
            child_parent_end = node["end_index"]
            if _is_catalog_container(node):
                child_parent_end = upper
            node["nodes"] = normalize_sibling_page_ranges(
                children,
                page_count=max_page,
                parent_start=node["start_index"],
                parent_end=child_parent_end,
                copy_nodes=False,
            )
            if _is_catalog_container(node):
                child_ends = [
                    child.get("end_index")
                    for child in node["nodes"]
                    if isinstance(child.get("end_index"), int)
                ]
                if child_ends:
                    node["end_index"] = max(node["end_index"], max(child_ends))
    return normalized


def normalize_tree_page_ranges(tree: List[Dict], page_count: int) -> List[Dict]:
    """Return a tree with valid recursive physical page ranges."""
    return normalize_sibling_page_ranges(tree, page_count=page_count, copy_nodes=True)


def _node_start_page(node: Dict[str, Any]) -> Optional[int]:
    return (
        _to_positive_int(node.get("start_index"))
        or _to_positive_int(node.get("physical_index"))
        or _to_positive_int(node.get("page"))
    )


def _node_end_page(node: Dict[str, Any]) -> Optional[int]:
    return (
        _to_positive_int(node.get("end_index"))
        or _to_positive_int(node.get("start_index"))
        or _to_positive_int(node.get("physical_index"))
        or _to_positive_int(node.get("page"))
    )


def _clamp_page(value: Optional[int], page_count: int) -> int:
    page = value if isinstance(value, int) and value > 0 else 1
    return max(1, min(page, max(1, int(page_count or 1))))


def _is_catalog_container(node: Dict[str, Any]) -> bool:
    if node.get("node_type") in {"catalog_group", "auxiliary_catalog"}:
        return True
    if node.get("page_type") == "catalog_group":
        return True
    catalog_type = str(node.get("catalog_type") or "")
    if catalog_type and catalog_type != CATALOG_MAIN:
        return True
    title = str(node.get("title") or "").strip().lower()
    compact = re.sub(r"\s+", "", title)
    return compact in {
        "目录",
        "contents",
        "tableofcontents",
        "图目录",
        "插图目录",
        "listoffigures",
        "表目录",
        "表格目录",
        "listoftables",
    }


# ---------------------------------------------------------------------------
# stage=range: 设置 start_index / end_index
# ---------------------------------------------------------------------------


def assign_page_ranges(toc_items: List[Dict], page_count: int) -> List[Dict]:
    """为每个条目设置 start_index 和 end_index。"""
    for i, item in enumerate(toc_items):
        if (
            item.get("_fixed_range")
            and isinstance(item.get("start_index"), int)
            and isinstance(item.get("end_index"), int)
        ):
            continue
        physical_index = item.get("physical_index") or 1
        item["start_index"] = physical_index

        if i < len(toc_items) - 1:
            # 找到下一个有有效页码的条目
            next_start = page_count
            for j in range(i + 1, len(toc_items)):
                next_pi = toc_items[j].get("physical_index")
                if next_pi is not None:
                    next_start = next_pi
                    break
            item["end_index"] = max(next_start - 1, item["start_index"])
        else:
            item["end_index"] = page_count

    return normalize_sibling_page_ranges(toc_items, page_count=page_count, copy_nodes=False)


# ---------------------------------------------------------------------------
# stage=tree: 扁平列表 → 树结构
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


def _ensure_level_structures(items: List[Dict]) -> List[Dict]:
    """Fill missing ``structure`` from LLM-provided levels."""
    counters: Dict[int, int] = {}
    result: List[Dict] = []
    for item in items:
        node = dict(item)
        structure = str(node.get("structure") or "").strip()
        if structure:
            result.append(node)
            continue

        level = node.get("level")
        if not isinstance(level, int) or isinstance(level, bool) or level < 1:
            level = 1
        level = max(1, min(6, level))
        while level > 1 and (level - 1) not in counters:
            level -= 1
        for depth in list(counters.keys()):
            if depth > level:
                counters.pop(depth, None)
        counters[level] = counters.get(level, 0) + 1
        for depth in range(1, level):
            counters.setdefault(depth, 1)
        node["structure"] = ".".join(str(counters[depth]) for depth in range(1, level + 1))
        result.append(node)
    return result


def _is_pure_catalog_heading(item: Dict, catalog_type: str) -> bool:
    title = re.sub(r"\s+", "", str(item.get("title") or "").strip().lower())
    if catalog_type == CATALOG_FIGURE:
        return title in {"图目录", "插图目录", "listoffigures", "figurecatalog", "figurescatalog"}
    if catalog_type == CATALOG_TABLE:
        return title in {"表目录", "表格目录", "listoftables", "tablecatalog", "tablescatalog"}
    return title in {"目录", "目次", "contents", "tableofcontents"}


def _prepare_catalog_items(items: List[Dict], catalog_type: str, page_count: int) -> List[Dict]:
    prepared: List[Dict] = []
    for item in _ensure_level_structures(items):
        node = dict(item)
        node["nodes"] = []
        if catalog_type in AUXILIARY_CATALOG_TYPES:
            node["catalog_type"] = catalog_type
            node["node_type"] = "auxiliary_catalog_item"
            node["is_auxiliary"] = True
            node["exclude_from_coverage"] = True
            node["exclude_from_llm_qc"] = True
            node["exclude_from_text"] = True
            page = node.get("physical_index") or node.get("start_index") or 1
            page = max(1, min(page_count, int(page))) if isinstance(page, int) else 1
            node["start_index"] = page
            node["end_index"] = page
            node["source_anchor"] = {"start_page": page, "end_page": page}
        prepared.append(node)
    if catalog_type not in AUXILIARY_CATALOG_TYPES:
        prepared = assign_page_ranges(prepared, page_count)
    return prepared


def _build_catalog_group_root(catalog_type: str, nodes: List[Dict], page_count: int) -> Dict:
    starts = [node.get("start_index") for node in _flatten_tree(nodes) if isinstance(node.get("start_index"), int)]
    ends = [node.get("end_index") for node in _flatten_tree(nodes) if isinstance(node.get("end_index"), int)]
    if catalog_type == CATALOG_MAIN:
        root: Dict[str, Any] = {
            "title": catalog_group_title(CATALOG_MAIN),
            "structure": "contents",
            "node_type": "catalog_group",
            "start_index": 1,
            "end_index": page_count,
            "physical_index": starts[0] if starts else 1,
            "nodes": nodes,
        }
        return root

    start = min(starts) if starts else 1
    end = max(ends) if ends else start
    return {
        "title": catalog_group_title(catalog_type),
        "structure": catalog_type,
        "node_type": "auxiliary_catalog",
        "catalog_type": catalog_type,
        "is_auxiliary": True,
        "exclude_from_coverage": True,
        "exclude_from_llm_qc": True,
        "exclude_from_text": True,
        "start_index": start,
        "end_index": end,
        "physical_index": start,
        "nodes": nodes,
    }


def _flatten_tree(nodes: List[Dict]) -> List[Dict]:
    flattened: List[Dict] = []
    for node in nodes:
        flattened.append(node)
        flattened.extend(_flatten_tree(node.get("nodes") or []))
    return flattened


def _build_multi_catalog_tree_if_present(items: List[Dict], page_count: int) -> Optional[List[Dict]]:
    groups: Dict[str, List[Dict]] = {
        CATALOG_MAIN: [],
        CATALOG_FIGURE: [],
        CATALOG_TABLE: [],
    }
    for item in items:
        catalog_type = detect_catalog_type(item)
        if _is_pure_catalog_heading(item, catalog_type):
            continue
        groups.setdefault(catalog_type, []).append(item)

    if not any(groups[catalog_type] for catalog_type in AUXILIARY_CATALOG_TYPES):
        return None

    tree: List[Dict] = []
    for catalog_type in (CATALOG_MAIN, CATALOG_FIGURE, CATALOG_TABLE):
        family_items = groups.get(catalog_type) or []
        if not family_items:
            continue
        prepared = _prepare_catalog_items(family_items, catalog_type, page_count)
        family_tree = build_tree(prepared)
        fix_parent_ranges(family_tree)
        tree.append(_build_catalog_group_root(catalog_type, family_tree, page_count))
    return tree or None


def _leaf_signature_stats(tree: List[Dict]) -> Dict[str, Any]:
    """Return leaf count and duplicate count for TOC integrity checks."""
    signatures = []

    def visit(nodes: List[Dict]) -> None:
        for node in nodes:
            children = node.get("nodes") or []
            if children:
                visit(children)
            elif node.get("node_type") != "catalog_group":
                title = re.sub(r"\s+", "", str(node.get("title", ""))).lower()
                signatures.append((title, node.get("physical_index")))

    visit(tree)
    unique = set(signatures)
    return {
        "leaf_count": len(signatures),
        "duplicate_count": len(signatures) - len(unique),
    }


def _grouping_preserves_toc(original_tree: List[Dict], grouped_tree: List[Dict]) -> bool:
    original = _leaf_signature_stats(original_tree)
    grouped = _leaf_signature_stats(grouped_tree)
    if grouped["duplicate_count"] > 0:
        print(
            f"[TOC-POST] Rejecting LLM grouping: "
            f"duplicates={grouped['duplicate_count']}"
        )
        return False
    if grouped["leaf_count"] < original["leaf_count"]:
        print(
            f"[TOC-POST] Rejecting LLM grouping: "
            f"leaf_count {grouped['leaf_count']} < {original['leaf_count']}"
        )
        return False
    return True


def _is_case_catalog_group(node: Dict) -> bool:
    title = str(node.get("title", "")).strip().lower()
    return title.startswith("ai+")


def _is_numbered_case_item(node: Dict) -> bool:
    title = str(node.get("title", "")).strip()
    return bool(re.match(r"^\d{1,2}\s+", title))


def _group_frozen_case_catalogs(tree: List[Dict]) -> List[Dict]:
    """Nest numbered case items under preceding AI+ catalog groups."""
    group_count = sum(1 for node in tree if _is_case_catalog_group(node))
    numbered_count = sum(1 for node in tree if _is_numbered_case_item(node))
    if group_count < 2 or numbered_count < 2:
        return tree

    grouped: List[Dict] = []
    current_group: Optional[Dict] = None
    moved = 0

    for node in tree:
        if _is_case_catalog_group(node):
            current_group = node
            current_group["nodes"] = list(current_group.get("nodes") or [])
            grouped.append(current_group)
        elif current_group is not None and _is_numbered_case_item(node):
            current_group["nodes"].append(node)
            moved += 1
        else:
            grouped.append(node)
            current_group = None

    if moved:
        print(
            f"[TOC-POST] Frozen TOC deterministic grouping: "
            f"{group_count} groups, {moved} case items"
        )
        fix_parent_ranges(grouped)
        return grouped
    return tree


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
# stage=repair: 修复父节点 end_index
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




def _collect_repair_reasons(tree: List[Dict]) -> List[str]:
    reasons = []

    def visit(nodes: List[Dict]) -> None:
        for node in nodes:
            for reason in node.get("repair_reasons") or []:
                reason_text = str(reason).strip()
                if reason_text:
                    reasons.append(reason_text)
            if node.get("needs_repair"):
                reasons.append("node_needs_repair")
            children = node.get("nodes") or []
            if children:
                visit(children)

    visit(tree or [])
    return sorted(set(reasons))
# ---------------------------------------------------------------------------
# stage=quality: 完整性检查
# ---------------------------------------------------------------------------


def check_completeness(tree: List[Dict], page_count: int) -> Dict[str, Any]:
    """检查 TOC 树的完整性。"""
    # 收集所有叶节点的页面范围
    ranges = []
    _collect_ranges(tree, ranges)
    repair_reasons = _collect_repair_reasons(tree)

    if not ranges:
        return {"coverage": 0, "gaps": [], "ok": False, "needs_repair": True, "repair_reasons": ["empty_ranges"]}

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
    if repair_reasons:
        needs_repair = True
        if quality in ("good", "ok"):
            quality = "warning"

    if not ok:
        print(
            f"[TOC-POST] Completeness: quality={quality}, coverage={coverage:.0%}, "
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
        "repair_reasons": repair_reasons,
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
# stage=format: 格式化输出
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
# LLM 目录分组辅助函数
# ---------------------------------------------------------------------------

def _get_toc_page_text(analysis: Dict) -> str:
    """从analysis中提取目录页文本。"""
    toc_page_info = analysis.get("toc_page", {})
    page_indices = toc_page_info.get("page_indices", [])
    page_texts = analysis.get("page_texts", [])
    
    if not page_indices or not page_texts:
        return ""
    
    toc_text = ""
    for idx in page_indices:
        if 0 <= idx < len(page_texts):
            toc_text += page_texts[idx] + "\n"
    
    return toc_text[:2000]  # 限制长度


def _llm_group_catalogs(tree: List[Dict], analysis: Dict, page_count: int, model: Optional[str]) -> Optional[List[Dict]]:
    """使用LLM进行目录分组。
    
    Returns:
        分组后的树列表，失败返回None
    """
    from pageindex.utils import llm_completion
    
    # 展平树获取所有节点
    all_nodes = []
    def flatten(nodes):
        for node in nodes:
            all_nodes.append(node)
            if node.get("nodes"):
                flatten(node["nodes"])
    flatten(tree)
    
    # 准备目录条目
    toc_items_for_llm = []
    for node in all_nodes:
        toc_items_for_llm.append({
            "title": node.get("title", ""),
            "page": node.get("physical_index", 0) or node.get("start_index", 0),
            "structure": node.get("structure", ""),
        })
    
    # 获取目录页文本
    toc_page_text = _get_toc_page_text(analysis)
    
    # 构建prompt
    prompt = CATALOG_GROUPING_PROMPT.format(
        page_count=page_count,
        toc_page_text=toc_page_text[:1500],
        toc_items_json=json.dumps(toc_items_for_llm[:30], ensure_ascii=False),
    )
    
    # 调用LLM（使用已有的重试机制）
    response = llm_completion(model, prompt)
    if not response:
        return None
    
    # 解析JSON
    try:
        # 尝试从response中提取JSON
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]
        
        data = json.loads(json_str.strip())
        
        # 构建分组树
        groups = []
        
        # 正文目录 - 直接使用原始节点（保留页码信息）
        chapter_items = data.get("chapter_catalog", [])
        if chapter_items:
            # 从原始节点中找到匹配的章节节点
            chapter_nodes = []
            for item in chapter_items:
                title = item.get("title", "")
                page = item.get("page", 0)
                
                # 在原始节点中查找匹配
                matched = None
                for node in all_nodes:
                    if node.get("title", "") == title or abs(node.get("physical_index", 0) - page) <= 1:
                        matched = dict(node)  # 复制节点
                        matched["nodes"] = []  # 清空子节点
                        break
                
                if matched:
                    chapter_nodes.append(matched)
                else:
                    # 未找到匹配，创建新节点
                    chapter_nodes.append({
                        "title": title,
                        "structure": str(item.get("level", "")),
                        "physical_index": page if page > 0 else 1,
                        "nodes": [],
                    })
            
            if chapter_nodes:
                # 重新分配页码范围
                chapter_nodes = assign_page_ranges(chapter_nodes, page_count)
                chapter_tree = build_tree(chapter_nodes)
                groups.append({
                    "title": "目录",
                    "node_type": "catalog_group",
                    "physical_index": chapter_nodes[0].get("physical_index", 1),
                    "start_index": chapter_nodes[0].get("start_index", 1),
                    "end_index": chapter_nodes[-1].get("end_index", page_count),
                    "nodes": chapter_tree,
                })
        
        # 图目录
        if data.get("has_figure_catalog"):
            figure_items = data.get("figure_catalog", [])
            if figure_items and len(figure_items) >= 2:  # 最少2个条目
                figure_nodes = []
                for item in figure_items:
                    title = item.get("title", "")
                    page = item.get("page", 0)
                    
                    # 在原始节点中查找匹配
                    matched = None
                    for node in all_nodes:
                        if node.get("title", "") == title or abs(node.get("physical_index", 0) - page) <= 1:
                            matched = dict(node)
                            matched["nodes"] = []
                            break
                    
                    if matched:
                        figure_nodes.append(matched)
                    else:
                        figure_nodes.append({
                            "title": title,
                            "structure": "",
                            "physical_index": page if page > 0 else 1,
                            "nodes": [],
                        })
                
                if figure_nodes:
                    figure_nodes = assign_page_ranges(figure_nodes, page_count)
                    figure_tree = build_tree(figure_nodes)
                    groups.append({
                        "title": "图目录",
                        "node_type": "catalog_group",
                        "physical_index": figure_nodes[0].get("physical_index", 1),
                        "start_index": figure_nodes[0].get("start_index", 1),
                        "end_index": figure_nodes[-1].get("end_index", page_count),
                        "nodes": figure_tree,
                    })
        
        # 表目录
        if data.get("has_table_catalog"):
            table_items = data.get("table_catalog", [])
            if table_items and len(table_items) >= 2:  # 最少2个条目
                table_nodes = []
                for item in table_items:
                    title = item.get("title", "")
                    page = item.get("page", 0)
                    
                    # 在原始节点中查找匹配
                    matched = None
                    for node in all_nodes:
                        if node.get("title", "") == title or abs(node.get("physical_index", 0) - page) <= 1:
                            matched = dict(node)
                            matched["nodes"] = []
                            break
                    
                    if matched:
                        table_nodes.append(matched)
                    else:
                        table_nodes.append({
                            "title": title,
                            "structure": "",
                            "physical_index": page if page > 0 else 1,
                            "nodes": [],
                        })
                
                if table_nodes:
                    table_nodes = assign_page_ranges(table_nodes, page_count)
                    table_tree = build_tree(table_nodes)
                    groups.append({
                        "title": "表目录",
                        "node_type": "catalog_group",
                        "physical_index": table_nodes[0].get("physical_index", 1),
                        "start_index": table_nodes[0].get("start_index", 1),
                        "end_index": table_nodes[-1].get("end_index", page_count),
                        "nodes": table_tree,
                    })
        
        return groups if groups else None
        
    except Exception as e:
        print(f"[TOC-POST] Failed to parse LLM grouping response: {e}")
        return None


def _build_single_tree(tree: List[Dict], page_count: int) -> List[Dict]:
    """构建单一目录树（不分组）。
    
    当LLM分组失败或文档没有图/表目录时使用。
    """
    # 展平并重新构建
    all_nodes = []
    def flatten(nodes):
        for node in nodes:
            # 移除node_type字段
            clean_node = {k: v for k, v in node.items() if k != "node_type"}
            all_nodes.append(clean_node)
            if node.get("nodes"):
                flatten(node["nodes"])
    flatten(tree)
    
    # 去重
    seen = set()
    unique_nodes = []
    for node in all_nodes:
        key = (node.get("title", ""), node.get("physical_index", 0))
        if key not in seen:
            seen.add(key)
            unique_nodes.append(node)
    
    # 构建单个目录组
    if unique_nodes:
        return [{
            "title": "目录",
            "node_type": "catalog_group",
            "physical_index": unique_nodes[0].get("physical_index", 1),
            "start_index": unique_nodes[0].get("start_index", 1),
            "end_index": unique_nodes[-1].get("end_index", page_count),
            "nodes": build_tree(unique_nodes),
        }]
    
    return tree


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
    # 分离 catalog_group 节点和常规节点
    catalog_groups = [x for x in items if x.get("page_type") == "catalog_group" or x.get("node_type") == "catalog_group"]
    regular_items = [x for x in items if not (x.get("page_type") == "catalog_group" or x.get("node_type") == "catalog_group")]
    regular_items.sort(key=lambda x: x["physical_index"] or 0)
    
    # 2. Ensure each divider has a corresponding top-level item
    # Find items that are "close" to dividers (±1 page)
    divider_items = {}  # divider -> item
    for item in regular_items:
        pi = item["physical_index"]
        if pi is None:
            continue
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
            for i, item in enumerate(regular_items):
                if (item["physical_index"] or 0) > d:
                    insert_idx = i
                    break
            
            synthetic = {
                "structure": "",
                "title": f"Chapter at page {d}",
                "physical_index": d,
            }
            regular_items.insert(insert_idx, synthetic)
            print(f"[TOC-POST] step=refine Inserted synthetic chapter at p.{d}")
    
    # 4. Re-sort after insertions
    regular_items.sort(key=lambda x: x["physical_index"] or 0)
    
    # 5. Fix empty structures: infer chapter numbers
    chapter_num = 1
    for i, item in enumerate(regular_items):
        if not item.get("structure"):
            # Check if this looks like a main chapter
            is_main = False
            if i < len(regular_items) - 1:
                next_struct = str(regular_items[i + 1].get("structure", ""))
                if "." in next_struct:
                    is_main = True
            
            if is_main:
                item["structure"] = str(chapter_num)
                chapter_num += 1
            else:
                # Sub-chapter: find parent
                parent_num = None
                for j in range(i - 1, -1, -1):
                    prev_struct = str(regular_items[j].get("structure", ""))
                    if prev_struct and "." not in prev_struct:
                        parent_num = prev_struct
                        break
                if parent_num:
                    item["structure"] = f"{parent_num}.1"
    
    # 6. Recombine catalog_groups with regular_items
    return catalog_groups + regular_items


def rebuild_structure_by_dividers(
    toc_items: List[Dict],
    dividers: List[int],
    page_count: int,
) -> List[Dict]:
    """利用divider位置重建层级structure。

    当候选 TOC 条目全部平铺（structure为"1","2"...）时，
    利用已校验的divider位置将条目重新组织为层级结构：
    - divider页上的标题 → 顶级（"1","2"...）
    - 各范围内的其他标题 → 子级（"1.1","1.2"...）

    Args:
        toc_items: TOC条目列表
        dividers: 章节分隔页列表（1-indexed）
        page_count: 文档总页数

    Returns:
        重建structure后的条目列表
    """
    if not dividers or len(dividers) < 2:
        return toc_items

    items = list(toc_items)  # 复制，避免修改原始数据
    sorted_dividers = sorted(dividers)

    # stage=clean: 识别divider页上的标题（精确匹配优先，±1容差兜底）
    divider_items = {}  # divider -> item_index
    used_indices = set()

    # 第一轮：精确匹配
    for d in sorted_dividers:
        for i, item in enumerate(items):
            if i in used_indices:
                continue
            pi = item.get("physical_index", 0)
            if pi == d:
                divider_items[d] = i
                used_indices.add(i)
                break

    # 第二轮：±1容差匹配（未匹配的divider）
    for d in sorted_dividers:
        if d in divider_items:
            continue
        best_match = None
        best_distance = float('inf')
        for i, item in enumerate(items):
            if i in used_indices:
                continue
            pi = item.get("physical_index", 0)
            distance = abs(pi - d)
            if distance <= 1 and distance < best_distance:
                best_match = i
                best_distance = distance
        if best_match is not None:
            divider_items[d] = best_match
            used_indices.add(best_match)

    print(f"[TOC-POST] step=rebuild Found {len(divider_items)} divider chapters out of {len(dividers)}")

    # stage=validate: 为divider页的条目分配顶级structure
    chapter_num = 1
    for d in sorted_dividers:
        if d in divider_items:
            idx = divider_items[d]
            items[idx]["structure"] = str(chapter_num)
            chapter_num += 1

    # stage=preface: 为范围内的其他条目分配子级structure
    sub_counters = {}  # parent_chapter -> count

    for i, item in enumerate(items):
        if i in used_indices:
            continue  # 跳过已处理的divider条目

        pi = item.get("physical_index", 0)

        # 找到属于哪个divider范围
        parent_chapter = None
        for j, d in enumerate(sorted_dividers):
            next_d = sorted_dividers[j + 1] if j + 1 < len(sorted_dividers) else page_count + 1
            if d <= pi < next_d:
                parent_chapter = j + 1
                break

        if parent_chapter:
            if parent_chapter not in sub_counters:
                sub_counters[parent_chapter] = 0
            sub_counters[parent_chapter] += 1
            items[i]["structure"] = f"{parent_chapter}.{sub_counters[parent_chapter]}"

    return items


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LLM 目录分组 Prompt
# ---------------------------------------------------------------------------

CATALOG_GROUPING_PROMPT = """You are a document TOC grouping analyst.

The current document has {page_count} physical PDF pages.

Catalog page text preview:
{toc_page_text}

Current flattened TOC items, in order:
{toc_items_json}

Task:
1. Classify the current TOC items into the main chapter catalog, figure catalog, and table catalog when those catalogs are clearly present.
2. Preserve original titles and page values. Do not invent page numbers.
3. If there is no dedicated figure or table catalog, set the corresponding has_* flag to false and return an empty list.
4. A chapter title that contains the word figure or table is still a chapter item unless it belongs to a dedicated figure/table list.

Return JSON only:
{{
  "chapter_catalog": [
    {{"title": "Chapter title", "page": 1, "level": 1}}
  ],
  "has_figure_catalog": false,
  "figure_catalog": [
    {{"title": "Figure 1 System Architecture", "page": 5}}
  ],
  "has_table_catalog": false,
  "table_catalog": [
    {{"title": "Table 1 Experimental Data", "page": 8}}
  ],
  "reasoning": "brief classification rationale"
}}
"""


def post_process_toc(
    toc_items: List[Dict],
    page_count: int,
    dividers: Optional[List[int]] = None,
    analysis: Optional[Dict] = None,
    use_llm_grouping: bool = True,
    model: Optional[str] = None,
) -> Tuple[List[Dict], Dict[str, Any]]:
    """TOC 后处理主入口。

    Args:
        toc_items: TOC 扁平条目列表
        page_count: 文档总页数
        dividers: 可选的章节分隔页列表，用于统一修正
        analysis: 文档分析结果（用于LLM分组）
        use_llm_grouping: 是否使用LLM进行目录分组
        model: LLM模型名称

    Returns:
        (tree, completeness_info)
    """
    # stage=clean: 清洗
    preserve_unpaged = _should_preserve_unpaged_toc_skeleton(analysis)
    toc_pages = _toc_pages_from_analysis(analysis)
    provisional_start_page = max(toc_pages or [0]) + 1
    provisional_start_page = max(1, min(page_count, provisional_start_page))
    items = clean_toc_items(
        toc_items,
        page_count=page_count,
        preserve_unpaged=preserve_unpaged,
        provisional_start_page=provisional_start_page,
    )
    if not items:
        print("[TOC-POST] No valid items after cleaning")
        items = [{"structure": "1", "title": "Document Content", "physical_index": 1}]

    top_level_frozen = bool(
        analysis
        and (
            analysis.get("top_level_frozen")
            or analysis.get("toc_frozen")
            or (analysis.get("build_state") or {}).get("top_level_frozen")
        )
    )
    explicit_toc_frozen = bool(analysis and analysis.get("toc_frozen"))
    if explicit_toc_frozen and not (
        analysis.get("toc_semi_frozen")
        or analysis.get("allow_child_expansion") is True
    ):
        allow_child_expansion = False
    else:
        allow_child_expansion = bool(
            not analysis
            or analysis.get(
                "allow_child_expansion",
                (analysis.get("build_state") or {}).get("allow_child_expansion", True),
            )
        )
    frozen_source = (
        (analysis.get("build_state") or {}).get("top_level_source")
        if analysis
        else None
    ) or (analysis.get("toc_frozen_source") if analysis else None)

    is_slide_outline = bool(frozen_source in {"slide_outline", "agenda_outline"})
    if not is_slide_outline:
        try:
            from pageindex.text_heading_extractor import repair_numbered_structures
            items = repair_numbered_structures(items)
        except Exception:
            pass

    semi_frozen = bool(
        analysis
        and (
            analysis.get("toc_semi_frozen")
            or (top_level_frozen and allow_child_expansion)
        )
    )
    text_rich_protected = bool(
        analysis
        and (
            top_level_frozen
            or semi_frozen
            or frozen_source in {"text_heading", "agenda_outline"}
            or analysis.get("text_coverage", 0) >= 0.8
        )
    )

    # stage=filter: 过滤图录/表录节点
    items, _ = filter_figure_catalogs(items)
    if not items:
        print("[TOC-POST] No valid items after filtering figure catalogs")
        items = [{"structure": "1", "title": "Document Content", "physical_index": 1}]

    # stage=refine: P3 Unified Refinement (dividers-based)
    if dividers and not text_rich_protected:
        items = refine_toc_with_dividers(items, dividers, page_count)

    # stage=rebuild: 基于divider重建层级structure（修复候选 TOC 平铺结构）
    if dividers and len(dividers) >= 2 and not text_rich_protected:
        items = rebuild_structure_by_dividers(items, dividers, page_count)

    # stage=validate: 边界校验
    items = validate_indices(items, page_count)
    if not items:
        print("[TOC-POST] No valid items after validation")
        items = [{"structure": "1", "title": "Document Content", "physical_index": 1}]

    # stage=preface: 补充 Preface
    items = _ensure_level_structures(items)

    multi_catalog_tree = _build_multi_catalog_tree_if_present(items, page_count)
    if multi_catalog_tree:
        tree = multi_catalog_tree
        fix_parent_ranges(tree)
        tree = normalize_tree_page_ranges(tree, page_count)
        completeness = check_completeness(tree, page_count)
        print(
            f"[TOC-POST] status=done {len(items)} items → tree with {len(tree)} top-level groups, "
            f"coverage={completeness['coverage']:.0%}"
        )
        return tree, completeness

    items = add_preface(items)

    # stage=range: 设置页面范围
    items = assign_page_ranges(items, page_count)

    # stage=tree: 构建树
    tree = build_tree(items)
    
    # stage=tree: 移除空结构的合成根节点，提升直接子节点
    def remove_synthetic_roots(nodes):
        result = []
        for node in nodes:
            if node.get("structure") == "" and "Chapter at page" in node.get("title", ""):
                # 提升直接子节点到当前层级
                children = node.get("nodes", [])
                if children:
                    print(f"[TOC-POST] Removed synthetic root '{node['title']}', promoted {len(children)} children")
                    # 递归处理子节点（它们可能也是合成根节点）
                    result.extend(remove_synthetic_roots(children))
                else:
                    print(f"[TOC-POST] Removed synthetic root '{node['title']}' (no children)")
            else:
                # 保留节点，但递归处理其子节点
                if node.get("nodes"):
                    node["nodes"] = remove_synthetic_roots(node["nodes"])
                result.append(node)
        return result
    
    tree = remove_synthetic_roots(tree)
    
    # stage=tree: 移除所有"Chapter at page"合成节点
    def remove_all_synthetic_nodes(nodes):
        result = []
        for node in nodes:
            if "Chapter at page" in node.get("title", ""):
                # 移除合成节点，但保留其子节点
                children = node.get("nodes", [])
                if children:
                    print(f"[TOC-POST] Removed synthetic chapter '{node['title']}', promoted {len(children)} children")
                    result.extend(remove_all_synthetic_nodes(children))
                else:
                    print(f"[TOC-POST] Removed synthetic chapter '{node['title']}' (no children)")
            else:
                # 保留节点，但递归处理其子节点
                if node.get("nodes"):
                    node["nodes"] = remove_all_synthetic_nodes(node["nodes"])
                result.append(node)
        return result
    
    tree = remove_all_synthetic_nodes(tree)
    
    # stage=tree: 使用structure重建正确的父子关系
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

    # stage=repair: 修复父节点范围
    fix_parent_ranges(tree)
    tree = normalize_tree_page_ranges(tree, page_count)

    # stage=group: LLM 目录分组（新架构）
    toc_frozen = top_level_frozen and not allow_child_expansion
    if toc_frozen:
        tree = _group_frozen_case_catalogs(tree)
        print("[TOC-POST] TOC frozen, skipping LLM catalog grouping")
    elif semi_frozen:
        print("[TOC-POST] TOC semi-frozen, skipping LLM catalog grouping")
    elif use_llm_grouping and analysis and analysis.get("toc_page", {}).get("has_toc_page"):
        try:
            print("[TOC-POST] action=llm_catalog_grouping status=started")
            grouped_result = _llm_group_catalogs(tree, analysis, page_count, model)
            if grouped_result:
                if _grouping_preserves_toc(tree, grouped_result):
                    print(f"[TOC-POST] action=llm_catalog_grouping status=ok groups={len(grouped_result)}")
                    tree = grouped_result
                else:
                    print("[TOC-POST] action=llm_catalog_grouping status=rejected fallback=original_tree")
            else:
                print("[TOC-POST] action=llm_catalog_grouping status=empty fallback=single_tree")
                tree = _build_single_tree(tree, page_count)
        except Exception as e:
            print(f"[TOC-POST] action=llm_catalog_grouping status=error error={e} fallback=single_tree")
            tree = _build_single_tree(tree, page_count)
    elif use_llm_grouping:
        # 没有TOC页，但有divider且树结构良好（多个顶级节点），保持现有结构
        if dividers and len(tree) > 1:
            print(f"[TOC-POST] No TOC page but has {len(dividers)} dividers and {len(tree)} top-level nodes, keeping tree structure")
        else:
            # 没有TOC页且树结构扁平，降级为单一目录树
            print("[TOC-POST] No TOC page detected, using single tree")
            tree = _build_single_tree(tree, page_count)

    tree = promote_single_catalog_root(tree, page_count)
    tree = repair_case_continuation_roots(tree)
    tree = repair_placeholder_chapter_titles(tree)

    # stage=quality: 完整性检查
    completeness = check_completeness(tree, page_count)

    print(
        f"[TOC-POST] status=done {len(items)} items → tree with {len(tree)} top-level groups, "
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
        source: TOC 来源 (bookmarks/regex/ocr/text)
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
    if source in {"text_heading", "slide_outline", "agenda_outline"}:
        completeness = check_completeness(tree, page_count)
        child_count = sum(1 for node in tree if node.get("nodes"))
        large_leaf_nodes = [
            {
                "title": node.get("title", ""),
                "span": (node.get("end_index") or 0) - (node.get("start_index") or 0) + 1,
                "issue": "missing_children",
            }
            for node in tree
            if not node.get("nodes")
            and isinstance(node.get("start_index"), int)
            and isinstance(node.get("end_index"), int)
            and (node.get("end_index") - node.get("start_index") + 1) > 20
        ]
        if completeness.get("ok") and child_count > 0 and not large_leaf_nodes:
            print(f"[TOC-QUALITY] provider=llm_qc {source} structure accepted locally")
            return {
                "structure_score": 90,
                "large_nodes": [],
                "missing_chapters": [],
                "overall_score": 90,
                "suggestions": [],
                "needs_repair": False,
            }

    try:
        from pageindex.json_utils import parse_llm_json
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
    
    try:
        from pageindex.index_quality import build_toc_fidelity_digest

        fidelity_digest = build_toc_fidelity_digest(
            {"structure": tree, "page_count": page_count},
            page_count=page_count,
        )
    except Exception:
        fidelity_digest = {
            "detected_style": "unknown",
            "hard_fail_reasons": [],
            "warnings": [],
        }

    prompt = TOC_QUALITY_CHECK_PROMPT.format(
        page_count=page_count,
        source=source,
        has_dividers="yes" if has_dividers else "no",
        divider_count=divider_count,
        toc_tree_formatted=toc_tree_formatted,
        toc_items_formatted=toc_items_formatted,
        fidelity_digest_json=json.dumps(fidelity_digest, ensure_ascii=False, indent=2),
    )
    
    try:
        response = await ChatGPT_API_async(model=model or "qwen3.6-flash", prompt=prompt)
        result = parse_llm_json(response)
        
        if isinstance(result, dict):
            verdict = str(result.get("verdict") or "").strip().lower()
            if verdict == "fail":
                result["needs_repair"] = True
            elif verdict == "pass" and "needs_repair" not in result:
                result["needs_repair"] = False
            print(f"[TOC-QUALITY] provider=llm_qc Quality check: overall_score={result.get('overall_score', 'N/A')}, "
                  f"needs_repair={result.get('needs_repair', False)}")
            if result.get("needs_repair"):
                print(f"[TOC-QUALITY] provider=llm_qc Suggestions: {result.get('suggestions', [])}")
            return result
    except Exception as e:
        print(f"[TOC-QUALITY] provider=llm_qc Failed: {e}")
    
    # 失败时返回默认结果
    return {
        "structure_score": 50,
        "large_nodes": [],
        "missing_chapters": [],
        "overall_score": 50,
        "suggestions": [],
        "needs_repair": False,
    }
