# PageIndex TOC Candidate Lifecycle Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前 TOC 构建从“路径执行后直接产物”升级为“候选生命周期闭环”，吸收官方 PageIndex 的验证、修复、降级能力，并用官方样例与 AI Knowledge 真实文件持续验证。

**Architecture:** 最终流程为 `PageTextMap -> Evidence -> Attempt Chain -> TocDraft -> S5 Mapping/Verify/Repair -> Child Refinement -> Quality Gate -> Save/Enrich`。每条路径只负责产出候选草稿，最终物理页码、范围、质量判断和降级统一由后续阶段处理；任何 fallback 都不能覆盖更好的已验证候选。

**Tech Stack:** Python, PyMuPDF, pytest, existing `backend/pageindex` modules, `scripts/run_ai_knowledge_toc_e2e.py`, official PageIndex examples under `D:\projects\PageIndex\examples\documents`, AI Knowledge PDFs under `D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`.

---

## 1. 背景

当前 Phase 0 基线已经跑完：

- 官方 PageIndex 样例输出目录：`D:\projects\page_chat\eval0618\phase0-official-baseline`
- AI Knowledge 样例输出目录：`D:\projects\page_chat\eval0618\phase0-ai-knowledge-baseline`
- 官方验证集提交：`5c8483e test: add official pageindex toc validation dataset`

Phase 0 结论：

- 官方 9 份样例中，`P03`、`P09` 通过；`P05`、`P06` failed；`P01`、`P02`、`P04`、`P07`、`P08` error。
- AI Knowledge 13 份在宽松 route fixture 下全部 ok，但严格 TOC reference 仍标记了多份 `reject_current` 或 `needs_child_expansion`，不能把 route ok 等同于 TOC 质量达标。
- `P06 PRML.pdf` 暴露出官方验证 fixture 中混入书内页码的问题，需要先修正为物理页码。
- `P01/P02/P08` 暴露出真实架构问题：fast 路径得到较好候选后，质量失败触发 balanced retry，后续较差 fallback 可能覆盖或丢弃前一个较好候选。
- 可见目录规则抽取现在一旦可选就提前返回，阻断 LLM TOC 候选参与比较，和“规则不确定则回退 LLM”的设计不一致。
- `content_outline` 还没有达到官方 PageIndex 在无目录/弱目录文档上的稳定性。

这份计划是后续开发主线。每个阶段都必须用真实文件验证，阶段完成后 commit，再进入下一阶段。

## 2. 参考文件

- 架构迁移说明：`D:\projects\page_chat\docs\architecture\pageindex_official_capability_migration.md`
- 官方验证集说明：`D:\projects\page_chat\docs\architecture\pageindex_official_validation_dataset.md`
- AI Knowledge 严格参考：`D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`
- 官方 fixture：`D:\projects\page_chat\backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json`
- AI Knowledge route fixture：`D:\projects\page_chat\backend\tests\fixtures\toc\ai_knowledge_expected_routes.json`
- AI Knowledge strict fixture：`D:\projects\page_chat\backend\tests\fixtures\toc\ai_knowledge_expected_toc_reference.json`
- E2E runner：`D:\projects\page_chat\scripts\run_ai_knowledge_toc_e2e.py`
- 当前主服务：`D:\projects\page_chat\backend\app\services\pageindex_service.py`

## 3. 总体原则

- 不做针对单个 PDF 的特例规则。
- 规则只做高置信抽取和硬校验；不确定时进入 LLM 或下一 attempt。
- OCR 只属于 S1 `PageTextMap` 预处理；TOC 检测、抽取、映射、节点填充都消费 `PageTextMap`。
- `TocDraft` 只保留目录结构和原始页码证据，不写最终物理页范围。
- S5 是唯一默认物理页映射入口。
- `end_index` 保留，但由系统派生，不由 LLM 生成。
- 相邻节点允许一页边界重合，质量门不能把合法重合误判为失败。
- 图目录、表目录、主目录必须独立建树、独立映射、独立展示。
- fallback 不能覆盖更好的已验证候选。
- 调试期质量门可以直接失败，以暴露前置能力问题；生成的 `eval0618/` 产物默认不提交。

## 4. 文件结构规划

### 主要修改文件

- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
  - 接入候选生命周期、attempt chain、best candidate、统一 S5、质量失败处理。

- Modify: `D:\projects\page_chat\backend\pageindex\pipeline\toc_state_machine.py`
  - 从单一路径选择扩展为 attempt chain 规划。

- Create/Modify: `D:\projects\page_chat\backend\pageindex\pipeline\toc_attempt_runner.py`
  - 新增候选生命周期执行器，统一执行 build/map/verify/repair/refine/quality/fallback。

- Create/Modify: `D:\projects\page_chat\backend\pageindex\toc_contracts.py`
  - 定义或补齐 `TocDraft`、`MappedToc`、candidate metadata 的轻量规范。

- Modify: `D:\projects\page_chat\backend\pageindex\toc_mapping.py`
  - 统一 S5 映射、offset 判断、标题锚点校验、局部修复、范围派生。

- Modify: `D:\projects\page_chat\backend\pageindex\visible_toc_rule_extractor.py`
  - 可见目录规则只产出 draft；不提前决定最终物理范围。

- Modify: `D:\projects\page_chat\backend\pageindex\candidates\llm_toc_page_extractor.py`
  - LLM TOC 抽取统一产出 draft；不要求模型推理物理页或 end range。

- Modify/Create: `D:\projects\page_chat\backend\pageindex\content_outline_extractor.py`
  - 迁移官方“带物理页标签的全文建树”能力。

- Modify: `D:\projects\page_chat\backend\pageindex\child_expansion_policy.py`
  - 将长节点递归展开升级为事实驱动的核心阶段。

- Modify: `D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
  - 统一硬失败、警告、LLM QC 输入。

- Modify: `D:\projects\page_chat\backend\pageindex\index_quality.py`
  - 对齐最终 index 质量报告。

- Modify: `D:\projects\page_chat\scripts\run_ai_knowledge_toc_e2e.py`
  - 增强报告矩阵、严格 reference 校验、耗时统计和失败原因输出。

### 主要测试文件

- Modify: `D:\projects\page_chat\backend\tests\test_official_pageindex_validation_fixture.py`
- Modify: `D:\projects\page_chat\backend\tests\test_ai_knowledge_e2e_report_contract.py`
- Create/Modify: `D:\projects\page_chat\backend\tests\test_toc_candidate_lifecycle.py`
- Create/Modify: `D:\projects\page_chat\backend\tests\test_toc_attempt_runner.py`
- Create/Modify: `D:\projects\page_chat\backend\tests\test_toc_contracts.py`
- Create/Modify: `D:\projects\page_chat\backend\tests\test_toc_mapping.py`
- Modify: `D:\projects\page_chat\backend\tests\test_visible_toc_rule_extractor.py`
- Modify: `D:\projects\page_chat\backend\tests\test_balanced_quality_gate.py`
- Modify: `D:\projects\page_chat\backend\tests\test_index_quality.py`
- Modify: `D:\projects\page_chat\backend\tests\test_pageindex_service_balanced_flow.py`

## 5. 阶段通过标准

每个阶段必须：

- 跑阶段相关单元测试。
- 跑官方 PageIndex 相关样本。
- 跑 AI Knowledge 相关样本。
- 阶段完成时跑官方 9 份和 AI Knowledge 13 份全量 E2E，除非该阶段明确只修改验证 fixture。
- 输出结果目录命名为 `eval0618/phase<N>-<topic>-official` 和 `eval0618/phase<N>-<topic>-ai-knowledge`。
- 记录每个文件耗时、实际路径、候选来源、质量状态、失败原因。
- 阶段目标样本必须达到预期后才能 commit。

运行原则：

- 真实文件一个一个跑，不一次性塞进队列。
- 若服务需要启动，明确端口并在阶段结束后停止。
- 不提交 `eval0618/` 生成物，除非用户明确要求。

## Phase 0: 修正验证口径并锁定基线

**Purpose:** 先消除验证集自身噪声，确保后续失败是管线问题，不是验收数据错。

**Files:**
- Modify: `D:\projects\page_chat\backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json`
- Modify: `D:\projects\page_chat\backend\tests\test_official_pageindex_validation_fixture.py`
- Modify: `D:\projects\page_chat\docs\architecture\pageindex_official_validation_dataset.md`
- Modify: `D:\projects\page_chat\scripts\run_ai_knowledge_toc_e2e.py`

- [ ] **Step 0.1: 修正 P06 PRML 的物理页断言**

  已验证的物理页示例：
  - `5 Neural Networks` 在物理页 245，不是 225。
  - `References` 在物理页 731，不是 697。
  - `Index` 在物理页 749，不是 721。

  更新 fixture，并在文档中说明官方书内页码和项目物理页码的区别。

- [ ] **Step 0.2: 增强 runner 的严格报告能力**

  报告必须输出：
  - `status`
  - `elapsed_seconds`
  - `content_type`
  - `selected_path`
  - `toc_source`
  - `root_count/node_count/max_depth`
  - `quality.status`
  - `hard_fail_reasons`
  - `failed_acceptance`
  - `route.fallbacks`

- [ ] **Step 0.3: 跑 fixture contract 测试**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_official_pageindex_validation_fixture.py backend/tests/test_ai_knowledge_e2e_report_contract.py -q
  ```

  Expected: PASS.

- [ ] **Step 0.4: 重跑官方 P06 单文件**

  ```powershell
  py -X utf8 scripts\run_ai_knowledge_toc_e2e.py `
    --fixture backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json `
    --input D:\projects\PageIndex\examples\documents `
    --file PRML.pdf `
    --output eval0618\phase0-fixture-fix-official
  ```

  Expected: P06 不再因书内页码误判 required_pages。

- [ ] **Step 0.5: Commit**

  ```powershell
  git add backend/tests/fixtures/toc/official_pageindex_expected_toc_reference.json backend/tests/test_official_pageindex_validation_fixture.py backend/tests/test_ai_knowledge_e2e_report_contract.py scripts/run_ai_knowledge_toc_e2e.py docs/architecture/pageindex_official_validation_dataset.md
  git commit -m "test: align official toc validation to physical pages"
  ```

## Phase 1: 引入候选生命周期与 best_candidate

**Purpose:** 解决好候选被差 fallback 覆盖的问题，这是 `P01/P02/P08/T13` 这类问题的根源。

**Files:**
- Create/Modify: `D:\projects\page_chat\backend\pageindex\pipeline\toc_attempt_runner.py`
- Modify: `D:\projects\page_chat\backend\pageindex\pipeline\toc_state_machine.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_candidate_lifecycle.py`
- Test: `D:\projects\page_chat\backend\tests\test_pageindex_service_balanced_flow.py`

- [ ] **Step 1.1: 写候选生命周期失败测试**

  测试场景：
  - fast embedded_toc 得到可导航候选。
  - 质量门给出 long leaf warning/hard reason。
  - balanced fallback 得到更差候选或失败。
  - 最终不能丢弃 fast 候选，必须保留 `best_candidate` 或给出明确失败链。

- [ ] **Step 1.2: 定义候选状态结构**

  每个 attempt 记录：
  - `attempt_id`
  - `path`
  - `source`
  - `candidate_items`
  - `mapping_report`
  - `quality_report`
  - `score`
  - `status`
  - `failure_reasons`
  - `can_be_best_candidate`

- [ ] **Step 1.3: 实现 best_candidate 策略**

  规则：
  - 硬事实失败候选不可成为 best。
  - 通过映射但质量 warning 的候选可成为 best。
  - fallback 只有在质量更高或错误更少时才能替换 best。
  - 所有 attempt 都失败时，调试期报错必须带完整 attempt chain。

- [ ] **Step 1.4: 替换 `_generate_pdf_index()` 递归 retry**

  将当前“质量失败后递归 balanced 并禁用 code_toc”的逻辑改为 attempt runner。保留 fallback_from 诊断，但不再丢弃第一次结果。

- [ ] **Step 1.5: 跑单元测试**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_toc_candidate_lifecycle.py backend/tests/test_pageindex_service_balanced_flow.py -q
  ```

  Expected: PASS.

- [ ] **Step 1.6: 跑官方关键样本**

  ```powershell
  py -X utf8 scripts\run_ai_knowledge_toc_e2e.py --fixture backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json --input D:\projects\PageIndex\examples\documents --file 2023-annual-report.pdf --output eval0618\phase1-lifecycle-official
  py -X utf8 scripts\run_ai_knowledge_toc_e2e.py --fixture backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json --input D:\projects\PageIndex\examples\documents --file "Regulation Best Interest_Interpretive release.pdf" --output eval0618\phase1-lifecycle-official
  ```

  Expected:
  - P01 不再因较差 fallback 覆盖高质量 embedded_toc。
  - P08 的失败原因进入 attempt chain，不再表现为不可解释的最终硬失败。

- [ ] **Step 1.7: 跑全量官方 9 份和 AI Knowledge 13 份**

  输出目录：
  - `eval0618\phase1-lifecycle-official`
  - `eval0618\phase1-lifecycle-ai-knowledge`

- [ ] **Step 1.8: Commit**

  ```powershell
  git add backend/pageindex/pipeline/toc_attempt_runner.py backend/pageindex/pipeline/toc_state_machine.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "feat: add toc candidate lifecycle"
  ```

## Phase 2: 让可见目录规则与 LLM 抽取共同进入候选池

**Purpose:** 修复“规则候选一旦可选就提前返回”的问题，让规则和 LLM 都进入统一候选生命周期。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\visible_toc_rule_extractor.py`
- Modify: `D:\projects\page_chat\backend\pageindex\candidates\llm_toc_page_extractor.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_visible_toc_rule_extractor.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_attempt_runner.py`

- [ ] **Step 2.1: 写规则候选不短路的测试**

  场景：
  - 规则抽取出候选，但 mapping 或质量不够稳定。
  - LLM 抽取也应被调用并加入候选池。
  - 最终由 attempt runner 比较选择。

- [ ] **Step 2.2: 明确规则候选准入标准**

  规则只在以下条件满足时标为高置信：
  - 标准目录行足够多。
  - 页码形态可信。
  - section kind 可判断。
  - 初步 title anchor 不明显失败。

  不满足时仍可作为低置信候选，但不能阻止 LLM。

- [ ] **Step 2.3: LLM TOC prompt 保持简单通用**

  输入是已识别的 TOC 页文本。
  输出只要求：
  - title
  - level
  - raw page label if visible
  - catalog kind if obvious

  不要求 LLM 推断物理页，不要求 end_index。

- [ ] **Step 2.4: 跑关键真实样本**

  样本：
  - T03 重庆案例集
  - T08 AI 眼镜
  - T09 OpenAI 深度报告
  - T11 人工智能安全治理
  - T13 生成式人工智能服务合规备案指南

  Expected:
  - 规则失败或低置信时能看到 LLM TOC 候选。
  - 主目录、图目录、表目录候选都保留 section kind。
  - 不再因为规则先返回而错过更好 LLM 候选。

- [ ] **Step 2.5: 跑全量官方 9 份和 AI Knowledge 13 份**

- [ ] **Step 2.6: Commit**

  ```powershell
  git add backend/pageindex/visible_toc_rule_extractor.py backend/pageindex/candidates/llm_toc_page_extractor.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "refactor: compare rule and llm toc candidates"
  ```

## Phase 3: 统一 TocDraft 与 S5 映射验证修复

**Purpose:** 所有路径都先产出 `TocDraft`，最终物理页和范围只由 S5 决定。

**Files:**
- Create/Modify: `D:\projects\page_chat\backend\pageindex\toc_contracts.py`
- Modify: `D:\projects\page_chat\backend\pageindex\toc_mapping.py`
- Modify: `D:\projects\page_chat\backend\pageindex\judge\content_page_mapper.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_contracts.py`
- Test: `D:\projects\page_chat\backend\tests\test_toc_mapping.py`

- [ ] **Step 3.1: 写 TocDraft normalization 测试**

  必须覆盖：
  - `raw_page_label` 原样保留。
  - draft 不要求 `physical_index`。
  - `section_kind` 归一为 `main_toc/figure_toc/table_toc/other_toc`。
  - 旧字段 `page/logical_page/physical_index` 可兼容读取但不直接信任。

- [ ] **Step 3.2: 写 S5 物理页映射测试**

  必须覆盖：
  - TOC 页码本来就是物理页时，不错误套 offset。
  - printed page offset 只有在多个 title anchor 支持时才成立。
  - 无页码目录通过 title search 定位顶级节点。
  - 多个目录类型独立映射。
  - 大量节点指向 TOC 页时 hard fail。
  - 页码非单调或坍缩时 hard fail。

- [ ] **Step 3.3: 实现统一 S5 entrypoint**

  建议入口：

  ```python
  def map_toc_draft_to_physical(
      draft: dict,
      *,
      page_texts: list[str],
      page_count: int,
      toc_pages: list[int],
      selected_path: str,
  ) -> tuple[list[dict], dict]:
      ...
  ```

- [ ] **Step 3.4: 实现局部修复接口**

  只修少量失败节点：
  - 搜索范围由前后已验证锚点限制。
  - 先做标题搜索，必要时才调用轻量 LLM finder。
  - 修复失败则记录，不继续粉饰。

- [ ] **Step 3.5: 系统派生 `end_index`**

  规则：
  - 正文主目录按同级节点顺序派生。
  - 如果下一节点从页首开始：`current.end_index = next.start_index - 1`。
  - 否则允许重合：`current.end_index = next.start_index`。
  - 子节点同样递归处理。
  - 图目录/表目录为点状导航，不参与正文覆盖范围。

- [ ] **Step 3.6: 跑关键真实样本**

  样本：
  - T03 重庆案例集：不得出现大量错误页码或目录页泄漏。
  - T09 OpenAI：已有物理页不得被错误 offset。
  - T13 合规备案：主/图/表目录都要独立。
  - P02 truncated annual report：非单调映射必须被识别。

- [ ] **Step 3.7: 跑全量官方 9 份和 AI Knowledge 13 份**

- [ ] **Step 3.8: Commit**

  ```powershell
  git add backend/pageindex/toc_contracts.py backend/pageindex/toc_mapping.py backend/pageindex/judge/content_page_mapper.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "feat: unify toc draft physical mapping"
  ```

## Phase 4: 迁移官方 content_outline 能力

**Purpose:** 无目录或弱目录文档不能坍缩为泛节点，要用官方式“带物理页标签的全文建树”作为主能力。

**Files:**
- Create/Modify: `D:\projects\page_chat\backend\pageindex\content_outline_extractor.py`
- Modify: `D:\projects\page_chat\backend\pageindex\hierarchical_extractor.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_content_outline_extractor.py`
- Test: `D:\projects\page_chat\backend\tests\test_hierarchical_extractor.py`

- [ ] **Step 4.1: 写 content_outline 输入构造测试**

  每页输入必须带物理页标签，例如：

  ```text
  <physical_index_12>
  page text excerpt...
  </physical_index_12>
  ```

  不使用规则猜测标题候选，不生成 summary。

- [ ] **Step 4.2: 实现长文分块**

  - 按 token 或页数分组。
  - 保留 1 页 overlap。
  - 第一组 init，后续组 continue。
  - 合并后仍进入 S5 验证。

- [ ] **Step 4.3: 去掉泛节点成功路径**

  `Document Content` 或单节点覆盖全文不能作为成功 TOC；只能作为失败诊断或临时显示。

- [ ] **Step 4.4: 跑官方关键样本**

  样本：
  - P04 `earthmover.pdf`
  - P05 `four-lectures.pdf`
  - P07 `q1-fy25-earnings.pdf`

  Expected:
  - P04 不坍缩。
  - P05 不漏 Preface 和第一讲。
  - P07 得到可导航的财报结构。

- [ ] **Step 4.5: 跑 AI Knowledge 对照样本**

  样本：
  - T04 第五范式
  - T05 2026AI应用专题
  - T07 快消白皮书
  - T12 清华职业教育

  Expected:
  - visible_toc_no_pages 顶级定位失败时能进入 content_outline。
  - 长章节不再只有一级。

- [ ] **Step 4.6: 跑全量官方 9 份和 AI Knowledge 13 份**

- [ ] **Step 4.7: Commit**

  ```powershell
  git add backend/pageindex/content_outline_extractor.py backend/pageindex/hierarchical_extractor.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "feat: build content outline from physical page text"
  ```

## Phase 5: 长节点递归展开成为核心阶段

**Purpose:** 把章节内建树从后置补丁升级为 S6 `Refine Large Nodes`，解决只有一级目录或部分章节展开不足的问题。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\child_expansion_policy.py`
- Modify: `D:\projects\page_chat\backend\pageindex\hierarchical_extractor.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_child_expansion_policy.py`
- Test: `D:\projects\page_chat\backend\tests\test_hierarchical_extractor.py`

- [ ] **Step 5.1: 写长叶子判定测试**

  规则保持简单：
  - 正文主目录叶子跨度 >= 8 页，尝试展开。
  - 正文主目录叶子跨度 > 15 页，展开失败进入 hard fail 或 tuning hard fail。
  - 图目录/表目录不要求展开。
  - 前言、参考文献、索引、附录可放宽。

- [ ] **Step 5.2: 简化章节内 LLM 输入**

  每页只传：
  - page
  - excerpt，默认前 400 字，保留换行

  不传 `heading_candidates`，不传 `short_summary`。

- [ ] **Step 5.3: 更新章节内 prompt**

  要求模型：
  - 只根据给定章节页级片段抽取子标题。
  - 返回标题、层级、物理起始页。
  - 不返回 end_index。
  - 如果重复编号但标题不同，允许保留。
  - 不确定就少返回，不要补造。

- [ ] **Step 5.4: 子树重新走 S5**

  子树 start/end 仍由系统映射和派生，不由模型决定。

- [ ] **Step 5.5: 跑关键真实样本**

  样本：
  - T04 第五范式
  - T05 2026AI应用专题
  - T07 快消白皮书，重点 Part03
  - T12 清华职业教育

  Expected:
  - 这些文件不再只是顶级目录。
  - Part03 至少能抽出多个真实子节点，若抽不出要质量门明确标记。

- [ ] **Step 5.6: 跑全量官方 9 份和 AI Knowledge 13 份**

- [ ] **Step 5.7: Commit**

  ```powershell
  git add backend/pageindex/child_expansion_policy.py backend/pageindex/hierarchical_extractor.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "feat: refine large toc leaves with page excerpts"
  ```

## Phase 6: 统一质量门语义

**Purpose:** 把 content mapping、balanced gate、index quality、LLM QC 的语义统一，避免宽松 ok 掩盖真实错误。

**Files:**
- Modify: `D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
- Modify: `D:\projects\page_chat\backend\pageindex\index_quality.py`
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
- Test: `D:\projects\page_chat\backend\tests\test_balanced_quality_gate.py`
- Test: `D:\projects\page_chat\backend\tests\test_index_quality.py`

- [ ] **Step 6.1: 定义硬失败**

  必须 hard fail：
  - 空 TOC。
  - 泛节点坍缩。
  - 大量节点指向 TOC 页。
  - 物理页越界。
  - 范围非法。
  - 可见目录有页码但标题锚点过低。
  - 页码大面积非单调或坍缩。
  - 主目录与图/表目录混合。
  - 需要展开的超长正文叶子展开后仍为空。

- [ ] **Step 6.2: 定义非硬失败**

  不能因这些直接失败：
  - 原始目录本身是平铺。
  - 图目录/表目录为点状页码。
  - 相邻正文节点一页边界重合。
  - 编号重复但标题不同。

- [ ] **Step 6.3: LLM QC 只消费事实报告**

  LLM QC 输入包括：
  - TOC tree preview
  - mapping report
  - child expansion report
  - route decision
  - quality facts

  LLM QC 不单独覆盖事实硬校验。

- [ ] **Step 6.4: 跑质量门测试**

  ```powershell
  py -X utf8 -m pytest backend/tests/test_balanced_quality_gate.py backend/tests/test_index_quality.py -q
  ```

  Expected: PASS.

- [ ] **Step 6.5: 跑全量官方 9 份和 AI Knowledge 13 份**

  Expected:
  - route ok 但 strict reference 错误的文件不能静默通过。
  - 失败报告必须指向稳定 reason code。

- [ ] **Step 6.6: Commit**

  ```powershell
  git add backend/pageindex/balanced_quality_gate.py backend/pageindex/index_quality.py backend/app/services/pageindex_service.py backend/tests
  git commit -m "fix: unify toc quality gate semantics"
  ```

## Phase 7: 严格 E2E 验收与 HTML 预览

**Purpose:** 用官方 9 份和 AI Knowledge 13 份完整验证最终流程、路径、耗时和 TOC 树质量。

**Files:**
- Modify: `D:\projects\page_chat\scripts\run_ai_knowledge_toc_e2e.py`
- Optional Create/Modify: `D:\projects\page_chat\scripts\render_toc_tree_review.py`
- Output: `D:\projects\page_chat\eval0618\phase7-final-official`
- Output: `D:\projects\page_chat\eval0618\phase7-final-ai-knowledge`

- [ ] **Step 7.1: 官方 9 份逐个运行**

  每个文件单独执行，记录耗时。目标：
  - P01 年报不被较差 fallback 覆盖。
  - P02 截断文档映射错误能被修复或明确失败。
  - P03/P09 继续通过。
  - P04/P05/P07 content_outline 明显改善。
  - P06 使用物理页口径后通过。
  - P08 不再出现质量门互相矛盾。

- [ ] **Step 7.2: AI Knowledge 13 份逐个运行**

  重点检查：
  - T03 重庆：目录完整、物理页准确、不得依赖坏规则结果。
  - T04/T05/T07/T12：长章节按预期展开。
  - T08/T09/T11/T13：主目录、图目录、表目录独立显示。
  - T09：原本就是物理页的目录不得被错误 remap。
  - T13：乱码/坏章节应回退或失败，不静默通过。

- [ ] **Step 7.3: 生成汇总矩阵**

  每份文件输出：
  - ID
  - file
  - elapsed seconds
  - content type
  - selected path
  - attempt chain
  - accepted candidate source
  - root/node/depth
  - quality status
  - hard fail reasons
  - reference mismatches

- [ ] **Step 7.4: 生成 HTML 树状预览**

  类似：

  ```text
  D:\projects\page_chat\eval0618\phase7-final-ai-knowledge\toc_tree_review.html
  ```

  HTML 必须展示：
  - 路由信息
  - 耗时
  - 质量报告
  - 完整 TOC 树
  - 每个节点 start/end
  - 失败/警告原因

- [ ] **Step 7.5: 汇报 checkpoint**

  向用户提供：
  - 官方结果目录。
  - AI Knowledge 结果目录。
  - HTML 预览路径。
  - 每份文件路径和质量摘要。
  - 仍未达标的文件和原因。

- [ ] **Step 7.6: Commit 核心代码**

  不提交 `eval0618/`，除非用户明确要求。

  ```powershell
  git add backend scripts docs
  git commit -m "test: validate pageindex toc lifecycle end to end"
  ```

## 6. 最终验收标准

功能验收：

- fast/balanced 不再是互相覆盖的两段递归流程，而是可观测的 attempt chain。
- `best_candidate` 防止高质量候选被差 fallback 覆盖。
- 规则 TOC 和 LLM TOC 可共同进入候选池。
- 所有 TOC 候选都走统一 S5。
- final TOC 页码全部是 1-based physical PDF pages。
- `end_index` 保留且由系统派生。
- 主目录、图目录、表目录独立。
- 无目录/弱目录文档不再坍缩为泛节点。
- 长正文叶子节点能够递归展开，或被质量门明确标记。
- LLM QC 只基于事实报告提出辅助意见。

验证验收：

- 官方 9 份样例有完整 E2E 报告。
- AI Knowledge 13 份样例有完整 E2E 报告。
- 每份文件都记录耗时。
- 每份文件都有路径、候选、映射、质量报告。
- HTML 树状预览可用于人工审查。
- 阶段相关样本通过后才进入下一阶段。

## 7. 当前建议的下一步

先执行 Phase 0，然后 Phase 1。

原因：

- Phase 0 先修验证集物理页口径，避免 P06 假失败干扰判断。
- Phase 1 修候选生命周期，是当前最高杠杆问题；不先修它，后续任何 fallback、content_outline、质量门优化都可能继续被“好候选丢失”污染结果。

Phase 1 完成后，再进入 Phase 2/3，把规则、LLM、S5 统一起来。这样后续 content_outline 和长节点展开不会继续依赖不稳定路径。
