# Phase 1 Improvement Report

Date: 2026-06-10

## Executive Summary

Phase 1 established the safety, scope, cache, migration, and retrieval trace foundation needed before larger product work such as configurable model providers, richer multi-format retrieval, frontend redesign, or retrieval planner changes.

The main outcome is that document access is now user-scoped and fail-closed, cache entries are separated by user and retrieval scope, retrieval results expose source trace metadata, uploaded files use safe storage names, folder deletion cleans related artifacts, and the backend has a lightweight migration path. Phase 1.1 then closed the remaining gaps around tree-reasoning trace metadata, agent message-state invalidation, table aggregation rejection reporting, stable JWT signing configuration, and two backend regression failures.

Fresh verification after Phase 1.1:

- Focused Phase 1 backend suite: `43 passed`
- Full backend suite: `271 passed, 8 skipped`
- Frontend build compatibility: passed from `frontend/` with `npm.cmd run build`

## What Changed

### 1. Database Migration Foundation

Phase 1 added a lightweight SQLite migration system and connected it to the existing database bootstrap path.

Implemented capabilities:

- `schema_migrations` records applied migrations.
- Migrations are idempotent.
- `documents.last_reindex_at` is added for future reindex scheduling and invalidation flows.
- Core indexes were added for user/document/folder/conversation query paths.
- SQLite foreign key enforcement is enabled for app connections.

Effect:

- Future backend phases can evolve schema deliberately instead of relying only on `CREATE TABLE IF NOT EXISTS`.
- User-scoped and folder-scoped queries have better database support.
- Reindex-oriented work now has a place to store document-level timing state.

### 2. Safe Upload Filename Handling

Phase 1 hardened uploaded filename handling and storage-path generation.

Implemented capabilities:

- Rejects path separators, path traversal names, null/control characters, and Windows reserved filenames.
- Preserves original display names as metadata.
- Stores source files using generated safe names such as `{doc_id}{extension}`.

Effect:

- Uploads can no longer influence filesystem paths through crafted filenames.
- Storage paths are predictable and independent of user-controlled display names.
- Later file-processing work can treat `file_path` as a safe internal path.

### 3. Retrieval Scope And Source Anchor Models

Phase 1 introduced shared retrieval models and source label helpers.

Implemented capabilities:

- `RetrievalScope` requires `user_id`.
- `allowed_doc_ids=None` means all documents owned by that user.
- `allowed_doc_ids=[]` means no documents are allowed.
- Scope cache keys differ by user and allowed document set.
- Source label helpers format anchors for PDF pages, text lines, DOCX paragraphs, spreadsheet rows, and slides.

Effect:

- Later retrieval features have a common language for user scope and source locations.
- Display labels such as `report.pdf p.12-15` are generated consistently.
- Scope can be passed through services without relying on ad hoc argument conventions.

### 4. Tool Access Is Fail-Closed

Phase 1 made `ToolExecutor` require explicit user scope and pass that scope into document reads.

Implemented capabilities:

- `ToolExecutor` cannot be constructed without `user_id`.
- Document structure, page content, document images, listing, table aggregation, and related-document search all operate under the current user.
- `allowed_doc_ids` narrows access but does not grant cross-user access.
- `allowed_doc_ids=[]` produces no accessible documents.

Effect:

- Agent tool calls no longer default to global document access.
- Direct tool paths reject cross-user document access.
- Chat and agent paths now share the same scoped access boundary.

### 5. User-Scoped Search

Phase 1 made document search require user scope and filter candidates before scoring.

Implemented capabilities:

- `DocumentSearchService.search()` requires `user_id`.
- Search candidates are filtered by user before BM25/rerank scoring.
- `allowed_doc_ids` is applied within the user's documents.
- Query expansion cache is user-aware.
- ToolExecutor passes user and allowed document scope into search.

Effect:

- Search results cannot leak other users' documents through global index state.
- Query expansion cache entries no longer collide across users.
- Retrieval behavior is now aligned with the same authorization model as tool access.

### 6. User-Aware Cache Keys

Phase 1 changed document-derived caches to include user scope.

Implemented capabilities:

- Structure cache keys include `user_id`.
- Page-content cache keys include `user_id`.
- Search-result cache keys include `user_id`.
- Agent per-conversation tool cache includes retrieval scope.
- Cache invalidation can clear entries for a specific user/document pair.

Effect:

- Same `doc_id` or query text under different users no longer collides in memory.
- Reusing a conversation with different document scope is less likely to reuse stale tool results.
- Cache behavior now matches the scoped retrieval model.

### 7. Retrieval Trace Metadata

Phase 1 added additive retrieval trace fields to search and fallback paths, and Phase 1.1 closed the remaining tree-reasoning gap.

Implemented capabilities:

- `document_search`, `keyword_fallback`, `visual_summary`, and `tree_reasoning` paths expose trace fields:
  - `retrieval_source`
  - `confidence`
  - `why_selected`
  - `source_anchor`
  - `display_label`
- Tool output propagates retrieval metadata into related documents and matched segments.
- Existing compatibility fields such as `start_index`, `end_index`, `relevance`, and `reasoning` were preserved.

Effect:

- The frontend and agent answer layer can explain where evidence came from.
- Later citation-quality and answer-grounding work can rely on a common metadata contract.
- Retrieval results are easier to debug because source type and selection rationale are explicit.

### 8. Folder And Document Deletion Cleanup

Phase 1 hardened document and folder deletion cleanup; Phase 1.1 extended it to agent message state.

Implemented capabilities:

- Folder deletion collects affected documents before DB row deletion.
- Source files and index files are removed.
- Default index paths are also cleaned when applicable.
- Document-derived caches are invalidated.
- Agent tool-result cache and message history are cleared after successful document or folder removal.

Effect:

- Deleted documents no longer leave active files, indexes, or cache entries behind.
- Agent conversations are less likely to answer from stale deleted-document state.
- Cleanup now covers both storage artifacts and process-local retrieval memory.

### 9. Table Aggregation Scope Feedback

Phase 1.1 improved `aggregate_tables` behavior for partial document participation.

Implemented capabilities:

- Requested IDs outside `allowed_doc_ids` are reported in `rejected_document_ids`.
- Requested IDs absent from the current user's indexed documents are also reported.
- A generic quality note explains that some requested document IDs were inaccessible or unavailable.
- Inaccessible document names or metadata are not returned.

Effect:

- The agent can explain partial table aggregation without silently omitting requested inputs.
- Users get actionable feedback while authorization boundaries remain intact.

### 10. Stable JWT Secret Configuration

Phase 1.1 moved JWT signing secret configuration out of import-time randomness.

Implemented capabilities:

- `JWT_SECRET` is read from `JWT_SECRET` or `SECRET_KEY`.
- Local/test fallback is stable across restarts.
- `auth.py` imports the configured secret instead of generating one with `secrets.token_hex()`.

Effect:

- Tokens are no longer invalidated every time the auth module is re-imported or the server restarts.
- Deployment configuration has a clear environment-backed path.
- Production enforcement is still a future task because no production-mode flag currently exists.

### 11. Regression Fixes

Phase 1.1 fixed two full-suite regressions found after the initial Phase 1 pass.

Implemented capabilities:

- ISO-like date titles such as `2026-01-14` are treated as noise before title normalization strips the year.
- The agent system prompt again includes the expected `【工具列表】` heading while preserving the current tool catalog content.

Effect:

- TOC quality repair no longer promotes date-only titles.
- Prompt catalog tests guard that tool definitions are injected under the expected heading.

## Verification Evidence

Focused Phase 1 backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_database_migrations.py tests/test_safe_upload_filenames.py tests/test_retrieval_models.py tests/test_tool_executor_scope.py tests/test_search_scope.py tests/test_cache_scope_keys.py tests/test_retrieval_trace_contract.py tests/test_folder_delete_cleanup.py tests/test_find_related_documents_modes.py tests/test_multi_format_adapter.py tests/test_table_analysis_service.py -q
```

Result:

```text
43 passed
```

Full backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
271 passed, 8 skipped
```

Frontend compatibility build:

```powershell
cd frontend
npm.cmd run build
```

Result:

```text
vite build completed successfully
```

Note: the root-level command `npm.cmd run build` fails because the repository root does not contain `package.json`; the frontend package is under `frontend/`.

## Planning Impact

Phase 1 turns several previously implicit assumptions into explicit contracts:

- Every retrieval/tool/search path must know the current `user_id`.
- `allowed_doc_ids` only narrows user-owned documents.
- Cache keys must include user and, where relevant, document scope.
- Retrieval results should carry trace metadata without removing legacy fields.
- File storage paths must not be derived directly from user filenames.
- Schema changes should go through idempotent migrations.

This means later plans can focus on capability expansion instead of repeatedly solving authorization, cache isolation, source citation, and migration basics.

## Remaining Limitations

These are intentionally not solved in Phase 1:

- Production-mode enforcement for missing `JWT_SECRET`.
- Persistent or distributed cache infrastructure.
- Targeted document-to-conversation reverse indexing for agent cache invalidation.
- Full multi-format parser rewrite or canonical adapter package.
- Legacy `.doc`, `.xls`, `.ppt` conversion.
- User-configurable model provider settings and BYOK persistence.
- Frontend production redesign.
- New retrieval planner or replacement of `find_related_documents`.
- Rich citation quality scoring and `needs_review` document status.

## Recommended Next Phases

### Phase 2: User-Configurable Model Foundation

Recommended scope:

- Add model provider/runtime settings persistence.
- Add encrypted API key storage or a clear local-only development alternative.
- Introduce model route/version into retrieval and query expansion cache keys.
- Enforce missing secrets in production once an environment mode exists.

Why now:

- Phase 1 already stabilized user scope, migrations, and cache key patterns.
- Model settings can now be added without making retrieval cache behavior ambiguous.

### Phase 3: Multi-Format Retrieval Expansion

Recommended scope:

- Promote canonical source anchors for DOCX, XLSX/CSV, PPTX, TXT/Markdown.
- Add parser-specific tests for row/paragraph/slide/line anchors.
- Extend retrieval trace coverage for table-schema and adapter-native retrieval paths.
- Decide how legacy Office formats are converted or rejected.

Why now:

- Source-anchor and display-label contracts already exist.
- Search and tool access are now user-scoped, reducing leakage risk during format expansion.

### Phase 4: Retrieval Quality And Planner Work

Recommended scope:

- Improve query planning and candidate selection.
- Add quality scoring for retrieval evidence.
- Define when `needs_review` or equivalent quality status should be persisted.
- Add answer-level citation validation using retrieval trace metadata.

Why now:

- Retrieval outputs now include enough metadata to evaluate why a source was chosen.
- Search and tree-reasoning paths share common trace fields.

### Phase 5: Frontend Production Redesign

Recommended scope:

- Surface source anchors and display labels in answer UI.
- Show inaccessible/missing document feedback for table aggregation.
- Improve document management workflows around deletion, upload errors, and scoped search.
- Align frontend build command/documentation with the `frontend/` package location.

Why now:

- Backend contracts for scoped retrieval, cache invalidation, and trace metadata are stable enough for UI work.

## Suggested Immediate Follow-Ups

1. Add production environment detection and fail startup when `JWT_SECRET` is missing in production.
2. Document the correct frontend build command as `cd frontend; npm.cmd run build`.
3. Add a document-to-conversation index if targeted agent cache invalidation becomes important.
4. Decide legacy `NULL user_id` migration policy before importing or exposing old documents.
5. Convert this report into the source context for the next implementation plan.

