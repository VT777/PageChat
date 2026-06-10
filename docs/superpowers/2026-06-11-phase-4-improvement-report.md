# Phase 4 Improvement Report

Date: 2026-06-11

Push verification: 2026-06-11 Asia/Shanghai

## Executive Summary

Phase 4 extended document Q&A from single-document retrieval toward explicit folder-aware and scope-aware retrieval.

The main outcome is that chat requests can now carry folder and scope metadata, search can filter by folder and descendants, agent tools can navigate folder trees and folder contents, `find_related_documents` can honor explicit document/folder scope, and the Agent has a deterministic first-step retrieval planner before falling back to the existing function-calling loop.

Fresh verification after Phase 4:

- Phase 4 focused backend suite: `45 passed`
- Full backend suite: `342 passed, 8 skipped`
- Pushed commit: `f219756 feat: add folder-aware agent retrieval`
- Branch: `vt_0610 -> origin/vt_0610`

## What Changed

### 1. Chat Scope Contract

Phase 4 added explicit chat scope fields to the request path.

Implemented capabilities:

- Added optional `folder_id`, `include_subfolders`, and `strict_scope` to `ChatRequest`.
- Forwarded scope from `backend/app/api/chat.py` into `ChatService`.
- Forwarded scope from `ChatService` into `AgentService`.
- Preserved compatibility for existing `document_ids`-only chat requests.

Effect:

- The backend can distinguish selected-document, selected-folder, mixed, strict, and expandable retrieval scopes.
- `strict_scope=true` keeps retrieval inside the selected documents or folder.
- `strict_scope=false` allows current-user library expansion without crossing user boundaries.

### 2. Folder-Aware Search Filtering

Phase 4 extended `DocumentSearchService.search()` with folder filters.

Implemented capabilities:

- Added `folder_id`, `folder_path`, `include_subfolders`, and `document_ids` filtering.
- Intersects `document_ids`, `folder_id`, and `allowed_doc_ids` rather than treating any one as widening access.
- Supports descendant matching through folder path prefixes when `include_subfolders=true`.
- Added regression coverage for sibling exclusion, descendant inclusion/exclusion, allowed-doc narrowing, document/folder intersection, folder rename path updates, and folder move path updates.

Effect:

- Search can now operate inside a folder scope without leaking sibling-folder documents.
- Explicit folder search remains inside the current user's document library.
- Folder rename and move keep document `folder_path` metadata aligned for later scoped search.

### 3. Folder Navigation Tools

Phase 4 added compact folder navigation tools to `ToolExecutor`.

Implemented tools:

- `list_folder_tree`
- `list_folder_contents`

Returned metadata includes:

- Folder id, name, path, parent id, child count, document count.
- Document id, name, file type, status, page count, folder path, description, updated time.
- Pagination fields for folder contents.

Effect:

- The Agent can inspect folder structure before deciding which documents to search.
- Folder tools return metadata only, not full document text.
- Missing or unauthorized `folder_id` values now produce a clear error instead of silently returning an empty result.
- Tool descriptions are readable UTF-8 text, so the model can reliably select them.

### 4. Scope-Aware `find_related_documents`

Phase 4 extended `find_related_documents` while preserving query-only compatibility.

Implemented inputs:

- `folder_id`
- `include_subfolders`
- `document_ids`
- `strict_scope`

Implemented outputs:

- `scope` trace metadata.
- `retrieval_mode`.
- `recommended_document_ids`.
- `recommended_next_action`.
- Existing matched segment anchors and labels remain available.

Effect:

- Explicit document and folder scopes default to strict scope.
- `strict_scope=false` records `expanded_to_user_library=true`.
- `allowed_doc_ids` remains a hard authorization boundary and cannot be widened.
- Tool output now tells the Agent whether to inspect structure, fetch source content, aggregate tables, inspect folder contents, or ask the user.

### 5. Compact Tree Structure Output

Phase 4 added a compact, hierarchy-preserving structure mode for agent retrieval.

Implemented capabilities:

- `get_document_structure` accepts `compact=true`.
- Compact nodes preserve hierarchy through `children`.
- Compact nodes include `node_id`, `title`, page range, summary, optional `source_anchor`, and children.
- Compact output excludes full text.
- Default preview-facing structure behavior remains flat and compatible.

Effect:

- The Agent can inspect document structure without pulling large full-text payloads into context.
- Phase 3 `quality_report` metadata is surfaced in compact structure output when present.
- Weak quality reports such as `needs_review` produce retrieval guidance that tells the Agent to verify against source content before final claims.

### 6. Lightweight Retrieval Planner

Phase 4 added `backend/app/services/retrieval_planner.py`.

Implemented capabilities:

- Added `RetrievalPlan`, `RetrievalStep`, and `RetrievalRoute`.
- Routes selected single-document questions to compact structure inspection first.
- Routes folder-scoped questions to folder-scoped related-document search.
- Routes global questions to current-user related-document search.
- Routes table/statistics questions through a search-first table aggregation path.
- Keeps Agent fallback when the question is empty or the deterministic route is insufficient.

Effect:

- Common retrieval paths now start with deterministic, testable tool selection.
- The existing function-calling Agent loop remains in place as fallback.
- Planner evidence is added to model history as normal assistant context, not as an orphan `tool` message, preserving chat message protocol validity.

### 7. Agent Prompt Policy

Phase 4 updated the Agent prompt policy.

Implemented capabilities:

- The prompt now states that folder/category/library/current-scope mentions should use folder navigation before scoped document search.
- Existing tree-first selected-document behavior remains intact.

Effect:

- Prompt behavior now matches the new backend tool surface.
- The model has explicit guidance to resolve folder scope before searching content.

## Verification Evidence

Phase 4 focused backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_folder_search_scope.py tests/test_folder_tools.py tests/test_scope_aware_find_related_documents.py tests/test_compact_tree_structure.py tests/test_retrieval_planner.py tests/test_search_scope.py tests/test_tool_executor_scope.py tests/test_chat_scope_contract.py tests/test_agent_retrieval_planner_integration.py -q
```

Result:

```text
45 passed, 44 warnings
```

Full backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
342 passed, 8 skipped, 83 warnings
```

Commit and push:

```text
f219756 feat: add folder-aware agent retrieval
```

Branch:

```text
vt_0610 -> origin/vt_0610
```

## Manual Scenario Checklist For Follow-Up Phases

These scenarios should be reused during Phase 6 frontend scope and evidence integration. They are not a replacement for the automated Phase 4 suite, but they define the user-visible behavior that the UI should preserve.

- Current-folder strict scope: ask a question from a selected folder and confirm sibling-folder documents are not used.
- Current-folder with descendants: ask with `include_subfolders=true` and confirm matching child-folder documents can be used.
- Selected-document strict scope: ask with selected `document_ids` and confirm unrelated current-user documents are not used.
- Expandable scope: ask with `strict_scope=false` and confirm expansion stays inside the current user's library and records `expanded_to_user_library=true` in scope trace metadata.
- Folder-only chat request: send a request with `folder_id` and no `document_ids`; the Agent should enter retrieval instead of simple chat.
- Invalid or unauthorized folder: request folder contents or folder-scoped retrieval with an invalid `folder_id`; the response should be clear not-found/access-denied behavior, not silent empty evidence.
- Weak tree quality: when compact structure includes a weak `quality_report`, the Agent should verify source content before making final claims.

## Gap Closure Notes

During completion review, four issues were found and closed before push.

Closed issues:

- Folder-only chat requests were initially routed to simple chat because `document_ids` was absent. The Agent now enters retrieval when an explicit folder scope is present.
- `strict_scope=false` was initially blocked by selected-document `allowed_doc_ids` at the executor boundary. The executor now allows current-user expansion while preserving hard allowed-doc authorization when strict scope is active.
- Planner evidence was initially appended as an orphan `tool` message. It is now appended as normal assistant context.
- New folder tool descriptions initially contained mojibake text. They are now readable UTF-8 descriptions.

Additional closure:

- Compact structure now surfaces `quality_report` and retrieval guidance so weak tree quality is not silently treated as fully reliable.
- Invalid folder content scopes now return clear not-found/access-denied errors.

The gap closure plan is recorded in:

```text
docs/superpowers/plans/2026-06-11-phase-4-gap-closure.md
```

## Planning Impact

Phase 4 changes the backend assumption from "chat scope is mainly a selected document list" to "chat scope is an explicit retrieval boundary."

Later phases should assume:

- `folder_id`, `include_subfolders`, `document_ids`, and `strict_scope` are the canonical chat scope fields.
- `scope` trace metadata is the canonical way to show whether retrieval expanded beyond selected scope.
- Folder tools are available for Agent planning but the frontend scope UI is still out of scope until Phase 6.
- Compact tree output is the preferred Agent-facing structure mode.
- `quality_report` can influence Agent retrieval guidance before the frontend displays it.

## Remaining Limitations

These are intentionally not solved in Phase 4:

- Full frontend chat scope picker UI.
- Frontend display of scope trace, fallback evidence, and quality report.
- Removing or replacing `find_related_documents`.
- Removing the existing Agent loop.
- Deep multi-format adapter migration.
- Persistent retrieval planner state or distributed retrieval cache.
- Production analytics for scope usage or quality trends.

### Follow-Up Ownership

| Limitation | Follow-up owner |
| --- | --- |
| Frontend chat scope picker | Phase 6: frontend evidence and settings integration |
| Display scope trace and quality report | Phase 6 |
| Model/settings UI | Phase 5 backend foundation, Phase 6 frontend |
| Full multi-format adapter migration | Phase 7 |
| Document management production redesign | Phase 8 |
| Retrieval analytics and dashboards | Future operations/observability phase |

## Recommended Next Phases

### Phase 5: User-Configurable Model Foundation

Recommended scope:

- Add backend model configuration ownership and validation.
- Preserve user, scope, and model-route cache boundaries.
- Do not expose saved user API keys back to the frontend.

Why next:

- Phase 4 stabilized retrieval scope semantics. Model configuration can now be added without changing retrieval authorization or scope behavior.

### Phase 6: Frontend Evidence And Settings Integration

Recommended scope:

- Expose chat scope controls for selected folders/documents.
- Display `quality_report`, source labels, fallback evidence, and expansion trace metadata.
- Keep unknown or missing metadata neutral.

Why next for UI:

- Phase 4 provides the backend fields and tool behavior needed for a useful scope-aware frontend.
