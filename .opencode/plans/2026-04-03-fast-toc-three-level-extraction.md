# Fast TOC 三级提取重构计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fast 模式用代码提取 TOC（PDF 书签 → Link Annotations → 正则），仅 1 次 LLM 轻校验，不通过则 fast raise / smart 升级 balanced。

**Architecture:** 三级优先级 TOC 提取 + 代码预检 + 1 次 LLM 校验。`tree_parser` 已有 `doc` 参数传递 file_path，Level 1/2 通过它打开 PDF。

**Tech Stack:** PyMuPDF (pymupdf), Python regex, FastAPI, Qwen3.5-flash

---

## 预期效果

### LLM 调用对比

| 文档类型 | 当前 | 改进后 |
|----------|------|--------|
| 有 PDF 书签 | 6-8 次 | **1 次** |
| 有 Link Annotations | 6-8 次 | **1 次** |
| 有标准格式 TOC 文本 | 6-8 次 | **1 次** |
| 无 TOC (fast) | fast raise | fast raise（不变） |
| 无 TOC (smart) | 6-8 次 + 升级 | **0 次 + 直接升级 balanced** |

---

## Task 1: 新增 TOC_LIGHT_VALIDATION_PROMPT

**Files:** `backend/app/prompts/pageindex_prompts.py`

## Task 2: 实现三级 TOC 提取函数

**Files:** `backend/pageindex/page_index.py`

- Level 1: `extract_toc_from_pdf_bookmarks(doc_path)` — pymupdf get_toc()
- Level 2: `extract_toc_from_link_annotations(doc_path)` — page.get_links() + get_text(clip=rect)
- Level 3: `find_toc_pages_by_rules(page_list)` — 正则 "标题...页码" 行检测
- 辅助: `_levels_to_structure(items)`, `_parse_toc_text_to_items(toc_text)`

## Task 3: 实现 `extract_toc_fast()` 入口

**Files:** `backend/pageindex/page_index.py`

- 三级提取 → 代码预检(last_page >= page_count*0.5) → LLM 轻校验(1次)
- 返回 `{"toc_items": [...], "source": "bookmarks|links|regex", "valid": True}` 或 None

## Task 4: 修改 `tree_parser` 集成新流程

**Files:** `backend/pageindex/page_index.py:2243`

- fast/smart 优先走 `extract_toc_fast()`
- 成功 → 直接 post_processing（跳过 meta_processor/toc_transformer/offset）
- 失败 → fast raise / smart fall through to balanced

## Task 5: 测试

**Files:** `backend/tests/test_fast_toc_extraction.py`

## Task 6: 回归测试 + 重启
