# Unified TOC State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `toc_generation_unified_architecture.md` 和 `ai_knowledge_toc_test_baseline.md` 实现确定性 TOC 状态机，确保每类真实 PDF 都走预期路径，并得到可用、可校验、使用物理页码的 TOC。

**Architecture:** 先把 PDF 统一转换为 `PageTextMap`，再按唯一状态机路径构建 TOC：`embedded_toc`、`visible_toc_with_pages`、`visible_toc_no_pages` 或 `content_outline`。每阶段都有硬验收门，只有真实样本达到预期后才进入下一阶段，最终逐个文件做端到端测试。

**Tech Stack:** Python 3.14, pytest, PyMuPDF, existing `backend/pageindex` pipeline modules, existing OCR resolver/cache, existing PageIndex service, existing LLM route through model gateway, Windows PowerShell.

---

## 0. 依据文档

实施前必须完整阅读并对齐这两份文档：

- `docs/architecture/toc_generation_unified_architecture.md`
- `docs/architecture/ai_knowledge_toc_test_baseline.md`

本计划只负责落地这两份文档，不新增更复杂的路径，不恢复多候选竞赛，不把 `page_outline` 作为独立路径。

## 1. 全局验收原则

- 每阶段都必须有自动化测试和真实 PDF 验证。
- 每阶段真实样本未达到预期时，不进入下一阶段。
- 每份文档一次只走一条主路径；fallback 必须显式记录原因。
- `PageTextMap` 是 TOC 构建和节点内容填充的唯一正文来源。
- 最终 TOC 只输出物理页码。
- 主目录、图目录、表目录必须按需拆成独立 `toc_sections` 和前端顶级节点。
- 质量门判断 TOC 是否忠实可用，不强制要求树状结构。
- 主日志保持高效，只记录阶段、路径、模型摘要和关键结果；OCR 详细输入输出写入单独诊断。

## 2. 真实测试数据

输入目录：

```text
D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge
```

真实样本和预期：

| 编号 | 文件 | 页数 | 预期路径 | 必须满足的结果 |
|---:|---|---:|---|---|
| T01 | `2025全球人工智能技术应用洞察报告.pdf` | 43 | `text -> embedded_toc` | 清洗弱 slide-export outline，拒绝 raw 幻灯片书签早返回；章节起始页约为 4/11/24/38 |
| T02 | `2025年AI治理报告：回归现实主义.pdf` | 76 | `ocr/hybrid -> embedded_toc` | 识别文本层乱码，节点内容来自 OCR 后 `PageTextMap`，outline 建主目录 |
| T03 | `2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf` | 44 | `ocr -> visible_toc_with_pages` | 全文 OCR，抽出案例目录，不能退化为单节点，节点不能大量落在目录页 |
| T04 | `2025年第五范式-人工智能驱动的科技创新报告.pdf` | 68 | `text -> visible_toc_no_pages` | 第 2-3 页提纲识别为无页码目录；5 个顶级章节；章节内由 LLM 建树 |
| T05 | `2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf` | 21 | `text -> visible_toc_no_pages` | 高质量可见目录优先规则抽取；去重重复目录页；4 个顶级章节；`01-04` 不能当物理页码 |
| T06 | `2026年AI Agent智能体技术发展报告.pdf` | 85 | `text -> embedded_toc` | PDF links 提取 3-8 页约 117 条目录；规范化为 6 章多级结构；不出现 `第二章 -> 1.x` |
| T07 | `2026年快消行业AI营销增长白皮书.pdf` | 62 | `hybrid -> visible_toc_no_pages` | OCR 修补第 3-5 页；识别第 4 页图片目录；抽取 Part01-Part05 并定位正文页 |
| T08 | `AI眼镜关键技术与产业生态研究报告（2025年）.pdf` | 49 | `text -> visible_toc_with_pages` | 无 code_toc；高质量可见目录优先规则抽取；顶层为 `目录`、`图目录`、`表目录` |
| T09 | `OpenAI深度报告：大模型王者，引领AGI之路.pdf` | 26 | `text -> visible_toc_with_pages` | 无 code_toc；高质量混排目录优先规则抽取；主/图/表目录拆分；`风险提示` 映射到物理页 25 |
| T10 | `中国AI+营销趋势洞察2026.pdf` | 16 | `text -> embedded_toc` | 使用内置 outline 形成页级 slide outline，允许平铺 |
| T11 | `人工智能安全治理研究报告（2025年）.pdf` | 50 | `text -> embedded_toc` 或 `visible_toc_with_pages` | 不能只接受缺少图目录的 bookmarks；进入可见目录后优先规则抽取主目录 + 图目录 |
| T12 | `清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf` | 201 | `text -> visible_toc_no_pages` | 第 2 页无页码目录；序言 + 8 章；章节内 LLM 建树 |
| T13 | `生成式人工智能服务合规备案指南（2026年）.pdf` | 70 | `text -> embedded_toc` | bookmarks + links 合并；顶层为 `目录`、`表目录`、`图目录`；`第一章总则` 到物理页 10 |

## 3. 计划文件边界

优先复用现有模块，避免把问题拆成更多路径。

### 3.1 主要修改文件

- `backend/pageindex/pdf_analyzer.py`：S0 便宜分析；采集多源 code TOC 原始证据。
- `backend/pageindex/fast_path/code_toc_fast_path.py`：S2 embedded TOC 硬校验。
- `backend/pageindex/providers/code_toc_provider.py`：S2 code TOC provider 与 fast path 共用可靠性判断。
- `backend/pageindex/pipeline/toc_state_machine.py`：确定性路由和路径状态。
- `backend/pageindex/pipeline/toc_page_detector.py`：S3 目录页检测和 LLM 分类 schema。
- `backend/pageindex/candidates/llm_toc_page_extractor.py`：S4 LLM 目录页抽取。
- `backend/pageindex/toc_page_extractor.py`：标准目录规则抽取，失败后降级 LLM。
- `backend/pageindex/judge/content_page_mapper.py`：标题检索和物理页定位。
- `backend/pageindex/page_mapping_service.py`：printed page offset 和物理页映射。
- `backend/pageindex/post_processing.py`：范围修正和树构建。
- `backend/pageindex/index_quality.py`：质量门和 hard fail reasons。
- `backend/pageindex/node_filler.py`：从 `PageTextMap` 填充节点内容。
- `backend/app/services/pageindex_service.py`：状态机编排、保存、日志和端到端服务入口。

### 3.2 可能新增文件

- `backend/pageindex/page_text_map.py`：`PageTextMap` 数据结构和按页文本工具。
- `backend/pageindex/preprocess_page_text.py`：PDF 文本/OCR/hybrid 预处理入口。
- `backend/pageindex/code_toc_collector.py`：bookmarks、links、regex 多源采集与合并。
- `backend/pageindex/code_toc_quality.py`：fast path、provider、质量门共享的 code TOC 可靠性判断。
- `backend/tests/fixtures/toc/ai_knowledge_expected_routes.json`：真实样本路径和关键断言基线。
- `scripts/run_ai_knowledge_toc_e2e.py`：逐个真实文件运行索引并输出阶段报告。

### 3.3 主要测试文件

- `backend/tests/test_toc_state_machine.py`
- `backend/tests/test_code_toc_provider.py`
- `backend/tests/test_fast_toc_gates.py`
- `backend/tests/test_toc_page_detector.py`
- `backend/tests/test_llm_toc_page_extractor.py`
- `backend/tests/test_content_page_mapper.py`
- `backend/tests/test_page_mapping_service.py`
- `backend/tests/test_toc_post_processing_ranges.py`
- `backend/tests/test_toc_quality_gate_failures.py`
- `backend/tests/test_pdf_index_quality_gates.py`
- `backend/tests/test_pageindex_service_balanced_flow.py`
- `backend/tests/test_ocr_pipeline.py`
- `backend/tests/test_index_progress_logging.py`

## 4. Phase 0：建立真实样本诊断基线

**目标：** 在不改变 TOC 行为前，先建立可重复诊断脚本和基线文件。此阶段只做只读采证和测试夹具。

**Files:**

- Create: `backend/tests/fixtures/toc/ai_knowledge_expected_routes.json`
- Create: `scripts/run_ai_knowledge_toc_diagnostics.py`
- Test: `backend/tests/test_ai_knowledge_baseline_fixture.py`

- [ ] **Step 0.1：写入真实样本基线 JSON**

`ai_knowledge_expected_routes.json` 至少包含：

```json
{
  "input_dir": "D:\\chrome_download\\rag-skill-main\\rag-skill-main\\knowledge\\AI Knowledge",
  "documents": [
    {
      "file": "生成式人工智能服务合规备案指南（2026年）.pdf",
      "page_count": 70,
      "expected_path": "text -> embedded_toc",
      "must_have_sections": ["main_toc", "table_toc", "figure_toc"],
      "known_pages": {"第一章总则": 10}
    }
  ]
}
```

- [ ] **Step 0.2：实现只读诊断脚本**

脚本只读取 PDF，不调用 LLM/OCR，不写索引。输出每份文件：

- page_count
- text_coverage
- raw bookmarks count
- raw PDF link pages
- current analyzer `code_toc.source`
- current analyzer `code_toc.items` count
- 是否有 weak slide-export outline
- 是否存在 bookmarks 与 links 互补

- [ ] **Step 0.3：写测试校验基线完整性**

Run:

```powershell
cd backend
py -m pytest tests/test_ai_knowledge_baseline_fixture.py -q
```

Expected:

- 13 份 PDF 全部在基线中。
- 每份文件都有 `expected_path` 和至少一个关键验收点。

- [ ] **Step 0.4：运行只读诊断并保存人工检查摘要**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --input "D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge" --output artifacts\toc_diagnostics\ai_knowledge_baseline.json
```

Expected:

- T06 显示 bookmarks=0，link pages=3-8，links≈117。
- T13 显示 bookmarks≈172，link pages=7-9，links 覆盖主/表/图目录。
- T01 显示 weak slide-export outline。

**Phase Gate 0：**

- [ ] 基线 JSON 覆盖 13 份真实文件。
- [ ] 只读诊断输出与 `ai_knowledge_toc_test_baseline.md` 一致。
- [ ] 未修改生产代码。

## 5. Phase 1：统一 `PageTextMap` 预处理

**目标：** 所有后续 TOC 构建和节点内容填充都从 `PageTextMap` 读取文本；文本型、OCR 型、hybrid 型先统一，再进入 TOC 路由。

**Files:**

- Create: `backend/pageindex/page_text_map.py`
- Create: `backend/pageindex/preprocess_page_text.py`
- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/pageindex/node_filler.py`
- Test: `backend/tests/test_page_text_map.py`
- Test: `backend/tests/test_ocr_pipeline.py`

- [ ] **Step 1.1：写 `PageTextMap` 单元测试**

覆盖：

- 文本型页面 `source=pdf_text`。
- OCR 页面 `source=ocr`。
- 混合页面 `source=mixed`。
- 每页必须保留 `physical_page`、`text`、`source`、`quality`、`ocr_used`。

Run:

```powershell
cd backend
py -m pytest tests/test_page_text_map.py -q
```

Expected: FAIL，模块未实现。

- [ ] **Step 1.2：实现 `PageTextMap` 和预处理入口**

核心行为：

- `content_type=text`：直接使用 PDF 文本层。
- `content_type=ocr`：全文 OCR，正文 OCR prompt 为 `Recognize all readable text in natural reading order.`
- `content_type=hybrid`：只 OCR 空白/乱码/图片坏页，再拼回原页序。

- [ ] **Step 1.3：改节点内容填充**

`node_filler` 和 `pageindex_service` 后续填充节点内容时，只能使用 `PageTextMap`；索引构建后不能再次 OCR。

- [ ] **Step 1.4：真实文件阶段测试**

Run one by one:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase preprocess --file "2026年快消行业AI营销增长白皮书.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase preprocess --file "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase preprocess --file "2025年AI治理报告：回归现实主义.pdf"
```

Expected:

- T07：第 3-5 页被识别为需要 OCR，第 4 页 OCR 文本包含 Part01-Part05 目录信号。
- T03：44 页全部 OCR，`PageTextMap` 覆盖 44 页。
- T02：乱码页不能作为最终节点内容来源，OCR 后文本可检索。

**Phase Gate 1：**

- [ ] `tests/test_page_text_map.py` 通过。
- [ ] T03/T07/T02 的 `PageTextMap` 达到预期。
- [ ] 后续节点内容填充不再触发额外 OCR。

## 6. Phase 2：确定性状态机与路由

**目标：** 替换多候选竞赛式执行。状态机显式执行 S0-S8，每份文档一次只走一条主路径，fallback 必须记录原因。

**Files:**

- Modify: `backend/pageindex/pipeline/toc_state_machine.py`
- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/pageindex/pipeline/toc_pipeline_controller.py`
- Test: `backend/tests/test_toc_state_machine.py`
- Test: `backend/tests/test_pageindex_route_decision.py`
- Test: `backend/tests/test_pageindex_service_balanced_flow.py`

- [ ] **Step 2.1：写状态机路径测试**

覆盖：

- high-quality `embedded_toc` 进入 S2 并可接受。
- S2 硬校验失败后进入 S3。
- `content_type=ocr` 先进入 S1 OCR，再进入 TOC 检测。
- `content_type=hybrid` 先补坏页。
- `enrich` 不参与 TOC 路由。

Run:

```powershell
cd backend
py -m pytest tests/test_toc_state_machine.py tests/test_pageindex_route_decision.py -q
```

Expected: 先 FAIL，当前路由仍有历史分支。

- [ ] **Step 2.2：实现状态机编排**

状态必须输出：

```json
{
  "requested_mode": "smart",
  "content_type": "text|ocr|hybrid",
  "states": ["S0", "S1", "S2", "..."],
  "selected_path": "embedded_toc|visible_toc_with_pages|visible_toc_no_pages|content_outline",
  "fallbacks": []
}
```

- [ ] **Step 2.3：禁止完整多路径并行竞赛**

删除或隔离“同时生成多个完整候选再评分”的入口。允许同一阶段内做低成本证据采集，但不能跑多个完整 TOC 构建结果竞赛。

- [ ] **Step 2.4：真实文件路由测试**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase route --all
```

Expected:

- T06 route=`text -> embedded_toc`
- T13 route=`text -> embedded_toc`
- T07 route=`hybrid -> visible_toc_no_pages`
- T03 route=`ocr -> visible_toc_with_pages`
- T12 route=`text -> visible_toc_no_pages`

**Phase Gate 2：**

- [ ] 路由测试通过。
- [ ] 13 份真实文件的 route 与基线一致，或有明确 fallback 原因。
- [ ] `enrich` 不影响 TOC 路由和结构。

## 7. Phase 3：`embedded_toc` 多源采集、合并与硬校验

**目标：** `embedded_toc` 不再是单一 source，而是并行采集 bookmarks/outline、PDF links、必要时 regex/text heading，再合并为 `toc_sections`。

**Files:**

- Create: `backend/pageindex/code_toc_collector.py`
- Create: `backend/pageindex/code_toc_quality.py`
- Modify: `backend/pageindex/pdf_analyzer.py`
- Modify: `backend/pageindex/fast_path/code_toc_fast_path.py`
- Modify: `backend/pageindex/providers/code_toc_provider.py`
- Test: `backend/tests/test_code_toc_provider.py`
- Test: `backend/tests/test_fast_toc_gates.py`
- Test: `backend/tests/test_ppt_bookmark_quality.py`
- Test: `backend/tests/test_auxiliary_catalogs.py`

- [ ] **Step 3.1：写多源采集测试**

用真实 PDF 或最小 fixture 覆盖：

- T13：bookmarks≈172，links≈112，link pages=7-9，输出 `main_toc/table_toc/figure_toc`。
- T06：bookmarks=0，links≈117，输出 `main_toc`。
- T01：raw outline 包含 `默认节`、`幻灯片 X`，不能直接 early return。

Run:

```powershell
cd backend
py -m pytest tests/test_code_toc_provider.py tests/test_fast_toc_gates.py tests/test_ppt_bookmark_quality.py -q
```

Expected: FAIL，当前实现仍可能单源短路或判断不一致。

- [ ] **Step 3.2：实现 `code_toc_collector`**

输出结构：

```json
{
  "sources": {
    "bookmarks": {"items": [], "count": 172},
    "links": {"items": [], "count": 112, "toc_pages": [7, 8, 9]},
    "regex": {"items": [], "count": 0}
  },
  "toc_sections": [
    {"kind": "main_toc", "source": "bookmarks+links", "items": []},
    {"kind": "table_toc", "source": "links", "items": []},
    {"kind": "figure_toc", "source": "links", "items": []}
  ]
}
```

- [ ] **Step 3.3：统一 code TOC 质量判断**

`CodeTOCFastPath`、`CodeTocProvider`、质量门必须共用：

- 页码范围校验。
- 标题抽样命中。
- 目录页泄漏校验。
- 辅助目录缺失校验。
- weak slide-export outline 清洗和拒绝逻辑。

- [ ] **Step 3.4：真实文件阶段测试**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase embedded --file "生成式人工智能服务合规备案指南（2026年）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase embedded --file "2026年AI Agent智能体技术发展报告.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase embedded --file "2025全球人工智能技术应用洞察报告.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase embedded --file "中国AI+营销趋势洞察2026.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase embedded --file "人工智能安全治理研究报告（2025年）.pdf"
```

Expected:

- T13：accepted `embedded_toc` only if sections include `main_toc/table_toc/figure_toc`。
- T06：accepted `embedded_toc` from links；结构为 6 章多级，第二章不挂成 `1.x`。
- T01：如果 raw weak slide outline 未清洗，必须 rejected；清洗后才可 accepted。
- T10：accepted slide outline；允许页级平铺。
- T11：如果 bookmarks 缺图目录，S2 rejected 或补齐图目录后 accepted。

**Phase Gate 3：**

- [ ] code TOC 相关测试通过。
- [ ] T06/T13/T01/T10/T11 达到预期。
- [ ] fast path、provider、质量门对同一 `code_toc` 的结果一致。

## 8. Phase 4：目录页检测与 LLM 分类 schema

**目标：** 先检测目录页，只判断位置和类型，不抽取完整目录；一页同时有多种目录类型时输出 `mixed_toc + sections[]`。

**Files:**

- Modify: `backend/pageindex/pipeline/toc_page_detector.py`
- Modify: `backend/pageindex/toc_detector.py`
- Modify: `backend/app/prompts/pageindex_prompts.py` if prompt is centralized there
- Test: `backend/tests/test_toc_page_detector.py`
- Test: `backend/tests/test_toc_page_detection_enrichment.py`
- Test: `backend/tests/test_pageindex_prompt_templates.py`

- [ ] **Step 4.1：写目录页检测测试**

覆盖：

- 连续目录页，最后一页仍为目录时继续补扫。
- 一页同时包含图目录和表目录，输出 `primary_kind=mixed_toc`。
- 普通章节首页、免责声明、参考文献不能误判。
- LLM 分类输出 `sections[]`，不是单个 `kind`。

Expected schema:

```json
{
  "is_toc": true,
  "primary_kind": "mixed_toc",
  "sections": [
    {"kind": "figure_toc", "confidence": 0.91},
    {"kind": "table_toc", "confidence": 0.86}
  ],
  "confidence": 0.9
}
```

- [ ] **Step 4.2：实现规则 detector**

规则必须依赖多个独立信号组合，不因单个关键词判定目录页。

- [ ] **Step 4.3：实现轻量 LLM fallback**

要求：

- 每页一次调用。
- 小批次内并发。
- 输出短 JSON。
- 不抽取完整目录项。

- [ ] **Step 4.4：真实文件阶段测试**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase detect --file "AI眼镜关键技术与产业生态研究报告（2025年）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase detect --file "OpenAI深度报告：大模型王者，引领AGI之路.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase detect --file "生成式人工智能服务合规备案指南（2026年）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase detect --file "2026年快消行业AI营销增长白皮书.pdf"
```

Expected:

- T08：toc_pages=4-5，sections include `main_toc/figure_toc/table_toc`。
- T09：toc_pages=2-3，sections include `main_toc/figure_toc/table_toc`。
- T13：toc_pages=7-9，sections include `main_toc/table_toc/figure_toc`。
- T07：OCR 后 toc_pages include physical page 4。

**Phase Gate 4：**

- [ ] 目录页检测测试通过。
- [ ] T08/T09/T13/T07 目录页和类型检测符合基线。
- [ ] 检测阶段没有抽取完整目录项。

## 9. Phase 5：四条 TOC 构建路径

**目标：** 实现并收敛到四条路径：`embedded_toc`、`visible_toc_with_pages`、`visible_toc_no_pages`、`content_outline`。

**Files:**

- Modify: `backend/pageindex/candidates/llm_toc_page_extractor.py`
- Modify: `backend/pageindex/toc_page_extractor.py`
- Modify: `backend/pageindex/hierarchical_extractor.py`
- Modify: `backend/pageindex/batch_extractor.py`
- Modify: `backend/pageindex/page_outline_extractor.py` only to isolate old behavior
- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_llm_toc_page_extractor.py`
- Test: `backend/tests/test_toc_page_extractor_contract.py`
- Test: `backend/tests/test_hierarchical_extractor.py`
- Test: `backend/tests/test_slide_outline_extractor.py`

- [ ] **Step 5.1：`visible_toc_with_pages`**

规则高置信先抽取；失败或低置信立即 LLM。

对没有可用 `code_toc`、但可见目录质量很高的样本，规则抽取是必须优先验证的子路径。规则通过完整性、页码语义、标题命中和图表目录拆分校验时，不应再调用 LLM 抽取。当前专项样本：

- T05 `2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf`
- T08 `AI眼镜关键技术与产业生态研究报告（2025年）.pdf`
- T09 `OpenAI深度报告：大模型王者，引领AGI之路.pdf`
- T11 `人工智能安全治理研究报告（2025年）.pdf`

T05 的 `01-04` 必须先做页码语义校验。若确认是章节号而非页码，则该文件仍走 `visible_toc_no_pages` 的标题定位映射，但 S4 目录项抽取应来自高置信规则。

LLM 只处理确认过的目录页文本，输出：

```json
{
  "toc_sections": [
    {"kind": "main_toc", "title": "目录", "items": []},
    {"kind": "figure_toc", "title": "图目录", "items": []},
    {"kind": "table_toc", "title": "表目录", "items": []}
  ]
}
```

- [ ] **Step 5.2：`visible_toc_no_pages`**

LLM 抽取标题和层级，不猜页码；后续标题搜索定位。

如果只定位到顶级 anchor，章节内部结构由 LLM 基于章节范围内每页前 200 字生成。

- [ ] **Step 5.3：`content_outline`**

无目录页统一进入 `content_outline`。它可以输出章节树，也可以输出符合原文的页级平铺。旧 `page_outline` 只能作为内部低级实现，不作为独立路径。

- [ ] **Step 5.4：真实文件阶段测试**

Run one by one:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "OpenAI深度报告：大模型王者，引领AGI之路.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "AI眼镜关键技术与产业生态研究报告（2025年）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "人工智能安全治理研究报告（2025年）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "2026年快消行业AI营销增长白皮书.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "2025年第五范式-人工智能驱动的科技创新报告.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase build --file "清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf"
```

Expected:

- T09：规则抽取拆出 `目录/图目录/表目录`；主目录包含 `复盘/展望/愿景/风险提示`；规则通过时不调用 LLM。
- T08：规则抽取拆出 `目录/图目录/表目录`，规则通过时不调用 LLM。
- T11：若 S2 因缺图目录降级，S4 规则抽取主目录 + 图目录，规则通过时不调用 LLM。
- T05：规则抽取 4 个顶级章节，去重重复目录页；`01-04` 不作为物理页码。
- T07：抽出 Part01-Part05；不计算 offset。
- T04：5 个顶级章节，章节内有 LLM 子结构。
- T12：序言 + 8 章，章节内有可用子结构或页级子节点。

**Phase Gate 5：**

- [ ] 四条路径单元测试通过。
- [ ] T09/T07/T04/T12 构建结果符合基线。
- [ ] 没有独立 `page_outline` 主路径。

## 10. Phase 6：统一物理页码映射和范围修正

**目标：** 所有路径最终输出物理页码；图目录/表目录独立映射，不参与主目录范围切分。

**Files:**

- Modify: `backend/pageindex/judge/content_page_mapper.py`
- Modify: `backend/pageindex/page_mapping_service.py`
- Modify: `backend/pageindex/post_processing.py`
- Modify: `backend/pageindex/tree_schema.py`
- Test: `backend/tests/test_content_page_mapper.py`
- Test: `backend/tests/test_page_mapping_service.py`
- Test: `backend/tests/test_toc_post_processing_ranges.py`
- Test: `backend/tests/test_auxiliary_catalog_normalization.py`

- [ ] **Step 6.1：写物理页映射测试**

覆盖：

- `embedded_toc` links 直接使用物理页，但要抽样标题校验。
- printed page offset 只用于有页码可见目录。
- 无页码目录只用标题搜索，不猜 offset。
- 大量节点映射到目录页时失败。

- [ ] **Step 6.2：实现统一映射报告**

输出：

```json
{
  "strategy": "embedded_links|printed_page_offset|title_search|content_outline",
  "anchor_match": "12/14",
  "offset": 9,
  "toc_page_leakage_count": 0,
  "status": "ok|failed"
}
```

- [ ] **Step 6.3：实现递归范围修正**

同级节点规则：

```text
if next.start_page == current.end_page:
    current.end_page = next.start_page
else:
    current.end_page = next.start_page - 1
```

对所有层级递归适用。允许边界重合，不允许无解释大范围重叠。

- [ ] **Step 6.4：真实文件阶段测试**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase map --file "OpenAI深度报告：大模型王者，引领AGI之路.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase map --file "生成式人工智能服务合规备案指南（2026年）.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase map --file "2026年AI Agent智能体技术发展报告.pdf"
py scripts/run_ai_knowledge_toc_diagnostics.py --phase map --file "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"
```

Expected:

- T09：`风险提示` -> 物理页 25。
- T13：`第一章总则` -> 物理页 10；表目录/图目录不落在目录页 8/9。
- T06：links 物理页抽样命中；第二章起始页正确。
- T03：案例节点不大量指向目录页。

**Phase Gate 6：**

- [ ] 映射和范围测试通过。
- [ ] T09/T13/T06/T03 关键页码符合基线。
- [ ] 最终 public TOC 只使用物理页码。

## 11. Phase 7：质量门、保存顺序和失败策略

**目标：** 质量门只判断 TOC 可用性；明显错误必须 fail，平铺和合理边界重合不能 fail。保存 base index 后再 enrich，enrich 不改变 TOC。

**Files:**

- Modify: `backend/pageindex/index_quality.py`
- Modify: `backend/pageindex/balanced_quality_gate.py`
- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_toc_quality_gate_failures.py`
- Test: `backend/tests/test_pdf_index_quality_gates.py`
- Test: `backend/tests/test_pageindex_base_save.py`
- Test: `backend/tests/test_index_quality_regression.py`

- [ ] **Step 7.1：写质量门 hard fail 测试**

必须失败：

- TOC 为空。
- 页码越界。
- 大量节点指向目录页。
- 有页码目录 offset 校验失败。
- 无页码目录标题定位率过低。
- 缺失必须存在的图目录/表目录。
- 节点内容无法从 `PageTextMap` 填充。

- [ ] **Step 7.2：写不应失败测试**

不应失败：

- 原文就是平铺目录。
- 图目录/表目录是索引节点，没有完整正文范围。
- 相邻或父子节点有合理边界重合。

- [ ] **Step 7.3：实现质量报告**

输出：

```json
{
  "status": "passed|failed",
  "hard_fail_reasons": [],
  "warnings": [],
  "route": "visible_toc_with_pages",
  "mapping_status": "ok"
}
```

- [ ] **Step 7.4：保存顺序**

固定顺序：

```text
TOC 通过质量门 -> Save base index -> Enrich -> Save final index
```

`enrich` 只消费 TOC，不参与路由，不改变 TOC 结构。

- [ ] **Step 7.5：真实文件阶段测试**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase quality --all
```

Expected:

- T01/T10 平铺不失败。
- T08/T09/T13 缺图表目录会失败。
- T03 大量目录项落在目录页会失败。
- 所有通过样本的节点内容来自 `PageTextMap`。

**Phase Gate 7：**

- [ ] 质量门测试通过。
- [ ] 13 份真实文件的质量状态符合基线。
- [ ] `enrich` 不改变 TOC 路径和结构。

## 12. Phase 8：日志和可观测性

**目标：** 主日志高效可读，OCR 详细信息不污染主日志；每阶段可定位。

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/app/services/ocr_engines/openai_compatible_adapter.py`
- Modify: `backend/app/services/ocr_engines/paddleocr_job_adapter.py`
- Test: `backend/tests/test_index_progress_logging.py`
- Test: `backend/tests/test_visual_extractor_logs.py`
- Test: `backend/tests/test_ocr_pipeline.py`

- [ ] **Step 8.1：写主日志测试**

主日志必须包含：

```text
[TOC-PIPELINE] stage=preprocess content_type=...
[TOC-PIPELINE] stage=toc_detect method=... toc_pages=... sections=...
[TOC-PIPELINE] stage=toc_build path=...
[TOC-MAPPING] strategy=... anchor_match=...
[TOC-QUALITY] status=...
```

主日志不能包含：

- OCR prompt full text
- raw OCR markdown/text
- page image payload
- token 或 API key

- [ ] **Step 8.2：实现 OCR 诊断文件**

详细 OCR 输入、输出摘要、耗时、错误写入单独调试日志，例如：

```text
backend/data/ocr_diagnostics/<doc_id>/<task>-<page>.json
```

- [ ] **Step 8.3：真实文件日志检查**

Run:

```powershell
py scripts/run_ai_knowledge_toc_diagnostics.py --phase logs --file "2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf"
```

Expected:

- 主日志只看到 `task=page_text model=qwen-vl-ocr pages=44 concurrency=20` 这类摘要。
- 详细 OCR 输出在诊断文件里。

**Phase Gate 8：**

- [ ] 日志测试通过。
- [ ] 主日志能清晰看出实际路径。
- [ ] OCR 详细内容不进入主日志和最终 index diagnostics。

## 13. Phase 9：真实文件端到端测试

**目标：** 逐个真实 PDF 端到端构建 TOC，验证流程、结果和质量门都符合基线。

**Files:**

- Create: `scripts/run_ai_knowledge_toc_e2e.py`
- Create: `artifacts/toc_e2e/README.md` or generated report directory
- Test: `backend/tests/test_ai_knowledge_e2e_report_contract.py`

- [ ] **Step 9.1：实现逐文件 E2E runner**

要求：

- 一次只跑一个文件。
- 每个文件输出独立 report JSON。
- report 包含 S0-S8 阶段、路径、fallback、TOC 顶级节点、节点数、图表目录状态、关键页码检查、质量门状态。
- 支持 `--stop-on-fail`。

Run:

```powershell
py scripts/run_ai_knowledge_toc_e2e.py --input "D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge" --file "2026年AI Agent智能体技术发展报告.pdf" --output artifacts\toc_e2e
```

- [ ] **Step 9.2：按推荐顺序逐个运行**

必须一份一份跑，不能并发跑 13 个文件：

```text
1. 中国AI+营销趋势洞察2026.pdf
2. 2025全球人工智能技术应用洞察报告.pdf
3. 2026年AI Agent智能体技术发展报告.pdf
4. AI眼镜关键技术与产业生态研究报告（2025年）.pdf
5. OpenAI深度报告：大模型王者，引领AGI之路.pdf
6. 生成式人工智能服务合规备案指南（2026年）.pdf
7. 人工智能安全治理研究报告（2025年）.pdf
8. 2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf
9. 2025年第五范式-人工智能驱动的科技创新报告.pdf
10. 清华大学：职业教育人工智能应用发展报告（2024-2025）.pdf
11. 2026年快消行业AI营销增长白皮书.pdf
12. 2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf
13. 2025年AI治理报告：回归现实主义.pdf
```

- [ ] **Step 9.3：检查每份文件的预期结果**

每份 report 必须满足第 2 节表格中的结果。关键 hard assertions：

- T06：`source=embedded_toc`，`code_toc.sources.links.toc_pages=[3,4,5,6,7,8]`，顶级约 6 章，第二章不是 `1.x`。
- T13：`toc_sections` 包含 `main_toc/table_toc/figure_toc`，`第一章总则` 物理页 10。
- T09：顶级包含 `目录/图目录/表目录`，`风险提示` 物理页 25。
- T09：S4 使用规则抽取，除非规则校验失败。
- T08：顶级包含 `目录/图目录/表目录`，S4 使用规则抽取，除非规则校验失败。
- T11：最终至少包含 `目录/图目录`；如果走可见目录路径，S4 使用规则抽取，除非规则校验失败。
- T05：S4 使用规则抽取 4 个顶级章节；`01-04` 被判为章节号，不触发 printed page offset。
- T07：第 4 页目录被 OCR 后识别，顶级 Part01-Part05，Part 节点不在目录页。
- T03：TOC 非单节点，目录项不大量落在目录页。
- T01：raw weak slide outline 不早返回；清洗后通过或明确 fallback。

- [ ] **Step 9.4：运行自动化测试套件**

Run:

```powershell
cd backend
py -m pytest ^
  tests/test_page_text_map.py ^
  tests/test_toc_state_machine.py ^
  tests/test_code_toc_provider.py ^
  tests/test_fast_toc_gates.py ^
  tests/test_toc_page_detector.py ^
  tests/test_llm_toc_page_extractor.py ^
  tests/test_content_page_mapper.py ^
  tests/test_page_mapping_service.py ^
  tests/test_toc_post_processing_ranges.py ^
  tests/test_toc_quality_gate_failures.py ^
  tests/test_pdf_index_quality_gates.py ^
  tests/test_pageindex_service_balanced_flow.py ^
  tests/test_ocr_pipeline.py ^
  tests/test_index_progress_logging.py ^
  -q
```

Expected: PASS。

- [ ] **Step 9.5：人工抽查最终索引**

检查生成的 `backend/data/indexes/<doc_id>.json`：

- `route_decision.selected_path` 与基线一致。
- `structure` 顶级节点符合预期。
- 所有节点 `start_index/end_index` 是物理页。
- 节点内容可从 `PageTextMap` 对应页范围提取。
- `quality_report.status` 通过。

**Phase Gate 9：**

- [ ] 13 份真实 PDF 逐个端到端通过。
- [ ] 每份 report 均符合基线。
- [ ] 自动化测试套件通过。
- [ ] 最终 TOC 构建按预期流程执行，得到预期结果。

## 14. 最终完成标准

本计划完成时必须同时满足：

- 状态机日志能看出 S0-S8 的实际执行路径。
- 13 份真实文件端到端 TOC 结果符合 `ai_knowledge_toc_test_baseline.md`。
- `embedded_toc` 支持 bookmarks + links 多源合并。
- 图目录/表目录不会混入主目录，也不会抢占主目录页码映射。
- 无页码目录不再猜 offset。
- OCR 只在 S1 预处理阶段生成 `PageTextMap`，后续复用。
- 质量门会拦截明显错误结果。
- 平铺目录不会因为没有层级而失败。
- 主日志精简，OCR 细节单独记录。

## 15. 回滚与失败处理

如果某阶段失败：

1. 停在当前阶段，不继续后续阶段。
2. 用该阶段真实样本和中间产物定位原因。
3. 不用补丁式特殊规则绕过失败。
4. 如果规则检测/抽取不确定，降级 LLM，而不是继续叠加规则。
5. 如果 `embedded_toc` 多源信息冲突，优先用标题命中和物理页校验判断；不能简单按 source 优先级覆盖。
6. 如果 LLM 超时，先检查输入是否只包含确认过的目录页，再考虑延长 timeout 或拆分输入。

## 16. 建议提交节奏

每个 Phase 至少一个提交：

```text
test: add ai knowledge toc baseline diagnostics
feat: add page text map preprocessing
refactor: route toc generation through deterministic state machine
feat: collect and validate multi-source embedded toc
feat: detect toc pages with typed sections
feat: build toc through four deterministic paths
fix: map toc items to physical pages consistently
fix: enforce toc quality gates
chore: compact toc pipeline logs
test: verify ai knowledge toc end to end
```

不要把多个 Phase 混成一个大提交。每次提交前运行该阶段的单元测试和对应真实文件阶段测试。
