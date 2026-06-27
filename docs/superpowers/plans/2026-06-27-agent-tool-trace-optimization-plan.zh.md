# PageChat Agent 工具轨迹与证据契约优化计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PageChat 的 Agent 执行轨迹接近官方 PageIndex 的观感：短 thought、清晰工具动作、稳定页码读取、准确视觉证据与引用，不引入过重架构。

**Architecture:** 保留当前显式 Agent Loop Runtime，不引入 LangGraph/Redis/新检索框架。优先修正工具参数解析、工具结果契约、planner/policy/answer prompt 协作，以及前端 timeline 展示语义。

**Tech Stack:** FastAPI / Python backend, Vue frontend, SQLite, existing AgentLoopRuntime, existing tool runner and SSE event protocol.

---

## 背景观察

官方 PageIndex 的执行轨迹有几个稳定特征：

- thought 存在，但短、自然、只说明当前策略。
- 工具动作标题清楚，例如 `Read pages 6-13,17-35 from "...pdf"`。
- 读取页面时支持自然多段页码格式，例如 `1-5,14-16,36-37,42,47,49,51,58-62`。
- 工具结果包含 `success`、`requested_pages`、`returned_pages`、`total_pages`、`content`、`next_steps` 等结构化信息。
- 对文档概览/共性总结类问题，会先读结构，再选择关键页段；不会每一步都重复长篇解释。

PageChat 当前主要问题：

- Planner visible thought 过长，容易重复“用户认为之前不够深入”等元叙述。
- 工具标题太抽象，例如 `Read page content`，用户看不出读了什么。
- 页码参数对 `10-13,36-40` 这类表达不稳定，容易暴露底层错误。
- OCR 文本页、视觉页、普通文本页的证据语义不清，policy 容易误判。
- 工具结果里的 `result_count/result_label/next_steps` 不一致，前端会显示 `0 results` 或低价值信息。
- 引用有时像 chunk 编号，而不是绑定真实文档页码或网页来源。

## 非目标

- 不引入 LangGraph。
- 不引入 Redis。
- 不重写整个 Agent Runtime。
- 不做复杂的视觉页分类模型。
- 不把 thought 全部隐藏，只优化成短 thought + 清晰工具动作。

---

## Phase 1: Baseline And Trace Contract Audit

**Files:**
- Read: `backend/app/agent/loop_runtime.py`
- Read: `backend/app/agent/planner.py`
- Read: `backend/app/agent/nodes.py`
- Read: `backend/app/agent/policy.py`
- Read: `frontend/src/components/chat/RunTimeline.vue`
- Read: `frontend/src/components/chat/ToolTimelineItem.vue`

- [ ] **Step 1: Capture current event shape**

  Inspect current SSE events for planner thought, tool start, tool result, final answer, and citation events.

- [ ] **Step 2: Record current problematic patterns**

  Add short notes to this plan or a progress note about:
  - repeated visible thought
  - tool titles without page ranges
  - `0 results` display
  - page range parse failures
  - visual-only evidence being treated as enough

- [ ] **Step 3: Confirm branch before any code change**

  Run:

  ```powershell
  git -C "C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration" branch --show-current
  ```

  Expected:

  ```text
  codex/pagechat-ui-agent-runtime-integration
  ```

---

## Phase 2: Short Thought Prompt Rules

**Files:**
- Modify: `backend/app/prompts/__init__.py`
- Modify: `backend/app/agent/planner.py`
- Test: `backend/tests/test_agent_structured_llm_planner.py`
- Test: `backend/tests/test_agent_loop_runtime.py`

**Design:**
Planner thought remains visible, but must be short and action-oriented.

Allowed style:

```text
我会补读两份文档中尚未覆盖的关键章节。
```

Avoid:

```text
用户认为之前的总结不够深入。为了提供更有洞察力的关键结论，我需要...
```

- [ ] **Step 1: Add planner prompt constraints**

  Rules:
  - visible thought is user-facing, not private scratchpad.
  - one short sentence preferred, two sentences maximum.
  - do not restate the user's request.
  - do not mention policy, guardrail, insufficient evidence checks, or backend validation.
  - describe the next action, not the whole reasoning chain.

- [ ] **Step 2: Add examples**

  Add good examples:
  - `我先定位两份文档的核心章节。`
  - `我会补读营销趋势相关的关键页段。`
  - `这些页面偏视觉内容，我继续查看页面图像。`

- [ ] **Step 3: Test planner output normalization**

  If the planner output is longer than expected, runtime should still keep compatibility, but tests should verify the prompt contains the new constraints.

- [ ] **Step 4: Verify no hard-coded thought**

  Ensure backend does not synthesize fake fixed thought except for non-LLM fallback/error states.

---

## Phase 3: Page Range Parser And Tool Argument Validation

**Files:**
- Modify: `backend/app/agent/nodes.py`
- Modify: related tool schema/helpers if page parsing is elsewhere.
- Test: `backend/tests/test_agent_loop_runtime.py`
- Test: add or extend focused tests for page range parsing.

**Design:**
`get_page_content` should accept common page range strings:

- `1`
- `1-3`
- `1,3,5`
- `1-3,8,10-12`

The parser should normalize, dedupe, sort, validate bounds, and return friendly errors.

- [ ] **Step 1: Write parser tests**

  Test valid inputs:

  ```text
  1
  1-3
  1,3,5
  1-3,8,10-12
  ```

  Expected normalized pages:

  ```text
  [1]
  [1,2,3]
  [1,3,5]
  [1,2,3,8,10,11,12]
  ```

- [ ] **Step 2: Test invalid inputs**

  Examples:
  - `0`
  - `5-3`
  - `abc`
  - page greater than total pages

  Expected: structured tool error, no Python exception leaked.

- [ ] **Step 3: Implement parser**

  Keep it small and local. Do not introduce a new dependency.

- [ ] **Step 4: Surface friendly retry guidance**

  Tool error should include short `next_steps`, for example:

  ```text
  Use pages like "1-3,8,10-12".
  ```

---

## Phase 4: Tool Result Contract And Clear Action Labels

**Files:**
- Modify: `backend/app/agent/nodes.py`
- Modify: `backend/app/agent/loop_runtime.py`
- Modify: `frontend/src/components/chat/ToolTimelineItem.vue`
- Test: `frontend/src/components/chat/ToolTimelineItem.contract.test.ts`
- Test: `backend/tests/test_agent_run_event_protocol.py`

**Design:**
Every user-visible tool result should expose lightweight display fields:

```json
{
  "success": true,
  "result_count": 19,
  "result_label": "19 pages",
  "next_steps": "Use page images if visual details are needed."
}
```

Document page tools should also expose:

```json
{
  "doc_id": "...",
  "doc_name": "...",
  "requested_pages": [1, 2, 3],
  "returned_pages": [1, 2, 3],
  "total_pages": 62
}
```

- [ ] **Step 1: Define per-tool display labels**

  Suggested labels:
  - `browse_documents`: `4 documents / 1 folder`
  - `get_document_structure`: `62 pages / 41 sections`
  - `search_within_document`: `8 matches`
  - `get_page_content`: `19 pages`
  - `get_page_image`: `1 image`
  - `web_search`: `6 results`

- [ ] **Step 2: Generate clear action titles**

  Examples:
  - `Read pages 6-13,17-35 from "2026年快消行业AI营销增长白皮书.pdf"`
  - `View page 18 image from "中国AI+营销趋势洞察2026.pdf"`
  - `Search "GEO 用户记忆 视频交互" in "中国AI+营销趋势洞察2026.pdf"`

- [ ] **Step 3: Frontend display priority**

  `ToolTimelineItem` should prefer:
  1. action title
  2. `result_label`
  3. existing fallback

  It should not show `0 results` when a tool succeeded but returned non-`items` content.

- [ ] **Step 4: Keep raw parameters/results expandable**

  Default timeline shows clear action. Expanded state can show parameters and compact result.

---

## Phase 5: OCR, Text, And Visual Evidence Semantics

**Files:**
- Modify: `backend/app/agent/nodes.py`
- Modify: `backend/app/agent/policy.py`
- Modify: `backend/app/prompts/__init__.py`
- Test: `backend/tests/test_agent_policy.py`
- Test: `backend/tests/test_agent_loop_runtime.py`

**Design:**
Do not choose between "always return OCR" and "never return OCR". Use explicit source modes.

Suggested page content result fields:

```json
{
  "source_mode": "text | ocr_text | visual_required",
  "visual_evidence_required": false,
  "text": "...",
  "ocr_preview": "...",
  "image_ref": "..."
}
```

Rules:

- Text page: return text and allow answer.
- OCR text page: return OCR text, mark `source_mode: "ocr_text"`, allow answer for text facts but be conservative for visual layout/chart claims.
- Visual-heavy page: return short OCR preview only, set `visual_evidence_required: true`, require `get_page_image` before final answer if the question depends on that page.

- [ ] **Step 1: Add policy tests**

  Cases:
  - text page content is sufficient.
  - OCR text page can support ordinary text facts.
  - visual-only page content is not sufficient for final answer.
  - page image after visual-required content is sufficient.

- [ ] **Step 2: Update tool output**

  Ensure `get_page_content` marks page source mode consistently.

- [ ] **Step 3: Update planner prompt**

  Add rule:

  ```text
  If a page result says visual_evidence_required, call the page image tool for those pages before answering visual or layout-dependent questions.
  ```

- [ ] **Step 4: Avoid large OCR dumps**

  Keep OCR previews compact for visual-required pages to avoid token bloat.

---

## Phase 6: Planner, Policy, And Answer Prompt Alignment

**Files:**
- Modify: `backend/app/prompts/__init__.py`
- Modify: `backend/app/agent/planner.py`
- Modify: `backend/app/agent/policy.py`
- Modify: `backend/app/agent/loop_runtime.py`
- Test: `backend/tests/test_agent_policy.py`
- Test: `backend/tests/test_agent_service_loop_runtime.py`

**Design:**
Keep policy deterministic, but make planner/policy expectations align.

- [ ] **Step 1: Overview question rules**

  For overview questions such as:
  - `主要讲什么`
  - `总结`
  - `概括`
  - `有哪些文档`
  - `overview`
  - `summary`

  Allow `browse_documents` and/or `get_document_structure` as sufficient evidence.

- [ ] **Step 2: Specific fact rules**

  For page-level or detail questions, require stronger evidence:
  - `search_within_document`
  - `get_page_content`
  - `get_page_image`
  - prior page/image/search evidence

- [ ] **Step 3: Tool failure retry behavior**

  If a tool argument is invalid, planner should retry with corrected arguments without exposing verbose failure reasoning.

- [ ] **Step 4: Citation rules**

  Answer prompt should require citations to bind to real sources:
  - document id/name + page for document evidence
  - URL/title for web evidence

  Do not cite arbitrary chunks as if they were source pages.

- [ ] **Step 5: Language rule**

  Answer language follows the user's question language. Do not force Chinese if the user asks in English.

---

## Phase 7: Timeline UI Polish

**Files:**
- Modify: `frontend/src/components/chat/RunTimeline.vue`
- Modify: `frontend/src/components/chat/ToolTimelineItem.vue`
- Modify: `frontend/src/types/stream.ts`
- Test: `frontend/src/components/chat/RunTimeline.contract.test.ts`
- Test: `frontend/src/components/chat/ToolTimelineItem.contract.test.ts`

**Design:**
The default timeline should look like:

```text
Thought for 2 seconds
我会补读两份文档中尚未覆盖的关键章节。

Read pages 6-13,17-35 from "2026年快消行业AI营销增长白皮书.pdf" · 28 pages
Read pages 4-8,11,14-19 from "2025年度重庆市人工智能应用场景典型案例集.pdf" · 14 pages
```

- [ ] **Step 1: Render short thought as normal timeline text**

  Keep thought visible, but avoid oversized blocks and gray-dot mechanical layout if possible within current design.

- [ ] **Step 2: Render tool action labels**

  Use backend-provided action title when available.

- [ ] **Step 3: Show compact result label**

  Use `result_label`, not `items.length`, as the primary result summary.

- [ ] **Step 4: Keep details expandable**

  Parameters/results remain available behind expand, similar to official PageIndex behavior.

- [ ] **Step 5: Web citations**

  Web citation clicks should open the URL, not try to use the document preview panel.

---

## Phase 8: Regression Scenarios

**Files:**
- Test: backend agent tests listed above.
- Test: frontend timeline tests listed above.
- Manual: local browser against `http://localhost:5173`.

- [ ] **Scenario 1: Simple greeting**

  User asks `你好`.

  Expected:
  - no document registry auto-load
  - no unnecessary tool calls
  - quick answer

- [ ] **Scenario 2: Document overview**

  User asks `第一个文档主要讲什么`.

  Expected:
  - browse/structure is enough
  - no repeated page reads unless needed
  - answer cites document/page if page anchors are available

- [ ] **Scenario 3: Deep comparison**

  User asks for deeper comparison across two documents.

  Expected:
  - short thought
  - structure first
  - batch page reads with multi-range page string
  - clear tool action labels
  - final answer streams normally

- [ ] **Scenario 4: Visual page**

  Ask about a page that is image-heavy.

  Expected:
  - `get_page_content` marks `visual_evidence_required`
  - planner calls page image
  - policy does not allow final answer before image evidence

- [ ] **Scenario 5: Search and citation**

  Ask about a specific term in the Chongqing parsed document.

  Expected:
  - search results point to pages
  - page reads use those pages
  - citations bind to actual pages, not arbitrary chunks

- [ ] **Scenario 6: Web Search**

  Ask a current web question with Web Search enabled.

  Expected:
  - web results can be cited
  - clicking web citation opens the source URL
  - no document preview panel for web-only citations

---

## Recommended Commit Sequence

1. Commit Phase 2 only: prompt constraints for short thought.
2. Commit Phase 3 only: page range parser and validation tests.
3. Commit Phase 4 only: tool result labels and action titles.
4. Commit Phase 5 only: OCR/visual evidence semantics.
5. Commit Phase 6 only: planner/policy/answer alignment.
6. Commit Phase 7 only: frontend timeline polish.
7. Final commit: regression tests and documentation updates.

Each commit should include focused tests for the changed behavior.

## Open Questions Before Implementation

- Whether `next_steps` should remain a string only, or allow a compact object with `summary/options`. Current preference: use a short string to save tokens.
- Whether page image evidence should be required for all OCR pages, or only pages marked visual-heavy. Current preference: only visual-heavy pages.
- Whether frontend should visually merge adjacent same-document page reads. Current preference: not in the first pass; clear action titles are enough.

