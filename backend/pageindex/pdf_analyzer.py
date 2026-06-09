"""Phase 0: PDF 文档预分析 — 纯代码，零 LLM/VLM 调用，< 100ms。

输出文档画像：页面分类、代码 TOC 提取（书签→链接注解→正则）、乱码/图片检测。
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

import pymupdf


# ---------------------------------------------------------------------------
# 页面分类
# ---------------------------------------------------------------------------


def _is_garbled_text(text: str, threshold: float = 0.5) -> bool:
    """检测文本是否大量乱码。CJK+ASCII 占比低于阈值视为乱码。"""
    if len(text) < 30:
        return False
    cjk_or_ascii = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or c.isascii())
    return (cjk_or_ascii / len(text)) < threshold


def _compute_meaningful_text_ratio(text: str) -> float:
    """计算文本中有意义内容的比例。
    
    排除：
    - 纯 ASCII 片段（URL、页码、英文碎片）
    - 重复乱码模式
    - 过短的行
    
    返回有意义字符占总字符的比例。
    """
    if not text or len(text) < 10:
        return 0.0
    
    lines = text.split('\n')
    meaningful_chars = 0
    total_chars = 0
    
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue
        
        total_chars += len(line)
        
        # 跳过 URL
        if re.match(r'^https?://', line):
            continue
        # 跳过纯数字/页码
        if re.match(r'^\d+$', line):
            continue
        # 跳过纯 ASCII 短文本（< 20 chars）
        if len(line) < 20 and all(ord(c) < 128 for c in line):
            continue
        # 跳过英文版权/页脚
        if re.match(r'^(Copyright|All rights reserved|www\.|Page \d+)', line, re.I):
            continue
            
        meaningful_chars += len(line)
    
    return meaningful_chars / total_chars if total_chars > 0 else 0.0


def _detect_toc_pages(page_texts: List[str], max_scan_pages: int = 20) -> Tuple[bool, List[int], float, List[Dict]]:
    """检测目录页（TOC pages）- v2 分批扫描 + 多维度打分。
    
    检测逻辑：
    1. 分批扫描（每批5页，最多4批=20页）
    2. 每页多维度打分（关键词、页码模式、递增性、章节编号、反噪音）
    3. 连续性检测：目录页通常连续出现，下一页不是目录时停止
    4. 返回：是否检测到、页码列表、置信度、提取的目录项预览
    
    返回:
        (has_toc_page, toc_page_indices, confidence, preview_items)
        toc_page_indices: 0-indexed 页码列表（物理页码）
        confidence: 0-1 置信度
        preview_items: 提取的目录项列表（仅用于路由决策）
    """
    if not page_texts:
        return False, [], 0.0, []
    
    # TOC 关键词（多语言支持）
    toc_keywords = {
        'high': ['目录', 'contents', 'table of contents', '目次', '目 录'],
        'medium': ['catalog', 'index', 'list of figures', 'list of tables', 
                   '图目录', '表目录', '图表目录', '插图目录']
    }
    
    # 噪音关键词（用于扣分）
    noise_keywords = ['表1', '表 1', 'table 1', '图1', '图 1', 'figure 1',
                      '序号', '编号', '编号', '日期', '页码']
    
    # 正则模式
    # 模式1: 行尾页码（标题...数字）
    dot_page_pattern = re.compile(
        r'^([^\n]{2,60})[\.\s\.\u00b7\u2026]{3,}(\d{1,4})\s*$',
        re.MULTILINE
    )
    
    # 模式2: 章节编号（1.1, 第一章, 一、等）
    section_pattern = re.compile(
        r'^(?:'
        r'第[一二三四五六七八九十百零〇两\d]+[章节部分篇]'
        r'|[\d]+(?:\.[\d]+){0,3}'
        r'|[一二三四五六七八九十]+[、．.]'
        r'|\([一二三四五六七八九十\d]+\)'
        r')\s*',
        re.MULTILINE
    )
    
    def score_page(page_idx: int) -> Tuple[int, List[Dict]]:
        """对单页进行打分，返回 (分数, 预览条目)。"""
        text = page_texts[page_idx] or ""
        text_lower = text.lower()
        lines = text.split('\n')
        score = 0
        preview_items = []
        
        # 1. 标题关键词检测 (+40 高分)
        has_high_kw = any(kw in text_lower for kw in toc_keywords['high'])
        has_medium_kw = any(kw in text_lower for kw in toc_keywords['medium'])
        if has_high_kw:
            score += 40
        elif has_medium_kw:
            score += 25
        
        # 2. 页码模式检测 (+30 核心特征)
        dot_matches = dot_page_pattern.findall(text)
        if len(dot_matches) >= 5:
            score += 30
            # 提取预览条目
            for match in dot_matches[:10]:
                title = match[0].strip()
                page_num = match[1].strip()
                if title and page_num.isdigit():
                    preview_items.append({
                        'title': title,
                        'physical_index': int(page_num),
                    })
        elif len(dot_matches) >= 3:
            score += 15
        
        # 3. 页码递增检测 (+20)
        if preview_items:
            page_nums = [p['physical_index'] for p in preview_items]
            if len(page_nums) >= 2 and all(page_nums[i] <= page_nums[i+1] 
                                            for i in range(len(page_nums)-1)):
                score += 20
            elif len(page_nums) >= 2 and all(page_nums[i] < page_nums[i+1] 
                                              for i in range(len(page_nums)-1)):
                score += 10  # 严格递增给一半分
        
        # 4. 章节编号模式 (+10)
        section_matches = section_pattern.findall(text)
        if len(section_matches) >= 3:
            score += 10
        elif len(section_matches) >= 1:
            score += 5
        
        # 5. 反噪音检测 (-20)
        noise_count = sum(1 for kw in noise_keywords if kw in text_lower)
        if noise_count >= 5:
            score -= 20
        elif noise_count >= 2:
            score -= 10
        
        # 6. 密度检查（条目太少或太多都扣分）
        if len(preview_items) < 3:
            score -= 10  # 条目太少
        elif len(preview_items) > 40:
            score -= 10  # 条目太多（可能是附录列表）
        
        return score, preview_items
    
    # 分批扫描
    batch_size = 5
    total_pages = len(page_texts)
    scan_limit = min(max_scan_pages, total_pages)
    
    detected_pages = []  # 检测到的目录页
    all_preview_items = []  # 所有预览条目
    max_score = 0  # 最高分数（用于置信度计算）
    
    for batch_start in range(0, scan_limit, batch_size):
        batch_end = min(batch_start + batch_size, scan_limit)
        batch_has_toc = False
        
        for page_idx in range(batch_start, batch_end):
            score, preview = score_page(page_idx)
            
            if score >= 60:  # 及格线
                detected_pages.append(page_idx)
                all_preview_items.extend(preview)
                max_score = max(max_score, score)
                batch_has_toc = True
                
                print(f"[PDF-ANALYZER] TOC candidate p.{page_idx + 1}: score={score}")
        
        # 连续性检测逻辑
        if batch_has_toc:
            # 检查下一页是否也是目录（跨批次）
            next_page = detected_pages[-1] + 1
            if next_page < total_pages:
                next_score, _ = score_page(next_page)
                if next_score < 60:
                    # 下一页不是目录，且当前批次已找到目录，停止扫描
                    print(f"[PDF-ANALYZER] TOC sequence ends at p.{detected_pages[-1] + 1}")
                    break
                # 否则继续扫描（下一页也是目录，会在下一批次处理）
            else:
                # 已到文档末尾
                break
        elif detected_pages:
            # 之前找到了目录，但当前批次没找到，说明目录序列已结束
            # 但这里不会执行，因为一旦找到目录就会检查下一页
            break
        # 如果从未找到目录，继续下一批次
    
    # 计算置信度
    confidence = 0.0
    if detected_pages:
        # 基础置信度
        confidence = 0.5
        # 分数加分（80分以上+0.2，60-80分+0.1）
        if max_score >= 80:
            confidence += 0.2
        elif max_score >= 60:
            confidence += 0.1
        # 多页加分（目录通常多页）
        if len(detected_pages) >= 2:
            confidence += 0.1
        # 预览条目数量加分
        if len(all_preview_items) >= 5:
            confidence += 0.1
        # 页码连续性加分
        if all_preview_items:
            page_nums = [p['physical_index'] for p in all_preview_items if p['physical_index'] > 0]
            if len(page_nums) >= 2 and all(page_nums[i] <= page_nums[i+1] 
                                            for i in range(len(page_nums)-1)):
                confidence += 0.1
    
    return bool(detected_pages), detected_pages, min(confidence, 1.0), all_preview_items


def _detect_chapter_dividers(page_texts: List[str]) -> List[int]:
    """检测章节分隔页：重复出现的相同短页面。
    
    章节分隔页特征：
    - 内容完全相同（使用内容指纹匹配）
    - 页面较短（< 300字符）
    - 分散在文档中（非连续出现）
    - 重复次数 >= 5（排除偶然的页眉/页脚重复）
    
    返回:
        分隔页物理页码列表（1-indexed），未检测到则返回空列表
    """
    if not page_texts or len(page_texts) < 10:
        return []
    
    total_pages = len(page_texts)
    
    # 参数配置
    MIN_SHORT_PAGES = 5       # 最少重复次数
    MIN_DISPERSION = 5        # 最小分散间隔（页）
    MAX_SHORT_LENGTH = 300    # 短页面最大字符数
    MIN_FINGERPRINT_LEN = 20  # 指纹最小长度
    
    def _extract_content_fingerprint(text: str, max_len: int = 100) -> str:
        """提取内容指纹：保留中文字符和英文字母，去除空格、数字、标点。"""
        return re.sub(r'[^\u4e00-\u9fa5a-zA-Z]', '', text[:max_len])
    
    # 步骤1：提取所有短页面的指纹（排除第一页和最后一页）
    from collections import defaultdict
    fingerprint_pages = defaultdict(list)
    
    for i, text in enumerate(page_texts):
        page_num = i + 1  # 1-indexed
        text_stripped = text.strip()
        text_len = len(text_stripped)
        
        # 跳过空白页、长页面、第一页和最后一页
        if text_len == 0 or text_len > MAX_SHORT_LENGTH:
            continue
        if page_num == 1 or page_num == total_pages:
            continue
        
        # 提取指纹
        fp = _extract_content_fingerprint(text_stripped)
        
        # 跳过太短的指纹
        if len(fp) < MIN_FINGERPRINT_LEN:
            continue
        
        fingerprint_pages[fp].append(page_num)
    
    # 步骤2：找重复出现的指纹（>= MIN_SHORT_PAGES 次）
    candidates = []
    for fp, pages in fingerprint_pages.items():
        if len(pages) >= MIN_SHORT_PAGES:
            pages_sorted = sorted(pages)
            if len(pages_sorted) >= 2:
                gaps = [pages_sorted[i+1] - pages_sorted[i] 
                       for i in range(len(pages_sorted)-1)]
                max_gap = max(gaps)
                
                # 需要有一定的分散性
                if max_gap >= MIN_DISPERSION:
                    avg_len = sum(len(page_texts[p-1].strip()) for p in pages_sorted) / len(pages_sorted)
                    
                    # 检查是否所有页面都是非连续的（真正的分隔符不应该连续出现太多）
                    non_consecutive = all(g >= 2 for g in gaps)
                    
                    candidates.append({
                        'pages': pages_sorted,
                        'count': len(pages_sorted),
                        'max_gap': max_gap,
                        'avg_len': avg_len,
                        'non_consecutive': non_consecutive
                    })
    
    if not candidates:
        return []
    
    # 步骤3：选择最佳候选
    # 优先选择：非连续的 > 页数多的 > 平均长度短的
    best = max(candidates, key=lambda x: (x['non_consecutive'], x['count'], -x['avg_len']))
    
    # 如果最佳候选是连续的，进行额外检查
    if not best['non_consecutive']:
        pages = best['pages']
        # 只有前两页连续（可能是目录跨页），其余都分散，这是可以接受的
        if len(pages) >= 4 and pages[1] - pages[0] == 1 and all(pages[i+1] - pages[i] >= 2 for i in range(1, len(pages)-1)):
            pass
        else:
            return []
    
    return best['pages']


def _check_text_quality(page_texts: List[str]) -> Dict[str, Any]:
    """评估整篇文档的文本质量。
    
    返回:
        {
            "meaningful_ratio": float,  # 平均有意义文本比例
            "duplicate_ratio": float,   # 重复页面比例
            "fragment_ratio": float,    # 碎片页面比例（文本<50字符）
            "is_low_quality": bool,     # 是否低质量
        }
    """
    if not page_texts:
        return {"meaningful_ratio": 0, "duplicate_ratio": 0, "fragment_ratio": 0, "is_low_quality": True}
    
    # 1. 有意义文本比例
    meaningful_ratios = [_compute_meaningful_text_ratio(t) for t in page_texts]
    avg_meaningful = sum(meaningful_ratios) / len(meaningful_ratios)
    
    # 2. 重复页面检测（使用简化指纹：前100字符）
    fingerprints = []
    for text in page_texts:
        # 取前100字符，去掉数字和空格作为指纹
        fp = re.sub(r'[\d\s]', '', text[:100])
        fingerprints.append(fp)
    
    duplicate_count = 0
    for i, fp in enumerate(fingerprints):
        if not fp or len(fp) < 10:
            continue
        # 检查是否有其他页面高度相似
        for j, other_fp in enumerate(fingerprints):
            if i != j and len(other_fp) >= 10:
                # 简单相似度：共同字符比例
                common = sum(1 for c in fp if c in other_fp)
                similarity = common / max(len(fp), len(other_fp))
                if similarity > 0.8:
                    duplicate_count += 1
                    break
    
    duplicate_ratio = duplicate_count / len(page_texts)
    
    # 3. 碎片页面比例
    fragment_count = sum(1 for t in page_texts if len(t.strip()) < 50)
    fragment_ratio = fragment_count / len(page_texts)
    
    # 4. 综合判断：低质量指标
    # - 有意义内容 < 30% 且重复页面 > 30%
    # - 或碎片页面 > 60%
    is_low_quality = (
        (avg_meaningful < 0.30 and duplicate_ratio > 0.3) or
        (fragment_ratio > 0.6)
    )
    
    return {
        "meaningful_ratio": round(avg_meaningful, 3),
        "duplicate_ratio": round(duplicate_ratio, 3),
        "fragment_ratio": round(fragment_ratio, 3),
        "is_low_quality": is_low_quality,
    }


def _classify_page(text: str, image_count: int) -> str:
    """分类单个页面类型。"""
    text_stripped = (text or "").strip()
    if not text_stripped and image_count > 0:
        return "image_only"
    if not text_stripped and image_count == 0:
        return "empty"
    if _is_garbled_text(text_stripped):
        return "garbled"
    return "text"


def _build_document_profile(
    *,
    page_count: int,
    text_coverage: float,
    image_coverage: float,
    image_only_pages: List[int],
    garbled_pages: List[int],
    text_quality: Dict[str, Any],
    chapter_dividers: List[int],
) -> Dict[str, Any]:
    """Build a route-oriented document profile from cheap analyzer signals."""
    safe_page_count = max(1, page_count)
    image_only_ratio = len(image_only_pages or []) / safe_page_count
    garbled_ratio = len(garbled_pages or []) / safe_page_count
    fragment_ratio = float((text_quality or {}).get("fragment_ratio") or 0.0)
    meaningful_ratio = float((text_quality or {}).get("meaningful_ratio") or 0.0)
    low_quality = bool((text_quality or {}).get("is_low_quality"))
    has_dividers = len(chapter_dividers or []) >= 3

    if low_quality or garbled_ratio > 0.5:
        text_layer_quality = "garbled" if garbled_ratio > 0.5 else "noisy"
    elif text_coverage >= 0.85 and meaningful_ratio >= 0.8 and fragment_ratio <= 0.2:
        text_layer_quality = "reliable"
    elif text_coverage >= 0.4:
        text_layer_quality = "partial"
    else:
        text_layer_quality = "noisy"

    visual_dependency_score = 0.0
    if image_coverage >= 0.9:
        visual_dependency_score += 0.45
    elif image_coverage >= 0.5:
        visual_dependency_score += 0.25
    if image_only_ratio >= 0.2:
        visual_dependency_score += 0.25
    elif image_only_ratio > 0:
        visual_dependency_score += 0.1
    if has_dividers:
        visual_dependency_score += 0.2
    if text_layer_quality in {"partial", "noisy", "garbled"}:
        visual_dependency_score += 0.15
    visual_dependency_score = min(1.0, round(visual_dependency_score, 3))

    has_reliable_full_text = (
        text_layer_quality == "reliable"
        and text_coverage >= 0.85
        and image_only_ratio == 0
    )

    if image_only_ratio > 0.9 or (text_coverage <= 0.05 and image_coverage >= 0.8):
        layout_type = "scanned_image_pdf"
    elif image_coverage >= 0.9 and not has_reliable_full_text and (
        image_only_ratio >= 0.15 or has_dividers
    ):
        layout_type = "mixed_visual_report"
    elif image_coverage >= 0.8 and has_dividers and not has_reliable_full_text:
        layout_type = "slide_like_report"
    else:
        layout_type = "native_text_report"

    if layout_type in {"scanned_image_pdf", "mixed_visual_report", "slide_like_report"}:
        structure_policy = "visual_required"
    elif visual_dependency_score >= 0.7:
        structure_policy = "visual_preferred"
    else:
        structure_policy = "text_allowed"

    return {
        "layout_type": layout_type,
        "text_layer_quality": text_layer_quality,
        "visual_dependency_score": visual_dependency_score,
        "structure_policy": structure_policy,
        "ocr_policy": "content_fill_only",
    }


# ---------------------------------------------------------------------------
# 代码 TOC 提取 — 三级优先
# ---------------------------------------------------------------------------


def _clean_title(title: str) -> str:
    """清洗标题：去尾部冒号/点线/空格。"""
    title = re.sub(r"[\s:：.…·\u00b7\u2026]+$", "", title)
    return title.strip()


def _normalize_for_search(text: str) -> str:
    """模糊搜索标准化：去所有空格和标点，便于匹配。"""
    text = re.sub(r"\s+", "", text)
    text = text.replace("：", ":").replace("（", "(").replace("）", ")")
    text = re.sub(r"[:\-–—,，.。;；!！?？()（）\[\]【】{}\"'" "'']+", "", text)
    return text.lower()


def extract_toc_from_bookmarks(doc: pymupdf.Document) -> Optional[List[Dict]]:
    """Level 1: PDF 原生书签。"""
    raw_toc = doc.get_toc()
    if len(raw_toc) < 3:
        return None

    filtered = []
    for level, title, page in raw_toc:
        t = _clean_title(title or "")
        if not t or re.match(r"^幻灯片\s*\d+:?\s*$", t):
            continue
        filtered.append({"level": level, "title": t, "physical_index": max(1, page)})

    if len(filtered) < 3:
        return None
    return _levels_to_structure(filtered)


def extract_toc_from_link_annotations(
    doc: pymupdf.Document, max_scan_pages: int = 20
) -> Optional[List[Dict]]:
    """Level 2: TOC 页面上的链接注解。精确物理页码。"""
    toc_entries = []
    found_toc_page = False

    for page_num in range(min(max_scan_pages, len(doc))):
        page = doc[page_num]
        links = page.get_links()
        internal_links = [
            l for l in links if l.get("kind") == 1 and l.get("page", -1) >= 0
        ]

        if len(internal_links) < 5:
            if found_toc_page:
                break
            continue

        found_toc_page = True
        internal_links.sort(key=lambda l: l["from"].y0)

        for link in internal_links:
            rect = pymupdf.Rect(link["from"])
            text = page.get_text("text", clip=rect).strip().replace("\n", " ")
            dest_page = link["page"] + 1

            if text and dest_page > 0:
                clean = _clean_title(re.sub(r"[.…·\s]+\d*\s*$", "", text))
                if clean and len(clean) > 1:
                    toc_entries.append({"title": clean, "physical_index": dest_page})

    if len(toc_entries) < 3:
        return None

    # 去重
    deduped = [toc_entries[0]]
    for entry in toc_entries[1:]:
        if (
            entry["title"] != deduped[-1]["title"]
            or entry["physical_index"] != deduped[-1]["physical_index"]
        ):
            deduped.append(entry)

    return _infer_structure_from_titles(deduped)


def extract_toc_by_regex(page_texts: List[str]) -> Optional[List[Dict]]:
    """Level 3: 正则匹配 TOC 文本页。

    Args:
        page_texts: 每页的纯文本列表（0-indexed）。
    """
    toc_pages = _find_toc_pages_by_rules(page_texts)
    if not toc_pages:
        return None

    toc_text = ""
    for idx in toc_pages:
        toc_text += page_texts[idx]
    toc_text = re.sub(r"\.{5,}", ": ", toc_text)

    return _parse_toc_text_to_items(toc_text)


# ---------------------------------------------------------------------------
# 正则辅助
# ---------------------------------------------------------------------------

_TOC_LINE_PATTERN = re.compile(
    r"(?:"
    r"第[一二三四五六七八九十百零〇两\d]+[章节部分篇]"
    r"|[\d]{1,2}(?:\.[\d]{1,2}){0,3}"
    r"|[一二三四五六七八九十]+、"
    r"|[（(][一二三四五六七八九十\d]+[)）]"
    r")\s*[^\n]{2,80}[.…:\s·\u00b7\u2026]+\d{1,4}"
)


def _find_toc_pages_by_rules(page_texts: List[str]) -> List[int]:
    """扫描所有页面，检测 TOC 格式行密集的页面。"""
    toc_pages: List[int] = []
    for i, text in enumerate(page_texts):
        if not text or not text.strip():
            continue
        matches = _TOC_LINE_PATTERN.findall(text)
        if len(matches) >= 3:
            toc_pages.append(i)
        elif toc_pages and len(matches) >= 1:
            toc_pages.append(i)
        elif toc_pages:
            break
    return toc_pages


def _parse_toc_text_to_items(toc_text: str) -> Optional[List[Dict]]:
    """从 TOC 纯文本正则解析条目。"""
    pattern = re.compile(
        r"^("
        r"(?:第[一二三四五六七八九十百零〇两\d]+[章节部分篇][：:\s]*)?"
        r"(?:[\d]{1,2}(?:\.[\d]{1,2}){0,3}\s+)?"
        r"(?:[一二三四五六七八九十]+、)?"
        r"(?:[（(][一二三四五六七八九十\d]+[)）]\s*)?"
        r")"
        r"([^\n.…·]{2,80})"
        r"[.…·\s\u00b7\u2026]+(\d{1,4})\s*$",
        re.MULTILINE,
    )
    items = []
    for match in pattern.finditer(toc_text):
        prefix = _clean_title(match.group(1))
        title_body = _clean_title(match.group(2))
        page = int(match.group(3))

        title = f"{prefix} {title_body}".strip() if prefix else title_body
        if not title or page <= 0:
            continue

        num_match = re.match(r"([\d]{1,2}(?:\.[\d]{1,2}){0,3})", prefix)
        structure = num_match.group(1) if num_match else None
        items.append({"title": title, "physical_index": page, "_num": structure})

    if len(items) < 3:
        return None

    top_counter = 0
    for item in items:
        num = item.pop("_num", None)
        if num:
            item["structure"] = num
        else:
            top_counter += 1
            item["structure"] = str(top_counter)
    return items


# ---------------------------------------------------------------------------
# Structure 辅助
# ---------------------------------------------------------------------------


def _levels_to_structure(items: List[Dict]) -> List[Dict]:
    """level-based → structure-based ("1", "1.1", "2")"""
    counters: Dict[int, int] = {}
    result = []
    for item in items:
        level = item["level"]
        for k in list(counters.keys()):
            if k > level:
                del counters[k]
        counters[level] = counters.get(level, 0) + 1
        parts = [str(counters[lv]) for lv in sorted(counters.keys())]
        result.append(
            {
                "structure": ".".join(parts),
                "title": item["title"],
                "physical_index": item["physical_index"],
            }
        )
    return result


def _infer_structure_from_titles(items: List[Dict]) -> List[Dict]:
    """从标题格式推断 structure 编号。"""
    result = []
    for item in items:
        title = item["title"]
        m = re.match(r"^(\d+(?:\.\d+)*)\s+", title)
        if m:
            result.append(
                {
                    "structure": m.group(1),
                    "title": title[m.end() :].strip() or title,
                    "physical_index": item["physical_index"],
                }
            )
        else:
            m2 = re.match(
                r"^第([一二三四五六七八九十百零〇两\d]+)[章节部分篇][：:\s]*(.*)", title
            )
            if m2:
                result.append(
                    {
                        "structure": str(
                            len([r for r in result if "." not in r["structure"]]) + 1
                        ),
                        "title": title,
                        "physical_index": item["physical_index"],
                    }
                )
            else:
                if result:
                    parent = result[-1]["structure"].split(".")[0]
                    sub_count = len(
                        [r for r in result if r["structure"].startswith(parent + ".")]
                    )
                    result.append(
                        {
                            "structure": f"{parent}.{sub_count + 1}",
                            "title": title,
                            "physical_index": item["physical_index"],
                        }
                    )
                else:
                    result.append(
                        {
                            "structure": "1",
                            "title": title,
                            "physical_index": item["physical_index"],
                        }
                    )
    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def analyze_pdf_structure(file_path: str) -> Dict[str, Any]:
    """文档预分析：纯代码，零 LLM/VLM，< 100ms。"""
    doc = pymupdf.open(file_path)
    page_count = len(doc)

    # 页面分类 + 文本提取
    pages_info = []
    page_texts: List[str] = []  # 纯文本列表，0-indexed
    page_list: List[Tuple[str, int]] = []  # (text, token_approx) 列表

    for i in range(page_count):
        page = doc[i]
        text = page.get_text() or ""
        images = page.get_images()
        ptype = _classify_page(text, len(images))
        pages_info.append(
            {
                "index": i,
                "type": ptype,
                "text_len": len(text),
                "image_count": len(images),
            }
        )
        page_texts.append(text)
        # token 近似：中文 1 char ≈ 0.7 token，英文 1 word ≈ 1.3 token
        token_approx = max(1, int(len(text) * 0.7))
        page_list.append((text, token_approx))

    text_pages = [p["index"] for p in pages_info if p["type"] == "text"]
    image_only_pages = [p["index"] for p in pages_info if p["type"] == "image_only"]
    image_pages = [p["index"] for p in pages_info if p["image_count"] > 0]
    garbled_pages = [p["index"] for p in pages_info if p["type"] == "garbled"]
    text_coverage = len(text_pages) / page_count if page_count > 0 else 0
    image_coverage = len(image_pages) / page_count if page_count > 0 else 0

    # 文本质量深度检测（针对扫描件/图片PDF但有伪文本层的情况）
    quality = _check_text_quality(page_texts)
    if quality["is_low_quality"]:
        print(f"[PDF-ANALYZER] Low quality text detected: meaningful={quality['meaningful_ratio']:.0%}, "
              f"duplicate={quality['duplicate_ratio']:.0%}, fragment={quality['fragment_ratio']:.0%}")
        # 降低 text_coverage，强制路由到 visual 路径
        text_coverage = min(text_coverage, 0.3)
        # 标记为乱码PDF
        if not garbled_pages:
            garbled_pages = text_pages.copy()
            # 将所有 text 页面重新标记为 garbled
            for p in pages_info:
                if p["type"] == "text":
                    p["type"] = "garbled"

    # 章节分隔页检测（用于识别"汇报提纲"等特殊文档模式）
    chapter_dividers = _detect_chapter_dividers(page_texts)
    if chapter_dividers:
        print(f"[PDF-ANALYZER] Chapter dividers detected: {chapter_dividers}")

    document_profile = _build_document_profile(
        page_count=page_count,
        text_coverage=text_coverage,
        image_coverage=image_coverage,
        image_only_pages=image_only_pages,
        garbled_pages=garbled_pages,
        text_quality=quality,
        chapter_dividers=chapter_dividers,
    )

    # 目录页检测已移到 Balanced 路径中按需执行（toc_detector.py）
    # 预分析不再做目录页检测，避免重复工作和不必要的计算
    has_toc_page, toc_page_indices, toc_confidence, toc_preview = False, [], 0.0, []

    # 代码 TOC 提取（三级优先）
    code_toc_items = None
    code_toc_source = None

    # Level 1: 书签
    code_toc_items = extract_toc_from_bookmarks(doc)
    if code_toc_items:
        code_toc_source = "bookmarks"

    # Level 2: 链接注解
    if not code_toc_items:
        code_toc_items = extract_toc_from_link_annotations(doc)
        if code_toc_items:
            code_toc_source = "links"

    # Level 3: 正则（只在有文本页时尝试）
    if not code_toc_items and text_coverage > 0.3:
        code_toc_items = extract_toc_by_regex(page_texts)
        if code_toc_items:
            code_toc_source = "regex"

    doc.close()

    # Recompute text_pages after potential reclassification
    text_pages = [p["index"] for p in pages_info if p["type"] == "text"]
    garbled_pages = [p["index"] for p in pages_info if p["type"] == "garbled"]

    return {
        "file_path": file_path,
        "page_count": page_count,
        "pages": pages_info,
        "text_coverage": text_coverage,
        **document_profile,
        "text_pages": text_pages,
        "image_only_pages": image_only_pages,
        "image_coverage": image_coverage,
        "garbled_pages": garbled_pages,
        "is_image_only_pdf": len(image_only_pages) / page_count > 0.9
        if page_count > 0
        else False,
        "is_garbled_pdf": len(garbled_pages) / page_count > 0.5
        if page_count > 0
        else False,
        "code_toc": {
            "items": code_toc_items,
            "source": code_toc_source,
        },
        "page_list": page_list,
        "page_texts": page_texts,
        "text_quality": quality,
        "chapter_dividers": chapter_dividers,
        "toc_page": {
            "has_toc_page": has_toc_page,
            "page_indices": toc_page_indices,
            "confidence": toc_confidence,
            "preview_items": toc_preview,
        },
    }
