# Phase 4 Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each behavior fix. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Phase 4 gaps so folder-aware chat scope works through the real Agent path, scope expansion is explicit and correct, folder tools are readable to the model, and quality metadata influences retrieval guidance.

**Architecture:** Keep the current Phase 4 shape: `ChatRequest` forwards scope to `ChatService`, `AgentService` builds the tool executor and deterministic first retrieval step, `ToolExecutor` performs scoped search/tool calls, and `FolderService` provides compact metadata. Fix the integration boundaries instead of replacing the agent loop.

**Tech Stack:** FastAPI backend, `AgentService`, `ToolExecutor`, `FolderService`, `DocumentSearchService`, pytest.

---

## Task 1: Real Chat Scope Entry

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_agent_retrieval_planner_integration.py`

- [ ] Write failing tests proving folder-only chat does not enter simple chat and selected-document `strict_scope=false` uses a user-library executor boundary.
- [ ] Run the targeted tests and verify the expected failures.
- [ ] Change `AgentService.run_agent_stream()` so simple chat is used only when there is no usable document library and no explicit retrieval scope.
- [ ] Make the executor authorization boundary distinguish selected-document narrowing from strict allowed documents. `strict_scope=false` may expand within the current user library, while explicit `allowed_doc_ids` remains narrower.
- [ ] Run targeted tests.

## Task 2: Planner Evidence Message Contract

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_agent_retrieval_planner_integration.py`

- [ ] Write a failing test proving planner evidence is added to model history as a normal assistant/context message, not as an orphan `tool` message.
- [ ] Run the targeted test and verify failure.
- [ ] Add a helper that formats planner evidence for history without violating tool-call message ordering.
- [ ] Run targeted tests.

## Task 3: Folder Tool Readability And Folder ID Validation

**Files:**
- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/folder_service.py`
- Test: `backend/tests/test_folder_tools.py`

- [ ] Write failing tests for readable folder tool descriptions and missing/unauthorized folder content responses.
- [ ] Run targeted tests and verify failures.
- [ ] Replace mojibake descriptions with readable UTF-8 text.
- [ ] Validate requested folder ownership before returning contents.
- [ ] Run targeted tests.

## Task 4: Quality-Aware Retrieval Guidance

**Files:**
- Modify: `backend/app/services/tool_executor.py`
- Test: `backend/tests/test_compact_tree_structure.py` or `backend/tests/test_scope_aware_find_related_documents.py`

- [ ] Write failing tests showing weak `quality_report.status = needs_review` is surfaced in compact structure and changes the recommended next action away from silent trust.
- [ ] Run targeted tests and verify failures.
- [ ] Include `quality_report` in compact structure output and adjust guidance to disclose/verify weak structure.
- [ ] Run targeted tests.

## Task 5: Verification

- [ ] Run Phase 4 focused backend suite.
- [ ] Run full backend suite if focused suite is clean.
- [ ] Record remaining non-blocking gaps, if any.
