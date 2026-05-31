"""Balanced TOC 模式 v3: 按文本质量路由到文本 LLM 或视觉 VLM。

视觉路径: 缩略图锚点检测 → 目录页提取+offset → 分段分析 → 验证修复
文本路径: LLM generate_toc_init/continue → 验证修复
"""

import asyncio
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from pageindex.vlm_utils import (
    render_pages_to_images,
    render_thumbnail_grids,
    vlm_call_with_images,
    parse_vlm_json,
)
from pageindex.fast_toc import verify_content_match, apply_offset
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


# ===========================================================================
# Balanced 视觉路径
# ===========================================================================


async def build_balanced_toc_visual(
    file_path: str,
    analysis: Dict,
    model: Optional[str] = None,
    anchors: Optional[Dict] = None,
    ocr_text_map: Optional[Dict[int, str]] = None,
) -> Dict:
    """Balanced 视觉路径: 缩略图锚点 → 目录提取 → 全文分析。"""
    page_count = analysis["page_count"]

    # ─── Phase 0.5: 缩略图锚点检测 (1 次 VLM) ───
    if anchors is None:
        print("[BALANCED-VIS] Phase 0.5: anchor detection via thumbnail grids")
        anchors = await _vlm_detect_anchors(file_path, model)
    else:
        print("[BALANCED-VIS] Phase 0.5: using provided anchors")

    toc_pages = anchors.get("toc_pages", [])
    dividers = anchors.get("chapter_dividers", [])
    first_content = anchors.get("first_content_page")

    # P0-6: 合并代码检测的章节分隔页（用于"汇报提纲"等VLM难以识别的模式）
    code_dividers = analysis.get("chapter_dividers", [])
    if code_dividers and not dividers:
        print(f"[BALANCED-VIS] Using code-detected chapter dividers: {code_dividers}")
        dividers = code_dividers
        # 如果 VLM 没有检测到 first_content，使用第一个 divider
        if not first_content and dividers:
            first_content = dividers[0]
    elif code_dividers and dividers:
        # VLM 和代码都检测到了，取并集（去重+排序）
        merged = sorted(set(dividers + code_dividers))
        if merged != dividers:
            print(f"[BALANCED-VIS] Merged dividers: {dividers} + {code_dividers} = {merged}")
            dividers = merged

    # 分类 divider 密度
    divider_density = len(dividers) / page_count if page_count > 0 else 0
    print(
        f"[BALANCED-VIS] Anchors: toc_pages={toc_pages}, "
        f"dividers={len(dividers)} (density={divider_density:.0%}), "
        f"first_content={first_content}"
    )

    # ─── Phase 1: TOC 构建（分支） ───

    # 分支 A: 有目录页
    if toc_pages:
        result = await _branch_a_toc_page(
            file_path, page_count, toc_pages, dividers, model,
            first_content_page=first_content,
            ocr_text_map=ocr_text_map,
        )
        if result:
            return result

    # 分支 B: 无目录但有 divider
    if dividers:
        if divider_density > 0.4:
            # 密集 divider → divider 列表当 TOC
            result = await _branch_b_dense_dividers(
                file_path, page_count, dividers, model
            )
        else:
            # 正常 divider → 按 divider 分组
            result = await _branch_b_normal_dividers(
                file_path, page_count, dividers, model
            )
        if result:
            return result

    # 分支 C: 无任何锚点 → 分层全文分析
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
    _map_toc_physical_pages(
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
            prev_pi = toc_items[i-1].get("physical_index", last_toc) if i > 0 else last_toc
            item["physical_index"] = prev_pi + 1

    pis = [it.get("physical_index", 0) for it in toc_items]
    print(
        f"[BALANCED-VIS] Branch A: {len(toc_items)} items, "
        f"physical_range={min(pis)}-{max(pis)} (page_count={page_count})"
    )

    # Task 3: 大节点检测 — 对 span ≥ 8 页的节点做 VLM 子章节发现
    LARGE_NODE_THRESHOLD = 8
    large_count = 0
    for i, item in enumerate(toc_items):
        start = item.get("physical_index", 0)
        if not start or start < 1:
            continue
        if i < len(toc_items) - 1:
            next_start = toc_items[i + 1].get("physical_index", start + 1)
            estimated_end = max(next_start - 1, start)
        else:
            estimated_end = page_count
        if estimated_end - start + 1 >= LARGE_NODE_THRESHOLD:
            large_count += 1

    # 判断是否需要全页扫描（条件：条目少 + 有大节点）
    need_full_scan = len(toc_items) < 10 and large_count > 0 and model

    if need_full_scan:
        print(
            f"[BALANCED-VIS] Detected {large_count} large nodes (span >= {LARGE_NODE_THRESHOLD}), "
            f"toc_items={len(toc_items)} < 10, running full document scan"
        )

        # Phase 2: 全页扫描
        page_titles = await _vlm_scan_document_pages(
            file_path, page_count, model=model
        )

        # Phase 3: 用目录标题匹配章节边界
        # 构建章节起始页映射
        chapter_boundaries = []
        for item in toc_items:
            toc_title = item.get("title", "")
            if not toc_title:
                continue
            # 在 page_titles 中找匹配的章节起始页
            # 匹配策略：TOC 标题的前 10 字符在页面标题中出现
            toc_prefix = toc_title[:10].strip()
            for pt in page_titles:
                page_title = pt.get("title", "")
                if pt.get("type") == "chapter" and toc_prefix and toc_prefix in page_title:
                    chapter_boundaries.append({
                        "structure": item.get("structure", ""),
                        "title": toc_title,
                        "start_page": pt["physical_index"],
                    })
                    break

        # 按起始页排序
        chapter_boundaries.sort(key=lambda x: x["start_page"])

        # 如果没有匹配到章节边界，用目录标题直接匹配 page_titles
        if not chapter_boundaries:
            print("[BALANCED-VIS] No chapter boundaries matched, using TOC titles directly")
            for item in toc_items:
                toc_title = item.get("title", "")
                toc_prefix = toc_title[:10].strip()
                for pt in page_titles:
                    page_title = pt.get("title", "")
                    if toc_prefix and toc_prefix in page_title and pt.get("physical_index", 0) > last_toc:
                        chapter_boundaries.append({
                            "structure": item.get("structure", ""),
                            "title": toc_title,
                            "start_page": pt["physical_index"],
                        })
                        break

        # 构建子节点
        insertions = []
        parent_count = 0
        for cb_idx, cb in enumerate(chapter_boundaries):
            start = cb["start_page"]
            # 确定章节结束页
            if cb_idx < len(chapter_boundaries) - 1:
                end = chapter_boundaries[cb_idx + 1]["start_page"] - 1
            else:
                end = page_count

            # 从 page_titles 中提取该章节范围内的子节点
            sub_items = [
                pt for pt in page_titles
                if start <= pt["physical_index"] <= end
                and pt.get("type") != "chapter"  # 排除章节起始页本身
            ]

            if sub_items:
                parent_count += 1
                parent_structure = str(parent_count)

                # 找到对应的 toc_item 并更新
                toc_item = None
                for item in toc_items:
                    if item.get("title", "")[:15] == cb["title"][:15]:
                        toc_item = item
                        break

                if toc_item:
                    toc_item["structure"] = parent_structure
                    toc_item["physical_index"] = start

                    valid_children = []
                    for j, si in enumerate(sub_items, 1):
                        pi = si.get("physical_index", 0)
                        if pi and start <= pi <= end:
                            valid_children.append({
                                "structure": f"{parent_structure}.{j}",
                                "title": si.get("title", ""),
                                "physical_index": pi,
                            })

                    if valid_children:
                        child_pis = [c["physical_index"] for c in valid_children]
                        toc_item["physical_index"] = min(child_pis)
                        for j, child in enumerate(valid_children, 1):
                            child["structure"] = f"{parent_structure}.{j}"

                    insertions.append((toc_items.index(toc_item), valid_children))
                    print(
                        f"[BALANCED-VIS] Chapter '{cb['title'][:30]}' -> structure={parent_structure}, "
                        f"{len(valid_children)} sub-items, range={start}-{end}"
                    )

        # 倒序插入
        for parent_idx, children in reversed(insertions):
            insert_pos = parent_idx + 1
            for child in reversed(children):
                toc_items.insert(insert_pos, child)

    elif large_count > 0 and model:
        # 原有逻辑：对每个大节点单独做 VLM 子章节提取
        print(
            f"[BALANCED-VIS] Detected {large_count} large nodes (span >= {LARGE_NODE_THRESHOLD}), "
            f"running per-node VLM sub-title extraction"
        )

        insertions = []
        parent_count = 0
        for i, item in enumerate(toc_items):
            start = item.get("physical_index", 0)
            if not start or start < 1:
                continue
            if i < len(toc_items) - 1:
                next_start = toc_items[i + 1].get("physical_index", start + 1)
                estimated_end = max(next_start - 1, start)
            else:
                estimated_end = page_count
            span = estimated_end - start + 1
            if span < LARGE_NODE_THRESHOLD:
                continue

            page_range = list(range(start - 1, min(estimated_end, page_count)))
            parent_context = item.get("title", "")

            sub_items = await _vlm_extract_page_titles(
                file_path, page_range, model=model,
                parent_context=parent_context,
            )
            if sub_items:
                parent_count += 1
                parent_structure = str(parent_count)
                item["structure"] = parent_structure

                valid_children = []
                for j, si in enumerate(sub_items, 1):
                    pi = si.get("physical_index", 0)
                    if pi and start <= pi <= estimated_end:
                        valid_children.append({
                            "structure": f"{parent_structure}.{j}",
                            "title": si.get("title", ""),
                            "physical_index": pi,
                        })
                    else:
                        if pi:
                            print(
                                f"[BALANCED-VIS] Filtered out sub-item (pi={pi}, "
                                f"not in range {start}-{estimated_end}): "
                                f"{si.get('title', '')[:30]}"
                            )

                if valid_children:
                    child_pis = [c["physical_index"] for c in valid_children]
                    item["physical_index"] = min(child_pis)
                    new_end = max(child_pis)
                    if new_end < estimated_end:
                        estimated_end = new_end
                    for j, child in enumerate(valid_children, 1):
                        child["structure"] = f"{parent_structure}.{j}"

                insertions.append((i, valid_children))
                print(
                    f"[BALANCED-VIS] Node '{item.get('title', '')[:30]}' -> structure={parent_structure}, "
                    f"{len(valid_children)} sub-items (filtered from {len(sub_items)}), "
                    f"range={item.get('physical_index')}-{estimated_end}"
                )

        # 倒序插入
        for parent_idx, children in reversed(insertions):
            insert_pos = parent_idx + 1
            for child in reversed(children):
                toc_items.insert(insert_pos, child)

        # Task 3: 去重 — 同一 physical_index 出现多次时，保留 structure 编号最小的
        seen_pi = {}
        deduped = []
        removed = 0
        for item in toc_items:
            pi = item.get("physical_index", 0)
            if pi and pi in seen_pi:
                # 同一 physical_index 已存在，比较 structure 编号
                existing = seen_pi[pi]
                existing_struct = existing.get("structure", "999")
                current_struct = item.get("structure", "999")
                if current_struct < existing_struct:
                    # 当前 structure 更小（更优先），替换
                    deduped.remove(existing)
                    deduped.append(item)
                    seen_pi[pi] = item
                removed += 1
            else:
                deduped.append(item)
                if pi:
                    seen_pi[pi] = item
        
        if removed > 0:
            print(f"[BALANCED-VIS] Deduplication: removed {removed} duplicate nodes")
            toc_items.clear()
            toc_items.extend(deduped)

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
    """正常 divider: 按 divider 切分，每段 VLM 分析子章节。"""
    all_items = []

    # 构建分组: 每个 divider 到下一个 divider-1
    groups = []
    for i, div in enumerate(dividers):
        if i < len(dividers) - 1:
            end = dividers[i + 1] - 1
        else:
            end = page_count
        groups.append((div, end))

    for start, end in groups:
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

        print(f"[BALANCED-VIS] Branch B (normal): pages {start}-{end}")
        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=8000)
        try:
            items = parse_vlm_json(raw)
            if isinstance(items, list):
                all_items.extend(items)
        except Exception as e:
            print(f"[BALANCED-VIS] Group {start}-{end} failed: {e}")

    if len(all_items) >= 2:
        return {"toc_items": _deduplicate(all_items), "source": "vlm_divider_groups"}
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

    return {"toc_items": toc_items, "source": "llm_text"}


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
                sub_pi = sub.get("physical_index", 0)
                if ch_start <= sub_pi < ch_end:
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
            sub_pi = sub.get("physical_index", 0)
            if ch_start <= sub_pi < ch_end:
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
    items_with_page = [it for it in toc_items if it.get("page") is not None]
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
        for item in toc_items:
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
            for i, item in enumerate(toc_items):
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
                for item in toc_items:
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
    _ensure_monotonic_physical(toc_items, page_count)


def _map_uniformly(
    toc_items: List[Dict], page_count: int, first_content_page: int
) -> None:
    """将条目均匀分配到文档页面。"""
    n = len(toc_items)
    available = page_count - first_content_page + 1
    if n <= 0 or available <= 0:
        return

    for i, item in enumerate(toc_items):
        physical = first_content_page + i * available / n
        item["physical_index"] = max(1, min(page_count, round(physical)))


def _ensure_monotonic_physical(toc_items: List[Dict], page_count: int) -> None:
    """确保 physical_index 单调递增且不超出 page_count。"""
    if not toc_items:
        return

    # 第一轮：确保单调递增
    for i in range(1, len(toc_items)):
        prev = toc_items[i - 1].get("physical_index", 1)
        curr = toc_items[i].get("physical_index", prev)
        if curr <= prev:
            # 至少比前一个多 1 页
            toc_items[i]["physical_index"] = min(page_count, prev + 1)

    # 第二轮：确保不超出 page_count
    for item in toc_items:
        pi = item.get("physical_index", 1)
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
