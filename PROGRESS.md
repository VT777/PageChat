# PageChat Agent Tool Contract PROGRESS

> **For agentic workers:** implement this task phase by phase. Update this file before and after each phase. Each phase must end with focused tests, a short progress entry, and a git commit.

**Goal:** Make PageChat agent tools reliable, compact, and easier for the model to use by standardizing model-visible tool results, string `next_steps`, error propagation, and document id resolution.

**Architecture:** Tool executors may keep rich internal raw results, but the agent loop and UI trace should consume a compact model view. `get_document_structure` is the explicit exception: it should return the complete deep hierarchy for the requested document, preserving nested children. Other tools should expose only actionable fields.

**Tech Stack:** FastAPI backend, SQLite, PageIndex service, pytest, Vue/Vitest frontend trace components.

---

## Current Requirements

- `next_steps` remains a short string list, not structured action objects.
- `get_document_structure` returns the complete deep tree.
- Other tools should save tokens by exposing compact model-visible fields only.
- Errors must remain visible to the model and UI; never compress an execution error into `0 results`.
- Document references must normalize file names, `doc_name`, and `doc_id` into canonical `doc_id`.
- Each implementation phase must include tests, a commit, and a short entry in this file.
- Do not use subagents for this work.

## Model-Visible Result Shape

Common model view:

```json
{
  "success": true,
  "status": "ok | empty | partial | error",
  "summary": "short actionable summary",
  "doc_id": "canonical document id when relevant",
  "doc_name": "display document name when relevant",
  "items": [],
  "citations": [],
  "next_steps": [
    "Use get_page_content(doc_id='...', pages='...') before answering."
  ],
  "error": null
}
```

Keep hidden from the model unless explicitly needed: local file paths, index paths, user ids, cache metadata, raw OCR text for visual pages, embedding/rerank scores, full document text, and large empty fields.

## Phase Plan

### Phase 1: Preserve Tool Errors and Compact Results

**Task:** Update compact result handling so `success=false`, `status=error`, `error`, `summary`, and `next_steps` survive into tool trace and planner evidence.

**Likely files:**
- `backend/app/agent/nodes.py`
- `backend/app/agent/loop_runtime.py`
- `backend/tests/test_agent_run_event_protocol.py`
- `backend/tests/test_agent_navigation_tools_contract.py`

**Tests:**
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_run_event_protocol.py backend/tests/test_agent_navigation_tools_contract.py -q`

**Commit message:** `fix(agent): preserve tool errors in compact results`

### Phase 2: Canonical Document Reference Resolution

**Task:** Make document tools resolve `doc_id`, `doc_name`, and accidental filename-in-`doc_id` inputs to a canonical document id. Ambiguous or missing references should return visible recoverable errors with short `next_steps`.

**Likely files:**
- `backend/app/services/tool_executor.py`
- `backend/tests/test_tool_executor_scope.py`
- `backend/tests/test_agent_navigation_tools_contract.py`

**Tests:**
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_executor_scope.py backend/tests/test_agent_navigation_tools_contract.py -q`

**Commit message:** `fix(agent): normalize document references for tools`

### Phase 3: Per-Tool Model Views and String next_steps

**Task:** Standardize compact model-visible results for all tools. Keep `get_document_structure` as a complete deep tree. Ensure other tools return short fields and 2-3 concise `next_steps` strings.

**Likely files:**
- `backend/app/services/tool_executor.py`
- `backend/app/services/document_keyword_locator.py`
- `backend/app/services/web_search_tool.py`
- `backend/app/agent/citations.py`
- `backend/tests/test_agent_navigation_tools_contract.py`
- `backend/tests/test_web_search_tool_contract.py`

**Tests:**
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_web_search_tool_contract.py backend/tests/test_agent_citation_bindings.py -q`

**Commit message:** `feat(agent): standardize compact tool model views`

### Phase 4: Planner and Policy Consumption

**Task:** Give the planner a compact document registry and teach policy to reject or repair invalid document references. Planner should use visible errors and `next_steps` instead of repeating bad calls.

**Likely files:**
- `backend/app/agent/planner.py`
- `backend/app/agent/policy.py`
- `backend/app/services/chat_service.py`
- `backend/tests/test_agent_loop_runtime.py`
- `backend/tests/test_agent_run_event_protocol.py`

**Tests:**
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_run_event_protocol.py backend/tests/test_agent_navigation_tools_contract.py -q`

**Commit message:** `feat(agent): guide planner with compact tool context`

### Phase 5: Integration Regression

**Task:** Run the real document scenario and frontend trace checks. Verify the Chongqing Normal University case follows `browse_documents -> search_within_document -> get_page_content -> answer` with a page citation.

**Likely files:**
- Backend tests added or adjusted in previous phases.
- Frontend trace tests only if event shape changes.

**Tests:**
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_agent_run_event_protocol.py backend/tests/test_agent_citation_bindings.py backend/tests/test_tool_executor_scope.py backend/tests/test_web_search_tool_contract.py -q`
- `cd frontend; npm.cmd exec -- vitest run src/components/chat/RunTimeline.contract.test.ts src/views/ChatView.contract.test.ts`
- `cd frontend; npm.cmd run build`

**Commit message:** `test(agent): cover tool contract integration`

## Progress Log

### 2026-06-26 Phase 0: Plan Created

**Current phase task:** Define implementation phases and progress process.

**Completed:** Created this PROGRESS plan. Captured the simplified `next_steps` rule, compact model-view boundary, full deep-tree exception for `get_document_structure`, and per-phase test/commit requirements.

**Tests:** Not run; documentation-only planning step.

**Next step:** Start Phase 1 by writing failing tests for tool error preservation, then implement minimal compact-result changes.

### 2026-06-26 Phase 1: Preserve Tool Errors and Compact Results

**Current phase task:** Preserve `success=false`, `status=error`, `error`, and string `next_steps` in compact tool results and observations.

**Completed:** Added regression tests for compact result errors and observation messages. Updated compact result handling and observation building so tool execution errors are visible instead of appearing as empty search results.

**Tests:** Passed `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_run_event_protocol.py backend/tests/test_agent_navigation_tools_contract.py -q` (`27 passed`).

**Next step:** Start Phase 2 by normalizing document references across `doc_id`, `doc_name`, and accidental filename-in-`doc_id` inputs.

### 2026-06-26 Phase 2: Canonical Document Reference Resolution

**Current phase task:** Resolve canonical document ids when tools receive `doc_id`, `doc_name`, or a file name accidentally passed as `doc_id`.

**Completed:** Added tests for filename-in-`doc_id` recovery and unknown-document recoverable errors. Updated document resolution so exact file names can resolve to the unique accessible document and missing/ambiguous references return visible `status=error` results with short `next_steps`.

**Tests:** Passed `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_executor_scope.py backend/tests/test_agent_navigation_tools_contract.py -q` (`28 passed`).

**Next step:** Start Phase 3 by standardizing compact model-visible results and concise string `next_steps` for each tool while keeping `get_document_structure` as a complete deep tree.
