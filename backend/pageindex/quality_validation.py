"""质量校验模块：VLM视觉校验TOC页和Divider页 + 路径决策。

职责：
1. 用VLM批量校验TOC页（验证是否是真正的目录页）
2. 用VLM批量校验Divider页（验证是否是有效的分隔页）
3. 基于TOC和Divider质量进行路径决策
"""

import asyncio
from collections import Counter
from typing import Any, Dict, List, Optional

from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json


# ===========================================================================
# TOC页 VLM校验
# ===========================================================================

TOC_VALIDATION_PROMPT = """你是一位文档分析专家。请分析以下图片是否是文档的目录页。

判断标准：
1. 【必选项】页面是否有"目录"/"Contents"/"目次"等标题？
2. 【必选项】页面是否有条目列表？（带编号、带点、或带缩进的列表）
3. 【必选项】条目右侧或末尾是否有页码？
4. 【可选项】目录结构是否看起来完整？（条目数量是否合理，有无明显的大章节遗漏）

请输出严格的JSON格式：
{
    "is_toc_page": true/false,
    "confidence": 0-1,
    "has_entries": true/false,
    "has_page_numbers": true/false,
    "structure_looks_complete": true/false,
    "estimated_entry_count": 数字,
    "issues": ["问题描述1", "问题描述2"],
    "reason": "判断理由"
}"""


async def validate_toc_pages_vlm(
    toc_pages: List[int],
    file_path: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """用VLM批量校验TOC页。
    
    Args:
        toc_pages: 候选目录页物理页码列表（1-indexed）
        file_path: PDF文件路径
        model: VLM模型名称
        
    Returns:
        {
            "valid_pages": [有效页码列表],
            "invalid_pages": [无效页码列表],
            "all_results": [完整结果列表]
        }
    """
    if not toc_pages:
        return {"valid_pages": [], "invalid_pages": [], "all_results": []}
    
    print(f"[QC-TOC] Validating {len(toc_pages)} candidate TOC pages: {toc_pages}")
    
    # 渲染候选TOC页
    images = render_pages_to_images(file_path, [p-1 for p in toc_pages])
    
    # 构建prompt
    annotations = []
    for i, img in enumerate(images):
        page_num = toc_pages[i]
        annotations.append(f"第{i+1}张图：物理页码 p.{page_num}")
    
    prompt = f"""{TOC_VALIDATION_PROMPT}

图片顺序说明：
{"\n".join(annotations)}

请逐一分析每张图片，输出JSON数组：
[
    {{
        "page_number": 物理页码,
        "is_toc_page": true/false,
        "has_entries": true/false,
        "has_page_numbers": true/false,
        "structure_looks_complete": true/false,
        "estimated_entry_count": 数字,
        "issues": [],
        "reason": "判断理由"
    }}
]"""
    
    try:
        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=4000)
        results = parse_vlm_json(raw)
        
        if not isinstance(results, list):
            print(f"[QC-TOC] VLM returned non-list: {type(results)}, accepting all candidates")
            return {"valid_pages": toc_pages, "invalid_pages": [], "all_results": []}
        
        valid_pages = []
        invalid_pages = []
        
        for r in results:
            page_num = r.get("page_number")
            is_toc = r.get("is_toc_page", False)
            has_entries = r.get("has_entries", False)
            
            if is_toc and has_entries:
                valid_pages.append(page_num)
            else:
                invalid_pages.append(page_num)
                print(f"[QC-TOC] p.{page_num} invalid: {r.get('reason', 'N/A')}")
        
        print(f"[QC-TOC] Valid: {valid_pages}, Invalid: {invalid_pages}")
        return {
            "valid_pages": valid_pages,
            "invalid_pages": invalid_pages,
            "all_results": results
        }
        
    except Exception as e:
        print(f"[QC-TOC] Validation failed: {e}, accepting all candidates")
        return {"valid_pages": toc_pages, "invalid_pages": [], "all_results": []}


# ===========================================================================
# Divider页 VLM校验
# ===========================================================================

DIVIDER_VALIDATION_PROMPT = """你是一位文档分析专家。请分析以下图片，判断这是什么类型的页面。

页面类型分类：
1. **empty_divider**：空页或纯装饰分隔页（几乎无内容，只有线条/色块/渐变背景）
2. **chapter_title**：章节标题页（大字号标题，带有"Part X"/"第X章"/"Chapter X"等标识）
3. **content**：内容页（有正文段落、图表、数据等实质内容）
4. **unknown**：无法判断

请输出严格的JSON格式：
{
    "page_type": "empty_divider/chapter_title/content/unknown",
    "is_valid_divider": true/false,
    "confidence": 0-1,
    "chapter_title": "如果是章节标题页，提取标题文字",
    "reason": "判断理由",
    "visual_features": ["特征1", "特征2"]
}"""


async def validate_dividers_vlm(
    dividers: List[int],
    file_path: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """用VLM批量校验Divider页。
    
    Args:
        dividers: 候选分隔页物理页码列表（1-indexed）
        file_path: PDF文件路径
        model: VLM模型名称
        
    Returns:
        {
            "valid_dividers": [有效分隔页],
            "chapter_titles": [{"page": x, "title": "..."}],
            "invalid_dividers": [{"page": x, "reason": "..."}],
            "all_results": [完整结果]
        }
    """
    if not dividers:
        return {
            "valid_dividers": [],
            "chapter_titles": [],
            "invalid_dividers": [],
            "all_results": []
        }
    
    print(f"[QC-DIV] Validating {len(dividers)} candidate dividers: {dividers}")
    
    images = render_pages_to_images(file_path, [d-1 for d in dividers])
    
    annotations = []
    for i, img in enumerate(images):
        page_num = dividers[i]
        annotations.append(f"第{i+1}张图：物理页码 p.{page_num}")
    
    prompt = f"""{DIVIDER_VALIDATION_PROMPT}

图片顺序说明：
{"\n".join(annotations)}

请逐一分析每张图片，输出JSON数组：
[
    {{
        "page_number": 物理页码,
        "page_type": "empty_divider/chapter_title/content/unknown",
        "is_valid_divider": true/false,
        "chapter_title": "提取的标题（如果是章节标题页）",
        "reason": "判断理由"
    }}
]"""
    
    try:
        raw = await vlm_call_with_images(images, prompt, model=model, max_tokens=4000)
        results = parse_vlm_json(raw)
        
        if not isinstance(results, list):
            print(f"[QC-DIV] VLM returned non-list: {type(results)}, accepting all candidates")
            return {
                "valid_dividers": dividers,
                "chapter_titles": [],
                "invalid_dividers": [],
                "all_results": []
            }
        
        valid_dividers = []
        chapter_titles = []
        invalid_dividers = []
        
        for r in results:
            page_num = r.get("page_number")
            page_type = r.get("page_type", "unknown")
            
            if page_type in ["empty_divider", "chapter_title"]:
                valid_dividers.append(page_num)
                if page_type == "chapter_title":
                    chapter_titles.append({
                        "page": page_num,
                        "title": r.get("chapter_title", "")
                    })
            else:
                invalid_dividers.append({
                    "page": page_num,
                    "reason": f"类型为{page_type}，不是有效的分隔页"
                })
        
        print(f"[QC-DIV] Valid: {valid_dividers}, Invalid: {[d['page'] for d in invalid_dividers]}")
        return {
            "valid_dividers": valid_dividers,
            "chapter_titles": chapter_titles,
            "invalid_dividers": invalid_dividers,
            "all_results": results
        }
        
    except Exception as e:
        print(f"[QC-DIV] Validation failed: {e}, accepting all candidates")
        return {
            "valid_dividers": dividers,
            "chapter_titles": [],
            "invalid_dividers": [],
            "all_results": []
        }


# ===========================================================================
# 路径决策
# ===========================================================================

def decide_extraction_path(toc_check: Dict, divider_check: Dict) -> Dict[str, str]:
    """基于TOC和Divider质量状态的路径决策。
    
    规则：
    1. TOC合格且有层级 → 分支A（已知TOC路径）
    2. TOC只有一级 或 TOC不合格，且Divider合格 → 分支B（按分隔页分段提取）
    3. TOC和Divider都不合格 → 分支C（全文扫描兜底）
    
    Args:
        toc_check: TOC质量检查结果
        divider_check: Divider质量检查结果
        
    Returns:
        {"path": "BRANCH_A|BRANCH_B|BRANCH_C", "reason": "决策原因"}
    """
    toc_valid = toc_check.get("is_valid", False)
    toc_skeleton_valid = toc_check.get("skeleton_valid", toc_valid)
    toc_has_hierarchy = toc_check.get("has_hierarchy", False)
    divider_valid = divider_check.get("is_valid", False)
    
    # 规则1：TOC骨架可信时优先保留；页码和子层级可在 Branch A 内继续修正/补充
    if toc_skeleton_valid:
        return {
            "path": "BRANCH_A",
            "reason": "TOC骨架可信，优先保留目录页结构"
        }
    
    # 规则2：Divider合格（无论TOC状态）
    if divider_valid:
        if toc_valid and not toc_has_hierarchy:
            return {
                "path": "BRANCH_B",
                "reason": f"TOC只有一级目录({toc_check.get('top_level_count', 0)}个)，使用Divider分段提取子章节"
            }
        else:
            return {
                "path": "BRANCH_B",
                "reason": "TOC不合格或不可靠，使用Divider分段提取"
            }
    
    # 规则3：都不合格
    toc_reason = toc_check.get("reason", "未检查")
    div_reason = divider_check.get("reason", "未检查")
    return {
        "path": "BRANCH_C",
        "reason": f"TOC({toc_reason})和Divider({div_reason})都不可靠，回退到全文扫描"
    }


# ===========================================================================
# TOC质量检查器
# ===========================================================================

class TocQualityChecker:
    """Validate whether an extracted TOC is good enough to preserve."""

    PAGE_FIELDS = ("start_index", "page", "logical_page", "physical_index")
    SYNTHETIC_ROOT_TITLES = {
        "目录",
        "目 录",
        "contents",
        "table of contents",
        "preface",
    }

    @staticmethod
    def _positive_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                parsed = int(stripped)
                return parsed if parsed > 0 else None
        return None

    def _page_stats(self, toc_items: List[Dict]) -> Dict[str, Any]:
        best_field = None
        best_pages: List[int] = []

        for field in self.PAGE_FIELDS:
            pages = []
            for item in toc_items:
                parsed = self._positive_int(item.get(field))
                if parsed is not None:
                    pages.append(parsed)
            if len(pages) > len(best_pages):
                best_field = field
                best_pages = pages

        monotonic = all(
            best_pages[i] <= best_pages[i + 1]
            for i in range(len(best_pages) - 1)
        )
        unique_ratio = len(set(best_pages)) / len(best_pages) if best_pages else 0.0
        diffs = [
            best_pages[i + 1] - best_pages[i]
            for i in range(len(best_pages) - 1)
            if best_pages[i + 1] >= best_pages[i]
        ]
        common_step = Counter(diffs).most_common(1)[0][0] if diffs else None

        return {
            "valid_page_field": best_field,
            "valid_page_count": len(best_pages),
            "page_monotonic": monotonic,
            "page_unique_ratio": unique_ratio,
            "common_page_step": common_step,
        }

    @staticmethod
    def _page_mapping_valid(
        *,
        item_count: int,
        valid_pages: int,
        page_monotonic: bool,
        unique_ratio: float,
        common_step: Optional[int],
    ) -> bool:
        if item_count <= 0 or valid_pages <= 0:
            return False

        enough_pages = valid_pages >= max(2, item_count * 0.5)
        if not enough_pages or not page_monotonic:
            return False

        if valid_pages == 1:
            return item_count == 1

        if unique_ratio < 0.5:
            return False

        if common_step == 0:
            return False

        return True

    @classmethod
    def _is_synthetic_root(cls, item: Dict) -> bool:
        title = str(item.get("title", "")).strip().lower()
        return title in cls.SYNTHETIC_ROOT_TITLES

    def _has_page_value(self, item: Dict) -> bool:
        return any(self._positive_int(item.get(field)) is not None for field in self.PAGE_FIELDS)

    def _infer_structural_synthetic_root(
        self,
        real_items: List[Dict],
        levels: List[int],
    ) -> Optional[Dict[str, Any]]:
        """Detect a single wrapper title above the actual TOC groups."""
        if not levels:
            return None

        min_level = min(levels)
        top_items = [
            item for item in real_items
            if item.get("level", min_level) == min_level
        ]
        if len(top_items) != 1:
            return None

        child_level = min((level for level in levels if level > min_level), default=None)
        if child_level is None:
            return None

        child_items = [
            item for item in real_items
            if item.get("level", min_level) == child_level
        ]
        paged_descendants = [
            item for item in real_items
            if item.get("level", min_level) > child_level and self._has_page_value(item)
        ]

        root = top_items[0]
        root_has_page = self._has_page_value(root)
        if len(child_items) >= 2 and paged_descendants and not root_has_page:
            return {
                "items": child_items,
                "detected": True,
                "reason": (
                    "single unpaged top-level wrapper with "
                    f"{len(child_items)} child groups"
                ),
            }
        return None

    def _effective_top_level_info(self, toc_items: List[Dict]) -> Dict[str, Any]:
        """Count real top-level groups after ignoring synthetic TOC roots."""
        real_items = [
            item for item in toc_items
            if str(item.get("title", "")).strip()
            and not self._is_synthetic_root(item)
        ]
        if not real_items:
            return {
                "items": [],
                "synthetic_root_detected": False,
                "synthetic_root_reason": "",
                "raw_min_level_count": 0,
                "level_distribution": {},
            }

        levels = [
            item.get("level", 1)
            for item in real_items
            if isinstance(item.get("level", 1), int)
            and not isinstance(item.get("level", 1), bool)
        ]
        if not levels:
            return {
                "items": real_items,
                "synthetic_root_detected": False,
                "synthetic_root_reason": "no numeric levels",
                "raw_min_level_count": len(real_items),
                "level_distribution": {},
            }

        min_level = min(levels)
        raw_top_level = [
            item for item in real_items
            if item.get("level", min_level) == min_level
        ]
        level_distribution = dict(Counter(levels))

        inferred = self._infer_structural_synthetic_root(real_items, levels)
        if inferred:
            return {
                "items": inferred["items"],
                "synthetic_root_detected": True,
                "synthetic_root_reason": inferred["reason"],
                "raw_min_level_count": len(raw_top_level),
                "level_distribution": level_distribution,
            }

        explicit_root_count = len(toc_items) - len(real_items)
        return {
            "items": raw_top_level,
            "synthetic_root_detected": explicit_root_count > 0,
            "synthetic_root_reason": (
                "explicit synthetic root title" if explicit_root_count > 0 else ""
            ),
            "raw_min_level_count": len(raw_top_level),
            "level_distribution": level_distribution,
        }

    def _effective_top_level(self, toc_items: List[Dict]) -> List[Dict]:
        return self._effective_top_level_info(toc_items)["items"]

    def check(self, toc_items: List[Dict], toc_pages: List[int]) -> Dict[str, Any]:
        if not toc_items:
            return {
                "is_valid": False,
                "skeleton_valid": False,
                "page_mapping_valid": False,
                "hierarchy_valid": False,
                "decision": "REJECT",
                "has_hierarchy": False,
                "top_level_count": 0,
                "item_count": 0,
                "valid_page_field": None,
                "valid_page_count": 0,
                "page_monotonic": False,
                "page_unique_ratio": 0.0,
                "common_page_step": None,
                "reason": "no TOC items",
            }

        top_level_info = self._effective_top_level_info(toc_items)
        top_level = top_level_info["items"]
        has_hierarchy = any(item.get("level", 1) > 1 for item in toc_items)
        page_stats = self._page_stats(toc_items)
        valid_pages = page_stats["valid_page_count"]
        non_empty_titles = sum(
            1 for item in toc_items
            if str(item.get("title", "")).strip()
        )
        title_ratio = non_empty_titles / len(toc_items)

        skeleton_valid = (
            len(top_level) >= 2
            and title_ratio >= 0.8
        )
        hierarchy_valid = has_hierarchy
        page_mapping_valid = self._page_mapping_valid(
            item_count=len(toc_items),
            valid_pages=valid_pages,
            page_monotonic=page_stats["page_monotonic"],
            unique_ratio=page_stats["page_unique_ratio"],
            common_step=page_stats["common_page_step"],
        )
        if skeleton_valid and page_mapping_valid:
            decision = "USE_DIRECT"
        elif skeleton_valid:
            decision = "USE_SKELETON_MAP_LATER"
        else:
            decision = "REJECT"

        is_valid = skeleton_valid and page_mapping_valid

        result = {
            "is_valid": is_valid,
            "skeleton_valid": skeleton_valid,
            "page_mapping_valid": page_mapping_valid,
            "hierarchy_valid": hierarchy_valid,
            "decision": decision,
            "has_hierarchy": has_hierarchy,
            "top_level_count": len(top_level),
            "item_count": len(toc_items),
            "title_ratio": title_ratio,
            "reason": f"{len(top_level)} top-level items, {'has' if has_hierarchy else 'no'} hierarchy",
        }
        result.update(page_stats)
        result.update({
            "synthetic_root_detected": top_level_info["synthetic_root_detected"],
            "synthetic_root_reason": top_level_info["synthetic_root_reason"],
            "raw_min_level_count": top_level_info["raw_min_level_count"],
            "level_distribution": top_level_info["level_distribution"],
        })
        return result
