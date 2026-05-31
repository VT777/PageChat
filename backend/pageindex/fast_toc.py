"""Fast TOC 模式：代码提取 + offset 校验 + LLM 质检。

输入：pdf_analyzer 的文档画像
输出：{"toc_items": [...], "source": str} 或 None
LLM 调用：最多 1 次（质检）
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from pageindex.pdf_analyzer import _normalize_for_search


# ---------------------------------------------------------------------------
# offset 校验 + 内容匹配
# ---------------------------------------------------------------------------


def verify_content_match(
    toc_items: List[Dict],
    page_list: List[Tuple[str, int]],
    sample_size: int = 12,
) -> Dict[str, Any]:
    """抽样验证 TOC 条目标题是否出现在对应 physical_index 的页面上。

    Returns:
        {
            "match_rate": 0.0-1.0,
            "offset_median": int,
            "mismatches": [...],
            "total_checked": int,
        }
    """
    if not page_list or not toc_items:
        return {
            "match_rate": 0,
            "offset_median": 0,
            "mismatches": [],
            "total_checked": 0,
        }

    n = len(toc_items)
    if n <= sample_size:
        indices = list(range(n))
    else:
        # 前 4 + 中 4 + 后 4
        indices = (
            list(range(min(4, n)))
            + list(range(max(0, n // 2 - 2), min(n, n // 2 + 2)))
            + list(range(max(0, n - 4), n))
        )
        indices = sorted(set(i for i in indices if 0 <= i < n))

    matches = 0
    offsets = []
    mismatches = []

    for i in indices:
        item = toc_items[i]
        title = item.get("title", "").strip()
        claimed_page = item.get("physical_index")

        if not title or len(title) < 3 or not claimed_page or claimed_page < 1:
            mismatches.append({"index": i, "title": title[:40], "reason": "invalid"})
            continue

        search_key = _normalize_for_search(title[:30])
        if len(search_key) < 2:
            mismatches.append(
                {"index": i, "title": title[:40], "reason": "key_too_short"}
            )
            continue

        found_page = None
        # 在 claimed_page ±5 页窗口搜索
        for delta in range(-5, 6):
            page_idx = claimed_page - 1 + delta
            if 0 <= page_idx < len(page_list):
                normalized_page = _normalize_for_search(page_list[page_idx][0][:3000])
                if search_key in normalized_page:
                    found_page = page_idx + 1
                    break

        if found_page == claimed_page:
            matches += 1
        elif found_page is not None:
            offsets.append(found_page - claimed_page)
            mismatches.append(
                {
                    "index": i,
                    "title": title[:40],
                    "claimed": claimed_page,
                    "actual": found_page,
                }
            )
        else:
            mismatches.append(
                {
                    "index": i,
                    "title": title[:40],
                    "claimed": claimed_page,
                    "reason": "not_found",
                }
            )

    total = len(indices)
    match_rate = matches / total if total > 0 else 0
    offset_median = 0
    if offsets:
        offsets.sort()
        offset_median = offsets[len(offsets) // 2]

    return {
        "match_rate": match_rate,
        "offset_median": offset_median,
        "mismatches": mismatches,
        "total_checked": total,
    }


def apply_offset(toc_items: List[Dict], offset: int) -> None:
    """原地应用 offset 校正到所有条目。"""
    if offset == 0:
        return
    for item in toc_items:
        if item.get("physical_index") is not None:
            item["physical_index"] = max(1, item["physical_index"] + offset)


# ---------------------------------------------------------------------------
# LLM 质检
# ---------------------------------------------------------------------------


async def llm_validate_toc(
    toc_items: List[Dict],
    page_count: int,
    match_info: Dict[str, Any],
    model: Optional[str] = None,
) -> bool:
    """LLM 轻校验 TOC 质量。1 次调用。

    Returns:
        True = 通过, False = 不通过
    """
    from pageindex.vlm_utils import parse_vlm_json
    from pageindex.utils import ChatGPT_API_async
    from app.prompts.pageindex_prompts import TOC_LIGHT_VALIDATION_PROMPT

    toc_outline = "\n".join(
        f"  {item.get('structure', '?')} {item['title']}  -> p.{item['physical_index']}"
        for item in toc_items
    )

    mismatch_details = "无"
    if match_info.get("mismatches"):
        parts = []
        for m in match_info["mismatches"][:5]:
            if "actual" in m:
                parts.append(f"'{m['title']}' 声称p.{m['claimed']}→实际p.{m['actual']}")
            else:
                parts.append(
                    f"'{m['title']}' 声称p.{m.get('claimed', '?')} {m.get('reason', '')}"
                )
        mismatch_details = "; ".join(parts)

    prompt = TOC_LIGHT_VALIDATION_PROMPT.format(
        page_count=page_count,
        toc_count=len(toc_items),
        toc_outline=toc_outline,
        match_rate=match_info.get("match_rate", 0),
        offset_median=match_info.get("offset_median", 0),
        mismatch_details=mismatch_details,
    )

    try:
        response = await ChatGPT_API_async(model=model, prompt=prompt)
        parsed = parse_vlm_json(response)
        valid = parsed.get("valid", "no") if isinstance(parsed, dict) else "no"
        reason = parsed.get("reason", "") if isinstance(parsed, dict) else ""
        print(f"[FAST-TOC] LLM validation: valid={valid}, reason={reason}")
        return valid == "yes"
    except Exception as e:
        # LLM 失败时，如果覆盖度 >= 70% 且匹配率 >= 50% 则接受
        last_page = max((it.get("physical_index", 0) for it in toc_items), default=0)
        if last_page >= page_count * 0.7 and match_info.get("match_rate", 0) >= 0.5:
            print(f"[FAST-TOC] LLM error: {e}, accepting (good coverage + match)")
            return True
        print(f"[FAST-TOC] LLM error: {e}, rejecting")
        return False


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def try_fast_toc(
    analysis: Dict[str, Any],
    model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Fast 模式 TOC 提取。

    Args:
        analysis: pdf_analyzer.analyze_pdf_structure 的输出
        model: LLM 模型名称

    Returns:
        {"toc_items": [...], "source": str} 或 None
    """
    code_toc = analysis.get("code_toc", {})
    toc_items = code_toc.get("items")
    source = code_toc.get("source")

    if not toc_items or len(toc_items) < 2:
        print("[FAST-TOC] No code TOC available")
        return None

    page_count = analysis["page_count"]
    page_list = analysis.get("page_list", [])

    print(f"[FAST-TOC] Code TOC: {len(toc_items)} items via {source}")

    # 1. 正则提取的 TOC 页码是逻辑页码，先做 offset 校正
    if source == "regex":
        check = verify_content_match(toc_items, page_list)
        print(
            f"[FAST-TOC] Pre-offset match: {check['match_rate']:.0%}, offset_median={check['offset_median']:+d}"
        )
        if check["offset_median"] != 0:
            apply_offset(toc_items, check["offset_median"])
            print(f"[FAST-TOC] Applied offset {check['offset_median']:+d}")

    # 2. 内容验证（区分来源）
    if source in ("bookmarks", "links"):
        # 书签/链接：直接信任元数据，只检查页码有效性
        valid_pages = all(1 <= it.get("physical_index", 0) <= page_count for it in toc_items)
        if not valid_pages:
            print("[FAST-TOC] Bookmarks/links have invalid page numbers, rejecting")
            return None
        # 检查页码单调递增
        pages = [it.get("physical_index", 0) for it in toc_items]
        is_monotonic = all(pages[i] <= pages[i+1] for i in range(len(pages)-1))
        if not is_monotonic:
            print("[FAST-TOC] Bookmarks/links page numbers not monotonic, rejecting")
            return None
        print(f"[FAST-TOC] Bookmarks/links: trusted source, {len(toc_items)} items")
        match_info = {"match_rate": 1.0, "total_checked": len(toc_items), "offset_median": 0}
    else:
        # 正则：需要内容验证
        match_info = verify_content_match(toc_items, page_list)
        print(
            f"[FAST-TOC] Content match: {match_info['match_rate']:.0%} "
            f"({match_info['total_checked']} checked)"
        )

        # 匹配率太低直接拒绝
        if match_info["match_rate"] < 0.1:
            print(f"[FAST-TOC] Match rate {match_info['match_rate']:.0%} < 10%, rejecting")
            return None

        # 如果验证后仍有系统性偏移（可能 Level 1/2 也有偏移），再校正一次
        if match_info["offset_median"] != 0:
            apply_offset(toc_items, match_info["offset_median"])
            print(
                f"[FAST-TOC] Secondary offset correction: {match_info['offset_median']:+d}"
            )
            # 重新验证
            match_info = verify_content_match(toc_items, page_list)
            print(f"[FAST-TOC] Post-correction match: {match_info['match_rate']:.0%}")

    # 3. 覆盖度预检（区分来源）
    last_page = max((it.get("physical_index", 0) for it in toc_items), default=0)
    if source in ("bookmarks", "links"):
        # 书签/链接：可能不包含封底/附录，放宽到10%
        if last_page < page_count * 0.1:
            print(f"[FAST-TOC] Coverage {last_page}/{page_count} < 10%, rejecting")
            return None
    else:
        # 正则：保持30%标准
        if last_page < page_count * 0.3:
            print(f"[FAST-TOC] Coverage {last_page}/{page_count} < 30%, rejecting")
            return None

    # 4. LLM 质检（区分来源）
    if source in ("bookmarks", "links"):
        # 书签/链接：跳过LLM质检，直接信任
        print("[FAST-TOC] Bookmarks/links: skipping LLM validation")
        valid = True
    else:
        valid = await llm_validate_toc(toc_items, page_count, match_info, model)
        if not valid:
            # P1-fix: LLM质检失败时，如果基础指标良好则接受
            if match_info.get("match_rate", 0) >= 0.3 and last_page >= page_count * 0.5:
                print(f"[FAST-TOC] LLM validation failed, but accepting (good coverage + match)")
                valid = True
    
    if not valid:
        print(f"[FAST-TOC] LLM validation failed, returning items for fallback")
        # P1-fix: 返回toc_items让调用方决定是否降级
        return {"toc_items": toc_items, "source": source, "quality_check_failed": True}

    return {"toc_items": toc_items, "source": source}
