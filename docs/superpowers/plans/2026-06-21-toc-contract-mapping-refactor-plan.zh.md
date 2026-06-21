# TOC Contract And Mapping Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TOC 构建流程收口为明确的 `TocDraft -> MappedToc -> QualityGate`，统一页码映射、`end_index` 派生和章节内子树扩展，避免不同路径各自处理导致质量不一致。

**Architecture:** S4 只负责抽取目录草稿，不写最终物理页范围；S5 作为唯一页码映射阶段，统一处理 printed page offset、标题搜索、物理页校验和 `end_index` 派生；S6 只基于事实做质量门判断。OCR 只属于 S1 `PageTextMap` 预处理，S1 之后所有 TOC 检测、抽取、映射、节点填充都只消费 `PageTextMap`。

**Tech Stack:** Python, PyMuPDF, existing `backend/pageindex` modules, pytest, real PDF fixtures under `D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`.

---

## Reference Documents

- Architecture: `D:\projects\page_chat\docs\architecture\toc_generation_unified_architecture.md`
- Test baseline: `D:\projects\page_chat\docs\architecture\ai_knowledge_toc_test_baseline.md`
- Expected TOC reference: `D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`
- Existing execution plan: `D:\projects\page_chat\docs\superpowers\plans\2026-06-20-toc-quality-recovery-plan.zh.md`
- Real sample PDFs: `D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`
- Current latest E2E output: `D:\projects\page_chat\eval0618\task6-full-final-v3`

## Guiding Constraints

- 不为单个 PDF 增加特例规则。
- 不让 LLM 推理 printed page offset 或 `end_index`。
- 不在 S1 之后单独 OCR 目录页。
- 规则只做高置信抽取和校验；不确定时 fallback 到 LLM。
- 最终 `start_index` / `end_index` 均为 1-based physical PDF pages。
- `end_index` 保留，但只由系统派生，不由模型生成。
- 先采用不重叠范围：`current.end_index = next.start_index - 1`。
- 每个阶段完成后运行真实样本测试；通过后再 commit。
- 生成的 `eval0618/` 产物默认不提交，除非用户明确要求。

## File Structure

### New Or Heavily Refactored Units

- Create: `D:\projects\page_chat\backend\pageindex\toc_contracts.py`
  - Defines normalized in-process contracts for `TocDraftItem`, `TocDraft`, `MappedTocItem`, `MappingReport`.
  - Provides small normalization helpers without importing service-level code.

- Create or refactor: `D:\projects\page_chat\backend\pageindex\toc_mapping.py`
  - Single S5 mapping entrypoint.
  - Consumes draft items plus `PageTextMap`/page text list.
  - Owns printed page mapping, title search fallback, auxiliary catalog isolation, and range derivation.

- Modify: `D:\projects\page_chat\backend\pageindex\visible_toc_rule_extractor.py`
  - Stop writing final `physical_index/start_index/end_index` during S4 extraction.
  - Return `TocDraft`-compatible structures with `raw_page_label`, `section_kind`, `source_page`, and parser confidence.

- Modify: `D:\projects\page_chat\backend\pageindex\candidates\llm_toc_page_extractor.py`
  - Normalize LLM extraction to `TocDraft`.
  - Preserve raw page labels; do not map physical pages.

- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
  - Route all selected TOC drafts through S5.
  - Remove or quarantine S1-after TOC-specific OCR/layout mapping branches.
  - Replace current child expansion trigger with a fact-based policy.

- Modify: `D:\projects\page_chat\backend\pageindex\hierarchical_extractor.py`
  - Simplify chapter expansion input to per-page raw excerpts.
  - Add windowed expansion for long chapters.

- Modify: `D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
  - Add fact-based checks for long leaf nodes, invalid ranges, TOC page leakage, and mapping evidence.

- Modify: `D:\projects\page_chat\backend\pageindex\index_quality.py`
  - Align index-level quality report with the new mapping and child-expansion reports.

### Tests

- Create/modify: `D:\projects\page_chat\backend\tests\test_toc_contracts.py`
- Create/modify: `D:\projects\page_chat\backend\tests\test_toc_mapping.py`
- Modify: `D:\projects\page_chat\backend\tests\test_visible_toc_rule_extractor.py`
- Modify: `D:\projects\page_chat\backend\tests\test_code_toc_quality.py`
- Modify: `D:\projects\page_chat\backend\tests\test_ai_knowledge_expected_toc_reference.py`
- Create/modify diagnostics script if needed: `D:\projects\page_chat\scripts\run_ai_knowledge_toc_diagnostics.py`

## Phase 0: Lock The Current Evidence Baseline

**Purpose:** 确认当前 13 份真实文件的路径、耗时、TOC 树和已知问题，避免后续“修好了但不知道修了什么”。

**Files:**
- Read: `D:\projects\page_chat\eval0618\task6-full-final-v3\summary.json`
- Read: `D:\projects\page_chat\eval0618\task6-full-final-v3\*.json`
- Read: `D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`
- Modify: `D:\projects\page_chat\backend\tests\fixtures\toc\ai_knowledge_expected_toc_reference.json`
- Modify/Test: `D:\projects\page_chat\backend\tests\test_ai_knowledge_expected_toc_reference.py`

- [ ] **Step 0.1: Record current per-file route and issue table**

  Build a compact table for T01-T13 with:
  - expected path
  - actual path
  - elapsed seconds
  - TOC source
  - mapping status
  - child expansion status
  - known wrong or risky nodes

- [ ] **Step 0.2: Strengthen expected reference fixture**

  Add required checks for at least:
  - T03: Chongqing should not accept collapsed page mapping.
  - T04: top chapters must be `[3-12]`, `[13-34]`, `[35-48]`, `[49-60]`, `[61-end]`.
  - T05: top chapters must be `[3-8]`, `[9-15]`, `[16-17]`, `[18-end]`.
  - T07: top-level ranges are correct and long chapters require child expansion.
  - T09: known physical page nodes must not be offset incorrectly.
  - T12: `visible_toc_no_pages`, page 2 TOC, long chapters require child expansion.
  - T13: main/table/figure catalogs must be independent when available.

- [ ] **Step 0.3: Run fixture validation**

  Run:

  ```powershell
  py -X utf8 -m pytest backend/tests/test_ai_knowledge_expected_toc_reference.py -q
  ```

  Expected: PASS after fixture/test updates.

- [ ] **Step 0.4: Commit**

  ```powershell
  git add backend/tests/fixtures/toc/ai_knowledge_expected_toc_reference.json backend/tests/test_ai_knowledge_expected_toc_reference.py docs/architecture/ai_knowledge_expected_toc_reference.md
  git commit -m "test: strengthen ai knowledge toc reference baseline"
  ```

## Phase 1: Define `TocDraft` And `MappedToc` Contracts

**Purpose:** 从数据结构上禁止 S4 抽取阶段提前决定最终物理范围。

**Files:**
- Create: `D:\projects\page_chat\backend\pageindex\toc_contracts.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_contracts.py`

- [ ] **Step 1.1: Write failing tests for draft normalization**

  Required behaviors:
  - Draft item keeps `raw_page_label` as raw string/int evidence.
  - Draft item does not require `physical_index`.
  - Section kind normalizes to `main_toc`, `figure_toc`, `table_toc`, or `other_toc`.
  - Existing items with old `page` fields can be normalized without losing raw label.

  Run:

  ```powershell
  py -X utf8 -m pytest backend/tests/test_toc_contracts.py -q
  ```

  Expected before implementation: FAIL.

- [ ] **Step 1.2: Implement contract helpers**

  Implement small functions:
  - `normalize_toc_draft_item(raw, default_section_kind, source_page=None)`
  - `normalize_toc_draft(items, section_kind, source)`
  - `is_auxiliary_section_kind(kind)`

  Keep this module dependency-light.

- [ ] **Step 1.3: Run contract tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_toc_contracts.py -q
  ```

  Expected: PASS.

- [ ] **Step 1.4: Commit**

  ```powershell
  git add backend/pageindex/toc_contracts.py backend/tests/test_toc_contracts.py
  git commit -m "feat: add toc draft mapping contracts"
  ```

## Phase 2: Extract A Single S5 Mapping Entrypoint

**Purpose:** 所有路径统一进入 S5，S4 只提供目录草稿和证据。

**Files:**
- Create/Modify: `D:\projects\page_chat\backend\pageindex\toc_mapping.py`
- Reuse: `D:\projects\page_chat\backend\pageindex\judge\content_page_mapper.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_mapping.py`

- [ ] **Step 2.1: Write failing tests for physical identity mapping**

  Test case: visible TOC gives page labels that already match physical pages, and target page title matches. The mapper must keep the same physical page instead of applying a false offset.

  Expected: this protects T09-style failures.

- [ ] **Step 2.2: Write failing tests for printed offset mapping**

  Test case: raw page labels are printed pages starting from 1 while content starts after TOC pages. The mapper should compute one stable offset only if sampled title anchors support it.

- [ ] **Step 2.3: Write failing tests for unpaged title search**

  Test case: no `raw_page_label`, titles are located by search in `PageTextMap`, and `start_index` is assigned from title anchors.

- [ ] **Step 2.4: Write failing tests for auxiliary catalog isolation**

  Figure/table catalog items must map independently and must not participate in main chapter range derivation.

- [ ] **Step 2.5: Implement `map_toc_draft_to_physical()`**

  Required signature:

  ```python
  def map_toc_draft_to_physical(
      draft: dict,
      *,
      page_texts: list[str],
      page_count: int,
      toc_pages: list[int] | None = None,
      selected_path: str,
  ) -> tuple[list[dict], dict]:
      ...
  ```

  Internally use existing `map_toc_items_to_physical_pages()` where appropriate, but this function becomes the single public S5 entrypoint.

- [ ] **Step 2.6: Run mapping tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_toc_mapping.py -q
  ```

  Expected: PASS.

- [ ] **Step 2.7: Commit**

  ```powershell
  git add backend/pageindex/toc_mapping.py backend/tests/test_toc_mapping.py
  git commit -m "feat: add unified toc physical mapper"
  ```

## Phase 3: Move Visible TOC Rule And LLM Extraction To Draft Output

**Purpose:** 规则抽取和 LLM 抽取只做 S4，不提前写最终物理范围。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\visible_toc_rule_extractor.py`
- Modify: `D:\projects\page_chat\backend\pageindex\candidates\llm_toc_page_extractor.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_visible_toc_rule_extractor.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_mapping.py`

- [ ] **Step 3.1: Write tests that visible TOC rule returns draft evidence**

  Assertions:
  - `raw_page_label` is preserved.
  - `section_kind` is preserved.
  - `source_page` is preserved.
  - No final `end_index` is required in S4 output.

- [ ] **Step 3.2: Change visible TOC rule output**

  Keep the strict parser conservative. If parser confidence or section split fails, return low-confidence/fallback metadata rather than trying extra special rules.

- [ ] **Step 3.3: Change LLM TOC extraction normalization**

  LLM extraction should output:
  - title
  - level
  - raw page label when present
  - section kind
  - source page

  Do not ask LLM to infer physical page or end range.

- [ ] **Step 3.4: Route selected draft through S5 in service**

  In `pageindex_service.py`, after selecting a visible TOC candidate, call `map_toc_draft_to_physical()` before post-processing.

- [ ] **Step 3.5: Run focused tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_visible_toc_rule_extractor.py backend/tests/test_toc_mapping.py -q
  ```

  Expected: PASS.

- [ ] **Step 3.6: Run targeted real samples**

  Run one by one:

  ```powershell
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "OpenAI深度报告：大模型王者，引领AGI之路.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "AI眼镜关键技术与产业生态研究报告（2025年）.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"
  ```

  Expected:
  - T09 does not remap physical TOC pages to the wrong page.
  - T08 keeps figure/table catalogs independent.
  - T03 does not accept mass collapsed mapping.

- [ ] **Step 3.7: Commit**

  ```powershell
  git add backend/pageindex/visible_toc_rule_extractor.py backend/pageindex/candidates/llm_toc_page_extractor.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "refactor: map visible toc drafts through unified s5"
  ```

## Phase 4: Centralize `end_index` Derivation

**Purpose:** `end_index` 保留为最终索引字段，但只能由系统根据同级 `start_index` 派生。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\toc_mapping.py`
- Modify: `D:\projects\page_chat\backend\pageindex\post_processing.py`
- Modify: `D:\projects\page_chat\backend\pageindex\tree_schema.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_mapping.py`

- [ ] **Step 4.1: Write failing tests for recursive non-overlap ranges**

  Required behavior:

  ```text
  current.end_index = next sibling start_index - 1
  last.end_index = parent.end_index or page_count
  child range must stay inside parent range
  ```

- [ ] **Step 4.2: Write failing tests for invalid range rejection**

  Cases:
  - `start_index > end_index`
  - child starts before parent
  - child ends after parent
  - mapped page outside document

- [ ] **Step 4.3: Implement range derivation in S5**

  Add a single recursive helper, for example:

  ```python
  def derive_toc_ranges(nodes: list[dict], *, page_count: int, parent_end: int | None = None) -> list[dict]:
      ...
  ```

  Keep it deterministic and non-overlapping.

- [ ] **Step 4.4: Remove competing range derivation where safe**

  Existing post-processing should normalize and validate, not invent a different range policy for mapped TOC.

- [ ] **Step 4.5: Run tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_toc_mapping.py backend/tests/test_post_processing.py -q
  ```

  Expected: PASS.

- [ ] **Step 4.6: Run targeted real samples**

  ```powershell
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2025年第五范式-人工智能驱动的科技创新报告.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf"
  ```

  Expected:
  - T12 top ranges remain `[3-4]`, `[5-33]`, `[34-56]`, ..., `[133-201]`.
  - T04 top ranges match expected chapters.
  - T05 top ranges match expected chapters.

- [ ] **Step 4.7: Commit**

  ```powershell
  git add backend/pageindex/toc_mapping.py backend/pageindex/post_processing.py backend/pageindex/tree_schema.py backend/tests
  git commit -m "fix: derive toc ranges in unified mapping stage"
  ```

## Phase 5: Remove S1-After TOC OCR/Layout Side Paths

**Purpose:** OCR 只属于 S1 `PageTextMap` 预处理；S1 后不再单独 OCR 目录页或走独立视觉 TOC 分支。

**Files:**
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Modify: `D:\projects\page_chat\backend\pageindex\preprocess_page_text.py`
- Modify: `D:\projects\page_chat\backend\pageindex\page_text_map.py`
- Test: existing OCR/PageTextMap tests under `D:\projects\page_chat\backend\tests`

- [ ] **Step 5.1: Identify all post-S1 OCR/layout TOC calls**

  Search:

  ```powershell
  rg -n "toc_page|recognize_toc|layout|ppocr|ocr_toc_page|_recognize_toc_pages_with_vl" backend/app/services/pageindex_service.py backend/pageindex -S
  ```

  Document which functions remain allowed and which must be removed or quarantined.

- [ ] **Step 5.2: Add diagnostics test or assertion**

  Add a test or service-level assertion that when `PageTextMap` exists, TOC detection/extraction uses page text rather than a separate OCR result.

- [ ] **Step 5.3: Quarantine legacy visual TOC helpers**

  Do not delete large helper code blindly. First make the state machine stop calling them by default. Keep only explicit debug fallback if needed, and mark it disabled by default.

- [ ] **Step 5.4: Ensure bad TOC text is repaired via S1**

  If a TOC page text entry is low quality, the remediation should be PageTextMap page repair, not S4 OCR.

- [ ] **Step 5.5: Run tests**

  ```powershell
  py -X utf8 -m pytest backend/tests -q
  ```

  Expected: all TOC-related tests pass.

- [ ] **Step 5.6: Run image/OCR real samples**

  ```powershell
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2026年快消行业AI营销增长白皮书.pdf"
  ```

  Expected:
  - OCR summary appears as S1/PageTextMap work.
  - TOC extraction consumes PageTextMap text.
  - Main log remains compact.

- [ ] **Step 5.7: Commit**

  ```powershell
  git add backend/app/services/pageindex_service.py backend/pageindex/preprocess_page_text.py backend/pageindex/page_text_map.py backend/tests
  git commit -m "refactor: restrict toc stages to page text map"
  ```

## Phase 6: Rewrite Child Expansion Policy

**Purpose:** `allow_child_expansion` 不再只是路径标志位，而是基于节点事实判断是否需要扩展。

**Files:**
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Modify: `D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
- Modify: `D:\projects\page_chat\backend\pageindex\index_quality.py`
- Test: `D:\projects\page_chat\backend\tests\test_balanced_quality_gate.py`
- Test: `D:\projects\page_chat\backend\tests\test_index_quality.py`

- [ ] **Step 6.1: Write failing tests for long leaf policy**

  Required behavior:

  ```text
  main catalog non-auxiliary leaf span >= 8 pages -> expansion attempted
  span 8-15 and expansion empty -> warning
  span > 15 and expansion empty -> needs_review or hard fail in tuning mode
  figure/table catalogs -> never require child expansion
  preface/appendix -> not forced by default
  ```

- [ ] **Step 6.2: Implement `ChildExpansionPolicy` helper**

  Keep it simple. It should inspect final mapped tree facts:
  - node type
  - catalog type
  - start/end span
  - has children
  - title front/back matter classification

- [ ] **Step 6.3: Replace current boolean-only checks**

  `_allows_child_outline_expansion()` may still gate path capability, but actual parent selection should use the policy result.

- [ ] **Step 6.4: Update quality reports**

  Add:
  - `child_expansion_attempted`
  - `child_expansion_required_count`
  - `unexpanded_long_leaf_count`
  - `unexpanded_long_leaf_sample`

- [ ] **Step 6.5: Run tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_balanced_quality_gate.py backend/tests/test_index_quality.py -q
  ```

  Expected: PASS.

- [ ] **Step 6.6: Run targeted real samples**

  ```powershell
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2026年快消行业AI营销增长白皮书.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2025年第五范式-人工智能驱动的科技创新报告.pdf"
  ```

  Expected:
  - T12 long leaves such as `8.6 [167-201]` are not silently treated as fully complete.
  - T07 and T04 do not finish as only top-level nodes.

- [ ] **Step 6.7: Commit**

  ```powershell
  git add backend/app/services/pageindex_service.py backend/pageindex/balanced_quality_gate.py backend/pageindex/index_quality.py backend/tests
  git commit -m "fix: require expansion for long toc leaves"
  ```

## Phase 7: Simplify Chapter-Internal LLM Expansion Input

**Purpose:** 不给 LLM 传规则猜测的 `heading_candidates`，不引入额外 `short_summary` 调用，只给保留换行的原文片段。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\hierarchical_extractor.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_hierarchical_extractor.py`

- [ ] **Step 7.1: Write tests for excerpt building**

  Required behavior:
  - The per-page input contains only `page` and `excerpt`.
  - Excerpt preserves line breaks.
  - No `heading_candidates`.
  - No summary field.

- [ ] **Step 7.2: Write tests for long chapter windowing**

  Required behavior:

  ```text
  <= 8 pages -> one window
  9-25 pages -> one compact window
  > 25 pages -> windows of 8-12 pages, overlap 1 page
  ```

- [ ] **Step 7.3: Update expansion prompt**

  Prompt requirements:
  - Extract subsection titles under the given parent chapter.
  - Return title, level, and physical start page.
  - Do not return end pages.
  - If unsure, return fewer items.
  - Use only provided excerpts.

- [ ] **Step 7.4: Merge window results**

  Merge by normalized title + page. Preserve order by page, then original order. Let S5/range derivation compute end ranges later.

- [ ] **Step 7.5: Run tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_hierarchical_extractor.py -q
  ```

  Expected: PASS.

- [ ] **Step 7.6: Run targeted real samples**

  ```powershell
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf"
  py scripts/run_ai_knowledge_toc_diagnostics.py --file "2026年快消行业AI营销增长白皮书.pdf"
  ```

  Expected:
  - Long chapters produce explainable child nodes or quality report flags them.
  - No extra summary LLM calls are introduced.

- [ ] **Step 7.7: Commit**

  ```powershell
  git add backend/pageindex/hierarchical_extractor.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "refactor: expand toc children from page excerpts"
  ```

## Phase 8: Strengthen Fact-Based Quality Gate

**Purpose:** 质量门不评审美，只判断 TOC 是否可用于导航和内容提取。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
- Modify: `D:\projects\page_chat\backend\pageindex\index_quality.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_balanced_quality_gate.py`
- Test: `D:\projects\page_chat\backend\tests\test_index_quality.py`

- [ ] **Step 8.1: Add hard-fail tests**

  Hard fail in tuning mode:
  - empty TOC
  - page out of range
  - invalid range
  - many nodes on TOC pages
  - visible TOC with pages has weak mapping anchors
  - unpaged TOC has low title anchor coverage
  - figure/table catalog mixed into main catalog
  - span > 15 leaf still unexpanded after expansion attempt

- [ ] **Step 8.2: Add non-fail tests**

  Must not fail:
  - source TOC is flat and leaf spans are short
  - auxiliary figure/table catalog has point-like ranges
  - front matter or appendix is long but explicitly marked front/back matter

- [ ] **Step 8.3: Implement quality report fields**

  Add stable fields:
  - `mapping_status`
  - `title_match_rate`
  - `toc_page_leakage_count`
  - `invalid_page_range_count`
  - `unexpanded_long_leaf_count`
  - `auxiliary_catalog_isolation`
  - `hard_fail_reasons`

- [ ] **Step 8.4: Run tests**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_balanced_quality_gate.py backend/tests/test_index_quality.py -q
  ```

  Expected: PASS.

- [ ] **Step 8.5: Commit**

  ```powershell
  git add backend/pageindex/balanced_quality_gate.py backend/pageindex/index_quality.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "fix: enforce fact based toc quality gate"
  ```

## Phase 9: Full End-To-End Real File Validation

**Purpose:** 逐个验证 13 份真实文件的路径、页码、子树和质量门，不再只看 `status=ok`。

**Files:**
- Use: `D:\projects\page_chat\scripts\run_ai_knowledge_toc_diagnostics.py`
- Output: `D:\projects\page_chat\eval0618\<new-run-folder>`
- Optional generated review: `D:\projects\page_chat\eval0618\toc_tree_review_<run>.html`

- [ ] **Step 9.1: Run all 13 files one by one**

  Do not run all files in one backend queue. Record elapsed time for each file.

- [ ] **Step 9.2: Generate machine-readable summary**

  Summary must include:
  - id
  - file
  - elapsed seconds
  - content type
  - selected path
  - toc pages
  - toc source
  - mapping report
  - child expansion report
  - quality report
  - key expected node checks

- [ ] **Step 9.3: Generate HTML tree review**

  Include each file's:
  - route
  - duration
  - quality status
  - full TOC tree
  - warnings/hard fail reasons
  - known reference mismatches

- [ ] **Step 9.4: Compare against expected reference**

  Required checks:
  - T03 route and pages no longer collapse.
  - T04/T05/T07/T12 do not remain top-level-only when long leaves exist.
  - T08/T09/T11 preserve main/figure/table catalog isolation.
  - T09 physical-page TOC entries are not incorrectly offset.
  - T13 main/table/figure catalogs are present when source evidence supports them.

- [ ] **Step 9.5: Report checkpoint to user**

  Stop after producing:
  - summary JSON path
  - HTML review path
  - per-file route table
  - per-file quality table
  - remaining mismatches

  Do not proceed to further tuning without user confirmation.

- [ ] **Step 9.6: Commit core test/report script changes only**

  Do not commit generated `eval0618/` outputs unless explicitly requested.

  ```powershell
  git add scripts backend docs
  git commit -m "test: verify unified toc mapping e2e"
  ```

## Acceptance Criteria

- S4 extraction outputs draft evidence only; final page ranges are not decided before S5.
- S5 is the only default page mapping entrypoint for TOC outputs.
- `end_index` remains in final index, but is system-derived and recursive.
- S1 after OCR/layout TOC paths are not used by default once `PageTextMap` exists.
- Main/figure/table catalogs are independently represented and mapped.
- Chapter child expansion is triggered by node facts, not vague document-shape inference.
- Chapter expansion input uses raw excerpts only, not rule guessed heading candidates or LLM summaries.
- Quality gate reports factual failures and warnings with stable reason codes.
- 13 AI Knowledge real PDFs run end to end one by one with route, duration, TOC tree, mapping report, and quality report.

## Stop Point

This plan is intentionally a confirmation checkpoint. After the user approves it, implementation should start at Phase 0 and commit after each completed phase.
