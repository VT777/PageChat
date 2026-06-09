"""Balanced TOC 模式 v3: 按文本质量路由到文本 LLM 或视觉 VLM。

视觉路径: 缩略图锚点检测 → 目录页提取+offset → 分段分析 → 验证修复
文本路径: LLM generate_toc_init/continue → 验证修复
"""

import asyncio
import json
import re
from collections import Counter
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from pageindex.vlm_utils import (
    render_pages_to_images,
    render_thumbnail_grids,
    vlm_call_with_images,
    parse_vlm_json,
)
from pageindex.fast_toc import verify_content_match, apply_offset
from pageindex.divider_fix import fix_toc_for_dividers
from pageindex.quality_validation import (
    validate_toc_pages_vlm,
    validate_dividers_vlm,
    decide_extraction_path,
    TocQualityChecker,
)
from app.prompts.pageindex_prompts import (
    VLM_ANCHOR_DETECTION_PROMPT,
    VLM_TOC_EXTRACT_PROMPT,
    VLM_TOC_EXTRACT_WITH_OFFSET_PROMPT,
    VLM_TOC_CONTINUE_PROMPT,
    VLM_FULLTEXT_SECTION_PROMPT,
    VLM_TOPIC_BOUNDARY_PROMPT,
    VLM_FIX_ITEM_PROMPT,
)


# ===========================================================================
# 路由决策
# ===========================================================================


def decide_balanced_path(analysis: Dict) -> str:
    """按文本质量决定走文本 LLM 还是视觉 VLM。"""
    tc = analysis.get("text_coverage", 0)
    garbled = analysis.get("is_garbled_pdf", False)
    if tc >= 0.8 and not garbled:
        return "text"
    return "visual"


def decide_v4_1_route(analysis: Dict[str, Any]) -> str:
    """Decide the initial v4.1 branch after TOC page detection/extraction."""
    toc_pages = analysis.get("toc_pages") or []
    toc_entries = analysis.get("toc_entries") or []

    if not toc_pages:
        return "B-bare"
    if analysis.get("toc_has_page_numbers") or any(entry.get("page") for entry in toc_entries):
        return "A"
    return "A+B"


def decide_v4_1_fallback(previous_branch: str, analysis: Dict[str, Any]) -> str:
    """Decide the v4.1 fallback branch without dropping extracted TOC info."""
    if previous_branch in {"A", "A+B"} and should_use_b_enhanced_v4_1(analysis):
        return "B-enhanced"
    return "C"


def should_use_b_enhanced_v4_1(analysis: Dict[str, Any]) -> bool:
    """Return true when fallback should preserve existing TOC hints."""
    return bool(analysis.get("toc_entries"))


def store_toc_entries_v4_1(
    analysis: Dict[str, Any],
    entries: List[Dict[str, Any]],
    toc_pages: Optional[List[int]] = None,
) -> None:
    """Persist TOC entries in analysis for A/A+B/B-enhanced reuse."""
    analysis["toc_entries"] = entries or []
    if toc_pages is not None:
        analysis["toc_pages"] = toc_pages
    analysis["toc_has_page_numbers"] = any(
        entry.get("page") or entry.get("logical_page") or entry.get("physical_index")
        for entry in entries or []
    )


def most_common(values: List[int]) -> Optional[int]:
    """Return the most common integer value."""
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _is_trusted_flat_toc_skeleton(toc_items: List[Dict[str, Any]], toc_check: Dict[str, Any]) -> bool:
    """Return true when the TOC page already provides the canonical flat skeleton."""
    if not toc_items or not toc_check.get("skeleton_valid"):
        return False
    if toc_check.get("has_hierarchy") or toc_check.get("hierarchy_valid"):
        return False
    top_level = [
        item
        for item in toc_items
        if int(item.get("level") or 1) == 1
    ]
    return len(top_level) >= 3 and len(top_level) == len(toc_items)


_PART_TITLE_RE = re.compile(r"^\s*(part|chapter)\s*0?\d+\s*[：:\-.\s]", re.IGNORECASE)
_CHINESE_PART_TITLE_RE = re.compile(r"^\s*第\s*[一二三四五六七八九十\d]+\s*[章节篇部]\s*[：:\-.\s]")
_SUBTITLE_LABEL_RE = re.compile(
    r"^\s*(?:增长引擎|核心模块|关键路径|主题|专题|篇章|阶段|模块|章节)\s*"
    r"[一二三四五六七八九十\d]*\s*[：:]\s*$"
)


def _is_main_part_title(title: str) -> bool:
    text = str(title or "").strip()
    return bool(_PART_TITLE_RE.search(text) or _CHINESE_PART_TITLE_RE.search(text))


def _is_short_subtitle_label(title: str) -> bool:
    text = str(title or "").strip()
    if not text or len(text) > 24:
        return False
    if _is_main_part_title(text):
        return False
    return bool(_SUBTITLE_LABEL_RE.search(text))


def _merge_flat_toc_subtitle_labels_legacy(toc_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge short subtitle labels into following numbered Part/Chapter TOC items."""
    if len(toc_items or []) < 3:
        return toc_items

    merged: List[Dict[str, Any]] = []
    pending_label: Optional[str] = None
    changed = False

    for raw_item in toc_items:
        item = deepcopy(raw_item)
        title = str(item.get("title") or "").strip()
        if _is_short_subtitle_label(title):
            pending_label = title.strip(" ：:")
            changed = True
            continue

        if pending_label and _is_main_part_title(title):
            prefix_match = re.match(
                r"^(\s*(?:part|chapter)\s*0?\d+\s*[：:\-.\s]+|第\s*[一二三四五六七八九十\d]+\s*[章节篇部]\s*[：:\-.\s]*)",
                title,
                flags=re.IGNORECASE,
            )
            if prefix_match:
                prefix = prefix_match.group(1)
                rest = title[prefix_match.end():].strip()
                item["title"] = f"{prefix}{pending_label}：{rest}" if rest else f"{prefix}{pending_label}"
                changed = True
            pending_label = None

        elif pending_label:
            merged.append({"title": pending_label, "level": 1})
            pending_label = None

        merged.append(item)

    if pending_label:
        merged.append({"title": pending_label, "level": 1})

    return merged if changed else toc_items


_MAIN_PART_PREFIX_RE_V2 = re.compile(
    r"^(\s*(?:part|chapter)\s*0?\d+\s*[：:\-.\s]+|"
    r"第\s*[一二三四五六七八九十\d]+\s*[章节篇部]\s*[：:\-.\s]*)",
    re.IGNORECASE,
)
_VISUAL_LABEL_TITLE_RE_V2 = re.compile(
    r"^\s*(?P<label>"
    r"(?:增长引擎|核心模块|关键路径|主题|专题|篇章|阶段|模块|章节|路径)\s*[一二三四五六七八九十\d]+"
    r"|(?:战略|策略|趋势|案例|技术|应用|行业|生态|治理|市场|洞察)[篇章]"
    r")\s*[·:：\-—\s]+(?P<rest>.+?)\s*$",
    re.IGNORECASE,
)
_SHORT_VISUAL_LABEL_RE_V2 = re.compile(
    r"^\s*(?P<label>"
    r"(?:增长引擎|核心模块|关键路径|主题|专题|篇章|阶段|模块|章节|路径)\s*[一二三四五六七八九十\d]+"
    r"|(?:战略|策略|趋势|案例|技术|应用|行业|生态|治理|市场|洞察)[篇章]"
    r")\s*[:：\-—]?\s*$",
    re.IGNORECASE,
)


def _split_main_part_title_v2(title: str) -> Optional[Tuple[str, str]]:
    text = str(title or "").strip()
    match = _MAIN_PART_PREFIX_RE_V2.match(text)
    if not match:
        return None
    return match.group(1), text[match.end():].strip()


def _split_visual_label_title_v2(title: str) -> Optional[Tuple[str, str]]:
    text = str(title or "").strip()
    if not text or _is_main_part_title(text):
        return None
    match = _VISUAL_LABEL_TITLE_RE_V2.match(text)
    if not match:
        return None
    label = match.group("label").strip()
    rest = match.group("rest").strip(" ：:")
    if not label or not rest:
        return None
    return label, rest


def _short_visual_label_v2(title: str) -> Optional[str]:
    text = str(title or "").strip()
    if not text or _is_main_part_title(text):
        return None
    match = _SHORT_VISUAL_LABEL_RE_V2.match(text)
    if not match:
        return None
    return match.group("label").strip()


def _normalize_title_for_overlap_v2(title: str) -> str:
    text = str(title or "").lower()
    return re.sub(r"[\s:：·\-—_，,。、“”\"'（）()\[\]【】]+", "", text)


def _titles_semantically_overlap_v2(left: str, right: str) -> bool:
    left_norm = _normalize_title_for_overlap_v2(left)
    right_norm = _normalize_title_for_overlap_v2(right)
    if len(left_norm) < 4 or len(right_norm) < 4:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True
    left_chunks = {left_norm[i:i + 2] for i in range(max(0, len(left_norm) - 1))}
    right_chunks = {right_norm[i:i + 2] for i in range(max(0, len(right_norm) - 1))}
    if not left_chunks or not right_chunks:
        return False
    overlap = len(left_chunks & right_chunks) / max(1, min(len(left_chunks), len(right_chunks)))
    return overlap >= 0.65


def _merge_flat_toc_subtitle_labels(toc_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge visual label rows into following numbered Part/Chapter TOC items."""
    if len(toc_items or []) < 3:
        return toc_items

    merged: List[Dict[str, Any]] = []
    pending_label: Optional[str] = None
    pending_label_rest: Optional[str] = None
    changed = False

    for raw_item in toc_items:
        item = deepcopy(raw_item)
        title = str(item.get("title") or "").strip()

        short_label = _short_visual_label_v2(title)
        if _is_short_subtitle_label(title) or short_label:
            pending_label = short_label or title.strip(" ：:")
            pending_label_rest = None
            changed = True
            continue

        visual_label = _split_visual_label_title_v2(title)
        if visual_label:
            pending_label, pending_label_rest = visual_label
            changed = True
            continue

        if pending_label and _is_main_part_title(title):
            split_part = _split_main_part_title_v2(title)
            if split_part:
                prefix, rest = split_part
                if pending_label_rest and not _titles_semantically_overlap_v2(pending_label_rest, rest):
                    merged.append({"title": f"{pending_label}：{pending_label_rest}", "level": 1})
                else:
                    title_rest = rest or pending_label_rest or ""
                    item["title"] = (
                        f"{prefix}{pending_label}：{title_rest}"
                        if title_rest
                        else f"{prefix}{pending_label}"
                    )
                    changed = True
            pending_label = None
            pending_label_rest = None
        elif pending_label:
            title_value = f"{pending_label}：{pending_label_rest}" if pending_label_rest else pending_label
            merged.append({"title": title_value, "level": 1})
            pending_label = None
            pending_label_rest = None

        merged.append(item)

    if pending_label:
        title_value = f"{pending_label}：{pending_label_rest}" if pending_label_rest else pending_label
        merged.append({"title": title_value, "level": 1})

    return merged if changed else toc_items


def _looks_like_ordinal_toc_pages(
    toc_items: List[Dict[str, Any]],
    first_content_page: Optional[int],
    last_toc_page: int,
) -> bool:
    """Detect fake page fields like 1,2,3,4 from no-page TOC pages."""
    pages = [
        item.get("page")
        for item in toc_items
        if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool)
    ]
    if len(pages) < 3:
        return False
    if pages != list(range(pages[0], pages[0] + len(pages))):
        return False
    content_start = first_content_page or (last_toc_page + 1)
    return max(pages) < content_start


def _chapter_marker_pattern(chapter_no: int) -> re.Pattern:
    chinese_numbers = {
        1: "一",
        2: "二",
        3: "三",
        4: "四",
        5: "五",
        6: "六",
        7: "七",
        8: "八",
        9: "九",
        10: "十",
    }
    chinese = chinese_numbers.get(chapter_no)
    alternatives = [rf"chapter\s*0?{chapter_no}\b"]
    if chinese:
        alternatives.append(rf"第\s*{chinese}\s*[章节篇部分]")
    alternatives.append(rf"第\s*0?{chapter_no}\s*[章节篇部分]")
    return re.compile("|".join(alternatives), re.IGNORECASE)


def _find_text_chapter_anchor_pages(
    page_texts: List[str],
    item_count: int,
    page_count: int,
    first_content_page: Optional[int],
    last_toc_page: int = 0,
) -> List[Optional[int]]:
    """Find chapter start pages from deterministic text markers such as Chapter 2."""
    if not page_texts or item_count <= 0:
        return []

    anchors: List[Optional[int]] = []
    search_from = max(1, last_toc_page + 1)
    for chapter_no in range(1, item_count + 1):
        pattern = _chapter_marker_pattern(chapter_no)
        found = None
        for page in range(search_from, page_count + 1):
            if page - 1 >= len(page_texts):
                break
            text = page_texts[page - 1] or ""
            if pattern.search(text):
                found = page
                search_from = page + 1
                break
        anchors.append(found)

    found_count = sum(1 for page in anchors if page)
    if found_count >= 2:
        print(f"[TOC-MAP] Text chapter anchors detected: {anchors}")
        return anchors
    return []


def _preserve_flat_toc_skeleton_result(
    toc_items: List[Dict[str, Any]],
    toc_check: Dict[str, Any],
    page_count: int,
    toc_pages: List[int],
    dividers: List[int],
    first_content_page: Optional[int],
    page_texts: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Keep a trusted flat TOC page skeleton and only repair its page mapping."""
    toc_items = _merge_flat_toc_subtitle_labels(toc_items)
    if not _is_trusted_flat_toc_skeleton(toc_items, toc_check):
        return None

    preserved = deepcopy(toc_items)
    last_toc = max(toc_pages) if toc_pages else 0
    if _looks_like_ordinal_toc_pages(preserved, first_content_page, last_toc):
        for item in preserved:
            item["logical_page"] = item.get("page")
            item.pop("page", None)
            item.pop("physical_index", None)

    top_items = [item for item in preserved if int(item.get("level") or 1) == 1]
    usable_dividers = [
        page
        for page in sorted(set(dividers or []))
        if isinstance(page, int) and 1 <= page <= page_count
    ]
    if usable_dividers:
        for item, page in zip(top_items, usable_dividers):
            item["physical_index"] = page

    text_anchors = _find_text_chapter_anchor_pages(
        page_texts or [],
        item_count=len(top_items),
        page_count=page_count,
        first_content_page=first_content_page,
        last_toc_page=last_toc,
    )
    if text_anchors:
        for item, page in zip(top_items, text_anchors):
            if page:
                item["physical_index"] = page

    missing = [item for item in top_items if not item.get("physical_index")]
    if missing:
        start_page = first_content_page or (last_toc + 1) or 1
        _map_uniformly(preserved, page_count, start_page)

    print(
        f"[BALANCED-VIS] Preserving flat TOC skeleton: "
        f"{len(preserved)} items, mapped={len([i for i in preserved if i.get('physical_index')])}"
    )
    return {
        "toc_items": preserved,
        "source": "vlm_toc_skeleton",
        "mapped": True,
        "semi_frozen": True,
        "prevalidated": True,
    }


def render_page(file_path: str, page_index: int, dpi: int = 180) -> Dict[str, Any]:
    """Render one page for VLM title checks."""
    return render_pages_to_images(file_path, [page_index], dpi=dpi)[0]


async def vlm_check_title_starts_page(image: Dict[str, Any], title: str, model: Optional[str] = None) -> bool:
    """Ask VLM whether the rendered page starts with the given title."""
    prompt = f"""请判断这页PDF是否以以下章节标题开始：{title}

要求：
1. 允许轻微空格、换行和标点差异。
2. 只有标题位于页面开头或作为明显大标题时才返回 true。
3. 如果标题只出现在正文段落、页眉、页脚或目录中，返回 false。

输出严格JSON：{{"found": true/false, "reason": "..."}}
"""
    raw = await vlm_call_with_images([image], prompt, model=model, max_tokens=800)
    result = parse_vlm_json(raw)
    return bool(isinstance(result, dict) and result.get("found"))


async def calculate_page_offset_visual_v4_1(
    file_path: str,
    toc_entries: List[Dict[str, Any]],
    page_count: int,
    model: Optional[str] = None,
) -> Optional[int]:
    """Calculate visual page offset by checking title matches in candidate windows."""
    offsets: List[int] = []
    for item in [entry for entry in toc_entries if entry.get("page")][:5]:
        for offset in range(-5, 6):
            physical_index = item["page"] + offset
            if physical_index < 1 or physical_index > page_count:
                continue
            image = render_page(file_path, physical_index - 1, dpi=180)
            if await vlm_check_title_starts_page(image, item.get("title", ""), model):
                offsets.append(offset)
                break
    return most_common(offsets)


def _split_range_v4_1(start_page: int, end_page: int, batch_size: int) -> List[Tuple[int, int]]:
    return [
        (page, min(page + batch_size - 1, end_page))
        for page in range(start_page, end_page + 1, batch_size)
    ]


def build_unsearched_batches_v4_1(
    start_page: int,
    end_page: int,
    searched: set[int],
    batch_size: int = 10,
) -> List[Tuple[int, int]]:
    """Build batches for pages not yet searched during progressive expansion."""
    batches: List[Tuple[int, int]] = []
    current_start: Optional[int] = None
    current_end: Optional[int] = None

    for page in range(start_page, end_page + 1):
        if page in searched:
            if current_start is not None and current_end is not None:
                batches.extend(_split_range_v4_1(current_start, current_end, batch_size))
                current_start = None
                current_end = None
            continue

        if current_start is None:
            current_start = page
        current_end = page

    if current_start is not None and current_end is not None:
        batches.extend(_split_range_v4_1(current_start, current_end, batch_size))

    return batches


# ===========================================================================
# 快速TOC提取（用于质量检查）
# ===========================================================================

async def _quick_extract_toc(
    file_path: str,
    toc_pages: List[int],
    model: Optional[str] = None,
) -> Optional[Dict]:
    """从目录页快速提取TOC条目（用于质量检查，不做完整验证）。"""
    try:
        images = render_pages_to_images(file_path, [p - 1 for p in toc_pages])
        
        prompt = """你是PDF文档分析专家。请从以下目录页图片中提取目录条目。

要求：
1. 提取所有条目（包括一级和二级）
2. 每个条目包含：标题、页码(physical_index)、层级（level=1为一级，level=2为二级）
3. 返回JSON格式

输出格式：
{
    "toc_items": [
        {"title": "第一章", "level": 1, "physical_index": 5},
        {"title": "1.1 简介", "level": 2, "physical_index": 6}
    ]
}"""
        
        prompt = """You are a PDF document analysis expert. Extract TOC entries from the provided TOC page images.

Requirements:
1. Extract all TOC entries, including top-level groups and nested entries.
2. Each entry must include title, level, and page.
3. page is the page number printed in the TOC. It is not the physical PDF page.
4. Do not put TOC page numbers in physical_index. physical_index is reserved for mapped PDF pages.
5. Do not output wrapper titles such as the document title, cover title, "目录", "Contents", or "Table of Contents" as TOC items.
6. For case catalogs like "AI+产业发展" followed by numbered case entries, set the "AI+..." category rows to level=1 and the numbered case rows such as "01 ..." to level=2.
7. Preserve the original TOC order and do not invent missing entries.
8. Return strict JSON only.

Output format:
{
    "toc_items": [
        {"title": "AI+产业发展", "level": 1},
        {"title": "01 渝车出海——汽车全球化智慧交互体验与服务模式创新", "level": 2, "page": 1}
    ]
}"""
        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=3000)
        result = parse_vlm_json(raw)
        
        if isinstance(result, dict) and "toc_items" in result:
            return result
        return None
        
    except Exception as e:
        print(f"[QUICK-TOC] Extraction failed: {e}")
        return None


# ===========================================================================
# Balanced 视觉路径
# ===========================================================================


async def build_balanced_toc_visual(
    file_path: str,
    analysis: Dict,
    model: Optional[str] = None,
    anchors: Optional[Dict] = None,
    ocr_text_map: Optional[Dict[int, str]] = None,
    hooks=None,
) -> Dict:
    """Balanced 视觉路径 v3.1: VLM校验 + 智能路径决策。"""
    page_count = analysis["page_count"]

    is_image_doc = (
        analysis.get("is_image_only_pdf", False)
        or analysis.get("image_coverage", 0.0) >= 0.3
    )

    # ─── Phase 0.5: 查找目录页（Step 1） ───
    toc_pages = []
    if anchors:
        toc_pages = list(anchors.get("toc_pages") or [])
    if not toc_pages:
        toc_pages = list(analysis.get("toc_pages") or [])

    if toc_pages:
        print(f"[BALANCED-VIS] Phase 0.5: using provided TOC pages {toc_pages}")
    else:
        print("[BALANCED-VIS] Phase 0.5: finding TOC pages")
        from pageindex.toc_detector import find_toc_pages
        toc_pages = await find_toc_pages(analysis, file_path, model)

    # ─── Phase 0.6: VLM校验TOC页（图片型文档） ───
    if toc_pages and is_image_doc:
        print(f"[BALANCED-VIS] Validating {len(toc_pages)} TOC pages with VLM")
        toc_validation = await validate_toc_pages_vlm(toc_pages, file_path, model)
        toc_pages = toc_validation["valid_pages"]
        if not toc_pages:
            print("[QC] 所有候选TOC页校验失败")

    # ─── Phase 0.7: 锚点检测（查找分隔页） ───
    if anchors is None:
        print("[BALANCED-VIS] Phase 0.7: anchor detection")
        anchors = await _vlm_detect_anchors(file_path, model)
    else:
        print("[BALANCED-VIS] Phase 0.7: using provided anchors")

    dividers = anchors.get("chapter_dividers", [])
    first_content = anchors.get("first_content_page")

    # 合并代码检测的章节分隔页
    code_dividers = analysis.get("chapter_dividers", [])
    if code_dividers and not dividers:
        print(f"[BALANCED-VIS] Using code-detected chapter dividers: {code_dividers}")
        dividers = code_dividers
        if not first_content and dividers:
            first_content = dividers[0]
    elif code_dividers and dividers:
        merged = sorted(set(dividers + code_dividers))
        if merged != dividers:
            print(f"[BALANCED-VIS] Merged dividers: {dividers} + {code_dividers} = {merged}")
            dividers = merged

    # ─── Phase 0.8: VLM校验Divider页（图片型文档） ───
    if dividers and is_image_doc:
        print(f"[BALANCED-VIS] Validating {len(dividers)} dividers with VLM")
        div_validation = await validate_dividers_vlm(dividers, file_path, model)
        dividers = div_validation["valid_dividers"]
        if not dividers:
            print("[QC] 所有候选divider页校验失败")

    # 打印当前状态
    divider_density = len(dividers) / page_count if page_count > 0 else 0
    print(
        f"[BALANCED-VIS] State: toc_pages={toc_pages}, "
        f"dividers={len(dividers)} (density={divider_density:.0%})"
    )

    # ─── Phase 1: TOC质量检查 ───
    toc_check = {"is_valid": False, "has_hierarchy": False}
    if toc_pages:
        # 快速提取TOC（用于质量检查）
        toc_result = await _quick_extract_toc(file_path, toc_pages, model)
        if toc_result and toc_result.get("toc_items"):
            _normalize_mislabeled_logical_pages(toc_result["toc_items"], page_count)
            store_toc_entries_v4_1(analysis, toc_result["toc_items"], toc_pages=toc_pages)
            checker = TocQualityChecker()
            toc_check = checker.check(toc_result["toc_items"], toc_pages)
            print(f"[QC] TOC check: {toc_check}")

    # ─── Phase 2: Divider质量检查 ───
    divider_check = {"is_valid": False}
    if dividers and len(dividers) >= 2:
        divider_check = {
            "is_valid": True,
            "valid_count": len(dividers),
            "reason": "VLM校验通过" if is_image_doc else "代码检测"
        }

    # ─── Phase 3: 路径决策 ───
    decision = decide_extraction_path(toc_check, divider_check)
    print(f"[QC] Decision: {decision['path']} - {decision['reason']}")

    # ─── Phase 4: 执行对应分支 ───

    # 分支A: TOC合格且有层级
    if decision["path"] == "BRANCH_A" and toc_pages:
        if toc_result and toc_result.get("toc_items"):
            preserved_result = _preserve_flat_toc_skeleton_result(
                toc_result["toc_items"],
                toc_check,
                page_count=page_count,
                toc_pages=toc_pages,
                dividers=dividers,
                first_content_page=first_content,
                page_texts=analysis.get("page_texts") or [],
            )
            if preserved_result:
                return preserved_result

        result = await _branch_a_toc_page(
            file_path, page_count, toc_pages, dividers, model,
            first_content_page=first_content,
            ocr_text_map=ocr_text_map,
        )
        if result:
            return result
        print("[QC] Branch A failed, will try Branch B")

    # 分支B: 按分隔页分段提取（包括分支A失败后的降级）
    if decision["path"] in ["BRANCH_B", "BRANCH_A_FAILED"] and dividers:
        if divider_density > 0.4:
            result = await _branch_b_dense_dividers(file_path, page_count, dividers, model)
        else:
            result = await _branch_b_normal_dividers(file_path, page_count, dividers, model)
        if result:
            return result
        print("[QC] Branch B failed, will try Branch C")

    # 分支C: 全文扫描兜底
    print("[QC] Falling back to Branch C (fulltext scan)")
    return await _branch_c_fulltext(file_path, page_count, model)


# ===========================================================================
# 分支 A: 有目录页
# ===========================================================================


async def _branch_a_toc_page(
    file_path: str,
    page_count: int,
    toc_pages: List[int],
    dividers: List[int],
    model: Optional[str] = None,
    first_content_page: Optional[int] = None,
    ocr_text_map: Optional[Dict[int, str]] = None,
) -> Optional[Dict]:
    """有目录页: VLM 看目录页+后续页 → TOC + offset (1 次 VLM)。
    
    offset 优先使用 first_content_page（来自锚点检测），不再依赖 VLM 计算。
    """
    # P1-4-fix: 用 OCR 验证并修正 toc_pages
    # VLM 锚点检测可能把正文页误判为目录页（如对开排版 PDF）
    if ocr_text_map and toc_pages:
        verified_toc_pages = []
        for tp in toc_pages:
            text = ocr_text_map.get(tp, "")
            # 目录页特征：包含目录/提纲/大纲/TOC 等关键词
            toc_keywords = ("目录", "提纲", "大纲", "CONTENTS", "TOC", "Contents")
            is_toc = any(kw in text[:500] for kw in toc_keywords)
            if is_toc:
                verified_toc_pages.append(tp)
            else:
                print(
                    f"[BALANCED-VIS] Filtered p.{tp} from toc_pages: "
                    f"OCR shows it's content page, not TOC"
                )
        if verified_toc_pages and len(verified_toc_pages) < len(toc_pages):
            print(
                f"[BALANCED-VIS] Corrected toc_pages: {toc_pages} -> {verified_toc_pages}"
            )
            toc_pages = verified_toc_pages
            # 同步修正 first_content_page（目录后第一页）
            corrected_first_content = max(toc_pages) + 1
            if first_content_page and first_content_page > corrected_first_content:
                print(
                    f"[BALANCED-VIS] Corrected first_content_page: "
                    f"{first_content_page} -> {corrected_first_content}"
                )
                first_content_page = corrected_first_content
        elif not verified_toc_pages and len(toc_pages) > 0:
            # P3-fix: 所有候选页面被 OCR 过滤 → 清空 toc_pages，回退到分支 B/C
            print(
                f"[BALANCED-VIS] All {len(toc_pages)} toc_pages filtered by OCR, "
                f"clearing and falling back to branch B/C"
            )
            toc_pages = []

    # 修正 first_content_page：如果 dividers 存在，以第一个 divider 为准
    if dividers and first_content_page:
        corrected = dividers[0]
        if first_content_page != corrected:
            print(
                f"[BALANCED-VIS] Corrected first_content_page from "
                f"{first_content_page} to {corrected} (using first divider)"
            )
            first_content_page = corrected

    # 传目录页 + 目录后 3-5 页高清图
    last_toc = max(toc_pages)
    # 所有目录页 + 后续 5 页（用于 offset 判断）
    pages_to_render = sorted(
        set(
            [p - 1 for p in toc_pages]  # 0-indexed
            + list(range(last_toc, min(last_toc + 5, page_count)))  # 目录后 5 页
        )
    )

    # 如果目录页太多(>10)，分批
    if len(pages_to_render) <= 15:
        images = render_pages_to_images(file_path, pages_to_render)
        
        # 构建页码标注：告诉 VLM 每张图对应哪一页，以及是否是目录页
        page_annotation_lines = []
        for img in images:
            page_idx = img["page_index"]  # 0-indexed
            phys_page = page_idx + 1       # 1-indexed 物理页码
            if phys_page in toc_pages:
                page_annotation_lines.append(
                    f"- 第 {len(page_annotation_lines)+1} 张图：物理页码 p.{phys_page}（目录页）"
                )
            else:
                page_annotation_lines.append(
                    f"- 第 {len(page_annotation_lines)+1} 张图：物理页码 p.{phys_page}（正文页）"
                )
        page_annotations = "图片序列说明（按顺序）：\n" + "\n".join(page_annotation_lines)
        
        # P0-1: 使用新 prompt，只要求提取条目，不计算 offset
        prompt = VLM_TOC_EXTRACT_PROMPT.format(
            page_annotations=page_annotations
        )
        
        print(f"[BALANCED-VIS] Branch A: {len(images)} pages (toc + following)")
        raw = await vlm_call_with_images(
            images, prompt, model=model, max_tokens=15000
        )
        result = parse_vlm_json(raw)
    else:
        # 分批提取
        result = await _extract_toc_multi_batch(file_path, toc_pages, page_count, model)

    if not isinstance(result, dict):
        print("[BALANCED-VIS] Branch A: VLM returned invalid format")
        return None

    toc_items = result.get("toc_items", [])
    is_complete = result.get("is_toc_complete", "yes")

    # 续提（如果目录未完成）
    if is_complete == "no" and toc_items:
        toc_items = await _continue_toc_extraction(
            file_path, page_count, toc_items, last_toc + 5, model
        )

    if len(toc_items) < 2:
        print("[BALANCED-VIS] Branch A: too few items")
        return None

    # P0-1-fix: 从 VLM 转录的 number 字段重建 structure 层级
    _infer_structure_from_numbers(toc_items)

    # 智能分组：如果 dividers 和 items 数量不匹配，先识别主章节和子章节
    if dividers and len(toc_items) > len(dividers):
        top_items = [it for it in toc_items if "." not in it.get("structure", "")]
        chapters, subsections = _smart_identify_chapters(top_items, dividers)
        
        if chapters and subsections and len(chapters) == len(dividers):
            print(f"[BALANCED-VIS] Smart grouping: {len(chapters)} chapters + {len(subsections)} subsections")
            
            # 标记子章节：给子章节添加 parent 标记，后续处理
            for sub in subsections:
                sub["_is_subsection"] = True
            
            # 重新排序：主章节在前，子章节在后（保持相对顺序）
            reordered = []
            for ch in chapters:
                reordered.append(ch)
                # 找到紧跟在这个 chapter 后面的 subsections
                ch_idx = toc_items.index(ch)
                for sub in subsections:
                    sub_idx = toc_items.index(sub)
                    if sub_idx > ch_idx and sub not in reordered:
                        reordered.append(sub)
                        break
            
            # 更新 toc_items
            toc_items.clear()
            toc_items.extend(reordered)

    # P1-4 / P2-8: 智能页码映射——检测目录页码可信度，自动选择映射策略
    # 传入 ocr_text_map 做标题搜索验证，传入 dividers 用于无页码场景
    # P4-fix: 使用分区映射，避免图表条目被强制递增到错误页码
    _map_toc_physical_pages_partitioned(
        toc_items,
        page_count=page_count,
        first_content_page=first_content_page,
        last_toc_page=last_toc,
        ocr_text_map=ocr_text_map,
        dividers=dividers,
    )
    
    # P1-4: OCR 完整性验证——检查 VLM 是否遗漏了条目
    if ocr_text_map and toc_items:
        _verify_toc_completeness_with_ocr(toc_items, ocr_text_map, last_toc)

    # 无页码 + 有 divider → 用 divider 物理位置
    items_without_pi = [it for it in toc_items if not it.get("physical_index")]
    if items_without_pi and dividers:
        _assign_divider_positions(toc_items, dividers)

    # 最后的兜底：还有无页码的，用位置顺序分配
    for i, item in enumerate(toc_items):
        if not item.get("physical_index"):
            prev_pi = (toc_items[i-1].get("physical_index") or last_toc) if i > 0 else last_toc
            item["physical_index"] = prev_pi + 1

    pis = [it.get("physical_index") or 0 for it in toc_items]
    print(
        f"[BALANCED-VIS] Branch A: {len(toc_items)} items, "
        f"physical_range={min(pis)}-{max(pis)} (page_count={page_count})"
    )

    # Task 3: 去重 — 只去重真正的重复（相同标题 + 相同页码）
    # 修复：不再按 physical_index 去重，因为一页可以有多个条目（如图表）
    seen = set()
    deduped = []
    removed = 0
    for item in toc_items:
        title = item.get("title", "")
        pi = item.get("physical_index", 0)
        key = (title[:30], pi)  # 用标题+页码作为去重键
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        deduped.append(item)
    
    if removed > 0:
        print(f"[BALANCED-VIS] Deduplication: removed {removed} duplicate nodes")
        toc_items.clear()
        toc_items.extend(deduped)

    # P5-fix: 子章节提取可能把图表标题误判为子章节，重置图表条目的 structure
    # 使图表条目成为独立根节点，避免被嵌套到章节下
    for item in toc_items:
        title = str(item.get("title", ""))
        number = str(item.get("number", ""))
        text = f"{number} {title}"
        if any(k in text for k in ['图', 'figure', 'Fig.', '表', 'Table']):
            # 重置图表条目的 structure，使其成为独立根节点
            if item.get("structure"):
                print(
                    f"[BALANCED-VIS] Reset figure/table structure: '{title[:40]}' "
                    f"from '{item['structure']}' to root"
                )
                item["structure"] = ""

    return {"toc_items": toc_items, "source": "vlm_toc"}


def _verify_toc_completeness_with_ocr(
    toc_items: List[Dict], ocr_text_map: Dict[int, str], last_toc: int
) -> None:
    """用 OCR 文本验证 VLM 提取的 TOC 是否完整。
    
    仅做日志记录和告警，不修改 toc_items（避免误伤）。
    """
    # 合并所有目录页的 OCR 文本
    toc_text = "\n".join(
        text for page_num, text in ocr_text_map.items()
        if page_num <= last_toc
    )
    if not toc_text:
        return

    # 从 OCR 文本中提取编号模式（如 01, 02, 03... 或 1, 2, 3...）
    # 连续数字序列暗示目录条目数量
    numbers = re.findall(r'\b(\d{1,2})\b', toc_text)
    if not numbers:
        return

    # 简单启发：如果 OCR 中数字的最大值远大于 VLM 提取的条目数，可能遗漏了
    try:
        max_num = max(int(n) for n in numbers)
    except ValueError:
        return

    vlm_count = len(toc_items)
    if max_num > vlm_count + 5:
        print(
            f"[BALANCED-VIS] WARNING: OCR detected up to item #{max_num}, "
            f"but VLM extracted only {vlm_count} items. "
            f"Possible missing entries from multi-page TOC."
        )


# ===========================================================================
# 分支 B (改进版): Divider主导 + 后端构建
# ===========================================================================

# Divider页专用Prompt
_DIVIDER_TITLE_PROMPT = """这是PDF文档的一个章节分隔页（第{page}页）。

请仔细观察该页面，提取章节的主标题。

注意：
1. 页面上可能有"Part01"、"Part02"等标签，这是章节编号，请保留
2. 主要标题通常是页面上最大、最显眼的文字
3. 不要提取页眉页脚或装饰性文字
4. 如果页面主要是图片，请根据图片主题描述章节内容

请只返回标题文字，不要解释。

输出格式（JSON）：
{{"title": "提取到的完整标题"}}
"""

# 内容页专用Prompt
_CONTENT_TITLES_PROMPT = """请分析以下PDF内容页图片，提取每页中的章节标题。

页码对应关系：
{page_annotations}

要求：
1. 只提取作为章节标题的文字（通常是该页最大、最显眼的文字）
2. 不要提取正文段落、图表说明、页眉页脚
3. 如果某页没有明显的章节标题，不要为该页生成条目
4. 标题原文提取，不要修改或概括

输出格式（JSON数组）：
[
  {{"title": "标题文字", "page_index": 0}},  // page_index对应第几张图（从0开始）
  {{"title": "标题文字", "page_index": 2}}
]

注意：
- page_index是图片的索引（第1张图=0，第2张图=1...）
- 不要在page_index中加上实际的页码数字
- 如果连续几页都没有标题，可以只返回有标题的页面
"""


async def _extract_divider_title(
    file_path: str,
    page: int,
    model: Optional[str] = None
) -> Optional[str]:
    """提取divider页的主标题
    
    Args:
        file_path: PDF文件路径
        page: divider页码（1-indexed）
        model: VLM模型名称
    
    Returns:
        主标题，提取失败返回None
    """
    try:
        # 渲染divider页（高DPI）
        images = render_pages_to_images(file_path, [page - 1], dpi=200)
        if not images:
            return None
        
        # 构建专用prompt
        prompt = _DIVIDER_TITLE_PROMPT.format(page=page)
        
        # 调用VLM
        raw = await vlm_call_with_images(
            images, prompt, model=model, max_tokens=500
        )
        
        # 解析结果
        result = parse_vlm_json(raw)
        if isinstance(result, dict) and "title" in result:
            title = result["title"].strip()
            if title:
                return title
        
        return None
        
    except Exception as e:
        print(f"    [ERROR] 提取divider标题失败: {e}")
        return None


async def _extract_content_titles(
    file_path: str,
    pages: List[int],
    model: Optional[str] = None
) -> List[Dict]:
    """提取内容页的子标题
    
    Args:
        file_path: PDF文件路径
        pages: 内容页码列表（1-indexed）
        model: VLM模型名称
    
    Returns:
        子标题列表，每个包含title和physical_index
    """
    if not pages:
        return []
    
    try:
        # 渲染内容页
        images = render_pages_to_images(
            file_path, [p - 1 for p in pages]
        )
        
        if not images:
            return []
        
        # 构建页码标注
        page_annotations = []
        for idx, img in enumerate(images):
            actual_page = img["page_index"] + 1
            page_annotations.append(f"第{idx+1}张图 = 第{actual_page}页")
        
        # 构建专用prompt
        prompt = _CONTENT_TITLES_PROMPT.format(
            page_annotations="\n".join(page_annotations)
        )
        
        # 调用VLM
        raw = await vlm_call_with_images(
            images, prompt, model=model, max_tokens=3000
        )
        
        # 解析结果
        result = parse_vlm_json(raw)
        
        items = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict) and "title" in item:
                    page_offset = item.get("page_index", 0)
                    # 后端计算物理页码
                    actual_page = pages[0] + page_offset
                    
                    # 确保页码在范围内
                    if 0 <= page_offset < len(pages):
                        items.append({
                            "title": item["title"].strip(),
                            "physical_index": actual_page
                        })
        
        return items
        
    except Exception as e:
        print(f"    [ERROR] 提取内容标题失败: {e}")
        return []


def _deduplicate_items_improved(items: List[Dict]) -> List[Dict]:
    """去重：相同标题+相邻页码(±1)视为重复"""
    if not items:
        return []
    
    # 按页码排序
    sorted_items = sorted(items, key=lambda x: x.get("physical_index", 0))
    
    result = []
    seen_titles = {}  # title -> last_page
    
    for item in sorted_items:
        title = item.get("title", "").strip()
        page = item.get("physical_index", 0)
        
        if not title:
            continue
        
        # 检查是否重复（标题相同且页码相邻）
        is_duplicate = False
        for seen_title, seen_page in seen_titles.items():
            if seen_title == title and abs(page - seen_page) <= 1:
                is_duplicate = True
                break
        
        if not is_duplicate:
            seen_titles[title] = page
            result.append(item)
    
    return result


def _assign_structure(
    main_items: List[Dict],
    sub_items_map: Dict[int, List[Dict]],
    dividers: List[int]
) -> List[Dict]:
    """后端分配structure
    
    Args:
        main_items: 主章节列表 [{"title": "xxx", "physical_index": 5}, ...]
        sub_items_map: 子章节映射 {divider_page: [{"title": "xxx", "physical_index": 6}, ...]}
        dividers: divider页码列表
    
    Returns:
        完整TOC条目列表，包含structure字段
    """
    result = []
    
    for i, div in enumerate(dividers):
        chapter_num = i + 1
        
        # 添加主章节
        main = main_items[i] if i < len(main_items) else None
        if main:
            result.append({
                "structure": str(chapter_num),
                "title": main["title"],
                "physical_index": div
            })
        else:
            # fallback
            result.append({
                "structure": str(chapter_num),
                "title": f"第{chapter_num}章",
                "physical_index": div
            })
        
        # 添加子章节
        sub_items = sub_items_map.get(div, [])
        for j, sub in enumerate(sub_items, 1):
            result.append({
                "structure": f"{chapter_num}.{j}",
                "title": sub["title"],
                "physical_index": sub["physical_index"]
            })
    
    return result


# ===========================================================================
# 分支 B: 有 divider
# ===========================================================================


async def _branch_b_dense_dividers(
    file_path: str,
    page_count: int,
    dividers: List[int],
    model: Optional[str] = None,
) -> Optional[Dict]:
    """密集 divider: 1 次 VLM 看 divider 页缩略图提取标题。"""
    # 渲染 divider 页的缩略图网格
    images = render_pages_to_images(file_path, [d - 1 for d in dividers[:50]], dpi=100)
    if not images:
        return None

    prompt = (
        f"这些是一份 {page_count} 页文档中每个章节/案例的首页缩略图。\n"
        f"请提取每个页面的标题。\n\n"
        f"回答 JSON 数组（不要 markdown fence）:\n"
        f'[{{"structure": "1", "title": "标题", "physical_index": N}}, ...]'
    )
    print(f"[BALANCED-VIS] Branch B (dense): {len(images)} divider pages")
    raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=10000)
    items = parse_vlm_json(raw)

    if isinstance(items, list) and len(items) >= 2:
        # 确保 physical_index 正确（从 divider 列表取）
        for i, item in enumerate(items):
            if i < len(dividers):
                item["physical_index"] = dividers[i]
        return {"toc_items": items, "source": "vlm_dividers"}
    return None


async def _branch_b_normal_dividers(
    file_path: str,
    page_count: int,
    dividers: List[int],
    model: Optional[str] = None,
) -> Optional[Dict]:
    """改进版 Branch B: Divider主导 + 后端构建
    
    核心改进：
    1. Divider页单独提取主标题（专用Prompt）
    2. 内容页批量提取子标题（专用Prompt + 后端页码计算）
    3. 后端直接分配Structure，不依赖VLM判断层级
    """
    if not dividers:
        return None
    
    # 排序divider
    sorted_dividers = sorted(dividers)
    
    # 存储结果
    main_items = []  # 主章节
    sub_items_map = {}  # 子章节映射
    
    print(f"[BALANCED-VIS] Branch B (improved): {len(sorted_dividers)} dividers")
    
    # 处理每个章节
    for i, div in enumerate(sorted_dividers):
        # 计算范围
        end = sorted_dividers[i + 1] - 1 if i + 1 < len(sorted_dividers) else page_count
        
        print(f"\n[BALANCED-VIS] Chapter {i+1}: divider p.{div}, range p.{div+1}~p.{end}")
        
        # Step 1: 提取divider页的主标题
        print(f"  [DIVIDER] Extracting main title from p.{div}")
        main_title = await _extract_divider_title(file_path, div, model)
        
        if main_title:
            print(f"    [OK] Main title: {main_title[:50]}")
            main_items.append({
                "title": main_title,
                "physical_index": div
            })
        else:
            print(f"    [WARN] Failed to extract main title, using fallback")
            main_items.append({
                "title": f"Chapter {i+1}",
                "physical_index": div
            })
        
        # Step 2: 提取内容页的子标题
        content_pages = list(range(div + 1, end + 1))
        if content_pages:
            print(f"  [CONTENT] Extracting sub-titles from p.{content_pages[0]}~p.{content_pages[-1]}")
            
            # 分批处理（每批最多8页）
            batch_size = 8
            all_sub_items = []
            
            for batch_start in range(0, len(content_pages), batch_size):
                batch = content_pages[batch_start:batch_start + batch_size]
                print(f"    Batch: p.{batch[0]}~p.{batch[-1]}")
                
                sub_items = await _extract_content_titles(file_path, batch, model)
                all_sub_items.extend(sub_items)
            
            # 去重
            all_sub_items = _deduplicate_items_improved(all_sub_items)
            sub_items_map[div] = all_sub_items
            
            print(f"    [OK] {len(all_sub_items)} unique sub-titles")
    
    # Step 3: 后端分配structure
    print(f"\n[BALANCED-VIS] Assigning structure...")
    toc_items = _assign_structure(main_items, sub_items_map, sorted_dividers)
    
    print(f"[BALANCED-VIS] Total: {len(toc_items)} items ({len(main_items)} main + {len(toc_items) - len(main_items)} sub)")
    
    if len(toc_items) >= 2:
        return {
            "toc_items": toc_items,
            "source": "vlm_divider_improved"
        }
    return None


# ===========================================================================
# 分支 C: 无锚点全文分析
# ===========================================================================


async def _branch_c_fulltext(
    file_path: str,
    page_count: int,
    model: Optional[str] = None,
) -> Dict:
    """无任何锚点: 分层全文分析。"""
    if page_count <= 60:
        # 一次传完全部高清图
        return await _fulltext_one_shot(file_path, page_count, model)
    else:
        # 两阶段: 缩略图找 boundary → 分组高清分析
        return await _fulltext_two_stage(file_path, page_count, model)


async def _fulltext_one_shot(
    file_path: str, page_count: int, model: Optional[str] = None
) -> Dict:
    """≤60 页: 1 次 VLM 传全部高清图。"""
    images = render_pages_to_images(file_path, list(range(page_count)))
    prompt = VLM_FULLTEXT_SECTION_PROMPT.format(
        start_page=1,
        end_page=page_count,
        start_page_plus1=2,
        previous_context="",
    )
    print(f"[BALANCED-VIS] Branch C (one-shot): {page_count} pages")
    raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=15000)
    items = parse_vlm_json(raw)
    if isinstance(items, list) and len(items) >= 2:
        return {"toc_items": items, "source": "vlm_fulltext"}
    return {
        "toc_items": [
            {"structure": "1", "title": "Document Content", "physical_index": 1}
        ],
        "source": "fallback",
    }


async def _fulltext_two_stage(
    file_path: str, page_count: int, model: Optional[str] = None
) -> Dict:
    """>60 页: 缩略图找 topic_boundary → 分组高清。"""
    # 阶段 1: 找 topic boundaries
    grids = render_thumbnail_grids(file_path, pages_per_grid=12, cols=4)
    grid_images = [{"page_index": 0, "image_base64": g["image_base64"]} for g in grids]
    print(f"[BALANCED-VIS] Branch C stage 1: {len(grids)} thumbnail grids")
    raw = await vlm_call_with_images(
        grid_images, VLM_TOPIC_BOUNDARY_PROMPT, model=model, max_tokens=3000
    )
    try:
        boundary_result = parse_vlm_json(raw)
        boundaries = boundary_result.get("topic_boundaries", [1])
    except Exception:
        boundaries = [1]

    if len(boundaries) < 2:
        boundaries = [1]
    # 确保从 1 开始
    if boundaries[0] != 1:
        boundaries = [1] + boundaries

    print(f"[BALANCED-VIS] Branch C stage 1: boundaries={boundaries}")

    # 阶段 2: 按 boundaries 分组高清分析
    all_items = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] - 1 if i < len(boundaries) - 1 else page_count
        pages = list(range(start - 1, min(end, page_count)))  # 0-indexed
        images = render_pages_to_images(file_path, pages)
        if not images:
            continue

        prev_context = ""
        if all_items:
            last_3 = json.dumps(all_items[-3:], ensure_ascii=False)
            prev_context = (
                f"\n之前已识别的章节（最后 3 个）:\n{last_3}\n请延续 structure 编号。\n"
            )

        prompt = VLM_FULLTEXT_SECTION_PROMPT.format(
            start_page=start,
            end_page=end,
            start_page_plus1=start + 1,
            previous_context=prev_context,
        )
        print(f"[BALANCED-VIS] Branch C stage 2: pages {start}-{end}")
        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=10000)
        try:
            items = parse_vlm_json(raw)
            if isinstance(items, list):
                all_items.extend(items)
        except Exception as e:
            print(f"[BALANCED-VIS] Group {start}-{end} failed: {e}")

    if len(all_items) >= 2:
        return {"toc_items": _deduplicate(all_items), "source": "vlm_fulltext"}
    return {
        "toc_items": [
            {"structure": "1", "title": "Document Content", "physical_index": 1}
        ],
        "source": "fallback",
    }


# ===========================================================================
# Balanced 文本路径
# ===========================================================================


async def build_balanced_toc_text(
    analysis: Dict,
    model: Optional[str] = None,
    dividers: Optional[List[int]] = None,
    hooks=None,
) -> Dict:
    """Balanced 文本路径: LLM 全文分析 (generate_toc_init/continue)。

    复用 page_index.py 中已有的 LLM 全文分析逻辑。
    新增: 如果提供 dividers，用 dividers 修正 TOC 结构。
    """
    from pageindex.page_index import (
        meta_processor,
        JsonLogger,
    )
    from types import SimpleNamespace

    page_list = analysis["page_list"]
    page_count = analysis["page_count"]

    # 构建 opt
    rule_result = _try_extract_text_heading_toc(analysis)
    if rule_result:
        return rule_result

    opt = SimpleNamespace(
        model=model or "qwen3.6-flash",
        toc_check_page_num=15,
        max_page_num_each_node=6,
        max_token_num_each_node=15000,
        if_add_node_id="no",
        if_add_node_summary="no",
        if_add_doc_description="no",
        if_add_node_text="no",
        index_mode="balanced",
    )

    logger = JsonLogger(analysis.get("file_path", "unknown"))

    toc_items = []
    try:
        # 直接走 process_no_toc（因为我们到这里说明没有高质量代码 TOC）
        toc_items = await meta_processor(
            page_list,
            mode="process_no_toc",
            start_index=1,
            opt=opt,
            logger=logger,
            doc_type="general",
            doc_type_confidence=0.0,
            hooks=hooks,
            doc=analysis.get("file_path"),
        )
        if not toc_items or len(toc_items) < 2:
            raise ValueError("Too few TOC items")
    except Exception as e:
        print(f"[BALANCED-TEXT] LLM analysis failed: {e}")
        return {
            "toc_items": [
                {"structure": "1", "title": "Document Content", "physical_index": 1}
            ],
            "source": "fallback",
        }

    # P2-fix: 用 dividers 修正 TOC 结构
    if dividers and len(dividers) > 0:
        print(f"[BALANCED-TEXT] Refining TOC with {len(dividers)} dividers")
        toc_items = _refine_toc_with_dividers(toc_items, dividers, page_count)

    # FIX: Post-process TOC to fix titles for divider-based documents
    try:
        toc_items = await fix_toc_for_dividers(
            toc_items,
            page_list,
            pdf_path=analysis.get("file_path"),
            use_vlm=True,
            vlm_model="qwen3.6-flash",
        )
    except Exception as e:
        print(f"[BALANCED-TEXT] Divider fix failed: {e}")

    return {"toc_items": toc_items, "source": "llm_text"}


def _try_extract_text_heading_toc(analysis: Dict) -> Optional[Dict]:
    """Use deterministic headings for text-rich docs with chapter-only TOC pages."""
    if analysis.get("text_coverage", 0) < 0.8:
        return None

    page_texts = analysis.get("page_texts") or []
    toc_pages = analysis.get("toc_pages") or analysis.get("toc_page", {}).get("pages") or []
    if not page_texts or not toc_pages:
        return None

    try:
        from pageindex.text_heading_extractor import (
            extract_text_headings,
            is_chapter_skeleton_toc,
            merge_chapter_skeleton_with_headings,
        )
    except Exception:
        return None

    toc_text = "\n".join(
        page_texts[p - 1]
        for p in toc_pages
        if isinstance(p, int) and 0 <= p - 1 < len(page_texts)
    )
    skeleton = is_chapter_skeleton_toc(toc_text)
    if not skeleton.get("is_skeleton"):
        return None

    headings = extract_text_headings(page_texts, start_page=1)
    body_headings = [
        item for item in headings
        if item.get("physical_index") not in toc_pages
    ]
    if len(body_headings) < 5:
        return None

    merged = merge_chapter_skeleton_with_headings(skeleton, body_headings)
    if len(merged) < 5:
        return None

    print(
        f"[BALANCED-TEXT] Rule heading extraction: "
        f"skeleton={len(skeleton.get('items') or [])}, headings={len(body_headings)}"
    )
    return {
        "toc_items": merged,
        "source": "text_heading",
        "mapped": True,
        "semi_frozen": True,
    }


# ===========================================================================
# 辅助函数
# ===========================================================================


def _refine_toc_with_dividers(
    toc_items: List[Dict],
    dividers: List[int],
    page_count: int,
) -> List[Dict]:
    """用 dividers 修正 TOC 结构。
    
    当 Text 路径生成的 TOC 和 dividers 不匹配时，重新组织结构。
    """
    if not dividers or not toc_items:
        return toc_items
    
    # 1. 识别主章节（没有 "." 的 structure）
    main_chapters = []
    sub_chapters = []
    
    for item in toc_items:
        struct = str(item.get("structure", ""))
        if "." not in struct:
            main_chapters.append(item)
        else:
            sub_chapters.append(item)
    
    # 2. 如果主章节数量和 dividers 匹配，直接分配 dividers
    if len(main_chapters) == len(dividers):
        print(f"[BALANCED-TEXT] Matching chapters({len(main_chapters)}) with dividers({len(dividers)})")
        for ch, div in zip(main_chapters, dividers):
            ch["physical_index"] = div
        
        # 分配子章节到对应主章节
        _assign_subchapters_to_parents(main_chapters, sub_chapters, dividers, page_count)
        
        # 合并并排序
        result = []
        for ch in main_chapters:
            result.append(ch)
            # 找到属于这个主章节的子章节
            ch_idx = main_chapters.index(ch)
            ch_start = dividers[ch_idx]
            ch_end = dividers[ch_idx + 1] if ch_idx + 1 < len(dividers) else page_count
            
            for sub in sub_chapters:
                sub_pi = sub.get("physical_index") or 0
                if sub_pi and ch_start <= sub_pi < ch_end:
                    result.append(sub)
        
        return result
    
    # 3. 如果数量不匹配，尝试 smart grouping
    chapters, subsections = _smart_identify_chapters(toc_items, dividers)
    if chapters and len(chapters) == len(dividers):
        print(f"[BALANCED-TEXT] Smart grouping: {len(chapters)} chapters + {len(subsections)} subsections")
        
        # 分配 dividers 给主章节
        for ch, div in zip(chapters, dividers):
            ch["physical_index"] = div
        
        # 重新构建层级
        result = []
        for i, ch in enumerate(chapters):
            ch["structure"] = str(i + 1)
            result.append(ch)
            
            # 找到属于这个主章节的子章节
            ch_start = dividers[i]
            ch_end = dividers[i + 1] if i + 1 < len(dividers) else page_count
            
            sub_count = 0
            for sub in subsections:
                sub_pi = sub.get("physical_index", 0)
                if not sub_pi:
                    # 根据位置推断
                    sub_idx = toc_items.index(sub)
                    ch_idx = toc_items.index(ch)
                    if sub_idx > ch_idx:
                        sub_count += 1
                        sub["structure"] = f"{i + 1}.{sub_count}"
                        result.append(sub)
                elif ch_start <= sub_pi < ch_end:
                    sub_count += 1
                    sub["structure"] = f"{i + 1}.{sub_count}"
                    result.append(sub)
        
        return result
    
    # 4. 无法修正，返回原始结果
    print(f"[BALANCED-TEXT] Cannot refine: chapters={len(main_chapters)}, dividers={len(dividers)}")
    return toc_items


def _assign_subchapters_to_parents(
    main_chapters: List[Dict],
    sub_chapters: List[Dict],
    dividers: List[int],
    page_count: int,
) -> None:
    """将子章节分配到对应的主章节下。"""
    for i, ch in enumerate(main_chapters):
        ch_start = dividers[i]
        ch_end = dividers[i + 1] if i + 1 < len(dividers) else page_count
        
        for sub in sub_chapters:
            sub_pi = sub.get("physical_index") or 0
            if sub_pi and ch_start <= sub_pi < ch_end:
                # 更新 structure 为 "X.Y" 格式
                parent_struct = str(ch.get("structure", i + 1))
                # 找到当前主章节下最大的子序号
                existing_subs = [s for s in sub_chapters 
                                if str(s.get("structure", "")).startswith(f"{parent_struct}.")]
                max_sub = len(existing_subs) + 1
                sub["structure"] = f"{parent_struct}.{max_sub}"


async def _vlm_detect_anchors(file_path: str, model: Optional[str] = None) -> Dict:
    """VLM 缩略图锚点检测。"""
    grids = render_thumbnail_grids(file_path, pages_per_grid=12, cols=4)
    grid_images = [{"page_index": 0, "image_base64": g["image_base64"]} for g in grids]

    raw = await vlm_call_with_images(
        grid_images, VLM_ANCHOR_DETECTION_PROMPT, model=model, max_tokens=3000
    )
    try:
        result = parse_vlm_json(raw)
        return result if isinstance(result, dict) else {}
    except Exception as e:
        print(f"[BALANCED-VIS] Anchor detection failed: {e}")
        return {}


async def _extract_toc_multi_batch(
    file_path: str,
    toc_pages: List[int],
    page_count: int,
    model: Optional[str] = None,
) -> Dict:
    """多批次提取目录（目录页 > 10 页时）。"""
    all_items = []
    batch_size = 8

    for i in range(0, len(toc_pages), batch_size):
        batch_pages = toc_pages[i : i + batch_size]
        page_indices = [p - 1 for p in batch_pages]  # 0-indexed

        # 最后一批加目录后 3 页用于 offset
        if i + batch_size >= len(toc_pages):
            last_toc = max(batch_pages)
            page_indices += list(range(last_toc, min(last_toc + 3, page_count)))

        images = render_pages_to_images(file_path, sorted(set(page_indices)))

        if i == 0:
            # 构建页码标注（仅第一批需要，因为包含目录页+正文页）
            page_annotation_lines = []
            for img in images:
                page_idx = img["page_index"]  # 0-indexed
                phys_page = page_idx + 1       # 1-indexed
                if phys_page in toc_pages:
                    page_annotation_lines.append(
                        f"- 第 {len(page_annotation_lines)+1} 张图：物理页码 p.{phys_page}（目录页）"
                    )
                else:
                    page_annotation_lines.append(
                        f"- 第 {len(page_annotation_lines)+1} 张图：物理页码 p.{phys_page}（正文页）"
                    )
            page_annotations = "图片序列说明（按顺序）：\n" + "\n".join(page_annotation_lines)
            # P0-1: 使用新 prompt，不计算 offset
            prompt = VLM_TOC_EXTRACT_PROMPT.format(
                page_annotations=page_annotations
            )
        else:
            prev = json.dumps(all_items[-3:], ensure_ascii=False)
            prompt = VLM_TOC_CONTINUE_PROMPT.format(previous_items=prev)

        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=10000)
        result = parse_vlm_json(raw)

        if isinstance(result, dict):
            new_items = result.get("toc_items", [])
            all_items.extend(new_items)
            if i == 0:
                offset = result.get("offset", 0)
        elif isinstance(result, list):
            all_items.extend(result)

    # P2-8: 修复 offset 变量作用域问题（使用新 prompt 后 VLM 不返回 offset，
    # offset 由 _branch_a_toc_page 统一计算）
    return {
        "toc_items": all_items,
        "is_toc_complete": "yes",
    }


async def _continue_toc_extraction(
    file_path: str,
    page_count: int,
    existing_items: List[Dict],
    start_from: int,
    model: Optional[str] = None,
    max_rounds: int = 3,
) -> List[Dict]:
    """续提目录（目录未完成时）。"""
    all_items = list(existing_items)

    for round_num in range(max_rounds):
        end = min(start_from + 5, page_count)
        if start_from >= end:
            break

        images = render_pages_to_images(file_path, list(range(start_from, end)))
        if not images:
            break

        prev = json.dumps(all_items[-3:], ensure_ascii=False)
        prompt = VLM_TOC_CONTINUE_PROMPT.format(previous_items=prev)

        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=8000)
        try:
            result = parse_vlm_json(raw)
            new_items = result.get("toc_items", []) if isinstance(result, dict) else []
            if new_items:
                all_items.extend(new_items)
            is_complete = (
                result.get("is_toc_complete", "yes")
                if isinstance(result, dict)
                else "yes"
            )
            if is_complete == "yes":
                break
        except Exception:
            break

        start_from = end

    return all_items


def _is_chinese_number(s: str) -> bool:
    """检查字符串是否为中文数字（如一、二、三）。"""
    chinese_nums = set('一二三四五六七八九十百千万')
    return bool(s) and all(c in chinese_nums for c in s)


def _is_arabic_number(s: str) -> bool:
    """检查字符串是否为阿拉伯数字（如 1, 2, 3）。"""
    return s.isdigit()


def _is_roman_number(s: str) -> bool:
    """检查字符串是否为罗马数字（如 I, II, III）。"""
    roman_chars = set('IVXLCDM')
    return bool(s) and all(c.upper() in roman_chars for c in s)


def _smart_identify_chapters(toc_items: List[Dict], dividers: List[int]) -> Tuple[List[Dict], List[Dict]]:
    """
    智能识别主章节和子章节。
    
    返回: (chapters, subsections)
    chapters: 应该分配 dividers 的主章节
    subsections: 应该作为子节点的子章节
    """
    if not toc_items:
        return [], []
    
    n_items = len(toc_items)
    n_dividers = len(dividers)
    
    # 如果数量匹配，所有都是主章节
    if n_items == n_dividers:
        return toc_items, []
    
    # 1. 检查是否有明确的点号层级（如 1, 1.1, 2, 2.1）
    has_dot_notation = any('.' in str(it.get('structure', '')) for it in toc_items)
    if has_dot_notation:
        chapters = [it for it in toc_items if '.' not in str(it.get('structure', ''))]
        subsections = [it for it in toc_items if '.' in str(it.get('structure', ''))]
        if len(chapters) == n_dividers:
            return chapters, subsections
    
    # 2. 检查交替模式（如 一, 2, 二, 4, 三, 6）
    structures = [str(it.get('structure', '')) for it in toc_items]
    if n_items >= 2:
        # 检测是否奇数位置是中文/罗马，偶数位置是阿拉伯
        odd_is_chinese = all(_is_chinese_number(structures[i]) for i in range(0, n_items, 2) if structures[i])
        even_is_arabic = all(_is_arabic_number(structures[i]) for i in range(1, n_items, 2) if structures[i])
        
        if odd_is_chinese and even_is_arabic and n_items // 2 + n_items % 2 == n_dividers:
            chapters = [toc_items[i] for i in range(0, n_items, 2)]
            subsections = [toc_items[i] for i in range(1, n_items, 2)]
            return chapters, subsections
        
        # 或者偶数位置是中文，奇数位置是阿拉伯
        even_is_chinese = all(_is_chinese_number(structures[i]) for i in range(0, n_items, 2) if structures[i])
        odd_is_arabic = all(_is_arabic_number(structures[i]) for i in range(1, n_items, 2) if structures[i])
        
        if even_is_chinese and odd_is_arabic and n_items // 2 + n_items % 2 == n_dividers:
            chapters = [toc_items[i] for i in range(0, n_items, 2)]
            subsections = [toc_items[i] for i in range(1, n_items, 2)]
            return chapters, subsections
    
    # 3. 基于标题长度判断（主章节通常更短、更概括）
    avg_len = sum(len(it.get('title', '')) for it in toc_items) / n_items
    chapters = [it for it in toc_items if len(it.get('title', '')) <= avg_len * 0.8]
    subsections = [it for it in toc_items if len(it.get('title', '')) > avg_len * 0.8]
    
    if len(chapters) == n_dividers:
        return chapters, subsections
    
    # 4. 无法识别，返回 None 触发强制分组
    return None, None


def _assign_divider_positions(toc_items: List[Dict], dividers: List[int]) -> None:
    """给没有 physical_index 的条目用 divider 物理位置赋值。
    
    智能识别主章节和子章节，确保 dividers 只分配给真正的主章节。
    """
    if not dividers:
        return
    
    # 只对顶级条目（无 "." 的 structure）赋 divider 位置
    top_items = [it for it in toc_items if "." not in it.get("structure", "")]
    
    # 如果数量匹配，直接分配
    if len(top_items) == len(dividers):
        for item, div in zip(top_items, dividers):
            if not item.get("physical_index"):
                item["physical_index"] = div
        return
    
    # 如果数量不匹配，使用智能识别
    chapters, subsections = _smart_identify_chapters(top_items, dividers)
    
    if chapters is not None and len(chapters) == len(dividers):
        # 分配 dividers 给主章节
        for item, div in zip(chapters, dividers):
            if not item.get("physical_index"):
                item["physical_index"] = div
        
        # 子章节不分配 physical_index（它们会被插入到主章节下）
        # 但先给它们一个临时位置，用于后续处理
        if subsections:
            print(f"[BALANCED-VIS] Identified {len(chapters)} chapters and {len(subsections)} subsections")
    else:
        # 无法识别，回退到原始行为（只分配前 N 个）
        for item, div in zip(top_items, dividers):
            if not item.get("physical_index"):
                item["physical_index"] = div


def _deduplicate(items: List[Dict]) -> List[Dict]:
    """去重: 相同标题 + 相近页码（±1）。"""
    if not items:
        return []
    seen = set()
    result = []
    for item in items:
        key = (item.get("title", "")[:30], item.get("physical_index", 0))
        is_dup = any(k[0] == key[0] and abs(k[1] - key[1]) <= 1 for k in seen)
        if not is_dup:
            seen.add(key)
            result.append(item)
    return result


def _normalize_mislabeled_logical_pages(toc_items: List[Dict], page_count: int) -> None:
    """Move logical TOC page numbers out of physical_index when mislabeled."""
    if any(item.get("page") is not None for item in toc_items):
        return

    candidates = [
        item
        for item in toc_items
        if isinstance(item.get("physical_index"), int)
        and not isinstance(item.get("physical_index"), bool)
        and item["physical_index"] > 0
    ]
    if not candidates:
        return

    out_of_range = [
        item for item in candidates
        if item["physical_index"] > page_count
    ]
    if len(out_of_range) < max(1, len(candidates) * 0.2):
        return

    print(
        f"[TOC-MAP] Normalizing {len(candidates)} logical page numbers "
        f"from physical_index ({len(out_of_range)} exceed page_count={page_count})"
    )
    for item in candidates:
        logical_page = item.get("physical_index")
        item["page"] = logical_page
        item["logical_page"] = logical_page
        item["physical_index"] = None


def _map_toc_physical_pages(
    toc_items: List[Dict],
    page_count: int,
    first_content_page: Optional[int],
    last_toc_page: int,
    ocr_text_map: Optional[Dict[int, str]] = None,
    dividers: Optional[List[int]] = None,
) -> None:
    """智能页码映射：检测目录页码可信度，自动选择映射策略。

    策略选择：
    1. OCR 标题搜索验证（最准确，优先）
    2. 标准 offset 法（页码可信）
    3. 均匀分配法（无页码或无法计算）
    """
    if not toc_items or page_count <= 0:
        return

    # 提取所有有 page 值的条目
    _normalize_mislabeled_logical_pages(toc_items, page_count)
    items_with_page = [it for it in toc_items if it.get("page") is not None]
    
    # 防御：如果已有 physical_index（VLM 已提取物理页码），保留它们
    items_with_physical = [it for it in toc_items if it.get("physical_index") is not None]
    if not items_with_page and items_with_physical:
        print(f"[TOC-MAP] No logical pages but {len(items_with_physical)} items already have physical_index, skipping mapping")
        # 只给没有 physical_index 的条目分配页码
        items_without = [it for it in toc_items if it.get("physical_index") is None]
        if items_without and dividers:
            _assign_divider_positions(toc_items, dividers)
        return
    
    if not items_with_page:
        print("[TOC-MAP] No logical pages found, using uniform distribution")
        # 如果提供了 dividers，优先用 dividers 给顶级条目定位
        if dividers:
            top_items = [it for it in toc_items if "." not in str(it.get("structure", ""))]
            if top_items and len(top_items) == len(dividers):
                print(f"[TOC-MAP] Using dividers for top-level items: {dividers}")
                for item, div in zip(top_items, dividers):
                    item["physical_index"] = div
                # 子章节（带点号的）不分配 dividers，保持原样或后续处理
                return
            # 如果顶级条目数量和 dividers 不匹配，尝试智能识别
            chapters, subsections = _smart_identify_chapters(toc_items, dividers)
            if chapters and len(chapters) == len(dividers):
                print(f"[TOC-MAP] Smart grouping: {len(chapters)} chapters + {len(subsections or [])} subsections")
                for item, div in zip(chapters, dividers):
                    item["physical_index"] = div
                return
        _map_uniformly(toc_items, page_count, first_content_page or last_toc_page + 1)
        return

    first_logical = items_with_page[0]["page"]
    last_logical = max(it["page"] for it in items_with_page)

    # 确定 first_content_page
    effective_first_content = first_content_page or (last_toc_page + 1)
    if effective_first_content > page_count:
        effective_first_content = last_toc_page + 1

    # Step 1: 计算初始 offset
    offset = effective_first_content - first_logical
    
    # 防御：offset < 0 意味着目录和正文之间有间隙（前言/空白页），
    # 或者目录中的页码本身就是物理页码。此时令 offset = 0。
    if offset < 0:
        print(
            f"[TOC-MAP] Negative offset detected ({offset}), "
            f"correcting to 0. This usually means there are preface pages "
            f"between TOC and content, or the TOC already uses physical page numbers."
        )
        offset = 0
    
    estimated_last = last_logical + offset

    # Step 2: OCR 验证（最优先）
    # 用第一个条目标题在 OCR 文本中搜索，找到真实物理页码
    if ocr_text_map:
        first_title = items_with_page[0].get("title", "")[:15]
        if first_title and len(first_title) >= 3:
            for phys_page in sorted(ocr_text_map.keys()):
                if phys_page <= last_toc_page:
                    continue  # 跳过目录页
                text = ocr_text_map.get(phys_page, "")
                if first_title in text:
                    # 找到了！用搜索结果修正 offset
                    corrected_offset = phys_page - first_logical
                    if corrected_offset != offset:
                        print(
                            f"[TOC-MAP] OCR verification: title='{first_title[:20]}' "
                            f"found at p.{phys_page}, "
                            f"correcting offset {offset} -> {corrected_offset}"
                        )
                        offset = corrected_offset
                    break

    # Step 3: 选择映射策略
    estimated_last = last_logical + offset
    TRUST_THRESHOLD = page_count * 1.2

    if estimated_last <= TRUST_THRESHOLD:
        # 页码可信：标准 offset（保留目录页码差值信息）
        print(
            f"[TOC-MAP] Standard offset: offset={offset}, "
            f"estimated_last={estimated_last}, threshold={TRUST_THRESHOLD}"
        )
        for item in items_with_page:
            logical = item.get("page")
            if logical is not None and isinstance(logical, (int, float)):
                physical = int(logical) + offset
                item["physical_index"] = max(1, min(page_count, physical))
            else:
                item["physical_index"] = None
    else:
        # 页码不可信（压缩/合并 PDF）：先检测是否是固定压缩
        logical_pages = [it["page"] for it in items_with_page]
        diffs = [logical_pages[i+1] - logical_pages[i] for i in range(len(logical_pages)-1)]

        from collections import Counter
        diff_counter = Counter(diffs)
        most_common_diff, most_common_count = diff_counter.most_common(1)[0]
        diff_ratio = most_common_count / len(diffs) if diffs else 0

        # 固定压缩：差值众数 >1 且占比 >= 80%
        is_fixed_compression = (
            most_common_diff > 1
            and diff_ratio >= 0.8
            and len(diffs) >= 3
        )

        if is_fixed_compression:
            # 固定压缩：每个条目在 PDF 中占 1 页，均匀分配
            print(
                f"[TOC-MAP] Fixed compression detected: "
                f"step={most_common_diff}, ratio={diff_ratio:.0%}, "
                f"using 1 page per item"
            )
            for i, item in enumerate(items_with_page):
                item["physical_index"] = min(
                    page_count, effective_first_content + i
                )
        else:
            # 非固定压缩：比例映射
            logical_range = last_logical - first_logical
            physical_range = page_count - effective_first_content + 1

            if logical_range > 0 and physical_range > 0:
                scale = physical_range / logical_range
                print(
                    f"[TOC-MAP] Proportional mapping: "
                    f"logical_range={logical_range}, physical_range={physical_range}, "
                    f"scale={scale:.3f}, estimated_last={estimated_last}, "
                    f"diffs={sorted(set(diffs))}"
                )
                for item in items_with_page:
                    logical = item.get("page", first_logical)
                    if logical is None:
                        continue
                    physical = effective_first_content + (logical - first_logical) * scale
                    item["physical_index"] = max(1, min(page_count, round(physical)))
            else:
                # 无法计算比例，fallback 到均匀分配
                print(
                    f"[TOC-MAP] Fallback to uniform: "
                    f"logical_range={logical_range}, physical_range={physical_range}"
                )
                _map_uniformly(toc_items, page_count, effective_first_content)

    # 确保单调递增且无重复
    _inherit_missing_physical_pages(toc_items, page_count, effective_first_content)
    _ensure_monotonic_physical(toc_items, page_count)


def _inherit_missing_physical_pages(
    toc_items: List[Dict], page_count: int, default_page: int
) -> None:
    """Give group headings a content page without consuming a mapping slot."""
    previous_page: Optional[int] = None

    for idx, item in enumerate(toc_items):
        current = item.get("physical_index")
        if isinstance(current, int) and not isinstance(current, bool) and current > 0:
            item["physical_index"] = max(1, min(page_count, current))
            previous_page = item["physical_index"]
            continue

        next_page = None
        for following in toc_items[idx + 1:]:
            candidate = following.get("physical_index")
            if (
                isinstance(candidate, int)
                and not isinstance(candidate, bool)
                and candidate > 0
            ):
                next_page = max(1, min(page_count, candidate))
                break

        inherited = next_page or previous_page or default_page
        item["physical_index"] = max(1, min(page_count, inherited))
        previous_page = item["physical_index"]


def _map_uniformly(
    toc_items: List[Dict], page_count: int, first_content_page: int
) -> None:
    """将条目均匀分配到文档页面。"""
    n = len(toc_items)
    available = page_count - first_content_page + 1
    if n <= 0 or available <= 0:
        return

    for i, item in enumerate(toc_items):
        # 防御：不覆盖已有的 physical_index
        if item.get("physical_index") is not None:
            continue
        physical = first_content_page + i * available / n
        item["physical_index"] = max(1, min(page_count, round(physical)))


def _classify_toc_item_type(item: Dict) -> str:
    """根据标题/编号特征分类目录条目类型。
    
    Returns:
        'chapter' | 'figure' | 'table' | 'appendix' | 'reference' | 'other'
    """
    title = str(item.get("title", "")).lower()
    number = str(item.get("number", "")).lower()
    text = f"{number} {title}"
    
    if "图目录" in text or "表目录" in text:
        return 'other'  # 过滤掉目录节点
    if any(k in text for k in ['图', 'figure', 'fig.']):
        return 'figure'
    elif any(k in text for k in ['表', 'table']):
        return 'table'
    elif any(k in text for k in ['附录', 'appendix']):
        return 'appendix'
    elif any(k in text for k in ['参考文献', 'references', 'reference']):
        return 'reference'
    elif any(k in text for k in ['致谢', 'acknowledgement']):
        return 'other'
    elif re.match(r'^\d', number) or '第' in number[:3]:
        return 'chapter'
    else:
        return 'other'


def _map_toc_physical_pages_partitioned(
    toc_items: List[Dict],
    page_count: int,
    first_content_page: Optional[int],
    last_toc_page: int,
    ocr_text_map: Optional[Dict[int, str]] = None,
    dividers: Optional[List[int]] = None,
) -> None:
    """分区版本的页码映射。
    
    将目录条目按类型分组（章节、图表、表格等），各组独立计算页码映射，
    避免不同类型条目互相干扰（如图表被章节强制递增到错误页码）。
    """
    if not toc_items or page_count <= 0:
        return
    
    # Step 1: 按类型分组，同时记录原始索引
    _normalize_mislabeled_logical_pages(toc_items, page_count)
    groups: Dict[str, List[Tuple[int, Dict]]] = {}
    for idx, item in enumerate(toc_items):
        item_type = _classify_toc_item_type(item)
        if item_type not in groups:
            groups[item_type] = []
        groups[item_type].append((idx, item))
    
    if len(groups) <= 1:
        # 只有一组，回退到原有逻辑
        _map_toc_physical_pages(
            toc_items, page_count, first_content_page, last_toc_page,
            ocr_text_map, dividers
        )
        return
    
    print(f"[TOC-MAP-PARTITION] {len(groups)} groups: {list(groups.keys())}")
    
    # Step 2: 计算统一的 offset（从章节组或所有条目）
    items_with_page = [it for it in toc_items if it.get("page") is not None]
    effective_first_content = first_content_page or (last_toc_page + 1)
    
    if items_with_page:
        first_logical = items_with_page[0]["page"]
        offset = effective_first_content - first_logical
        if offset < 0:
            offset = 0
    else:
        offset = 0
    
    # Step 3: 各组独立映射
    for group_type, indexed_items in groups.items():
        items = [item for _, item in indexed_items]
        
        if group_type in ('figure', 'table'):
            # 图表组：应用 offset，但组内单调不减（允许同页）
            for item in items:
                logical = item.get("page")
                if logical is not None and isinstance(logical, (int, float)):
                    physical = int(logical) + offset
                    item["physical_index"] = max(1, min(page_count, physical))
                else:
                    item["physical_index"] = None
            
            # 组内单调不减
            for i in range(1, len(items)):
                prev = items[i-1].get("physical_index")
                curr = items[i].get("physical_index")
                if prev is not None and curr is not None and curr < prev:
                    items[i]["physical_index"] = prev
                    
        else:
            # 章节/附录/参考文献：使用原有逻辑
            _map_toc_physical_pages(
                items, page_count, first_content_page, last_toc_page,
                ocr_text_map=None, dividers=None
            )
    
    # Step 4: 确保所有条目都有 physical_index
    for item in toc_items:
        if not item.get("physical_index"):
            logical = item.get("page")
            if logical is not None:
                item["physical_index"] = max(1, min(page_count, int(logical) + offset))
            else:
                item["physical_index"] = effective_first_content
    
    # 注意：不再调用全局 _ensure_monotonic_physical
    # 因为混合列表中，图表的页码可能小于后面的章节页码
    # 各组已在 Step 3 中独立确保单调性


def _ensure_monotonic_physical(toc_items: List[Dict], page_count: int) -> None:
    """确保 physical_index 单调不减且不超出 page_count。
    
    修复：从严格递增（>）改为单调不减（>=），允许同页多个条目。
    这对图表条目尤为重要（一页可以放多个图表）。
    """
    if not toc_items:
        return

    # 第一轮：确保单调不减（允许相等）
    for i in range(1, len(toc_items)):
        prev = toc_items[i - 1].get("physical_index") or 1
        curr = toc_items[i].get("physical_index") or prev
        
        # 防御：父子节点允许共享同一页码（如父章节和1.1子章节都在第4页开始）
        prev_struct = str(toc_items[i - 1].get("structure", ""))
        curr_struct = str(toc_items[i].get("structure", ""))
        if prev_struct and curr_struct.startswith(prev_struct + "."):
            continue  # 跳过父子节点的递增强制
        
        # 修复：从严格递增改为单调不减
        if curr < prev:
            # 当前页码倒退，修正为与前一项相同（单调不减）
            toc_items[i]["physical_index"] = prev

    # 第二轮：确保不超出 page_count
    for item in toc_items:
        pi = item.get("physical_index") or 1
        if pi > page_count:
            item["physical_index"] = page_count
        elif pi < 1:
            item["physical_index"] = 1


def _infer_structure_from_numbers(toc_items: List[Dict]) -> None:
    """从 VLM 转录的 number 字段推断层级 structure。

    纯代码逻辑，零 VLM/LLM 调用。

    支持的编号格式：
    - 阿拉伯数字："1", "1.1", "1.2.3" → 直接作为 structure
    - 中文序号："一" → "1"; "二" → "2"
    - 带括号中文："（一）" → 延续上一级的子编号
    - 纯数字子级："1" 在 "一" 之后 → "1.1"
    - 空编号：视为与上一条同级的兄弟节点
    - 所有编号为空：视为全平级，按序号分配 "1", "2", "3"...
    """
    if not toc_items:
        return

    # 中文数字映射
    CN_MAP = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }

    numbers = [item.get("number", "") for item in toc_items]

    # 检测是否所有 number 都为空 → 全平级
    if all(not n for n in numbers):
        print("[TOC-INFER] All numbers empty, assigning flat structure")
        for i, item in enumerate(toc_items, 1):
            item["structure"] = str(i)
        return

    # 检测编号模式
    dot_count = sum(1 for n in numbers if "." in n)
    cn_count = sum(1 for n in numbers if any(c in n for c in CN_MAP))

    if dot_count > len(numbers) * 0.5:
        # 阿拉伯数字层级模式（如 1, 1.1, 1.2, 2, 2.1...）
        _infer_dot_structure(toc_items, numbers)
    elif cn_count > len(numbers) * 0.5:
        # 中文序号模式（如一、二、三...）
        _infer_cn_structure(toc_items, numbers)
    else:
        # 混合/不确定模式：按出现顺序分配
        _infer_mixed_structure(toc_items, numbers)
    
    # P2-fix: 为 structure 仍为空的主章节分配序号
    # 这通常发生在主章节标题没有 number 字段时
    _fix_empty_structures(toc_items)


def _infer_dot_structure(toc_items: List[Dict], numbers: List[str]) -> None:
    """推断阿拉伯数字编号的层级。"""
    for item, num in zip(toc_items, numbers):
        if num and all(c.isdigit() or c == "." for c in num):
            item["structure"] = num
        elif num and any(c.isdigit() for c in num):
            # 包含数字的混合编号，提取数字部分
            digits = "".join(c for c in num if c.isdigit() or c == ".")
            item["structure"] = digits or num
        else:
            item["structure"] = num or ""


def _infer_cn_structure(toc_items: List[Dict], numbers: List[str]) -> None:
    """推断中文序号编号的层级。"""
    CN_MAP = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }

    current_top = 0
    current_sub = 0

    for item, num in zip(toc_items, numbers):
        if not num:
            # 空编号，视为同行
            if "current_top" in dir():
                current_sub += 1
                item["structure"] = f"{current_top}.{current_sub}"
            else:
                item["structure"] = str(len(toc_items) + 1)
            continue

        # 纯中文序号：一、二... → 顶级
        if num in CN_MAP:
            current_top = CN_MAP[num]
            item["structure"] = str(current_top)
            current_sub = 0
            continue

        # 带括号：（一）、（二）... → 子级
        paren_match = re.match(r"^[（(]([一二三四五六七八九十]+)[）)]$", num)
        if paren_match and paren_match.group(1) in CN_MAP:
            current_sub = CN_MAP[paren_match.group(1)]
            item["structure"] = f"{current_top}.{current_sub}"
            continue

        # 阿拉伯数字子级：如 "1" 跟在 "一" 后面 → 子级
        if num.isdigit() and current_top > 0:
            current_sub = int(num)
            item["structure"] = f"{current_top}.{current_sub}"
            continue

        # 包含点号 → 直接用
        if "." in num:
            item["structure"] = num
            continue

        # 默认
        item["structure"] = num or ""


def _infer_mixed_structure(toc_items: List[Dict], numbers: List[str]) -> None:
    """混合编号模式：按占位符策略分配。"""
    for i, (item, num) in enumerate(zip(toc_items, numbers), 1):
        if num and "." in num:
            item["structure"] = num
        elif num and all(c.isdigit() for c in num):
            item["structure"] = num
        elif num:
            item["structure"] = num
        else:
            item["structure"] = str(i)


def _fix_empty_structures(toc_items: List[Dict]) -> None:
    """为 structure 为空的主章节分配序号。
    
    当 VLM 没有给主章节分配 number 时，structure 会为空。
    这导致 build_tree 无法识别章节边界。
    """
    # 找到所有 structure 为空的条目
    empty_items = [i for i, item in enumerate(toc_items) if not item.get("structure")]
    
    if not empty_items:
        return
    
    print(f"[TOC-INFER] Fixing {len(empty_items)} empty structures")
    
    # 为每个空 structure 分配序号
    chapter_counter = 0
    last_seen_chapter = 0
    
    for i, item in enumerate(toc_items):
        struct = item.get("structure", "")
        
        if not struct:
            # 这是一个没有 structure 的条目
            # 检查它是否是主章节（后面跟着子章节如 X.Y）
            is_main_chapter = False
            
            # 检查后面的条目是否有子章节编号
            for j in range(i + 1, min(i + 5, len(toc_items))):
                next_struct = toc_items[j].get("structure", "")
                if "." in str(next_struct):
                    # 后面的条目有子编号，说明当前是主章节
                    is_main_chapter = True
                    break
                elif next_struct:
                    # 后面的条目有 structure 但没有 "."，可能是同级主章节
                    break
            
            if is_main_chapter:
                chapter_counter += 1
                item["structure"] = str(chapter_counter)
                last_seen_chapter = chapter_counter
            else:
                # 可能是同级条目或导语
                if last_seen_chapter > 0:
                    # 作为前一个主章节的子章节
                    # 找到前一个主章节下最大的子序号
                    max_sub = 0
                    for prev_item in toc_items[:i]:
                        prev_struct = str(prev_item.get("structure", ""))
                        if prev_struct.startswith(f"{last_seen_chapter}."):
                            try:
                                sub_num = int(prev_struct.split(".")[1])
                                max_sub = max(max_sub, sub_num)
                            except:
                                pass
                    item["structure"] = f"{last_seen_chapter}.{max_sub + 1}"
                else:
                    # 作为独立章节
                    chapter_counter += 1
                    item["structure"] = str(chapter_counter)
                    last_seen_chapter = chapter_counter


async def _vlm_extract_page_titles(
    file_path: str,
    page_indices: List[int],
    model: Optional[str] = None,
    thumb_width: int = 400,
    thumb_height: int = 500,
    parent_context: str = "",
    detect_type: bool = False,
) -> List[Dict]:
    """VLM 缩略图网格提取每页标题。

    physical_index 从 page_indices 计算（100% 准确），不让 VLM 返回。

    Args:
        file_path: PDF 文件路径
        page_indices: 要渲染的页面列表（0-indexed）
        model: VLM 模型名称
        thumb_width: 缩略图宽度（默认 400）
        thumb_height: 缩略图高度（默认 500）
        parent_context: 章节上下文信息（如章节标题），用于引导 VLM
        detect_type: 是否检测页面类型（chapter/content/skip）

    Returns:
        [{"title": "...", "physical_index": N, "type": "chapter"|"content"|"skip"}, ...]
    """
    import io, math, base64
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    if not page_indices:
        return []

    doc = pymupdf.open(file_path)
    total = len(page_indices)
    cols = 2
    pages_per_grid = 4

    grids = []
    grid_page_indices = []  # 每个网格对应的 page_indices
    for batch_start in range(0, total, pages_per_grid):
        batch_indices = page_indices[batch_start:batch_start + pages_per_grid]
        n_pages = len(batch_indices)
        rows = math.ceil(n_pages / cols)

        padding = 16
        label_height = 24
        canvas_width = cols * (thumb_width + padding) + padding
        canvas_height = rows * (thumb_height + label_height + padding) + padding

        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(canvas)

        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font = ImageFont.load_default()

        for i, page_idx in enumerate(batch_indices):
            if page_idx < 0 or page_idx >= len(doc):
                continue
            row = i // cols
            col = i % cols
            x = padding + col * (thumb_width + padding)
            y = padding + row * (thumb_height + label_height + padding)

            page = doc[page_idx]
            page_rect = page.rect
            scale = min(thumb_width / page_rect.width, thumb_height / page_rect.height)

            mat = pymupdf.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat)
            thumb_img = Image.open(io.BytesIO(pix.tobytes("png")))

            offset_x = (thumb_width - thumb_img.width) // 2
            offset_y = (thumb_height - thumb_img.height) // 2
            canvas.paste(thumb_img, (x + offset_x, y + label_height + offset_y))

            draw.rectangle(
                [x, y + label_height, x + thumb_width, y + label_height + thumb_height],
                outline="#999999",
                width=1,
            )
            draw.text((x + 4, y + 2), f"p.{page_idx + 1}", fill="black", font=font)

        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        grids.append({"image_base64": b64})
        grid_page_indices.append(batch_indices)

    doc.close()

    if not grids:
        return []

    # 根据 detect_type 选择不同的 prompt
    if detect_type:
        prompt = """这些是一份文档的连续页面截图（2x2 网格排列，每页左上角标注了页码 p.N）。

请从左到右、从上到下，按顺序识别每一页的标题和类型：

类型判断：
- "chapter"：章节起始页（页面上方有大标题，通常是新章节/新主题的开始）
- "content"：内容页（有子标题或正文内容）
- "skip"：封面、目录、空白、广告页

返回 JSON 数组，每个元素对应网格中的一张图（从左到右、从上到下）：
[{"title": "标题", "type": "chapter"}, {"title": "子标题", "type": "content"}, {"title": null, "type": "skip"}, ...]

注意：
- 必须为网格中的每张图返回一个元素，即使该页没有标题
- 如果某页是封面/目录/空白，type 设为 "skip"，title 设为 null
- 只返回 JSON，不要其他文字"""
    else:
        prompt = f"""这些是一份文档的连续页面截图（2x2 网格排列，每页左上角标注了页码 p.N）。
{f'当前正在分析的章节是："{parent_context}"。' if parent_context else ''}
{f'请只提取属于"{parent_context}"这个章节的子标题。' if parent_context else ''}

请从左到右、从上到下，按顺序提取每一页的标题：
- 标题通常是页面上方最醒目的文字（字号最大、粗体、特殊颜色）
- 如果某页没有标题（纯图片、正文内容、空白），跳过该页
- 封面页、目录页、广告页跳过

只返回标题列表，按顺序排列，不要返回页码：
["标题1", "标题2", ...]"""

    all_items = []
    max_tokens_per_batch = 1000

    for grid, batch_indices in zip(grids, grid_page_indices):
        try:
            raw = await vlm_call_with_images(
                [grid], prompt, model=model, max_tokens=max_tokens_per_batch
            )
            result = parse_vlm_json(raw)
            if isinstance(result, list):
                # VLM 返回列表，顺序对应网格中的页面
                for idx, item in zip(batch_indices, result):
                    if detect_type:
                        # detect_type 模式：item 是 {"title": ..., "type": ...}
                        if isinstance(item, dict):
                            title = item.get("title")
                            page_type = item.get("type", "skip")
                            if page_type != "skip" and title and isinstance(title, str):
                                all_items.append({
                                    "title": title.strip(),
                                    "physical_index": idx + 1,
                                    "type": page_type,
                                })
                        elif isinstance(item, str) and item.strip():
                            # 兼容 VLM 只返回标题字符串的情况
                            all_items.append({
                                "title": item.strip(),
                                "physical_index": idx + 1,
                                "type": "content",
                            })
                    else:
                        # 普通模式：item 是标题字符串
                        title = item if isinstance(item, str) else (item.get("title") if isinstance(item, dict) else None)
                        if title and isinstance(title, str) and title.strip():
                            all_items.append({
                                "title": title.strip(),
                                "physical_index": idx + 1,
                            })
        except Exception as e:
            print(f"[VLM-PAGE-TITLE] Batch error: {e}")

    print(f"[VLM-PAGE-TITLE] Extracted {len(all_items)} page titles from {len(page_indices)} pages")
    return all_items


async def _vlm_scan_document_pages(
    file_path: str,
    page_count: int,
    model: Optional[str] = None,
) -> List[Dict]:
    """逐页扫描整个文档，提取每页标题和类型。

    用于无目录页的文档（如纯图片型报告）。
    physical_index 从页面顺序计算（100% 准确）。

    Args:
        file_path: PDF 文件路径
        page_count: 文档总页数
        model: VLM 模型名称

    Returns:
        [{"title": "...", "physical_index": N, "type": "chapter"|"content"|"skip"}, ...]
    """
    page_indices = list(range(page_count))
    return await _vlm_extract_page_titles(
        file_path, page_indices, model=model,
        detect_type=True,
    )
