# Phase 1.1 Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining Phase 1 safety, scope, retrieval trace, cache invalidation, and regression gaps found during the post-implementation scan.

**Architecture:** Keep Phase 1 behavior intact and patch only the uncovered edges. Add missing retrieval trace metadata to the tree-reasoning path, clear all agent state after document removal, expose rejected table document IDs without broadening access, move JWT signing to stable environment-backed configuration, and fix the two currently failing backend regressions.

**Tech Stack:** FastAPI backend, aiosqlite/SQLite, existing `PageIndexService`, `AgentService`, `DocumentService`, `FolderService`, `ToolExecutor`, `app.core.config`, pytest, current prompt catalog helpers.

---

## Why This Plan Exists

Phase 1 focused verification passes, but a second scan found four remaining plan gaps and two unrelated backend test failures:

- `PageIndexService.search_in_structure_async()` does not add `retrieval_source`, `confidence`, `source_anchor`, `display_label`, and `why_selected` to LLM-selected `tree_reasoning` results.
- `clear_conversation_cache()` clears `_CONVERSATION_CACHES` but leaves `_CONVERSATION_MESSAGES`.
- `FolderService.delete_folder()` clears document-derived caches but does not clear agent conversation state.
- `ToolExecutor._aggregate_tables()` safely skips out-of-scope document IDs, but does not report rejected IDs or explain partial participation.
- `backend/app/api/auth.py` still generates a new `JWT_SECRET` at import time.
- Full backend suite currently fails in `test_toc_quality_repair.py::test_noise_title_detects_short_acronym` and `test_tools_prompt_catalog.py::test_agent_prompt_injects_latest_tool_catalog`.

This is a gap-closure plan, not a new feature phase. Do not introduce a new retrieval planner, new auth system, frontend redesign, or model-provider settings UI here.

## Current Verification Baseline

Focused Phase 1 suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_database_migrations.py tests/test_safe_upload_filenames.py tests/test_retrieval_models.py tests/test_tool_executor_scope.py tests/test_search_scope.py tests/test_cache_scope_keys.py tests/test_retrieval_trace_contract.py tests/test_folder_delete_cleanup.py tests/test_find_related_documents_modes.py tests/test_multi_format_adapter.py tests/test_table_analysis_service.py -q
```

Expected current result: `40 passed`.

Full backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Current result before Phase 1.1: `2 failed, 265 passed, 8 skipped`.

## Files And Responsibilities

- Modify: `backend/app/services/pageindex_service.py`
  - Add missing retrieval trace fields to the LLM-selected `tree_reasoning` branch in `search_in_structure_async()`.
- Modify: `backend/tests/test_retrieval_trace_contract.py`
  - Add a focused contract test for `tree_reasoning` results.
- Modify: `backend/app/services/agent_service.py`
  - Make `clear_conversation_cache()` clear both tool-result cache and message-history cache.
- Modify: `backend/app/services/document_service.py`
  - Keep document deletion calling the central agent cache clear helper.
- Modify: `backend/app/services/folder_service.py`
  - Clear agent cache after successful folder deletion affects documents.
- Modify: `backend/tests/test_folder_delete_cleanup.py`
  - Add coverage for clearing agent caches and message history after folder deletion.
- Modify: `backend/app/services/tool_executor.py`
  - Report rejected/unavailable document IDs from `aggregate_tables`.
- Modify: `backend/tests/test_tool_executor_scope.py`
  - Cover rejected table document IDs.
- Modify: `backend/app/core/config.py`
  - Add stable JWT secret configuration.
- Modify: `backend/app/api/auth.py`
  - Read JWT signing secret from config instead of generating it on import.
- Create or modify: `backend/tests/test_auth_config.py`
  - Cover configured JWT secret behavior without weakening development defaults.
- Modify: `backend/app/services/pageindex_service.py`
  - Fix date-like noise title detection.
- Modify: `backend/tests/test_toc_quality_repair.py`
  - Keep the existing failing test as the guard.
- Modify: `backend/app/prompts/__init__.py`
  - Restore prompt tool catalog heading expected by tests while preserving current prompt content.
- Modify: `backend/tests/test_tools_prompt_catalog.py`
  - Keep existing prompt catalog assertions as the guard.

---

### Task 1: Add Tree-Reasoning Retrieval Trace Fields

**Files:**
- Modify: `backend/app/services/pageindex_service.py:4429`
- Modify: `backend/tests/test_retrieval_trace_contract.py`

- [ ] **Step 1: Write the failing trace test**

Add a test that stubs `async_chat_completion()` and `verify_candidate_nodes()` so `search_in_structure_async()` returns one LLM-selected node. Assert the result includes:

```python
assert result["retrieval_source"] == "tree_reasoning"
assert result["confidence"] == result["relevance"]
assert result["why_selected"] == result["reasoning"]
assert result["source_anchor"]["unit_type"] == "page"
assert result["display_label"]
```

- [ ] **Step 2: Run the focused test and verify it fails**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_retrieval_trace_contract.py -q
```

Expected: FAIL because the LLM-selected branch lacks the new trace fields.

- [ ] **Step 3: Add minimal implementation**

In `PageIndexService.search_in_structure_async()`, when appending the LLM-selected result, merge:

```python
relevance = item.get("relevance_score", 0.5)
reasoning = item.get("reasoning", "")
**self._retrieval_trace_fields(
    doc_name,
    node.get("start_index"),
    node.get("end_index"),
    relevance,
    "tree_reasoning",
    reasoning or "Selected by tree reasoning.",
)
```

Keep existing fields such as `reasoning`, `relevance`, `start_index`, and `end_index`.

- [ ] **Step 4: Run the focused test and verify it passes**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_retrieval_trace_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/tests/test_retrieval_trace_contract.py
git commit -m "fix: add tree reasoning retrieval trace"
```

---

### Task 2: Clear Agent Message State After Deletions

**Files:**
- Modify: `backend/app/services/agent_service.py:34`
- Modify: `backend/app/services/folder_service.py:477`
- Modify: `backend/tests/test_folder_delete_cleanup.py`

- [ ] **Step 1: Write failing cache cleanup tests**

Add tests that seed both agent globals:

```python
from app.services import agent_service

agent_service._CONVERSATION_CACHES["conv:scope:tool"] = {"old": True}
agent_service._CONVERSATION_MESSAGES["conv:scope"] = [{"role": "assistant", "content": "old"}]
```

Assert `clear_conversation_cache()` removes both dictionaries.

Add a folder deletion test that seeds both dictionaries, deletes a folder containing a document, and asserts both dictionaries are empty after deletion.

- [ ] **Step 2: Run the cleanup tests and verify they fail**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_delete_cleanup.py -q
```

Expected: FAIL because `_CONVERSATION_MESSAGES` is not cleared and folder deletion does not call the helper.

- [ ] **Step 3: Update `clear_conversation_cache()`**

In `backend/app/services/agent_service.py`, clear both global stores.

For a specific `conversation_id`, delete keys from both dictionaries when:

```python
key == conversation_id or key.startswith(f"{conversation_id}:")
```

For no `conversation_id`, clear both dictionaries.

- [ ] **Step 4: Clear agent state from folder deletion**

In `FolderService.delete_folder()`, after affected documents have been cleaned and document-derived caches have been invalidated, call:

```python
from app.services.agent_service import clear_conversation_cache

clear_conversation_cache()
```

Only call it when deletion will commit successfully. A broad clear is acceptable for Phase 1.1 because the existing helper is process-local and document-to-conversation reverse indexing does not exist.

- [ ] **Step 5: Run tests and verify they pass**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_delete_cleanup.py tests/test_cache_scope_keys.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/agent_service.py backend/app/services/folder_service.py backend/tests/test_folder_delete_cleanup.py
git commit -m "fix: clear agent state after document removal"
```

---

### Task 3: Report Rejected Table Document IDs

**Files:**
- Modify: `backend/app/services/tool_executor.py:737`
- Modify: `backend/tests/test_tool_executor_scope.py`

- [ ] **Step 1: Write the failing table scope test**

Add a test where `ToolExecutor(user_id="user-a", allowed_doc_ids=["doc-a"])` receives:

```python
document_ids=["doc-a", "doc-b", "missing-doc"]
```

Assert:

```python
assert result["data"]["document_count"] == 1
assert result["data"]["rejected_document_ids"] == ["doc-b", "missing-doc"]
assert any("not accessible" in note.lower() for note in result["data"]["quality_notes"])
```

- [ ] **Step 2: Run the test and verify it fails**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_tool_executor_scope.py -q
```

Expected: FAIL because rejected IDs are silently skipped.

- [ ] **Step 3: Add minimal rejected-ID reporting**

In `_aggregate_tables()`, track:

```python
rejected_document_ids = []
```

Append any requested ID when it is outside `allowed_doc_ids` or absent from `doc_map`.

Return it in `data` for both empty and non-empty selected cases:

```python
"rejected_document_ids": rejected_document_ids,
```

Add a quality note only when the list is non-empty. Do not include document names for inaccessible documents.

- [ ] **Step 4: Run table scope tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_tool_executor_scope.py tests/test_table_analysis_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/tool_executor.py backend/tests/test_tool_executor_scope.py
git commit -m "fix: report rejected table document ids"
```

---

### Task 4: Move JWT Secret To Environment Configuration

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/auth.py:19`
- Create or modify: `backend/tests/test_auth_config.py`

- [ ] **Step 1: Write failing config tests**

Add tests that verify:

```python
assert isinstance(config.JWT_SECRET, str)
assert len(config.JWT_SECRET) >= 32
```

If the project has an environment mode flag, add a production-mode test that fails when `JWT_SECRET` is missing. If no such mode exists, do not invent a new production settings system in this task; just add a clear TODO comment in the plan follow-up section.

- [ ] **Step 2: Run auth config tests and verify they fail or expose current behavior**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py -q
```

Expected: FAIL if the test imports `app.api.auth.JWT_SECRET` and detects import-time randomness or missing config.

- [ ] **Step 3: Add config-backed secret**

In `backend/app/core/config.py`, add:

```python
JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY")
if not JWT_SECRET:
    JWT_SECRET = "dev-only-change-me-page-chat-jwt-secret"
```

Use a stable development fallback only for local/test behavior. Do not generate a random secret at import time.

- [ ] **Step 4: Update auth module**

In `backend/app/api/auth.py`, remove `import secrets` if unused and import:

```python
from app.core.config import DATA_DIR, JWT_SECRET
```

Keep `JWT_ALGORITHM` and `JWT_EXPIRATION_DAYS` local unless they already exist in config.

- [ ] **Step 5: Run auth-related tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py tests/test_auth_api.py -q
```

If `tests/test_auth_api.py` does not exist, run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests -q -k "auth or jwt"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/config.py backend/app/api/auth.py backend/tests/test_auth_config.py
git commit -m "fix: use stable jwt secret configuration"
```

---

### Task 5: Fix Current Full-Suite Regressions

**Files:**
- Modify: `backend/app/services/pageindex_service.py:555`
- Modify: `backend/app/prompts/__init__.py:69`
- Existing tests: `backend/tests/test_toc_quality_repair.py`
- Existing tests: `backend/tests/test_tools_prompt_catalog.py`

- [ ] **Step 1: Reproduce the two failures**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_toc_quality_repair.py::test_noise_title_detects_short_acronym tests/test_tools_prompt_catalog.py::test_agent_prompt_injects_latest_tool_catalog -q
```

Expected: FAIL.

- [ ] **Step 2: Fix date-like noise titles**

In `PageIndexService._is_noise_title()`, treat ISO-like dates as noise:

```python
if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", stripped):
    return True
```

Place this near other short/noise identifier checks. Do not mark all numeric titles as noise if existing tests rely on numeric section titles.

- [ ] **Step 3: Restore the prompt catalog heading**

In `build_agent_system_prompt()`, ensure the rendered prompt includes the exact heading:

```text
【工具列表】
```

Keep existing tool catalog content and existing additional constraints.

- [ ] **Step 4: Run regression tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_toc_quality_repair.py tests/test_tools_prompt_catalog.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/app/prompts/__init__.py
git commit -m "fix: restore backend regression tests"
```

---

### Task 6: Final Verification Sweep

**Files:**
- No code changes expected.

- [ ] **Step 1: Run Phase 1 focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_database_migrations.py tests/test_safe_upload_filenames.py tests/test_retrieval_models.py tests/test_tool_executor_scope.py tests/test_search_scope.py tests/test_cache_scope_keys.py tests/test_retrieval_trace_contract.py tests/test_folder_delete_cleanup.py tests/test_find_related_documents_modes.py tests/test_multi_format_adapter.py tests/test_table_analysis_service.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Expected: PASS except already-known skips.

- [ ] **Step 3: Run frontend build compatibility check**

From repository root:

```powershell
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 4: Inspect git status**

```powershell
git status --short
```

Expected: only intended Phase 1.1 changes are present.

- [ ] **Step 5: Commit verification-only updates if any**

Usually no commit is needed here. If test snapshots or documentation were intentionally updated:

```powershell
git add <intended-files>
git commit -m "test: verify phase 1.1 gap closure"
```

---

## Done Criteria

Phase 1.1 is complete when:

- `tree_reasoning`, `keyword_fallback`, `visual_summary`, and `document_search` paths all expose retrieval trace metadata.
- Deleting a document or folder clears document-derived caches and agent conversation/message state.
- Table aggregation reports inaccessible or missing requested document IDs without leaking metadata.
- JWT signing secret is stable across restarts and comes from configuration.
- The two current full-suite failures are fixed.
- Phase 1 focused backend suite passes.
- Full backend suite passes.
- Frontend build passes.

## Out Of Scope

- Building the model-provider settings UI.
- Adding BYOK provider persistence.
- Rewriting retrieval planning or folder traversal.
- Implementing full multi-format Phase 1 beyond regression safety.
- Redesigning frontend screens.
- Replacing process-local caches with distributed cache infrastructure.

## Follow-Up Notes

- If production environment detection already exists, enforce missing `JWT_SECRET` as a startup error in production during Task 4.
- If production environment detection does not exist, leave enforcement for the user-configurable models foundation phase and keep Phase 1.1 limited to stable config-backed secrets.
- Agent cache invalidation remains broad. A future phase can add document-to-conversation indexing for targeted invalidation.
