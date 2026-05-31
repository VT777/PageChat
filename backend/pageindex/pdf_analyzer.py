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
    garbled_pages = [p["index"] for p in pages_info if p["type"] == "garbled"]
    text_coverage = len(text_pages) / page_count if page_count > 0 else 0

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
        "text_pages": text_pages,
        "image_only_pages": image_only_pages,
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
    }
