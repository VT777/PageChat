# TOC Legacy Cleanup And Unified Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理 TOC 构建旧路径，统一 OCR、候选生命周期、TOC 抽取、物理页码映射、质量门和输出契约，让 `toc_generation_unified_architecture.md` 成为唯一有效架构。

**Architecture:** 最终流程固定为 `S0 Analyze -> S1 PageTextMap -> S2 Code TOC Evidence -> S3 TOC Page Detection -> S4 TocDraft Build -> S5 Physical Mapping/Range Derivation -> S6 Quality Gate -> S7 Save Base -> S8 Enrich`。OCR 只属于 S1；S4 只产出结构草稿；S5 是唯一写入 `physical_index/start_index/end_index` 的位置；S6 是唯一决定通过/失败/needs_review 的质量入口。

**Tech Stack:** Python 3.14, PyMuPDF, OpenAI-compatible OCR (`qwen3.5-ocr`), existing `PageIndexService`, pytest, real AI Knowledge PDF dataset, official PageIndex validation dataset.

---

## Scope

本计划只处理 PDF TOC 构建链路，不改前端展示、不重写检索模块、不重做摘要生成。所有改动必须保持节点内容最终仍从 `PageTextMap` 填充。

当前工作区已有多处未提交改动。执行前先做工作区审计，只提交本计划相关核心文件；测试输出、临时评估目录和无关文件不得提交。

## Target Invariants

- OCR task 只有 `page_text`，提示词统一为：`完整、准确地抽取内容，用markdown输出`。
- `toc_page` 只能表示“目录页语义”，不能再作为 OCR task 或 OCR profile。
- `PageTextMap` 是 TOC 检测、抽取、映射、节点填充的唯一文本输入。
- `TOCPipelineController` / `TOCJudge` 不再参与生产主链路。
- 所有路径先产出 `TocDraft`，不得在 S4 写最终物理页码。
- `physical_index/start_index/end_index` 只由 S5 统一写入。
- `end_index` 按官方 PageIndex 思路派生：如果下一个节点起始标题在下一页页首附近，当前节点结束页为 `next.start_index - 1`；否则允许当前节点结束页与下个节点起始页重合。
- 规则抽取只能作为高置信 TOC draft 入口；不确定时进入 LLM TOC draft。
- `visible_toc_with_pages` 映射失败时降级为 `visible_toc_no_pages`，不能硬算 offset。
- `segment_fallback`、独立 `page_heading_outline`、独立 `page_outline` 不再作为 TOC 路由或候选。
- 图目录、表目录、主目录必须统一进入 `toc_sections`，前端顶级仍可显示为 `目录 / 图目录 / 表目录`。
- 质量门只判断事实可用性，不因“平铺但符合原文”失败。
- 输出 JSON 必须严格可解析，不能含未转义控制字符。

## File Structure

### Create

- `backend/pageindex/toc_contracts.py`
  - 定义 `TocDraft`、`TocSectionDraft`、`MappedToc`、`TocAttemptRecord`、`QualityFacts` 的轻量 dict/dataclass 契约。
- `backend/pageindex/pipeline/toc_attempt_runner.py`
  - 唯一候选生命周期执行器：按 state machine 的 attempt chain 执行 build、S5 map、quality、fallback、best candidate。
- `backend/pageindex/toc_quality_gate.py`
  - 汇总 deterministic facts、LLM QC 结果和 final verdict，替代分散 hard-fail 汇总。
- `backend/tests/test_toc_attempt_runner.py`
  - 覆盖 attempt chain、fallback、best candidate、旧 controller 不参与。
- `backend/tests/test_toc_contracts.py`
  - 覆盖 draft/mapped contract，不允许 S4 写最终页码。
- `backend/tests/test_ocr_unified_page_text_only.py`
  - 覆盖 `toc_page` OCR task 不再被主链路调用。

### Modify

- `backend/app/services/pageindex_service.py`
  - 从巨型 service 中移除旧候选竞争、旧 visual TOC OCR、旧 fallback、重复 mapping、分散 quality 入口。
- `backend/pageindex/pipeline/toc_state_machine.py`
  - 输出 deterministic attempt chain，而不是只输出单一路径标签。
- `backend/pageindex/preprocess_page_text.py`
  - 保留唯一 PageTextMap 预处理入口，接入 OCR cache。
- `backend/app/services/ocr_engines/task_prompts.py`
  - 保留统一 page_text prompt。
- `backend/app/services/ocr_settings_service.py`
  - 删除或兼容迁移 `toc_page` OCR task 配置。
- `backend/app/services/ocr_cache_service.py`
  - 接入 PageTextMap OCR 调用链。
- `backend/pageindex/code_toc_collector.py`
  - 修复 main/table/figure sections 合并和 `items`/`toc_sections` 下游一致性。
- `backend/pageindex/candidates/llm_toc_page_extractor.py`
  - 统一目录页 LLM 抽取 schema，支持 `toc_sections`。
- `backend/pageindex/visible_toc_rule_extractor.py`
  - 只保留 draft 抽取函数，删除或废弃内部 mapped 版本。
- `backend/pageindex/toc_mapping.py`
  - 成为唯一 S5 entrypoint，统一 offset、标题锚点、范围派生、目录页泄漏校验。
- `backend/pageindex/hierarchical_extractor.py`
  - 子树展开只输出结构和标题证据，不让 LLM 猜物理页。
- `backend/pageindex/post_processing.py`
  - 删除重复 range normalization 对最终页码的所有权，仅保留 schema cleanup。
- `backend/pageindex/balanced_quality_gate.py`
  - 并入或调用 `toc_quality_gate.py` 的统一 facts。
- `backend/pageindex/index_quality.py`
  - 与统一质量门共享 facts 和 reason code。
- `backend/tests/fixtures/toc/ai_knowledge_expected_toc_reference.json`
  - 更新 13 份真实文档预期路径、关键页码、质量门结果。
- `scripts/run_ai_knowledge_toc_e2e.py`
  - 报告 attempt chain、耗时、OCR 统计、S5 mapping facts、quality facts。

### Delete Or Retire From Production Path

- `backend/pageindex/pipeline/toc_pipeline_controller.py`
- `backend/pageindex/judge/toc_judge.py`
- `backend/pageindex/candidates/ocr_toc_page_extractor.py`
- `backend/pageindex/toc_page_extractor.py` 的生产调用
- `segment_fallback` 生产候选
- `page_heading_outline` 生产候选
- `legacy visual toc layout` 生产路径

如果直接删除会影响旧测试，先改测试指向新 contract；不得为了旧测试保留生产分支。

---

## Task 0: Baseline And Guard Rails

**Files:**
- Modify: `backend/tests/test_toc_new_architecture.py`
- Modify: `backend/tests/test_ai_knowledge_e2e_report_contract.py`
- Modify: `scripts/run_ai_knowledge_toc_e2e.py`

- [ ] **Step 0.1: 记录当前工作区**

Run:

```powershell
git status --short
git diff --stat
```

Expected: 记录已有改动，确认本计划只处理 TOC 核心文件。

- [ ] **Step 0.2: 增加旧路径禁止测试**

新增测试断言生产主链路不得引用：

```python
def test_pdf_index_main_flow_does_not_use_legacy_controller():
    source = inspect.getsource(PageIndexService._generate_pdf_index)
    assert "TOCPipelineController" not in source
    assert "TOCJudge" not in source
```

并增加 OCR 任务约束：

```python
def test_pdf_index_ocr_uses_page_text_only():
    source = inspect.getsource(PageIndexService._generate_pdf_index)
    assert '_resolve_ocr_engine("toc_page")' not in source
```

- [ ] **Step 0.3: 跑失败测试确认 guard 有效**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_toc_new_architecture.py -q
```

Expected: 当前实现应 FAIL，失败点指向旧 controller / `toc_page` OCR 残留。

- [ ] **Step 0.4: 保存阶段基线报告**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-baseline --mode smart
```

Expected: 每个文件都有耗时、路径、质量、index 路径；失败项作为后续对照。

---

## Task 1: Unified Contracts And Attempt Runner

**Files:**
- Create: `backend/pageindex/toc_contracts.py`
- Create: `backend/pageindex/pipeline/toc_attempt_runner.py`
- Modify: `backend/pageindex/pipeline/toc_state_machine.py`
- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_toc_contracts.py`
- Test: `backend/tests/test_toc_attempt_runner.py`

- [ ] **Step 1.1: 写 contract 测试**

覆盖：

- `TocDraft` 允许 `raw_page_label`，不允许 `physical_index/start_index/end_index`。
- `MappedToc` 必须有 `physical_index/start_index/end_index`。
- `toc_sections` 保留 `main_toc/table_toc/figure_toc`。

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_toc_contracts.py -q
```

Expected: FAIL，因为 contract 尚未实现。

- [ ] **Step 1.2: 实现 `toc_contracts.py`**

实现最小函数：

```python
def normalize_toc_draft(payload: Mapping[str, Any]) -> dict[str, Any]: ...
def assert_s4_draft_contract(draft: Mapping[str, Any]) -> None: ...
def normalize_mapped_toc(payload: Mapping[str, Any]) -> dict[str, Any]: ...
```

S4 draft 中发现最终页码字段时抛错，除非字段在 `metadata.source_*` 内。

- [ ] **Step 1.3: 写 attempt runner 测试**

场景：

- `embedded_toc` 通过质量门则直接 accept。
- `embedded_toc` 失败后进入 `visible_toc_with_pages`。
- `visible_toc_with_pages` S5 mapping 失败后进入 `visible_toc_no_pages`。
- 所有 attempts 失败时保留 `best_candidate` 和完整 failure chain。
- 任何 attempt 都必须先走 S5 再走 S6。

- [ ] **Step 1.4: 实现 `toc_attempt_runner.py`**

核心接口：

```python
class TocAttemptRunner:
    async def run(self, plan, context) -> dict[str, Any]:
        ...
```

`context` 包含 `analysis`、`page_text_map`、`page_texts`、`page_count`、`model`、`toc_pages`。

每个 attempt 记录：

- `attempt_id`
- `path`
- `builder`
- `draft_item_count`
- `mapping_status`
- `quality_status`
- `failure_reasons`
- `can_be_best_candidate`

- [ ] **Step 1.5: 改 state machine 输出 attempt chain**

输出示例：

```json
[
  {"path": "embedded_toc", "reason": "code_toc_signal"},
  {"path": "visible_toc_with_pages", "reason": "toc_pages_with_page_numbers"},
  {"path": "visible_toc_no_pages", "reason": "mapping_fallback"},
  {"path": "content_outline", "reason": "last_resort"}
]
```

不得输出 `hierarchical`、`batch`、`fast_text`、`ppocr_layout` 作为独立路径。

- [ ] **Step 1.6: 接入 PageIndexService**

在 `_generate_pdf_index` 中：

- S1 之后构建 context。
- 调用 `TocStateMachine.plan(...)`。
- 调用 `TocAttemptRunner.run(...)`。
- 删除旧 `controller.generate(...)` 主链路调用。

- [ ] **Step 1.7: 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_toc_contracts.py backend/tests/test_toc_attempt_runner.py backend/tests/test_toc_state_machine.py backend/tests/test_toc_new_architecture.py -q
```

Expected: PASS。

- [ ] **Step 1.8: 真实数据阶段测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-phase1 --mode smart
```

Expected:

- 13 份文件都有 `attempt_chain`。
- 不再出现 `[TOC-JUDGE]`。
- 不再出现 `source=segment_fallback`。
- 质量差的结果可以失败，但失败报告必须指向具体 attempt 和 reason。

- [ ] **Step 1.9: Commit**

```powershell
git add backend/pageindex/toc_contracts.py backend/pageindex/pipeline/toc_attempt_runner.py backend/pageindex/pipeline/toc_state_machine.py backend/app/services/pageindex_service.py backend/tests scripts/run_ai_knowledge_toc_e2e.py
git commit -m "refactor: add unified toc attempt lifecycle"
```

---

## Task 2: OCR Unification And Cache

**Files:**
- Modify: `backend/pageindex/preprocess_page_text.py`
- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/app/services/ocr_engines/task_prompts.py`
- Modify: `backend/app/services/ocr_settings_service.py`
- Modify: `backend/app/services/ocr_cache_service.py`
- Test: `backend/tests/test_ocr_unified_page_text_only.py`
- Test: `backend/tests/test_page_text_map.py`

- [ ] **Step 2.1: 写 OCR 单入口测试**

断言：

- `OCR_TASKS == {"page_text"}` 或 `toc_page` 仅作为向后兼容配置迁移，不被主链路请求。
- `_generate_pdf_index` 不调用 `_resolve_ocr_engine("toc_page")`。
- `preprocess_page_text_map` 是唯一 OCR 入口。
- OCR prompt 等于 `完整、准确地抽取内容，用markdown输出`。

- [ ] **Step 2.2: 删除 `toc_page` OCR 生产入口**

处理：

- 删除 `_build_layout_with_resolver` 生产调用。
- 删除 `_recognize_toc_pages_with_vl` 生产调用。
- `toc_page` OCR diagnostics 只保留旧数据读取兼容，不再写新数据。
- `layout_required` 不再触发 S4 layout 路径，只影响 S1 OCR 策略。

- [ ] **Step 2.3: 统一 prompt 来源**

保留单一 prompt 常量，建议放在 `backend/app/services/ocr_engines/task_prompts.py`，`preprocess_page_text.py` 从这里导入，避免两处维护。

```python
PAGE_TEXT_PROMPT = "完整、准确地抽取内容，用markdown输出"
```

- [ ] **Step 2.4: 接入 OCR cache**

缓存 key 必须包含：

- PDF path 或文件 hash
- page number
- rendered image hash
- model
- prompt sha256
- OCR profile version

PageTextMap 调用 OCR 前先查 cache，miss 时调用 OCR，成功后写 cache。

- [ ] **Step 2.5: OCR 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_ocr_unified_page_text_only.py backend/tests/test_page_text_map.py backend/tests/test_ocr_pipeline.py -q
```

Expected: PASS。

- [ ] **Step 2.6: 快消真实 OCR 验证**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --file "2026年快消行业AI营销增长白皮书.pdf" --output eval0618\legacy-cleanup-phase2-t07 --mode smart
```

Expected:

- OCR summary 只有 `page_text`。
- 不出现 `toc_page` OCR。
- Part03 仍展开 Step1-4。
- 第二次重跑应命中 cache，耗时明显下降或 diagnostics 显示 cache hits。

- [ ] **Step 2.7: 全量真实数据测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-phase2 --mode smart
```

Expected:

- 所有 OCR 型/混合型文件只有 `page_text` OCR。
- 主日志仅有 OCR 摘要，不写详细 OCR 输入输出。

- [ ] **Step 2.8: Commit**

```powershell
git add backend/pageindex/preprocess_page_text.py backend/app/services/pageindex_service.py backend/app/services/ocr_engines/task_prompts.py backend/app/services/ocr_settings_service.py backend/app/services/ocr_cache_service.py backend/tests
git commit -m "refactor: unify ocr through page text map"
```

---

## Task 3: Unified TOC Draft Builders

**Files:**
- Modify: `backend/pageindex/code_toc_collector.py`
- Modify: `backend/pageindex/candidates/llm_toc_page_extractor.py`
- Modify: `backend/pageindex/visible_toc_rule_extractor.py`
- Modify: `backend/app/services/pageindex_service.py`
- Delete/Retire: `backend/pageindex/toc_page_extractor.py` production usage
- Test: `backend/tests/test_code_toc_collector.py`
- Test: `backend/tests/test_visible_toc_rule_extractor.py`
- Test: `backend/tests/test_pageindex_prompt_templates.py`

- [ ] **Step 3.1: 写 unified draft builder 测试**

覆盖：

- code_toc 同时采集 bookmarks 和 links，不因 bookmarks 存在跳过 links。
- `items` 与 `toc_sections` 一致，不丢图目录/表目录。
- 规则抽取只返回 draft，不返回 mapped final items。
- LLM TOC 抽取返回 `toc_sections`，支持一页同时有 `main_toc/table_toc/figure_toc`。

- [ ] **Step 3.2: 修复 code_toc collector**

要求：

- `toc_sections` 为权威结构。
- `items` 只是 `main_toc` 的兼容视图，不作为下游唯一输入。
- `embedded_toc` 接受时必须保留辅助目录。

- [ ] **Step 3.3: 统一 visible TOC rule extractor**

删除或内部私有化这些会直接 mapping 的旧函数：

- `extract_visible_toc_with_pages`
- `extract_visible_toc_no_pages`

生产主链路只调用：

- `extract_visible_toc_with_pages_draft`
- `extract_visible_toc_no_pages_draft`

如果保留旧函数供测试对比，必须命名为 `_legacy_*` 且生产代码不得引用。

- [ ] **Step 3.4: 统一 LLM TOC extractor**

只保留一个 prompt/schema：

```json
{
  "toc_sections": [
    {
      "kind": "main_toc",
      "title": "目录",
      "items": [
        {"title": "Chapter title", "level": 1, "raw_page_label": "5"}
      ]
    }
  ]
}
```

LLM 不输出 `physical_index/start_index/end_index`。

- [ ] **Step 3.5: 删除旧 fallback candidates**

从生产代码删除：

- `segment_fallback`
- `page_heading_outline`
- 独立 `page_outline`
- `hierarchical` / `batch` / `fast_text` 作为并列候选

`hierarchical` 和 batch 能力只允许作为 `content_outline` 内部实现。

- [ ] **Step 3.6: 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_code_toc_collector.py backend/tests/test_visible_toc_rule_extractor.py backend/tests/test_pageindex_prompt_templates.py backend/tests/test_pageindex_service_provider_shortcut.py -q
```

Expected: PASS。

- [ ] **Step 3.7: 真实数据阶段测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-phase3 --mode smart
```

Expected:

- T13 保留目录、图目录、表目录。
- T06 / T13 的 code_toc 能力不因单源短路丢 sections。
- T03/T08/T09/T11 的可见目录规则通过时走 rule draft；规则不够高置信时走 LLM draft。

- [ ] **Step 3.8: Commit**

```powershell
git add backend/pageindex/code_toc_collector.py backend/pageindex/candidates/llm_toc_page_extractor.py backend/pageindex/visible_toc_rule_extractor.py backend/app/services/pageindex_service.py backend/tests
git commit -m "refactor: unify toc draft builders"
```

---

## Task 4: Single S5 Physical Mapping And Official Range Rule

**Files:**
- Modify: `backend/pageindex/toc_mapping.py`
- Modify: `backend/pageindex/judge/content_page_mapper.py`
- Modify: `backend/pageindex/post_processing.py`
- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_toc_mapping.py`
- Test: `backend/tests/test_auxiliary_catalog_normalization.py`

- [ ] **Step 4.1: 写 S5 所有权测试**

断言：

- S4 draft 输入含 `raw_page_label`，S5 输出最终页码。
- post-processing 不再重写已映射页码。
- controller/judge 不再 mapping。
- 辅助目录为 point-like 或独立 catalog range，不抢占正文页码。

- [ ] **Step 4.2: 实现统一 S5 entrypoint**

保留单一入口：

```python
def map_toc_draft_to_physical(draft, *, page_texts, page_count, toc_pages, selected_path) -> tuple[list[dict], dict]:
    ...
```

所有路径必须通过该函数。

- [ ] **Step 4.3: 实现官方 end_index 派生规则**

为每个 mapped node 保存标题命中位置：

```json
{
  "matched_page": 23,
  "line_index": 0,
  "char_offset": 12,
  "near_page_top": true
}
```

范围派生：

- 若下个节点 `near_page_top=true`，当前 `end_index = next.start_index - 1`。
- 否则当前 `end_index = next.start_index`。
- 对无法判断位置的情况，默认允许边界重合，但必须记录 `range_boundary_uncertain` warning。

- [ ] **Step 4.4: 修复 title mapping**

要求：

- `visible_toc_with_pages` 先尝试 printed page offset，再抽样标题校验。
- offset 校验失败时降级为 `visible_toc_no_pages`，按标题检索定位。
- `visible_toc_no_pages` 不允许硬算 offset。
- 标题搜索排除 TOC 页，避免目录页泄漏。
- 图目录/表目录使用独立 section mapping，不参与正文 offset。

- [ ] **Step 4.5: 删除重复 range normalization 所有权**

`post_processing.normalize_tree_page_ranges` 不再作为最终页码规则入口。若仍需 schema cleanup，只能补缺失字段，不能覆盖 S5 输出。

- [ ] **Step 4.6: 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_toc_mapping.py backend/tests/test_auxiliary_catalog_normalization.py backend/tests/test_pageindex_service_balanced_flow.py -q
```

Expected: PASS。

- [ ] **Step 4.7: 针对问题样本测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --file "OpenAI深度报告：大模型王者，引领AGI之路.pdf" --output eval0618\legacy-cleanup-phase4-t09 --mode smart
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --file "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf" --output eval0618\legacy-cleanup-phase4-t03 --mode smart
```

Expected:

- T09 已有物理页目录时，不被错误 remap；`1.3 估值` 回到正确页段。
- T03 不接受低置信规则页码；必要时回退 LLM draft + S5 标题定位。

- [ ] **Step 4.8: 全量真实数据测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-phase4 --mode smart
```

Expected:

- 不出现大量节点指向目录页。
- 辅助目录不抢占正文页码。
- `mapping.source == unified_s5`。

- [ ] **Step 4.9: Commit**

```powershell
git add backend/pageindex/toc_mapping.py backend/pageindex/judge/content_page_mapper.py backend/pageindex/post_processing.py backend/app/services/pageindex_service.py backend/tests
git commit -m "fix: make s5 the single toc page mapping owner"
```

---

## Task 5: Child Expansion Through Structure Draft Plus S5

**Files:**
- Modify: `backend/pageindex/hierarchical_extractor.py`
- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/pageindex/toc_mapping.py`
- Test: `backend/tests/test_hierarchical_extractor.py`
- Test: `backend/tests/test_toc_mapping.py`

- [ ] **Step 5.1: 写子树 contract 测试**

测试要求：

- LLM child expansion 输出 `title/level/structure/raw_evidence`。
- LLM 不输出最终 `page/physical_index/start_index/end_index`。
- 子节点最终页码由 S5 按标题在父章节范围内定位。
- 同名但内容不同的序号允许通过，例如 T04/T12 中相同编号不同章节。

- [ ] **Step 5.2: 改子树 prompt**

输入每页最多 200 字，保持用户确认的限制。

Prompt 要求：

- Extract subsection structure only.
- Use original heading text and numbering.
- Do not guess physical pages or end pages.
- Repeated numbering in different chapters is allowed when titles differ.

输出：

```json
{
  "sub_chapters": [
    {"title": "Step1——小额测试", "level": 2, "structure": "Step1"}
  ]
}
```

- [ ] **Step 5.3: 子树进入 S5 局部映射**

为 parent 子树调用：

```python
map_child_draft_to_physical(parent, child_draft, page_texts, parent_start, parent_end)
```

限制搜索范围为父节点 `[start_index, end_index]`。

- [ ] **Step 5.4: 清理 page-based dedupe**

不再用 `seen_pages` 决定是否丢子节点。去重只基于同一父节点下的规范化标题和结构；如果 S5 将多个标题定位到同页，按事实保留并交给质量门判断。

说明：用户第 7 项认为第 6 项修复后同页异常会自然消失；这里不把同页作为硬过滤条件，避免误删真实同页子标题。

- [ ] **Step 5.5: 快消 Part03 回归测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --file "2026年快消行业AI营销增长白皮书.pdf" --output eval0618\legacy-cleanup-phase5-t07 --mode smart
```

Expected:

- Part03 有 Step1、Step2、Step3、Step4。
- Step1-4 的页码来自 S5 title mapping report。
- 不出现只剩 Step1。

- [ ] **Step 5.6: 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_hierarchical_extractor.py backend/tests/test_toc_mapping.py backend/tests/test_pageindex_service_balanced_flow.py -q
```

Expected: PASS。

- [ ] **Step 5.7: 全量真实数据测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-phase5 --mode smart
```

Expected:

- T04/T05/T07/T08/T11/T12 不再只有一级目录，除非参考预期明确允许平铺。
- 子树展开失败时 quality facts 明确说明原因。

- [ ] **Step 5.8: Commit**

```powershell
git add backend/pageindex/hierarchical_extractor.py backend/app/services/pageindex_service.py backend/pageindex/toc_mapping.py backend/tests
git commit -m "fix: map child outline pages through s5"
```

---

## Task 6: Unified Quality Gate

**Files:**
- Create: `backend/pageindex/toc_quality_gate.py`
- Modify: `backend/pageindex/balanced_quality_gate.py`
- Modify: `backend/pageindex/index_quality.py`
- Modify: `backend/pageindex/post_processing.py`
- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_balanced_quality_gate.py`
- Test: `backend/tests/test_index_quality.py`
- Test: `backend/tests/test_pdf_index_quality_gates.py`

- [ ] **Step 6.1: 写统一 quality facts 测试**

facts 至少包括：

- `path`
- `source`
- `toc_sections`
- `toc_pages`
- `mapping_status`
- `title_match_rate`
- `toc_page_leakage`
- `range_validity`
- `node_content_fill_rate`
- `child_expansion_expected`
- `child_expansion_status`
- `llm_qc_verdict`

- [ ] **Step 6.2: 实现 `toc_quality_gate.py`**

统一返回：

```json
{
  "status": "ok|needs_review|failed",
  "hard_fail_reasons": [],
  "warnings": [],
  "facts": {}
}
```

硬失败条件：

- S5 mapping failed。
- 页码越界。
- 大量正文节点落在 TOC 页。
- collapsed single node 覆盖全文。
- 节点内容无法从 PageTextMap 填充。
- 需要子树展开但展开后仍缺失且不符合参考预期。

非硬失败：

- 平铺但符合原文目录。
- 相邻节点边界重合。
- 辅助目录 point-like。

- [ ] **Step 6.3: 移除 advisory/suppress 混乱**

处理：

- `llm_quality_check` 只提供 verdict 和 factual reasons。
- 不再使用分散的 `llm_quality_advisory_only` 掩盖 hard facts。
- `retained_best_candidate` 只允许在调试报告中说明，不能把 failed 改写成 ok。

- [ ] **Step 6.4: 接入 service**

`PageIndexService` 最终只调用一次统一质量门。`completeness`、`balanced_quality_gate`、`quality_report` 保留为兼容字段时，必须来自同一个 `quality_report.facts`。

- [ ] **Step 6.5: 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_balanced_quality_gate.py backend/tests/test_index_quality.py backend/tests/test_pdf_index_quality_gates.py -q
```

Expected: PASS。

- [ ] **Step 6.6: 全量真实数据测试**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-phase6 --mode smart
```

Expected:

- 每份报告都有统一 `quality.facts`。
- 平铺可接受文件不因“没有层级”失败。
- 页码错误/目录页泄漏必须失败或 needs_review，并给出明确 reason。

- [ ] **Step 6.7: Commit**

```powershell
git add backend/pageindex/toc_quality_gate.py backend/pageindex/balanced_quality_gate.py backend/pageindex/index_quality.py backend/pageindex/post_processing.py backend/app/services/pageindex_service.py backend/tests
git commit -m "fix: unify toc quality gate"
```

---

## Task 7: Output Hygiene, Logging, And Legacy Deletion

**Files:**
- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/pageindex/node_filler.py`
- Modify: `scripts/run_ai_knowledge_toc_e2e.py`
- Delete: legacy files only after tests prove no production imports.
- Test: `backend/tests/test_ai_knowledge_e2e_report_contract.py`
- Test: `backend/tests/test_toc_new_architecture.py`

- [ ] **Step 7.1: 写严格 JSON 输出测试**

测试保存后的 index：

```python
text = path.read_text(encoding="utf-8")
json.loads(text)
assert not any(ord(ch) < 32 and ch not in "\r\n\t" for ch in text)
```

- [ ] **Step 7.2: 清理节点文本控制字符**

在写 index 前统一 sanitize：

- 删除非法控制字符。
- 保留合法换行和 tab。
- 确保 `ensure_ascii=False` 输出仍为严格 JSON。

- [ ] **Step 7.3: 清理日志语义**

主日志只保留：

```text
[TOC-OCR] task=page_text model=qwen3.5-ocr pages=62 concurrency=20 status=done
[TOC-ROUTE] selected_path=visible_toc_no_pages attempts=...
[TOC-MAPPING] source=unified_s5 status=ok ...
[TOC-QUALITY] status=ok|needs_review|failed ...
```

删除或停止输出：

- `[TOC-JUDGE]`
- `pipeline_path=ppocr_layout`
- `structure_source=layout_first`
- `task=toc_page`

- [ ] **Step 7.4: 删除旧生产文件或隔离到 legacy 测试目录**

删除前运行：

```powershell
rg -n "TOCPipelineController|TOCJudge|ocr_toc_page|toc_page_extractor|segment_fallback|page_heading_outline" backend/app backend/pageindex backend/tests
```

Expected: 生产目录无引用；测试目录若引用，必须是“旧路径禁止”测试。

- [ ] **Step 7.5: 单元测试**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_ai_knowledge_e2e_report_contract.py backend/tests/test_toc_new_architecture.py -q
```

Expected: PASS。

- [ ] **Step 7.6: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/pageindex/node_filler.py scripts/run_ai_knowledge_toc_e2e.py backend/tests
git add -u backend/pageindex
git commit -m "chore: remove legacy toc pipeline paths"
```

---

## Task 8: Full End-To-End Verification

**Files:**
- Modify: `backend/tests/fixtures/toc/ai_knowledge_expected_toc_reference.json`
- Modify: `docs/architecture/ai_knowledge_current_e2e_baseline_2026-06-21.md`
- Modify: `docs/architecture/pageindex_official_validation_dataset.md`

- [ ] **Step 8.1: 跑 AI Knowledge 13 份真实文档**

Run:

```powershell
py -X utf8 scripts/run_ai_knowledge_toc_e2e.py --all --output eval0618\legacy-cleanup-final-ai-knowledge --mode smart
```

Expected:

- 13 份文件都完成 index 构建，除非参考预期明确要求失败。
- 每份都有处理耗时。
- 每份都有 selected_path、attempt_chain、S5 mapping facts、quality facts。
- T07 快消 Part03 展开 Step1-4。
- T09 OpenAI 页码不被错误 remap。
- T13 合规备案保留目录/图目录/表目录。

- [ ] **Step 8.2: 跑官方 PageIndex 验证集**

Run:

```powershell
py -X utf8 scripts/run_official_pageindex_validation_e2e.py --all --output eval0618\legacy-cleanup-final-official --mode smart
```

If script does not exist, create or extend existing official validation runner before continuing.

Expected:

- `2023-annual-report*.pdf` 高质量 code_toc 不被更差 fallback 覆盖。
- 无显式目录样本进入 `content_outline`。
- 弱目录样本有明确 fallback chain。

- [ ] **Step 8.3: 生成 HTML 树状预览**

Run:

```powershell
py -X utf8 scripts/render_toc_tree_review.py --input eval0618\legacy-cleanup-final-ai-knowledge --output eval0618\legacy-cleanup-final-ai-knowledge\toc_tree_review.html
```

Expected: HTML 可直接打开，显示每份文件完整 TOC、页码范围、质量状态、attempt chain。

- [ ] **Step 8.4: 严格 JSON 校验**

Run:

```powershell
py -X utf8 - <<'PY'
import json
from pathlib import Path
for path in Path("backend/data/indexes").glob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
print("all index json parse ok")
PY
```

Expected: `all index json parse ok`。

- [ ] **Step 8.5: 全量测试套件核心集**

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_toc_contracts.py backend/tests/test_toc_attempt_runner.py backend/tests/test_page_text_map.py backend/tests/test_toc_mapping.py backend/tests/test_hierarchical_extractor.py backend/tests/test_code_toc_collector.py backend/tests/test_visible_toc_rule_extractor.py backend/tests/test_ai_knowledge_e2e_report_contract.py backend/tests/test_toc_new_architecture.py -q
```

Expected: PASS。

- [ ] **Step 8.6: 更新文档**

更新：

- `docs/architecture/toc_generation_unified_architecture.md`
- `docs/architecture/ai_knowledge_current_e2e_baseline_2026-06-21.md`
- `docs/architecture/pageindex_official_validation_dataset.md`

内容：

- 新的唯一执行流程。
- 删除的旧路径列表。
- 13 份文件最终路径、耗时、质量状态。
- 官方验证集结果。

- [ ] **Step 8.7: Final Commit**

```powershell
git add docs backend/tests/fixtures/toc scripts
git commit -m "test: verify unified toc architecture end to end"
```

---

## Acceptance Checklist

- [ ] `rg "TOCPipelineController|TOCJudge" backend/app backend/pageindex` 在生产路径无结果。
- [ ] `rg "_resolve_ocr_engine\\(\"toc_page\"\\)" backend/app backend/pageindex` 在生产路径无结果。
- [ ] `rg "segment_fallback|page_heading_outline" backend/app backend/pageindex` 在生产路径无结果，或仅在旧兼容测试中出现。
- [ ] `rg "pipeline_path=ppocr_layout|structure_source=layout_first" backend/app backend/pageindex` 在生产日志中无结果。
- [ ] 所有 TOC candidates 都先产出 `TocDraft`。
- [ ] 所有最终页码都来自 `toc_mapping.map_toc_draft_to_physical`。
- [ ] `end_index` 按官方边界规则派生，允许合理边界重合。
- [ ] OCR prompt 单一来源，值为 `完整、准确地抽取内容，用markdown输出`。
- [ ] OCR cache 在 PageTextMap 主链路生效。
- [ ] 13 份 AI Knowledge 文档 E2E 报告可读、耗时完整、路径符合预期。
- [ ] 官方 PageIndex 验证集通过预期检查。
- [ ] 保存的 index JSON 可被 `json.loads` 严格解析。

## Execution Notes

- 每个 task 完成后必须 commit；不要把多个阶段混成一个大提交。
- 每个 task 完成后必须跑对应单元测试和真实数据阶段测试。
- 如果某阶段真实数据结果不符合预期，停止进入下一阶段，先补诊断而不是继续叠修。
- 不提交 `eval0618/*`、`task3_eval_runs/*` 等临时输出，除非用户明确要求保存基线。
- 删除旧代码时优先删除生产引用，再删除文件；如果旧测试失败，更新测试到新架构，不为旧路径保留生产分支。
