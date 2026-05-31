# PageIndex 流程重构计划 v3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 重构 fast/balanced/smart 三种模式的文档解析流程，代码提取优先 + VLM 兜底，消除 TOC 截断/页码错乱/乱码等系统性问题。

**Architecture:** 统一文档预分析 → 按文本质量路由 → fast 代码提取 / balanced 文本 LLM / balanced 视觉 VLM → 统一后处理 → 节点填充 → 摘要。

**Tech Stack:** PyMuPDF, Qwen3.5-flash (文本+视觉), glm-ocr (图片页OCR), Python 3.14, FastAPI, Pillow

---

## 核心流程图

```
Phase 0: pdf_analyzer — 纯代码 < 100ms
  ├─ 页面分类 (text / image_only / garbled / empty)
  ├─ text_coverage 计算
  ├─ 代码 TOC 提取 (书签 → 链接注解 → 正则)
  └─ 输出: 文档画像

路由决策 (纯代码):
  ├─ 有代码 TOC → Fast 路径 (0 VLM)
  ├─ 无代码 TOC + text_coverage >= 80% + 非乱码 → Balanced 文本路径 (0 VLM)
  └─ 无代码 TOC + text_coverage < 80% 或乱码 → Balanced 视觉路径 (VLM)

Fast 路径:
  代码 TOC → offset 校验 → LLM 质检 (1 次) → 完成或升级 balanced

Balanced 文本路径:
  LLM 全文分析 (generate_toc_init/continue) → 验证修复 → 完成

Balanced 视觉路径:
  Phase 0.5: VLM 缩略图网格 → 锚点检测 (toc_pages + dividers) — 1 次 VLM
  Phase 1:
    有 toc_page → VLM 看目录页+后续页 → TOC 提取 + offset 一步完成 — 1 次 VLM
    无 toc_page + 正常 divider → 按 divider 分组分析 — N 次 VLM
    无 toc_page + 密集 divider → divider 列表当 TOC — 1 次 VLM
    无任何锚点 → 固定分组全文分析 — N 次 VLM

Phase 2: 统一后处理 (post_processing.py)
  clean → validate → preface → assign_ranges → build_tree
  → fix_parent_ranges → completeness_check → split_large_nodes

Phase 3: 节点填充
  文本页 pymupdf 直取 + 图片/乱码页 OCR → 摘要生成

Phase 4: 前端进度上报
  阶段性进度 (分析/TOC构建/节点填充/摘要) + 实时模式显示
```

---

## 文件结构

| 文件 | 改动 | 职责 |
|------|------|------|
| `backend/pageindex/pdf_analyzer.py` | **已实现** | Phase 0: 文档预分析 |
| `backend/pageindex/fast_toc.py` | **已实现** | Fast: offset 校验 + LLM 质检 |
| `backend/pageindex/balanced_toc.py` | **需更新** | Balanced 视觉: 缩略图锚点 + 目录提取 + 全文分析 |
| `backend/pageindex/post_processing.py` | **已实现已测试** | 统一后处理: 8 步流程 + 完整性检查 |
| `backend/pageindex/node_filler.py` | **已实现** | 节点填充: 文本直取 + OCR + 摘要 |
| `backend/pageindex/vlm_utils.py` | **已实现** | VLM API 封装 + 页面渲染 + JSON 解析 |
| `backend/gen_thumbnail_grid.py` | **已实现已测试** | 缩略图网格生成工具 |
| `backend/app/services/pageindex_service.py` | **需更新** | 主流程编排 (~100行) |
| `backend/app/prompts/pageindex_prompts.py` | **需更新** | 新增 VLM 提示词 |
| `backend/pageindex/page_index.py` | **待精简** | 保留 process_large_node_recursively 等 |

---

## Task 1: pdf_analyzer.py — 文档预分析 ✅ 已实现

纯代码，零 LLM/VLM 调用，< 100ms。

输出文档画像:
```python
{
    "file_path": str,
    "page_count": 85,
    "pages": [{"index": 0, "type": "text"|"image_only"|"garbled"|"empty", ...}],
    "text_coverage": 0.85,
    "text_pages": [...],
    "image_only_pages": [...],
    "garbled_pages": [...],
    "is_image_only_pdf": False,
    "is_garbled_pdf": False,
    "code_toc": {"items": [...] or None, "source": "bookmarks"|"links"|"regex"|None},
    "page_list": [(text, token_count), ...],
    "page_texts": [str, ...],
}
```

---

## Task 2: fast_toc.py — Fast 模式 ✅ 已实现

**触发条件**: 文档画像中有代码 TOC（书签/链接注解/正则）
**VLM 调用**: 0 次
**LLM 调用**: 1 次（质检）

流程:
1. 从 `analysis["code_toc"]` 获取 TOC
2. 正则来源 → 模糊搜索计算 offset 并校正
3. 内容验证 (`verify_content_match`): 模糊搜索标题在页面中的位置
4. 如果有系统性偏移 → 二次 offset 校正
5. 覆盖度预检（last_page >= 50% page_count）
6. LLM 质检 (1 次): 传入匹配率/偏移量/不匹配详情
7. 通过 → 返回; 不通过 → return None（smart 升级 balanced）

---

## Task 3: balanced_toc.py — Balanced 模式 ⚠️ 需按最新方案更新

### 路由子分支

```python
def decide_balanced_path(analysis):
    text_coverage = analysis["text_coverage"]
    is_garbled = analysis["is_garbled_pdf"]
    
    if text_coverage >= 0.8 and not is_garbled:
        return "balanced_text"      # 纯文本 LLM
    else:
        return "balanced_visual"    # VLM 视觉
```

### Balanced 文本路径 (text_coverage >= 80%, 非乱码)

不需要 VLM。复用改良后的 LLM 全文分析:
- `generate_toc_init` + `generate_toc_continue`（闭合标签 `</physical_index_N>` 格式）
- 层级提取 prompt（"hierarchical tree structure", "x.x.x" 格式）
- 验证 + 修复循环
- **0 VLM + N LLM 调用**

### Balanced 视觉路径 (text_coverage < 80% 或乱码)

#### Phase 0.5: VLM 缩略图锚点检测 — 1 次 VLM

**方法**: 将所有页面渲染成缩略图网格（4x3 排列，每张 ≤12 页），传给 VLM

```
输入: 缩略图网格图片（多张，每张 12 页，4列×3行）
输出: {
  "toc_pages": [4],               // 目录页（物理页码，1-indexed）
  "chapter_dividers": [5,13,25],  // 章节分隔页
  "first_content_page": 6         // 第一个章节内容实际开始的物理页
}
```

**divider 密度处理**:
- 0 个 divider → 固定分组全文分析
- 2-10 个 (< 40% 页面) → 按 divider 分组分析
- > 40% 页面 → divider 列表直接当 TOC 条目

#### Phase 1 分支 A: 有目录页 — 1 次 VLM（含 offset）

**方法**: VLM 看目录页高清图 + 目录后 3-5 页高清图

```
输入: 目录页(高清) + 后续 3-5 页(高清)
任务:
  1. 提取目录所有条目 (structure, title, page)
  2. 判断第一章内容从哪一页开始 → first_chapter_physical_page
  3. 计算 offset = first_chapter_physical_page - first_item_page
  4. 判断目录是否延续到后续页面
输出: {
  "toc_items": [{structure, title, page}, ...],
  "first_chapter_physical_page": 6,
  "offset": 5,
  "toc_continues": "no"
}
```

**offset 直接由 VLM 回答，不需要代码计算。**

如果目录延续 → 续传更多页面继续提取（最多 3 轮）

如果目录无页码数字（page=null）→ 用 divider 物理位置作为 physical_index

#### Phase 1 分支 B: 无目录有 divider — N 次 VLM

**密集 divider (> 40% 页面)**: 1 次 VLM 看全部 divider 缩略图提取标题
**正常 divider (2-10)**: 按 divider 切分，每段 1 次 VLM 分析子章节

分组逻辑基于 divider 位置而非固定页数:
```
dividers = [5, 13, 25, 35, 41]
groups = [
  (5, 12),    # Part01
  (13, 24),   # Part02
  (25, 34),   # Part03
  (35, 40),   # Part04
  (41, 62),   # Part05
]
```

#### Phase 1 分支 C: 无任何锚点 — 分层全文分析

**注意: DashScope API 不支持直接传 PDF 文件，必须渲染为图片。**
**但 1M context 可以一次传 100+ 张图片（每张 ~2560 tokens）。**

**分层策略:**

**≤60 页（一次传完）:**
- 1 次 VLM 调用，传全部页面高清图
- prompt: "提取完整的层级 TOC，标注每个章节开始的物理页码"
- 准确率最高，无拼接问题
- 约 60 × 2560 = 153K tokens，远在 1M 限制内

**61-100 页（两阶段）:**
- 阶段 1: 1 次 VLM 看全部缩略图网格 → 识别"内容主题切换的大致页码"
  （不是提取 TOC，是找 topic_boundaries）
- 阶段 2: 按 boundaries 分组 → 每组传高清图 1 次 VLM 分析
- prompt 中包含前一组最后几个条目保证编号延续

**>100 页（三阶段）:**
- 阶段 1: 缩略图网格 → topic_boundaries（粗粒度）
- 阶段 2: 按 boundaries 分组 → 每组 VLM 高清分析（细粒度）
- 阶段 3: 合并 + 统一 structure 编号 + 去重

**Topic boundary 检测 prompt:**
```
这份文档没有明显的目录页或章节分隔页。
请观察页面内容的变化，识别主题切换的大致位置。
不需要精确标题，只需找到"内容发生明显变化"的页码。
回答 JSON: {"topic_boundaries": [1, 11, 25, 40]}
```

#### 验证 + 修复（所有视觉分支共用）

内容验证（仅 text_coverage > 50% 时执行，否则跳过）:
- 匹配率 >= 60% → 接受
- 匹配率 40-60% → VLM 逐项修复（最多 2 轮）
- 匹配率 < 40% → 进入下一个 fallback

### Balanced VLM 调用次数

| 场景 | Phase 0.5 | Phase 1 | 修复 | 总计 |
|------|-----------|---------|------|------|
| 有目录页（典型） | 1 | 1 | 0 | **2** |
| 有目录 + 续页 | 1 | 2 | 0 | **3** |
| 密集 divider | 1 | 1 | 0 | **2** |
| 正常 divider (5个) | 1 | 5 | 0-2 | **6-8** |
| 无锚点 (30页) | 1 | 4 | 0-4 | **5-9** |

---

## Task 4: node_filler.py — 节点填充 ✅ 已实现

- 文本页: pymupdf 直取
- 图片/乱码页: OCR（只用于检索，问答时模型看原始 PDF 图片）
- 摘要: fast 代码生成 / balanced LLM 生成
- 节点 ID: 深度优先 4 位编号

---

## Task 5: vlm_utils.py — VLM 封装 ✅ 已实现

- `render_pages_to_images()` — PyMuPDF 渲染高清页面图片
- `render_thumbnail_grid()` — 缩略图网格生成（4x3 排列，每张 ≤12 页）
- `vlm_call_with_images()` — Qwen3.5-flash 视觉 API 调用
- `parse_vlm_json()` — 健壮的 JSON 解析（处理 markdown fence、尾部逗号等）

---

## Task 6: VLM 提示词 ⚠️ 需更新

新增到 `pageindex_prompts.py`:

- `VLM_ANCHOR_DETECTION_PROMPT` — 缩略图网格锚点检测（目录页 + 分隔页 + first_content_page）
- `VLM_TOC_EXTRACT_WITH_OFFSET_PROMPT` — 看目录页+后续页，提取 TOC + offset 一步完成
- `VLM_TOC_CONTINUE_PROMPT` — 目录续提
- `VLM_FULLTEXT_SECTION_PROMPT` — 全文章节识别（按组）
- `VLM_FIX_ITEM_PROMPT` — 逐项修复
- 保留 `TOC_LIGHT_VALIDATION_PROMPT` — Fast LLM 质检

---

## Task 7: 重构 pageindex_service.py ⚠️ 需更新

```python
async def generate_index(self, file_path, doc_id, mode_override=None):
    # Phase 0: 文档预分析
    analysis = analyze_pdf_structure(file_path)
    
    # 路由决策
    requested_mode = mode_override or "smart"
    has_code_toc = analysis["code_toc"]["items"] is not None
    
    if requested_mode == "smart":
        execution_mode = "fast" if has_code_toc else "balanced"
    else:
        execution_mode = requested_mode
    
    # 细分 balanced 路径
    balanced_path = None
    if execution_mode == "balanced":
        tc = analysis["text_coverage"]
        garbled = analysis["is_garbled_pdf"]
        balanced_path = "text" if (tc >= 0.8 and not garbled) else "visual"
    
    # Phase 1: TOC 构建
    if execution_mode == "fast":
        result = await try_fast_toc(analysis, model)
        if not result:
            if requested_mode == "fast": raise ValueError("FAST_TOC_INCOMPLETE")
            execution_mode = "balanced"
            balanced_path = "text" if ... else "visual"
    
    if execution_mode == "balanced":
        if balanced_path == "text":
            result = await build_balanced_toc_text(analysis, model)
        else:
            result = await build_balanced_toc_visual(file_path, analysis, model)
    
    # Phase 2: 后处理 (post_processing.py)
    tree, completeness = post_process_toc(result["toc_items"], analysis["page_count"])
    
    # Phase 3: 节点填充 + OCR + 摘要
    await fill_nodes(tree, analysis, file_path, model, execution_mode)
    
    # 保存
    ...
```

---

## Task 8: 清理旧代码

保留:
- `process_large_node_recursively`（大节点递归拆分）
- `generate_node_summary`（LLM 摘要生成）
- `ChatGPT_API_async` / `ChatGPT_API`（LLM 调用封装）
- `count_tokens`（token 计数）

从 `page_index.py` 删除或标记废弃:
- `check_toc`, `find_toc_pages`, `toc_detector_batch`
- `toc_extractor`, `detect_page_index`
- `extract_toc_fast`, `extract_toc_code_only`, `validate_and_finalize_toc`
- 旧的 `meta_processor` 中 fast 模式分支
- 旧的 `tree_parser` 中 fast/smart 分支

---

## Task 9: 测试

- `test_pdf_analyzer.py` — 文档预分析（各种 PDF 类型）
- `test_fast_toc.py` — offset 校验 + 模糊搜索 + LLM 质检
- `test_post_processing.py` — 后处理 8 步 + 完整性检查
- `test_balanced_toc.py` — VLM 路径 (mock VLM)
- `test_node_filler.py` — 文本直取 / OCR
- 集成测试: 实际文档端到端

---

## Task 10: 前端阶段性进度条

### 后端上报阶段信息

```python
progress = {
    "stage": "analyzing"|"toc_building"|"node_filling"|"summary"|"completed"|"failed",
    "stage_label": "文件分析"|"TOC构建"|"节点填充"|"摘要生成"|"已完成"|"失败",
    "mode": "fast"|"balanced_text"|"balanced_visual",
    "detail": "正在用VLM扫描目录页...",
}
```

新增 DB 字段 `progress_data TEXT`，前端轮询读取。

### 前端 UI

4 个阶段圆点 + 进度条 + 模式显示 + 详情文本

---

## Task 11: 重试时清除报错

- 后端 reindex 接口: `SET error_message=NULL, progress_data=NULL`（启动新任务前）
- 前端: 点击重试时乐观更新 UI，立即清除错误

---

## 预期效果

### VLM/LLM 调用次数

| 文档类型 | 路径 | VLM | LLM |
|---------|------|-----|-----|
| 有书签 PDF | Fast | **0** | **1** (质检) |
| 有链接注解 PDF | Fast | **0** | **1** |
| 有正则 TOC | Fast | **0** | **1** |
| 纯文本无 TOC | Balanced 文本 | **0** | **N** (全文分析) |
| PPT 转 PDF (有目录页) | Balanced 视觉 | **2** | **0** |
| 纯图片 PDF (有目录页) | Balanced 视觉 | **2** | **0** |
| 无目录有 divider | Balanced 视觉 | **2-8** | **0** |
| 无目录无 divider (≤60页) | Balanced 视觉 | **2** (缩略图+全页) | **0** |
| 无目录无 divider (>60页) | Balanced 视觉 | **2+N** (缩略图+分组) | **0** |
| 乱码 PDF | Balanced 视觉 | **2** | **0** |

### 耗时估算

| 模式 | 当前 | 重构后 |
|------|------|--------|
| fast | 5-15s | **2-3s** |
| balanced 文本 | 60-180s | **20-40s** |
| balanced 视觉 | N/A(失败) | **15-60s** |

---

## 附录 A: 后处理详细逻辑 (post_processing.py) ✅ 已实现已测试

8 步处理: clean → validate → preface → assign_ranges → build_tree → fix_parent → completeness_check → format

### Coverage 分层阈值

```
max_uncovered = min(max(2, ceil(page_count * 0.05)), 10)
```

| 页数 | 允许漏页 | 覆盖率要求 |
|------|---------|---------|
| 10 页 | 2 页 | 80% |
| 20 页 | 2 页 | 90% |
| 40 页 | 2 页 | 95% |
| 80 页 | 4 页 | 95% |
| 100 页 | 5 页 | 95% |
| 200 页 | 10 页(上限) | 95% |

### Coverage 不足时的处理

```
quality = "good"    → 漏 ≤3 且 ≥95%
quality = "ok"      → 漏 ≤阈值 且到达末尾
quality = "warning" → 漏 ≤阈值*2 → 需要修复
quality = "bad"     → 其他 → 需要修复

修复流程:
  1. 定位 gaps（未覆盖的连续页面段）
  2. 对 gap 区域补充分析:
     - 文本路径: LLM 分析缺失页面文本
     - 视觉路径: VLM 看缺失页面图片
  3. 新条目插入现有 TOC → 重新 post_process
  4. 仍不足 → 兜底: 创建占位节点 "内容 (p.N-M)"
```

### 其他保证

- Preface 独立为顶级节点，不做其他章节的父
- 父节点 end_index 覆盖所有子节点
- 同页条目正确处理
- 乱序输入自动排序

---

## 附录 B: Offset 计算策略

| TOC 来源 | 返回页码类型 | offset 方式 |
|---------|---------|-----------|
| PDF 书签 | 物理页码 | 不需要 |
| Link Annotations | 物理页码 | 不需要 |
| 正则提取 | 逻辑页码 | 代码模糊搜索 |
| VLM 看目录页 | 逻辑页码 | **VLM 同时看后续页直接返回 offset** |
| VLM 全文分析 | 物理页码 | 不需要（prompt 告知页码） |
| VLM 看 divider | 物理页码 | 不需要（缩略图标注页码） |

---

## 附录 C: 缩略图网格规格

- 排列: 4 列 × 3 行 = 每张 12 页
- 缩略图尺寸: 250×350 px
- 页码标注: 左上角 "p.N"
- 62 页文档 → 6 张网格图
- 每张约 400-700 KB
- 已测试: 快消白皮书(62页) + 重庆案例集(44页)

---

## 附录 D: divider 密度处理策略

**不做任何硬编码校验规则，完全信任 VLM 的锚点判断。只做密度分类路由：**

| divider 密度 | 策略 |
|------------|------|
| 0 个 | 分层全文分析（≤60 页一次传完 / >60 页两阶段） |
| ≤40% 页面 | 按 divider 分组，每组 VLM 分析子章节 |
| >40% 页面 | 优先用目录页；否则 divider 列表当 TOC 条目 |

---

## 附录 E: DashScope API 限制

- **不支持直接传 PDF 文件**，必须渲染为图片（PNG/JPEG/WEBP）
- **图片数量无硬限制**，受 token 总量限制
- 每张图片默认 ~2560 tokens（max_pixels=2621440, 32×32 per token）
- 1M context → 理论上可传 ~390 张图片
- 实际考虑输出 tokens 和 prompt → **安全上限约 100-200 张图片**
- 60 页 PDF × 2560 tokens ≈ 153K tokens → **1 次调用可传完**
- Base64 编码支持（OpenAI compatible API）
- 本地文件路径仅 DashScope SDK 支持
