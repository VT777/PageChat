"""TOC页提取路径 — 从文档目录页直接提取结构化目录。

coordinate 改进：
- 主路径：PyMuPDF 坐标提取 + LLM智能分组（高质量、处理分行问题）
- Fallback：旧正则提取（兼容性）
- 质量检查：不过关自动降级（返回 None），由调用方处理

适用场景: 文档有明确的目录页（如"目录"、"Contents"页）
优势: 坐标提取更准确，LLM分组智能，能处理"表1"/"图1"分行问题
局限: 依赖目录页格式规范，无法处理无目录页的文档
"""

import json
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

# 质量阈值
MIN_ITEMS_COUNT = 3
MIN_PAGE_COVERAGE_RATIO = 0.3
MIN_CONFIDENCE = 0.5


# ---------------------------------------------------------------------------
# TOC行解析模式（旧正则，作为 fallback）
# ---------------------------------------------------------------------------

# 模式1: "第X章 标题 ................ 5"
_CHAPTER_PATTERN = re.compile(
    r'^(?:第([一二三四五六七八九十百零〇两\d]+)[章节部分篇][:：\s]*)?'
    r'(.{2,80}?)'
    r'[\.\s\.\u00b7\u2026]{2,}(\d{1,4})\s*$',
    re.MULTILINE
)

# 模式2: "1.1 标题 ............... 5"
_NUMBERED_PATTERN = re.compile(
    r'^(\d{1,2}(?:\.\d{1,2}){0,3})\s+'
    r'(.{2,80}?)'
    r'[\.\s\.\u00b7\u2026]{2,}(\d{1,4})\s*$',
    re.MULTILINE
)

# 模式3: "一、标题 ............... 5"
_CHINESE_NUMBER_PATTERN = re.compile(
    r'^([一二三四五六七八九十]+)[、．.]\s*'
    r'(.{2,80}?)'
    r'[\.\s\.\u00b7\u2026]{2,}(\d{1,4})\s*$',
    re.MULTILINE
)

# 模式4: "(一) 标题 ............... 5"
_PAREN_NUMBER_PATTERN = re.compile(
    r'^[(（]([一二三四五六七八九十\d]+)[)）]\s*'
    r'(.{2,80}?)'
    r'[\.\s\.\u00b7\u2026]{2,}(\d{1,4})\s*$',
    re.MULTILINE
)

# 模式5: "Chapter 1 标题 ............... 5"
_ENGLISH_CHAPTER_PATTERN = re.compile(
    r'^(?:Chapter|Section|Part)\s+(\d+|[IVX]+)[:：\s]*'
    r'(.{2,80}?)'
    r'[\.\s\.\u00b7\u2026]{2,}(\d{1,4})\s*$',
    re.MULTILINE | re.IGNORECASE
)

_ALL_PATTERNS = [
    ("numbered", _NUMBERED_PATTERN),
    ("chapter", _CHAPTER_PATTERN),
    ("chinese_number", _CHINESE_NUMBER_PATTERN),
    ("paren_number", _PAREN_NUMBER_PATTERN),
    ("english", _ENGLISH_CHAPTER_PATTERN),
]


def normalize_toc_entries(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize TOC entries to the canonical structure/title/page/physical_index shape."""
    counters: List[int] = []

    def normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal counters

        if item.get("page_type") == "catalog_group":
            return {
                **item,
                "nodes": normalize_toc_entries(item.get("nodes", [])),
            }

        structure = item.get("structure")
        level = int(item.get("level") or 1)
        if not structure:
            while len(counters) < level:
                counters.append(0)
            counters = counters[:level]
            counters[level - 1] += 1
            structure = ".".join(str(part) for part in counters)

        normalized = {
            "structure": str(structure),
            "title": item.get("title", "").strip(),
            "page": item.get("page"),
            "physical_index": item.get("physical_index"),
        }
        if item.get("nodes"):
            normalized["nodes"] = normalize_toc_entries(item["nodes"])
        return normalized

    return [normalize_item(item) for item in items]


def extract_main_chapters(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract top-level chapters without relying only on dotted numeric structure."""
    main_chapters = []
    for item in items:
        structure = str(item.get("structure") or "").strip()
        title = item.get("title", "").strip()
        if re.fullmatch(r"\d+", structure):
            main_chapters.append(item)
        elif re.fullmatch(r"[一二三四五六七八九十百]+", structure):
            main_chapters.append(item)
        elif re.search(r"\b(Part|Chapter)\s*\d+\b", structure, re.IGNORECASE):
            main_chapters.append(item)
        elif re.match(r"第[一二三四五六七八九十百\d]+章", title):
            main_chapters.append(item)
    return main_chapters


# ---------------------------------------------------------------------------
# LLM 分组 Prompt
# ---------------------------------------------------------------------------

CATALOG_GROUPING_PROMPT = """You are a PDF table-of-contents analyst. Analyze the ordered list of TOC entries below and identify how many independent catalog groups it contains.

Entries, in original order:
{entries_text}

Requirements:
1. Identify each entry group's type, such as chapter catalog, table catalog, or figure catalog.
2. Return each group's start and end entry numbers. Entry numbers are 1-based positions in the list, not PDF page numbers.
3. A group is usually a contiguous run of entries of the same catalog type.
4. Cover every entry exactly once. Do not leave gaps or overlaps.

Return JSON only:
{{
  "groups": [
    {{
      "title": "Contents",
      "type": "chapter_catalog",
      "entry_start": 1,
      "entry_end": 22
    }}
  ],
  "reasoning": "brief grouping rationale"
}}

Allowed type values: chapter_catalog, table_catalog, figure_catalog.
If there is only one group, return one object in the groups array.
"""


# ===========================================================================
# 主入口函数
# ===========================================================================

def extract_toc_from_pages(
    doc_path: str,
    toc_page_indices: List[int],
    doc_page_count: int = 0,
    model: Optional[str] = None,
    page_texts: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """从目录页提取结构化目录（coordinate 坐标提取 + fallback）。

    Args:
        doc_path: PDF文件路径
        toc_page_indices: 目录页索引列表（0-indexed）
        doc_page_count: 文档总页数
        model: LLM模型（用于分组，默认qwen3.6-flash）
        page_texts: 可选，页面文本列表（用于fallback正则提取）

    Returns:
        {
            "items": List[Dict],
            "structure": "flat" | "hierarchical",
            "source": "toc_page",
            "confidence": float,
            "toc_page_indices": List[int],
            "extraction_method": "coordinate" | "regex",  # 记录实际使用的方法
        }
        提取失败或质量不过关返回 None（由调用方降级处理）
    """
    if not toc_page_indices:
        return None

    model = model or "qwen3.6-flash"

    # === 主路径：coordinate 坐标提取 ===
    try:
        print("[TOC-CANDIDATE] provider=toc_page action=coordinate_extract status=started")
        result = _extract_toc_coordinate(doc_path, toc_page_indices, doc_page_count, model, page_texts)
        if result and _check_quality(result, doc_page_count):
            result["items"] = normalize_toc_entries(result.get("items", []))
            print(f"[TOC-CANDIDATE] provider=toc_page action=coordinate_extract status=ok items={len(result['items'])}")
            result["extraction_method"] = "coordinate"
            return result
        elif result:
            print(f"[TOC-CANDIDATE] provider=toc_page action=coordinate_extract status=low_quality fallback=regex")
        else:
            print("[TOC-CANDIDATE] provider=toc_page action=coordinate_extract status=empty fallback=regex")
    except Exception as e:
        print(f"[TOC-CANDIDATE] provider=toc_page action=coordinate_extract status=error error={e} fallback=regex")

    # === Fallback：旧正则提取 ===
    if page_texts:
        try:
            print("[TOC-CANDIDATE] provider=toc_page action=regex_extract status=started")
            result = _extract_toc_regex(page_texts, toc_page_indices, doc_page_count)
            if result and _check_quality(result, doc_page_count):
                result["items"] = normalize_toc_entries(result.get("items", []))
                print(f"[TOC-CANDIDATE] provider=toc_page action=regex_extract status=ok items={len(result['items'])}")
                result["extraction_method"] = "regex"
                return result
            elif result:
                print(f"[TOC-CANDIDATE] provider=toc_page action=regex_extract status=low_quality")
            else:
                print("[TOC-CANDIDATE] provider=toc_page action=regex_extract status=empty")
        except Exception as e:
            print(f"[TOC-CANDIDATE] provider=toc_page action=regex_extract status=error error={e}")

    # 所有方法都失败或质量不过关 → 返回 None（降级标记）
    print("[TOC-CANDIDATE] provider=toc_page action=extract status=rejected reason=no_quality_candidate")
    return None


# ===========================================================================
# coordinate 坐标提取核心
# ===========================================================================

def _extract_toc_coordinate(
    doc_path: str,
    toc_page_indices: List[int],
    doc_page_count: int,
    model: str,
    page_texts: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """coordinate 坐标提取主逻辑。"""
    import fitz

    doc = fitz.open(doc_path)
    all_entries = []

    try:
        for page_idx in toc_page_indices:
            page = doc[page_idx]
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if "lines" not in block:
                    continue

                # 合并同一 block 中相同 y0 的 line
                merged_lines = _merge_lines_by_y(block["lines"])

                for line_text, x0, y0, font_size in merged_lines:
                    if not line_text.strip():
                        continue

                    # 跳过目录页标题
                    if _is_toc_header(line_text):
                        continue

                    # 提取页码和标题
                    title, page_num = _split_title_and_pagenum(line_text)
                    if title is None:
                        continue

                    # 识别编号模式
                    structure = _infer_structure_from_title(title)

                    all_entries.append({
                        "title": title,
                        "physical_index": page_num,
                        "x0": x0,
                        "y0": y0,
                        "font_size": font_size,
                        "structure": structure,
                        "source_page": page_idx + 1,
                    })
    finally:
        doc.close()

    if len(all_entries) < MIN_ITEMS_COUNT:
        return None

    # 后处理：推断缺失的页码
    all_entries = _infer_missing_pages(all_entries)

    # 计算并应用页码偏移量（逻辑页码 → 物理页码）
    offset = _calculate_offset(all_entries, page_texts, toc_page_indices)
    if offset != 0:
        _apply_offset(all_entries, offset)
        print(f"[TOC-MAPPING] provider=toc_page action=apply_offset offset={offset:+d}")

    # 智能层级推断
    entries_with_level = _infer_hierarchy_smart(all_entries)

    # LLM智能分组
    groups = _llm_group_entries(entries_with_level, model)

    # 按分组构建树结构
    tree = _build_tree_by_groups(entries_with_level, groups)

    # 转换为生产代码格式
    items = _convert_tree_to_items(tree)

    # 计算置信度
    confidence = _calculate_confidence(items, doc_page_count)

    return {
        "items": items,
        "structure": "hierarchical" if _has_hierarchy(items) else "flat",
        "source": "toc_page",
        "confidence": confidence,
        "toc_page_indices": toc_page_indices,
    }


def _merge_lines_by_y(lines: List[Dict]) -> List[Tuple[str, float, float, float]]:
    """合并相同 y0（y坐标）的 line，处理表/图编号与标题分开展示。"""
    if not lines:
        return []

    y_groups = {}
    for line in lines:
        text = ""
        for span in line["spans"]:
            text += span["text"]
        text = text.strip()
        if not text:
            continue

        bbox = line["bbox"]
        y0 = round(bbox[1], 1)
        x0 = bbox[0]
        font_size = line["spans"][0]["size"] if line["spans"] else 12

        if y0 not in y_groups:
            y_groups[y0] = []
        y_groups[y0].append({"text": text, "x0": x0, "font_size": font_size})

    result = []
    for y0 in sorted(y_groups.keys()):
        group = sorted(y_groups[y0], key=lambda x: x["x0"])
        merged_text = " ".join(item["text"] for item in group)
        min_x0 = group[0]["x0"]
        font_size = group[0]["font_size"]
        result.append((merged_text, min_x0, y0, font_size))

    return result


def _is_toc_header(text: str) -> bool:
    """判断是否为目录页标题。"""
    if text in ["目", "录", "表", "图"]:
        return True

    headers = [
        "目录", "表目录", "图目录", "contents", "table of contents",
        "list of figures", "list of tables", "目次", "插图目录", "表格目录"
    ]
    text_clean = text.strip().lower().replace(" ", "").replace("\u3000", "")
    return text_clean in [h.replace(" ", "") for h in headers]


def _split_title_and_pagenum(text: str) -> Tuple[Optional[str], Optional[int]]:
    """从行尾分离页码。"""
    text = text.strip()

    patterns = [
        r'^(.*?)[\.\s\u00b7\u2026\uff0e]{2,}(\d{1,4})$',
        r'^(.*?)\s+(\d{1,4})$',
    ]

    for pat in patterns:
        m = re.match(pat, text)
        if m:
            title = m.group(1).strip()
            pagenum = int(m.group(2))
            if 1 <= pagenum <= 5000 and title:
                return title, pagenum

    if re.match(r'^\d{1,4}$', text):
        return None, int(text)

    return text, None


def _calculate_offset(entries: List[Dict], page_texts: List[str], toc_page_indices: List[int]) -> int:
    """计算页码偏移量（物理页码 - 逻辑页码）。
    
    策略：
    1. 取第一个条目的逻辑页码（如 p.1）
    2. 从目录页之后的页面开始搜索
    3. 找到第一个带有章节标题特征的页面
    4. offset = 该物理页码 - 逻辑页码
    
    更可靠的策略：
    - 目录页通常在文档前面（如第7-9页）
    - 目录之后的页面（如第10页）通常是正文开始
    - 正文第一页通常包含第一个章节的标题
    - 所以：offset = (目录最后一页 + 1) - 第一个条目的逻辑页码
    """
    if not entries or not page_texts or not toc_page_indices:
        return 0
    
    # 找到第一个有有效页码的条目
    first_item = None
    for entry in entries:
        if entry.get("physical_index") and entry.get("title"):
            first_item = entry
            break
    
    if not first_item:
        return 0
    
    logical_page = first_item["physical_index"]
    title = first_item["title"]
    
    # 目录最后一页的下一个页面通常是正文开始
    last_toc_page = max(toc_page_indices)  # 0-indexed
    first_content_page = last_toc_page + 1  # 0-indexed
    
    # 如果第一个条目的逻辑页码是1，且目录后面有页面
    if logical_page == 1 and first_content_page < len(page_texts):
        # 尝试在目录后几页搜索第一个章节标题
        search_end = min(len(page_texts), first_content_page + 5)
        
        for page_idx in range(first_content_page, search_end):
            page_text = page_texts[page_idx] or ""
            # 搜索标题（前20个字符）
            if title[:20] in page_text:
                physical_page = page_idx + 1  # 转 1-indexed
                offset = physical_page - logical_page
                print(f"[TOC-MAPPING] provider=toc_page action=title_match status=exact title='{title[:30]}' physical_page={physical_page} offset={offset:+d}")
                return offset
            
            # 模糊搜索
            title_clean = title[:20].replace(" ", "").replace("\u3000", "")
            page_clean = page_text.replace(" ", "").replace("\u3000", "")
            if title_clean in page_clean:
                physical_page = page_idx + 1
                offset = physical_page - logical_page
                print(f"[TOC-MAPPING] provider=toc_page action=title_match status=fuzzy title= '{title[:30]}' physical_page={physical_page} offset={offset:+d}")
                return offset
    
    # 如果搜索失败，使用基于目录页位置的估算
    # 通常 offset ≈ 目录最后一页的页码
    estimated_offset = last_toc_page + 1 - logical_page
    if estimated_offset > 0:
        print(f"[TOC-MAPPING] provider=toc_page action=estimate_offset reason=toc_position offset={estimated_offset:+d}")
        return estimated_offset
    
    print(f"[TOC-MAPPING] provider=toc_page action=estimate_offset status=failed offset=0")
    return 0


def _apply_offset(entries: List[Dict], offset: int) -> None:
    """应用偏移量到所有条目。"""
    if offset == 0:
        return
    
    for entry in entries:
        if entry.get("physical_index") is not None:
            entry["physical_index"] += offset


def _is_unpaged_toc_candidate(title: str) -> bool:
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"\d{1,4}\s*/\s*\d{1,4}", text):
        return False
    lower = text.lower()
    footer_markers = (
        "important disclosure",
        "important disclosures",
        "final rating",
        "read final",
        "\u8bf7\u9605\u8bfb",
        "\u91cd\u8981\u58f0\u660e",
        "\u8bc4\u7ea7\u8bf4\u660e",
    )
    if any(marker in lower or marker in text for marker in footer_markers):
        return False
    if "|" in text and len(compact) <= 24:
        return False
    if re.fullmatch(r"[A-Za-z\u4e00-\u9fff]{1,12}", compact):
        return False
    if re.match(r"^(?:\d+(?:\.\d+)*|[A-Za-z]?\d+)[\s\u3001,\.\uff0c\uff0e-]", text):
        return True
    if re.match(r"^(?:figure|table)\s*\d+", lower):
        return True
    if re.match(r"^[\u56fe\u8868]\s*\d+", text):
        return True
    if re.search(r"[\.\u2026]{3,}$", text):
        return True
    return False


def _infer_missing_pages(entries: List[Dict]) -> List[Dict]:
    """Infer missing page numbers only for rows that look like TOC entries."""
    entries_sorted = sorted(
        [entry for entry in entries if entry.get("physical_index") is not None or _is_unpaged_toc_candidate(entry.get("title", ""))],
        key=lambda e: (e["source_page"], e["y0"]),
    )

    for i, entry in enumerate(entries_sorted):
        if entry["physical_index"] is not None:
            continue

        prev_page = None
        next_page = None

        for j in range(i - 1, -1, -1):
            if entries_sorted[j]["physical_index"] is not None:
                prev_page = entries_sorted[j]["physical_index"]
                break

        for j in range(i + 1, len(entries_sorted)):
            if entries_sorted[j]["physical_index"] is not None:
                next_page = entries_sorted[j]["physical_index"]
                break

        if prev_page is not None:
            entry["physical_index"] = prev_page
        elif next_page is not None:
            entry["physical_index"] = next_page

    return entries_sorted


def _infer_structure_from_title(title: str) -> str:
    """从标题推断结构编号。"""
    title = title.strip()

    m = re.match(r'^第([一二三四五六七八九十百零〇两\d]+)[章节部分篇]', title)
    if m:
        return m.group(1)

    m = re.match(r'^(\d+(?:\.\d+)*)', title)
    if m:
        return m.group(1)

    m = re.match(r'^([一二三四五六七八九十]+)[、．.]', title)
    if m:
        return m.group(1)

    m = re.match(r'^[（(]([一二三四五六七八九十\d]+)[）)]', title)
    if m:
        return m.group(1)

    m = re.match(r'^(图|表|Figure|Table)\s*(\d+)', title, re.IGNORECASE)
    if m:
        return f"{m.group(1)}{m.group(2)}"

    return ""


def _infer_hierarchy_smart(entries: List[Dict]) -> List[Dict]:
    """智能层级推断（基于 x0 缩进 + structure）。"""
    if not entries:
        return []

    for entry in entries:
        title = entry["title"]
        structure = entry["structure"]

        if not structure:
            if entry["x0"] < 100:
                entry["level"] = 1
            elif entry["x0"] < 120:
                entry["level"] = 2
            else:
                entry["level"] = 3
        elif re.match(r'^第', title):
            entry["level"] = 1
        elif re.match(r'^[一二三四五六七八九十]+[、．.]', title):
            entry["level"] = 2
        elif re.match(r'^[（(]', title):
            entry["level"] = 3
        elif '.' in structure:
            entry["level"] = structure.count('.') + 1
        else:
            entry["level"] = 1

    return entries


# ===========================================================================
# LLM 分组
# ===========================================================================

def _format_entries_for_llm(entries: List[Dict]) -> str:
    """将条目格式化为LLM可读的文本。"""
    lines = []
    for i, entry in enumerate(entries, 1):
        title = entry["title"]
        page = entry.get("physical_index") or "?"
        lines.append(f"{i}. {title} (p.{page})")
    return "\n".join(lines)


def _extract_json_from_response(response: str) -> str:
    """从LLM响应中提取JSON。"""
    if not response:
        return ""

    response = response.strip()

    if "```json" in response:
        parts = response.split("```json")
        if len(parts) > 1:
            return parts[1].split("```")[0].strip()
    elif "```" in response:
        parts = response.split("```")
        if len(parts) > 1:
            return parts[1].strip()

    try:
        start = response.index("{")
        end = response.rindex("}") + 1
        return response[start:end]
    except ValueError:
        pass

    return response


def _validate_groups(groups: List[Dict], total_entries: int) -> bool:
    """校验LLM返回的分组是否合法。"""
    groups = _normalize_group_ranges(groups)
    if not groups:
        return False

    covered = set()
    for g in groups:
        start = g.get("entry_start", 0)
        end = g.get("entry_end", 0)
        if start < 1 or end > total_entries or start > end:
            print(f"[TOC-GROUP] provider=toc_page Invalid range: {start}-{end} (total={total_entries})")
            return False
        for i in range(start, end + 1):
            if i in covered:
                print(f"[TOC-GROUP] provider=toc_page Overlap at index {i}")
                return False
            covered.add(i)

    if len(covered) != total_entries:
        print(f"[TOC-GROUP] provider=toc_page Not all entries covered: {len(covered)}/{total_entries}")
        return False

    return True


def _normalize_group_ranges(groups: List[Dict]) -> List[Dict]:
    """Normalize LLM grouping item ranges away from page range field names."""
    normalized = []
    for group in groups or []:
        item = dict(group)
        entry_start = item.pop("entry_start", None)
        entry_end = item.pop("entry_end", None)
        fallback_start = item.pop("start_index", None)
        fallback_end = item.pop("end_index", None)
        item["entry_start"] = entry_start if entry_start is not None else fallback_start
        item["entry_end"] = entry_end if entry_end is not None else fallback_end
        normalized.append(item)
    return normalized


def _fallback_grouping(entries: List[Dict]) -> List[Dict]:
    """LLM分组失败时的回退：所有条目作为一组。"""
    return [{
        "title": "目录",
        "type": "chapter_catalog",
        "entry_start": 1,
        "entry_end": len(entries)
    }]


def _llm_group_entries(entries: List[Dict], model: str) -> List[Dict]:
    """调用LLM进行目录分组。"""
    if not entries:
        return []

    print(f"[TOC-GROUP] provider=toc_page action=llm_group status=started entries={len(entries)}")

    try:
        from pageindex.utils import llm_completion

        entries_text = _format_entries_for_llm(entries)
        prompt = CATALOG_GROUPING_PROMPT.format(entries_text=entries_text)

        response = llm_completion(model, prompt)
        if not response:
            print("[TOC-GROUP] provider=toc_page action=llm_group status=empty fallback=single_group")
            return _fallback_grouping(entries)

        json_str = _extract_json_from_response(response)
        data = json.loads(json_str)
        groups = data.get("groups", [])
        groups = _normalize_group_ranges(groups)

        if _validate_groups(groups, len(entries)):
            print(f"[TOC-GROUP] provider=toc_page action=llm_group status=ok groups={len(groups)}")
            for g in groups:
                print(f"  - {g['title']}: items {g['entry_start']}-{g['entry_end']}")
            return groups
        else:
            print("[TOC-GROUP] provider=toc_page action=llm_group status=rejected fallback=single_group")
            return _fallback_grouping(entries)

    except Exception as e:
        print(f"[TOC-GROUP] provider=toc_page action=llm_group status=error error={e}")
        return _fallback_grouping(entries)


# ===========================================================================
# 树构建与格式转换
# ===========================================================================

def _build_tree_by_groups(entries: List[Dict], groups: List[Dict]) -> List[Dict]:
    """按LLM分组结果分别建树。"""
    if not entries or not groups:
        return []

    result = []
    for group in groups:
        normalized_group = _normalize_group_ranges([group])[0]
        start = normalized_group["entry_start"] - 1
        end = normalized_group["entry_end"]
        subset = entries[start:end]

        if not subset:
            continue

        subtree = _build_subtree(subset)

        result.append({
            "title": normalized_group["title"],
            "page_type": "catalog_group",
            "children": subtree,
        })

    return result


def _build_subtree(entries: List[Dict]) -> List[Dict]:
    """构建子树（栈算法）。"""
    root = []
    stack = []

    for entry in entries:
        level = entry.get("level", 1)

        node = {
            "title": entry["title"],
            "physical_index": entry.get("physical_index"),
            "structure": entry.get("structure", ""),
            "level": level,
            "nodes": [],
        }

        while stack and stack[-1]["level"] >= level:
            stack.pop()

        if stack:
            stack[-1]["nodes"].append(node)
        else:
            root.append(node)

        stack.append(node)

    return root


def _convert_tree_to_items(tree: List[Dict]) -> List[Dict]:
    """将分组树转换为生产代码的 items 格式，保留 catalog_group 分组结构。"""
    items = []
    
    def convert_node(node: Dict) -> Dict:
        """递归转换单个节点。"""
        item = {
            "title": node["title"],
            "structure": node.get("structure", ""),
            "physical_index": node.get("physical_index"),
            "nodes": [],
        }
        
        # 递归处理子节点
        children = node.get("children", node.get("nodes", []))
        if children:
            item["nodes"] = [convert_node(child) for child in children]
        
        return item
    
    # 保留分组节点结构
    for group in tree:
        group_item = {
            "title": group["title"],
            "page_type": "catalog_group",
            "structure": "",
            "physical_index": None,
            "nodes": [],
        }
        
        # 将分组的子节点放入 nodes
        children = group.get("children", group.get("nodes", []))
        for child in children:
            group_item["nodes"].append(convert_node(child))
        
        items.append(group_item)
    
    return items


# ===========================================================================
# 旧正则提取（Fallback）
# ===========================================================================

def _extract_toc_regex(
    page_texts: List[str],
    toc_page_indices: List[int],
    doc_page_count: int = 0
) -> Optional[Dict[str, Any]]:
    """旧正则提取逻辑（fallback）。"""
    if not toc_page_indices or not page_texts:
        return None

    # 合并所有目录页文本
    toc_text = ""
    for idx in toc_page_indices:
        if 0 <= idx < len(page_texts):
            toc_text += page_texts[idx] + "\n"

    if not toc_text.strip():
        return None

    # 预处理
    toc_text = _preprocess_toc_text(toc_text)

    # 提取所有条目
    all_items = _extract_all_entries_regex(toc_text, doc_page_count)

    if len(all_items) < 3:
        return None

    # 构建层次结构
    structured_items = _build_hierarchy_regex(all_items)

    # 计算置信度
    confidence = _calculate_confidence_regex(all_items, structured_items, doc_page_count)

    return {
        "items": structured_items,
        "structure": "hierarchical" if _has_hierarchy(structured_items) else "flat",
        "source": "toc_page",
        "confidence": confidence,
        "toc_page_indices": toc_page_indices,
    }


def _preprocess_toc_text(text: str) -> str:
    """预处理目录文本。"""
    text = re.sub(r'[\.\u00b7\u2026]{2,}', '....', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'^(目录|Contents|目次|目 录)\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
    return text


def _extract_all_entries_regex(toc_text: str, doc_page_count: int) -> List[Dict]:
    """正则提取所有条目。"""
    items = []
    seen = set()

    for pattern_name, pattern in _ALL_PATTERNS:
        for match in pattern.finditer(toc_text):
            if pattern_name == "chapter":
                prefix = match.group(1) or ""
                title = match.group(2).strip()
                page = match.group(3)
            elif pattern_name == "numbered":
                prefix = match.group(1)
                title = match.group(2).strip()
                page = match.group(3)
            elif pattern_name == "chinese_number":
                prefix = match.group(1)
                title = match.group(2).strip()
                page = match.group(3)
            elif pattern_name == "paren_number":
                prefix = match.group(1)
                title = match.group(2).strip()
                page = match.group(3)
            elif pattern_name == "english":
                prefix = match.group(1)
                title = match.group(2).strip()
                page = match.group(3)
            else:
                continue

            if not title or not page.isdigit():
                continue

            page_num = int(page)
            if page_num <= 0:
                continue
            if doc_page_count > 0 and page_num > doc_page_count:
                continue

            structure = _infer_structure_old(prefix, pattern_name)

            key = f"{structure}:{title}:{page_num}"
            if key in seen:
                continue
            seen.add(key)

            items.append({
                "title": title,
                "structure": structure,
                "physical_index": page_num,
            })

    items.sort(key=lambda x: (x["physical_index"], x["structure"] or ""))
    return items


def _infer_structure_old(prefix: str, pattern_type: str) -> str:
    """旧版结构推断。"""
    if not prefix:
        return ""

    if re.match(r'^\d+(?:\.\d+)*$', prefix):
        return prefix

    chinese_nums = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
        '零': 0, '〇': 0, '两': 2,
    }

    if pattern_type == "chinese_number":
        num = chinese_nums.get(prefix, 0)
        return str(num) if num > 0 else ""

    if pattern_type == "paren_number":
        if prefix.isdigit():
            return prefix
        num = chinese_nums.get(prefix, 0)
        return str(num) if num > 0 else ""

    if pattern_type == "chapter":
        if prefix.isdigit():
            return prefix
        num = chinese_nums.get(prefix, 0)
        return str(num) if num > 0 else ""

    if pattern_type == "english":
        if prefix.isdigit():
            return prefix
        roman = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
                 'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}
        return str(roman.get(prefix.upper(), 0)) if prefix.upper() in roman else ""

    return ""


def _build_hierarchy_regex(items: List[Dict]) -> List[Dict]:
    """旧版层次构建。"""
    if not items:
        return []

    items_sorted = sorted(items, key=lambda x: _structure_sort_key_old(x["structure"]))

    result = []
    stack = []

    for item in items_sorted:
        structure = item.get("structure", "")
        node = {
            "title": item["title"],
            "structure": structure,
            "physical_index": item["physical_index"],
            "nodes": [],
        }

        if not structure or '.' not in structure:
            result.append(node)
            stack = [node]
        else:
            parent_structure = structure.rsplit('.', 1)[0]
            found_parent = False

            for parent in reversed(stack):
                if parent.get("structure") == parent_structure:
                    parent.setdefault("nodes", []).append(node)
                    found_parent = True
                    break

            if not found_parent:
                result.append(node)

            current_depth = structure.count('.') + 1
            while stack and _get_depth_old(stack[-1].get("structure", "")) >= current_depth:
                stack.pop()
            stack.append(node)

    return result


def _structure_sort_key_old(structure: str) -> Tuple:
    """旧版排序键。"""
    if not structure:
        return (999,)
    try:
        parts = [int(p) for p in structure.split('.')]
        return tuple(parts + [0] * (5 - len(parts)))
    except ValueError:
        return (999,)


def _get_depth_old(structure: str) -> int:
    """旧版深度计算。"""
    if not structure:
        return 0
    return structure.count('.') + 1


def _calculate_confidence_regex(
    all_items: List[Dict],
    structured_items: List[Dict],
    doc_page_count: int
) -> float:
    """旧版置信度计算。"""
    confidence = 0.5

    if len(all_items) >= 10:
        confidence += 0.15
    elif len(all_items) >= 5:
        confidence += 0.1

    page_nums = [item["physical_index"] for item in all_items]
    if len(page_nums) >= 2:
        ascending = sum(1 for i in range(len(page_nums)-1) if page_nums[i] <= page_nums[i+1])
        continuity = ascending / (len(page_nums) - 1)
        confidence += continuity * 0.15

    if _has_hierarchy(structured_items):
        confidence += 0.1

    if doc_page_count > 0 and page_nums:
        valid_pages = sum(1 for p in page_nums if 1 <= p <= doc_page_count)
        if valid_pages / len(page_nums) >= 0.9:
            confidence += 0.1

    return min(confidence, 1.0)


# ===========================================================================
# 质量检查
# ===========================================================================

def _check_quality(result: Dict[str, Any], doc_page_count: int) -> bool:
    """检查提取结果质量。

    Returns:
        True = 质量过关
        False = 质量不过关（应降级）
    """
    items = result.get("items", [])
    confidence = result.get("confidence", 0)

    # 1. 条目数检查
    if len(items) < MIN_ITEMS_COUNT:
        print(f"[TOC-QUALITY] provider=toc_page action=quality_check status=rejected reason=too_few_items items={len(items)} min_items={MIN_ITEMS_COUNT}")
        return False

    # 2. 页码覆盖率检查
    if doc_page_count > 0:
        page_nums = []
        def collect_pages(nodes):
            for node in nodes:
                pi = node.get("physical_index")
                if pi:
                    page_nums.append(pi)
                collect_pages(node.get("nodes", []))
        collect_pages(items)

        if page_nums:
            last_page = max(page_nums)
            coverage = last_page / doc_page_count
            if coverage < MIN_PAGE_COVERAGE_RATIO:
                print(f"[TOC-QUALITY] provider=toc_page action=quality_check status=rejected reason=low_coverage coverage={coverage:.0%} min_coverage={MIN_PAGE_COVERAGE_RATIO:.0%}")
                return False

    # 3. 置信度检查
    if confidence < MIN_CONFIDENCE:
        print(f"[TOC-QUALITY] provider=toc_page action=quality_check status=rejected reason=low_confidence confidence={confidence:.2f} min_confidence={MIN_CONFIDENCE}")
        return False

    # 4. 重复检查
    titles = []
    def collect_titles(nodes):
        for node in nodes:
            titles.append(node.get("title", ""))
            collect_titles(node.get("nodes", []))
    collect_titles(items)

    unique_titles = set(titles)
    if len(unique_titles) < len(titles) * 0.8:  # 超过20%重复
        dup_count = len(titles) - len(unique_titles)
        print(f"[TOC-QUALITY] provider=toc_page action=quality_check status=rejected reason=duplicates count={dup_count}/{len(titles)}")
        return False

    print(f"[TOC-QUALITY] provider=toc_page action=quality_check status=ok items={len(items)} confidence={confidence:.2f}")
    return True


def _calculate_confidence(items: List[Dict], doc_page_count: int) -> float:
    """计算 coordinate 提取的置信度。"""
    confidence = 0.6  # coordinate 基础分更高

    # 条目数量
    if len(items) >= 10:
        confidence += 0.15
    elif len(items) >= 5:
        confidence += 0.1

    # 页码连续性
    page_nums = []
    def collect_pages(nodes):
        for node in nodes:
            pi = node.get("physical_index")
            if pi:
                page_nums.append(pi)
            collect_pages(node.get("nodes", []))
    collect_pages(items)

    if len(page_nums) >= 2:
        ascending = sum(1 for i in range(len(page_nums)-1) if page_nums[i] <= page_nums[i+1])
        continuity = ascending / (len(page_nums) - 1)
        confidence += continuity * 0.15

    # 结构层次
    if _has_hierarchy(items):
        confidence += 0.1

    # 页码范围合理性
    if doc_page_count > 0 and page_nums:
        valid_pages = sum(1 for p in page_nums if 1 <= p <= doc_page_count)
        if valid_pages / len(page_nums) >= 0.9:
            confidence += 0.1

    return min(confidence, 1.0)


def _has_hierarchy(items: List[Dict]) -> bool:
    """检查是否包含多级结构。"""
    for item in items:
        if item.get("nodes"):
            return True
    return False


# ===========================================================================
# 便捷函数（对外接口）
# ===========================================================================

def extract_toc_from_analysis(
    analysis: Dict[str, Any],
    doc_path: str = ""
) -> Optional[Dict[str, Any]]:
    """从文档分析结果中提取目录（对外主入口）。

    Args:
        analysis: pdf_analyzer.analyze_pdf_structure 的输出
        doc_path: PDF文件路径（coordinate坐标提取必需）

    Returns:
        提取结果字典，或 None（质量不过关，需降级）
    """
    toc_page_info = analysis.get("toc_page", {})
    if not toc_page_info.get("has_toc_page"):
        return None

    toc_page_indices = toc_page_info.get("page_indices", [])
    doc_page_count = analysis.get("page_count", 0)
    page_texts = analysis.get("page_texts", [])
    model = analysis.get("model", "qwen3.6-flash")

    return extract_toc_from_pages(
        doc_path=doc_path,
        toc_page_indices=toc_page_indices,
        doc_page_count=doc_page_count,
        model=model,
        page_texts=page_texts,
    )
