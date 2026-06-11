# Phase 6 Implementation Report

Date: 2026-06-11

## Executive Summary

Phase 6 implemented the frontend evidence and settings integration planned after the Phase 5.1 backend model-routing closure.

The frontend now surfaces anchor-aware evidence labels, retrieval fallback disclosures, retrieval scope trace metadata, document index quality, explicit chat scope controls, model provider settings, and route mapping controls for the backend route slots introduced in Phase 5 and verified through Phase 5.1.

The phase also added a small backend compatibility endpoint for model provider updates so the UI can update non-secret provider fields while preserving the saved API key state.

Final verification after gap closure:

- Frontend evidence and retrieval-scope utility tests: `9 passed`
- Model settings API focused backend suite: `9 passed`
- Frontend production build: passed
- Full backend suite: `383 passed, 8 skipped`
- Completion gate result: pass, with no P0/P1 gaps

Gap closure completed after the initial report:

- Provider API key replacement now updates the same saved provider instead of creating a duplicate provider.
- Retrieval scope trace display now understands backend `requested_document_ids` and `requested_folder_id` fields.
- Deleting a provider explicitly clears route mappings so affected routes fall back to server defaults without relying on SQLite connection-level foreign-key cascade behavior.
- XLSX preview extraction now reads common `inlineStr` cell values, preserving spreadsheet text in preview blocks and row-range source anchors.
- The index queue regression test now waits for the worker to enter the fake job before asserting start order, removing a real test race observed during full-suite verification.
- Browser smoke verification covered login/register, chat scope controls and evidence preview shell, document empty-state rendering, provider key replacement, and route mapping save via Playwright against local FastAPI/Vite dev servers.

## Scope Completed

### 1. Evidence Labels In Chat And Preview

Implemented capabilities:

- Added a shared frontend evidence label formatter for backend `display_label` and frontend `source_anchor` fallback labels.
- Covered PDF page ranges, text line ranges, DOCX paragraph ranges, spreadsheet row ranges, and PPTX slide labels with Vitest tests.
- Chat messages now collect evidence metadata from streamed tool results and completion payloads.
- Chat answer UI now shows compact evidence chips when `display_label` or `source_anchor` metadata is available.
- Retrieval fallbacks such as `keyword_fallback` and `visual_summary` are disclosed subtly on assistant messages.
- The citation preview subtitle now uses the shared evidence formatter.
- `SourcePreviewDrawer` supports anchor-aware labels while preserving its existing props.
- Preview viewers now emit explicit `unit_type` metadata for line, row, paragraph, and slide anchors.

Key files:

- `frontend/src/utils/evidence.ts`
- `frontend/src/utils/evidence.test.ts`
- `frontend/src/stores/chat.ts`
- `frontend/src/views/ChatView.vue`
- `frontend/src/components/SourcePreviewDrawer.vue`
- `frontend/src/components/preview/TextViewer.vue`
- `frontend/src/components/preview/MarkdownViewer.vue`
- `frontend/src/components/preview/TableViewer.vue`
- `frontend/src/components/preview/DocxViewer.vue`
- `frontend/src/components/preview/PptxViewer.vue`

### 2. Document Quality Display

Implemented capabilities:

- Added frontend `QualityReport` typing.
- Preserved optional `quality_report` metadata in document store types.
- Document preview metadata now shows index quality state.
- `completed`, `needs_review`, failed statuses, unknown statuses, and missing quality reports are handled without breaking preview rendering.
- Concrete warning reasons from `quality_report.warnings` are displayed when present.
- Node count, score, and page range coverage are shown when the backend provides them.

Key files:

- `frontend/src/types/retrieval.ts`
- `frontend/src/stores/document.ts`
- `frontend/src/views/DocumentView.vue`

### 3. Chat Scope Controls And Scope Trace Display

Implemented capabilities:

- Added frontend `ChatScopeRequest` and `RetrievalScopeTrace` types.
- Chat requests can now include:
  - `document_ids`
  - `folder_id`
  - `include_subfolders`
  - `strict_scope`
- Chat UI exposes explicit scope modes:
  - All documents
  - Current folder
  - Folder plus subfolders
  - Selected documents
- Selected documents and folder scopes default to strict scope.
- Assistant messages display available retrieval scope trace metadata.
- Retrieval expansion beyond selected scope is disclosed when `expanded_to_user_library=true`.
- Missing trace metadata falls back to neutral current-scope text.
- Backend `requested_document_ids` and `requested_folder_id` trace fields are normalized for frontend display.

Key files:

- `frontend/src/types/retrieval.ts`
- `frontend/src/api/index.ts`
- `frontend/src/stores/chat.ts`
- `frontend/src/views/ChatView.vue`

### 4. Model Provider Settings UI

Implemented capabilities:

- Added model provider API client methods.
- Settings page now has a Models section.
- Provider settings UI supports:
  - Loading provider presets.
  - Saving provider, base URL, and API key.
  - Displaying saved-key mask without exposing raw API keys.
- Editing non-secret fields while preserving the saved key.
- Replacing an API key only when the user provides a new key.
- Replacing an API key updates the same provider record and does not create a duplicate provider.
- Testing provider connections.
- Deleting providers with fallback disclosure.
- Deleting providers removes route mappings for fallback behavior.
- Displaying validation errors without rendering raw secret values.

Backend compatibility added:

- `PATCH /api/settings/model-providers/{provider_id}` updates provider/base URL fields and replaces `api_key_ciphertext` / `api_key_mask` only when the user provides a new key.
- Regression coverage verifies non-secret updates preserve the saved key mask, key replacement updates the same provider record, and responses never echo the raw API key.

Key files:

- `frontend/src/types/modelSettings.ts`
- `frontend/src/api/index.ts`
- `frontend/src/components/settings/ModelProviderSettings.vue`
- `frontend/src/views/SettingsView.vue`
- `backend/app/api/settings.py`
- `backend/app/services/model_settings_service.py`
- `backend/tests/test_model_settings_api.py`

### 5. Route Mapping Controls

Implemented capabilities:

- Added route mapping UI for all backend route slots:
  - `general_chat`
  - `document_qa`
  - `query_expansion`
  - `indexing`
  - `vision`
- Empty route mappings remain on server defaults.
- The Index generation route is presented as production-backed by the Phase 5.1 verification baseline.
- Vision/OCR route controls expose the existing `supports_vision` flag.
- Route settings reload after provider changes.

Key files:

- `frontend/src/components/settings/ModelRouteSettings.vue`
- `frontend/src/types/modelSettings.ts`
- `frontend/src/api/index.ts`
- `frontend/src/views/SettingsView.vue`

## Product Decisions Preserved

Phase 6 preserved the earlier phase contracts:

- Evidence fields are additive and tolerant of partial backend rollout.
- Backend `display_label` is preferred when present.
- Frontend anchor formatting is used only as fallback.
- Missing quality reports do not break document rendering.
- Missing retrieval scope trace does not break chat rendering.
- Scope expansion is disclosed as metadata, not treated as an error.
- Model provider credentials remain server-side and write-only from the UI perspective.
- Route mappings can fall back to environment defaults.
- Indexing and vision route controls rely on the Phase 5.1 verification baseline.

## Verification Evidence

### Frontend Evidence And Retrieval Scope Tests

```powershell
cd frontend
npm.cmd run test -- src/utils/evidence.test.ts src/utils/retrievalScope.test.ts
```

Result:

```text
9 passed
```

### Model Settings API Focused Suite

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_model_settings_api.py -q
```

Result:

```text
9 passed
```

### Frontend Build

```powershell
cd frontend
npm.cmd run build
```

Result:

```text
vue-tsc and vite build passed
```

### Full Backend Suite

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
383 passed, 8 skipped
```

### Gap Closure And Browser Smoke Verification

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_content_extraction_source_anchors.py backend\tests\test_source_anchor_resolution.py backend\tests\test_source_anchor_resolution_office.py backend\tests\test_multi_format_adapter.py backend\tests\test_model_settings_api.py -q
```

Result:

```text
28 passed
```

Additional focused checks:

- `C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_index_queue.py -q`: `1 passed`
- Live API smoke against `http://127.0.0.1:8000`: provider key replacement kept the same provider and updated the mask; deleting a provider removed its `general_chat` route mapping.
- Playwright smoke against `http://127.0.0.1:5173`: login/register rendered without page errors, chat scope controls and evidence preview shell rendered, Documents empty state rendered, Models tab saved/replaced a provider without duplicating it, and route mapping save persisted `general_chat`.

## Actual Code Scans Performed

The completion audit used real scans rather than memory-based review.

Chat evidence and scope scan:

```powershell
rg -n "chatApi\.stream|sendMessage\(|folder_id|include_subfolders|strict_scope|retrievalScope|retrievalFallbacks|evidenceItems|display_label|source_anchor|retrieval_source" frontend\src
```

Result summary:

- Chat requests can carry explicit scope fields.
- Assistant messages can preserve retrieval scope, fallback, and evidence metadata.
- Evidence chips are derived from `display_label` and `source_anchor`.
- Fallback disclosures are derived from `retrieval_source`.

Quality report scan:

```powershell
rg -n "quality_report|QualityReport|qualityLabel|qualityTone" frontend\src backend\app backend\tests
```

Result summary:

- Frontend types and document preview UI handle optional `quality_report`.
- Backend document APIs already expose `quality_report`.
- Existing backend tests continue to cover quality report generation and API exposure.

Model settings and secret scan:

```powershell
rg -n "model-providers|model-routes|api_key|api_key_mask|api_key_ciphertext|update_provider_config_fields|MODEL_SETTINGS_SECRET" frontend\src backend\app backend\tests
```

Result summary:

- Frontend only submits raw API keys on save/replace.
- Read/list UI displays `api_key_mask`, not raw keys.
- Backend stores ciphertext/mask and exposes non-secret provider config fields.
- PATCH updates non-secret fields while preserving stored key material when no new key is provided, and replaces stored key material when a new key is provided.

Anchor formatter and preview scan:

```powershell
rg -n "formatEvidenceLabel|unit_type:|start_slide|slide:|row_range|paragraph|start_line" frontend\src\utils frontend\src\components\preview frontend\src\views\ChatView.vue
```

Result summary:

- Shared evidence formatter is used by chat and source preview UI.
- Preview components emit explicit unit types for line, row, paragraph, and slide anchors.
- Legacy citation click handling now adds slide unit metadata.

## Completion Gate Result

The Phase 6 completion gate used:

- Latest user request.
- Phase 6 implementation plan.
- Next phase roadmap.
- Prior phase reports and Phase 5.1 execution baseline.
- Current git status and recent commits.
- Current codebase state.
- Fresh frontend and backend verification output.
- Actual `rg` project scans.

Findings:

- P0: none.
- P1: none.
- P2: none recorded as blocking.

Decision:

- Phase 6 can be declared complete under the completion gate because required verification passed and no P0/P1 gaps were found.

## Working Tree Notes

At report time, the working tree includes Phase 6 implementation changes plus pre-existing documentation edits from Phase 5.1 planning/report context.

Notable uncommitted groups:

- Backend model provider update support:
  - `backend/app/api/settings.py`
  - `backend/app/services/model_settings_service.py`
  - `backend/tests/test_model_settings_api.py`
- Frontend Phase 6 integration:
  - `frontend/src/api/index.ts`
  - `frontend/src/stores/chat.ts`
  - `frontend/src/stores/document.ts`
  - `frontend/src/views/ChatView.vue`
  - `frontend/src/views/DocumentView.vue`
  - `frontend/src/views/SettingsView.vue`
  - `frontend/src/components/SourcePreviewDrawer.vue`
  - `frontend/src/components/preview/*Viewer.vue`
  - `frontend/src/components/settings/ModelProviderSettings.vue`
  - `frontend/src/components/settings/ModelRouteSettings.vue`
  - `frontend/src/types/modelSettings.ts`
  - `frontend/src/types/retrieval.ts`
  - `frontend/src/utils/evidence.ts`
  - `frontend/src/utils/evidence.test.ts`
- Documentation context:
  - `docs/superpowers/2026-06-10-next-phase-roadmap.md`
  - `docs/superpowers/plans/2026-06-10-phase-6-frontend-evidence-settings-integration.md`
  - `docs/superpowers/2026-06-11-phase-5-and-5-1-execution-report.md`

Git reported a permission warning while scanning `backend/.pytest-tmp/`; this did not affect implementation or verification.

## Remaining Limitations

The following remain out of scope after Phase 6:

- Full document management production redesign.
- Live provider model discovery.
- Model billing, quotas, provider budgets, or virtual keys.
- Standalone LiteLLM Proxy administration.
- Legacy `.doc`, `.xls`, or `.ppt` conversion UI.
- End-to-end browser-driven manual verification with real uploaded fixtures for every file format.
- Full multi-format adapter migration.

## Recommended Next Phase

Proceed to Phase 7: Multi-Format Adapter Migration.

Recommended focus:

1. Migrate format-specific parsing paths toward the canonical adapter model from Phase 2.
2. Preserve Phase 6 evidence label and source anchor UI contracts.
3. Keep `quality_report`, retrieval scope trace, and route metadata additive.
4. Avoid legacy Office upload support until conversion support exists and is tested.
