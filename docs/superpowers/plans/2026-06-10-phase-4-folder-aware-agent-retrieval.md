# Phase 4 Folder-Aware Agent Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make document Q&A follow a reliable folder -> document -> structure -> evidence flow while preserving current tool compatibility.

**Architecture:** Add folder-aware search scope and folder navigation tools before introducing a lightweight retrieval planner. Keep `find_related_documents` for compatibility, extend it with explicit scope fields, and keep the existing Agent loop as fallback while deterministic retrieval paths mature.

**Tech Stack:** FastAPI backend, `FolderService`, `DocumentService`, `DocumentSearchService`, `ToolExecutor`, `AgentService`, `ChatService`, pytest.

---

## Entry Criteria

Start this phase after Phase 2 is complete. Phase 3 is recommended but not strictly blocking.

Required:

- Search/tool outputs include source anchors and display labels.
- User and allowed document scope remains mandatory and tested.
- Folder metadata exists in search segment metadata.

## Files And Responsibilities

- Modify: `backend/app/services/search_service.py`
  - Add `folder_id`, `folder_path`, and `include_subfolders` filtering.
- Modify: `backend/app/services/tool_executor.py`
  - Add `list_folder_tree`.
  - Add `list_folder_contents`.
  - Extend `find_related_documents` scope inputs.
- Modify: `backend/app/services/folder_service.py`
  - Provide compact folder tree and contents helpers if existing methods are insufficient.
- Modify: `backend/app/services/agent_service.py`
  - Pass selected folder/document scope into tool execution.
  - Keep Agent fallback.
- Modify: `backend/app/services/chat_service.py`
  - Accept and forward optional chat scope.
- Modify: `backend/app/models/schemas.py`
  - Add request/response fields for chat scope if needed.
- Modify: `backend/app/prompts/__init__.py`
  - Teach the Agent folder-first retrieval policy.
- Create: `backend/app/services/retrieval_planner.py`
  - Add lightweight deterministic first-step planner.
- Create: `backend/tests/test_folder_search_scope.py`
- Create: `backend/tests/test_folder_tools.py`
- Create: `backend/tests/test_scope_aware_find_related_documents.py`
- Create: `backend/tests/test_compact_tree_structure.py`
  - Test hierarchy-preserving, text-free structure output for agent retrieval.
- Create: `backend/tests/test_retrieval_planner.py`

## Scope Contract

Chat and tools should understand:

```json
{
  "folder_id": "folder-1",
  "include_subfolders": true,
  "document_ids": ["doc-1"],
  "strict_scope": true
}
```

Rules:

- `user_id` remains mandatory.
- `document_ids` narrows current user scope.
- `folder_id` narrows current user scope.
- `strict_scope=true` means do not search outside selected documents/folder.
- `strict_scope=false` allows current-user expansion only, never cross-user access.

## Task 1: Add Folder-Aware Search Filtering

**Files:**

- Modify: `backend/app/services/search_service.py`
- Create: `backend/tests/test_folder_search_scope.py`

- [ ] **Step 1: Write failing tests**

Cover:

- Search within one folder excludes sibling folders.
- `include_subfolders=true` includes descendants.
- `include_subfolders=false` excludes descendants.
- `allowed_doc_ids` still narrows folder results.
- Renaming a folder updates descendant `documents.folder_path`.
- Moving a folder updates descendant `documents.folder_path`.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_search_scope.py -q
```

- [ ] **Step 3: Add folder filters to search API**

Add optional parameters:

```python
folder_id: str | None = None
folder_path: str | None = None
include_subfolders: bool = False
```

Filter candidate segments before scoring.

- [ ] **Step 4: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_search_scope.py tests/test_search_scope.py tests/test_folder_delete_cleanup.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/search_service.py backend/tests/test_folder_search_scope.py
git commit -m "feat: add folder-scoped document search"
```

## Task 2: Add Folder Tools

**Files:**

- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/folder_service.py`
- Modify: `backend/app/prompts/__init__.py`
- Create: `backend/tests/test_folder_tools.py`

- [ ] **Step 1: Write failing folder tool tests**

Cover:

- `list_folder_tree` returns only current user's folders.
- `list_folder_contents` returns compact child folders and documents.
- Pagination works for contents.
- Cross-user folders are not returned.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_tools.py -q
```

- [ ] **Step 3: Implement executor methods**

Add tools:

- `list_folder_tree`
- `list_folder_contents`

Return compact metadata only:

- folder id, name, path, parent id, child counts
- document id, name, file type, status, page count, description, updated time

- [ ] **Step 4: Update prompt catalog**

Describe folder-first behavior when users mention a folder, category, current library, or selected scope.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_tools.py tests/test_tools_prompt_catalog.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/tool_executor.py backend/app/services/folder_service.py backend/app/prompts/__init__.py backend/tests/test_folder_tools.py
git commit -m "feat: add folder navigation tools"
```

## Task 3: Extend `find_related_documents` Scope

**Files:**

- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/search_service.py`
- Create: `backend/tests/test_scope_aware_find_related_documents.py`

- [ ] **Step 1: Write failing tests**

Cover:

- Explicit `document_ids` defaults to strict scope.
- Explicit `folder_id` defaults to strict scope.
- `strict_scope=false` allows current-user expansion.
- Returned matched segments include actionable anchors.
- `recommended_next_action` is present.

- [ ] **Step 2: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_scope_aware_find_related_documents.py -q
```

- [ ] **Step 3: Extend tool schema and executor**

Add inputs:

- `folder_id`
- `include_subfolders`
- `document_ids`
- `strict_scope`

Keep query-only compatibility.

- [ ] **Step 4: Add recommended next action**

Use:

- `get_page_content` when page/anchor hints are strong.
- `get_document_structure` when document confidence is strong but page hints are weak.
- `list_folder_contents` when folder is relevant but document confidence is weak.
- `ask_user` when confidence is low and no fallback is safe.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_scope_aware_find_related_documents.py tests/test_find_related_documents_modes.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/tool_executor.py backend/app/services/search_service.py backend/tests/test_scope_aware_find_related_documents.py
git commit -m "feat: make related document search scope-aware"
```

## Task 4: Add Compact Tree Structure Output

**Files:**

- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/pageindex_service.py` if shared tree helpers are needed
- Create: `backend/tests/test_compact_tree_structure.py`

- [ ] **Step 1: Write failing compact tree tests**

Cover:

- `get_document_structure` can return a hierarchy-preserving compact tree for agent retrieval.
- Compact nodes include `node_id`, `title`, `start_page` or anchor, `end_page` or anchor, `summary`, and `children`.
- Compact nodes do not include full `text`.
- Existing preview-facing structure behavior remains compatible.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_compact_tree_structure.py -q
```

- [ ] **Step 3: Implement compact tree helper**

Add a helper such as:

```python
def build_compact_structure(index_payload: dict) -> list[dict]:
    ...
```

Preserve hierarchy. Do not flatten unless the caller explicitly requests a flat compatibility shape.

- [ ] **Step 4: Wire into tool output**

Add a mode or internal branch for agent retrieval that returns the compact tree.

Do not break any frontend preview API that expects current structure fields.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_compact_tree_structure.py tests/test_tool_executor_scope.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/tool_executor.py backend/app/services/pageindex_service.py backend/tests/test_compact_tree_structure.py
git commit -m "feat: add compact tree structure output"
```

## Task 5: Add Lightweight Retrieval Planner

**Files:**

- Create: `backend/app/services/retrieval_planner.py`
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/services/chat_service.py`
- Create: `backend/tests/test_retrieval_planner.py`

- [ ] **Step 1: Write planner tests**

Cover:

- Selected document question -> inspect structure first.
- Selected folder question -> folder-scoped search.
- Global question -> current-user search.
- Table/statistics query -> table aggregation route.
- Low confidence -> Agent fallback.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_retrieval_planner.py -q
```

- [ ] **Step 3: Implement planner dataclasses**

Add:

- `RetrievalPlan`
- `RetrievalStep`
- `RetrievalRoute`

- [ ] **Step 4: Implement route detection**

Keep it deterministic and conservative.

Do not remove the Agent loop. Planner should prepare the first retrieval step and pass evidence to existing answer generation.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_retrieval_planner.py tests/test_folder_tools.py tests/test_scope_aware_find_related_documents.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/retrieval_planner.py backend/app/services/agent_service.py backend/app/services/chat_service.py backend/tests/test_retrieval_planner.py
git commit -m "feat: add lightweight retrieval planner"
```

## Task 6: Final Verification And Completion Gate

- [ ] **Step 1: Run focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_search_scope.py tests/test_folder_tools.py tests/test_scope_aware_find_related_documents.py tests/test_compact_tree_structure.py tests/test_retrieval_planner.py tests/test_search_scope.py tests/test_tool_executor_scope.py -q
```

- [ ] **Step 2: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 3: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 4 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-agent-retrieval-improvement-plan.md`
- Current git status.
- Test output from Steps 1-2.

## Done Criteria

Phase 4 is complete when:

- Search supports folder and subfolder scope.
- Folder tools are available and user-scoped.
- `find_related_documents` supports explicit scope while preserving query-only compatibility.
- Folder rename and move keep document folder metadata consistent.
- `get_document_structure` has a compact hierarchy-preserving, text-free output for agent retrieval.
- Agent prompt describes folder-first retrieval.
- Lightweight retrieval planner handles common routes and keeps Agent fallback.
- Focused and full backend tests pass.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Full frontend chat scope UI.
- Removing `find_related_documents`.
- Replacing the Agent loop entirely.
- Distributed or persistent retrieval cache infrastructure.
