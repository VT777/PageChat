# Phase 6 Frontend Evidence And Settings Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface source evidence, index quality, scoped retrieval, and model settings in the frontend without redesigning the whole product at once.

**Architecture:** Integrate stable backend fields from Phases 2-5 into existing Vue views and stores. Keep the document management layout familiar, avoid wholesale copying from the design demo, and make evidence visibility useful without making chat noisy.

**Tech Stack:** Vue frontend, Vite, Pinia stores, existing API client, `ChatView.vue`, `DocumentView.vue`, preview components, Settings view, backend APIs from prior phases.

---

## Entry Criteria

Start after:

- Phase 2 for citation labels and source anchors.
- Phase 3 for quality display.
- Phase 5 for model settings UI.

Phase 4 is recommended if chat scope UI is included.

Phase 6 can be executed in slices. Do not block all frontend evidence work on model settings or chat scope if the required backend fields for a smaller slice are already stable:

| Slice | Required backend baseline |
| --- | --- |
| Evidence labels in chat and preview | Phase 2 source anchors and display labels |
| Document quality display | Phase 3 `quality_report` metadata |
| Chat scope UI | Phase 4 folder/document scope request and trace behavior |
| Model settings UI | Phase 5 settings API and write-only key contract |
| Indexing model controls | Phase 5.1 indexing route closure |

If a slice starts before the later slices are ready, keep API types tolerant of missing fields and record the deferred slices in the completion gate.

Phase 5.1 is now complete and verified. Phase 6 may present index generation model controls as production-backed when those controls use the Phase 5 settings APIs and the route mapping contract verified by:

- `docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md`
- `docs/superpowers/2026-06-11-phase-5-and-5-1-execution-report.md`

## Post-Phase-5.1 Backend Baseline

Phase 5.1 closed the PageIndex indexing-route gap that remained after Phase 5.

Verified backend baseline:

- Phase 5.1 focused backend suite: `25 passed`
- Indexing regression suite: `34 passed, 4 skipped`
- Full backend suite after Phase 5.1: `379 passed, 8 skipped`
- PageIndex text model calls can use the configured `indexing` route when user settings exist.
- PageIndex vision enrichment can use the configured `vision` route when user settings exist.
- Tree-search cache keys include route version when model settings affect output.
- Generated index payloads may include sanitized `model_routes` metadata.
- Route metadata must not expose API keys, ciphertext, or provider secrets.

Frontend implication:

- Model route UI may include all backend route slots: `general_chat`, `document_qa`, `query_expansion`, `indexing`, and `vision`.
- The UI should label routes by user-facing tasks, not by raw route keys alone.
- Indexing and vision route controls should clearly explain fallback to server defaults when no user route is configured.

## Execution Slice Priority

Execute Phase 6 in independently verifiable slices:

1. Evidence labels and source preview anchor display.
2. Document quality display.
3. Chat scope controls and retrieval scope trace display.
4. Model provider settings.
5. Route mapping controls for `general_chat`, `document_qa`, `query_expansion`, `indexing`, and `vision`.

Each slice should run `npm.cmd run build` before moving to the next slice. Run backend tests only when frontend API changes reveal a backend contract mismatch or when a backend compatibility patch is required.

## Files And Responsibilities

- Modify: `frontend/src/api/index.ts`
  - Add model settings API methods and chat scope fields.
- Modify or create: `frontend/src/types/preview.ts`
  - Keep `SourceAnchor` in sync with backend anchor fields.
- Modify or create: `frontend/src/types/retrieval.ts`
  - Add retrieval trace, quality report, and chat scope types if no existing type home is more appropriate.
- Modify: `frontend/src/stores/document.ts`
  - Preserve source anchors and quality metadata.
- Modify: `frontend/src/stores/folder.ts`
  - Expose selected folder scope for chat if needed.
- Modify: `frontend/src/views/ChatView.vue`
  - Show source labels and fallback disclosure.
  - Include optional selected scope in chat requests.
- Modify: `frontend/src/views/DocumentView.vue`
  - Show index quality state and warnings.
  - Keep current document management workflow.
- Modify: `frontend/src/components/SourcePreviewDrawer.vue`
  - Display anchor-aware labels.
- Modify: `frontend/src/components/preview/MarkdownViewer.vue`
- Modify: `frontend/src/components/preview/TextViewer.vue`
- Modify: `frontend/src/components/preview/TableViewer.vue`
- Modify: `frontend/src/components/preview/DocxViewer.vue`
- Modify: `frontend/src/components/preview/PptxViewer.vue`
  - Show correct units for line, row, paragraph, and slide anchors.
- Modify: `frontend/src/views/SettingsView.vue`
  - Add Models section.
- Create: `frontend/src/components/settings/ModelProviderSettings.vue`
- Create: `frontend/src/components/settings/ModelRouteSettings.vue`

## UI Principles

- Use existing design language.
- Keep controls dense and work-focused.
- Avoid a marketing-style settings page.
- Do not expose raw config names such as `llm.default_fast_model`.
- API keys are never displayed after saving.
- Saved credentials should be represented as a masked or saved state, not as reusable plaintext.
- Deleting or disabling a provider should make affected route fallback behavior visible.
- Evidence labels should be concise:
  - `report.pdf p.12`
  - `notes.md lines 20-42`
  - `contract.docx paragraphs 10-18`
  - `sales.xlsx Sheet1 rows 2-80`
  - `deck.pptx slide 7`

## Frontend Data Contracts

The frontend should tolerate partial backend rollout:

- Prefer backend `display_label` when present.
- Fall back to formatting `source_anchor` when `display_label` is missing.
- Fall back to the existing page/index label when both `display_label` and `source_anchor` are missing.
- Prefer backend retrieval `scope` trace metadata when present.
- Show neutral current-scope copy when retrieval trace metadata is missing.
- When trace metadata reports expansion beyond the selected scope, disclose that expansion without treating it as an error.
- Treat `quality_report` as optional.
- Treat unknown `quality_report.status` values as neutral metadata, not fatal UI states.
- Preserve existing chat requests when no folder/document scope is selected.

Minimum TypeScript shapes:

```ts
type SourceAnchor = {
  format?: string
  unit_type?: 'page' | 'line' | 'paragraph' | 'row_range' | 'slide' | string
  start_page?: number
  end_page?: number
  start_line?: number
  end_line?: number
  start_paragraph?: number
  end_paragraph?: number
  sheet?: string
  start_row?: number
  end_row?: number
  start_slide?: number
  end_slide?: number
}

type QualityReport = {
  status?: 'completed' | 'needs_review' | 'failed:indexing' | string
  score?: number
  warnings?: string[]
  node_count?: number
  page_range_coverage?: number
}

type RetrievalScopeTrace = {
  folder_id?: string
  folder_path?: string
  include_subfolders?: boolean
  document_ids?: string[]
  strict_scope?: boolean
  expanded_to_user_library?: boolean
  retrieval_mode?: string
  recommended_next_action?: string
}
```

## API And UI Acceptance Matrix

Model provider settings must cover these states:

| Scenario | Expected frontend behavior |
| --- | --- |
| List presets | Show curated provider choices and allow custom OpenAI-compatible configuration when supported. |
| Create provider config | Save provider, base URL when applicable, model IDs, and API key without echoing raw key back into the UI. |
| Update non-secret fields | Preserve saved-key state unless the user explicitly replaces or clears the key. |
| Replace API key | Require explicit save and return to masked/saved state after success. |
| Delete provider config | Warn that routes using the provider will fall back to server defaults or need remapping. |
| Test connection succeeds | Show success without revealing request payload secrets. |
| Test connection fails | Show provider validation error without exposing raw API key or ciphertext. |
| Production secret unavailable | Show a clear save failure when backend refuses model-key writes. |

Route mapping controls must cover these states:

| Route | User-facing label | Expected behavior |
| --- | --- | --- |
| `general_chat` | General chat | Select a saved provider/model or fallback to server default. |
| `document_qa` | Document Q&A | Select a saved provider/model or fallback to server default. |
| `query_expansion` | Query expansion | Select a saved provider/model or fallback to server default. |
| `indexing` | Index generation | Enabled as production-backed because Phase 5.1 is verified. |
| `vision` | Vision/OCR enrichment | Select a vision-capable provider where the backend marks capability support. |

Evidence and quality UI must cover these sample states:

| Data shape | Expected label or state |
| --- | --- |
| PDF page anchor | `report.pdf p.12-15` |
| Markdown/TXT line anchor | `notes.md lines 20-42` |
| DOCX paragraph anchor | `contract.docx paragraphs 10-18` |
| XLSX row anchor | `sales.xlsx Sheet1 rows 2-80` |
| PPTX slide anchor | `deck.pptx slide 7` |
| `quality_report.status = completed` | Stable completed status. |
| `quality_report.status = needs_review` | Warning state with concrete warning reasons. |
| `quality_report.status = failed:indexing` | Failed indexing state without breaking document detail rendering. |
| Unknown quality status | Neutral metadata state. |
| Missing quality report | Existing document UI remains usable. |

Chat scope UI must cover these states:

| Scope state | Expected behavior |
| --- | --- |
| Current document | Request includes selected document IDs and strict scope unless user expands. |
| Current folder | Request includes `folder_id`; subfolder inclusion is explicit. |
| Folder including subfolders | Request includes `folder_id` and `include_subfolders=true`. |
| All documents | User explicitly chooses all-documents scope. |
| Backend trace reports expansion | UI discloses expansion without treating it as an error. |
| Backend trace missing | UI shows neutral current-scope metadata and preserves answer rendering. |

## Task 1: Evidence Labels In Chat And Preview

**Files:**

- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/components/SourcePreviewDrawer.vue`
- Modify: `frontend/src/components/preview/MarkdownViewer.vue`
- Modify: `frontend/src/components/preview/TextViewer.vue`
- Modify: `frontend/src/components/preview/TableViewer.vue`
- Modify: `frontend/src/components/preview/DocxViewer.vue`
- Modify: `frontend/src/components/preview/PptxViewer.vue`

- [ ] **Step 1: Add frontend label helper**

Create or colocate a helper that formats `source_anchor` the same way as backend labels.

- [ ] **Step 2: Add evidence label tests if frontend test framework exists**

If no frontend test framework is configured, document this as a verification limitation and rely on build plus manual checks.

Manual checks must include examples for page, line, row, paragraph, and slide labels when fixtures are available.

- [ ] **Step 3: Update citation rendering**

Use backend `display_label` when present. Fall back to frontend helper when only `source_anchor` exists.

- [ ] **Step 4: Add fallback disclosure**

If evidence contains `retrieval_source` of `keyword_fallback` or `visual_summary`, show a subtle note.

- [ ] **Step 5: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/ChatView.vue frontend/src/components/SourcePreviewDrawer.vue frontend/src/components/preview
git commit -m "feat: show anchor-aware evidence labels"
```

## Task 2: Document Quality Display

**Files:**

- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/stores/document.ts`
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Add quality fields to types/store**

Support optional:

- `quality_report.status`
- `quality_report.score`
- `quality_report.warnings`
- `quality_report.node_count`
- `quality_report.page_range_coverage`

- [ ] **Step 2: Update detail panel**

Show:

- Completed
- Needs review
- Failed

For `needs_review`, show concrete warning reasons.

- [ ] **Step 3: Keep layout stable**

Do not redesign the whole page. Add quality status inside the existing detail/status area.

- [ ] **Step 4: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/views/DocumentView.vue frontend/src/stores/document.ts frontend/src/api/index.ts
git commit -m "feat: surface document index quality"
```

## Task 3: Chat Scope UI

**Files:**

- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/stores/document.ts`
- Modify: `frontend/src/stores/folder.ts`
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Add chat request scope type**

Support:

- `folder_id`
- `include_subfolders`
- `document_ids`
- `strict_scope`

- [ ] **Step 2: Show current scope compactly**

Examples:

- Current document
- Current folder
- Folder including subfolders
- All documents

- [ ] **Step 3: Display retrieval scope trace when available**

Use backend trace metadata to show what scope the answer actually used:

- Selected document scope.
- Selected folder scope.
- Folder plus descendants.
- Expanded current-user library scope when `expanded_to_user_library=true`.
- Unknown or missing trace as neutral current-scope metadata.

- [ ] **Step 4: Add explicit all-documents option**

Avoid silently expanding from selected folder/document to all documents.

- [ ] **Step 5: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/ChatView.vue frontend/src/stores/document.ts frontend/src/stores/folder.ts frontend/src/api/index.ts
git commit -m "feat: add chat retrieval scope controls"
```

## Task 4: Model Settings UI

**Files:**

- Modify: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/api/index.ts`
- Create: `frontend/src/components/settings/ModelProviderSettings.vue`
- Create: `frontend/src/components/settings/ModelRouteSettings.vue`

- [ ] **Step 1: Add API client methods**

Add methods for:

- Provider presets.
- Provider config list/create/update/delete.
- Test connection.
- Route mapping read/update.
- Error responses for failed provider validation.
- Safe handling for masked saved-key state.

- [ ] **Step 2: Build provider settings component**

Fields:

- Provider preset.
- API key input.
- Base URL for custom providers.
- Model IDs.
- Test connection.
- Masked saved key state.
- Validation error state.
- Delete/reset behavior that makes route fallback explicit.

- [ ] **Step 3: Build route settings component**

Route slots:

- General chat.
- Document Q&A.
- Query expansion.
- Index generation, backed by the verified Phase 5.1 indexing-route baseline.
- Vision/OCR.

- [ ] **Step 4: Integrate into SettingsView**

Use grouped settings, not low-level config names.

- [ ] **Step 5: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/SettingsView.vue frontend/src/api/index.ts frontend/src/components/settings
git commit -m "feat: add model settings interface"
```

## Task 5: Final Verification And Completion Gate

- [ ] **Step 1: Run frontend build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 2: Run backend regression if API types changed**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 3: Manual verification**

Check:

- Chat answer citations show correct units.
- Source preview opens for page, line, row, paragraph, and slide anchors where supported.
- `needs_review` documents show concrete warnings.
- Model settings save without displaying raw saved keys.
- Provider test failures show clear errors without exposing raw keys.
- Route mappings fall back to environment defaults after a provider is deleted or disabled.
- Chat scope can be switched explicitly.
- Chat answers disclose when retrieval expanded beyond the selected document or folder scope.
- Missing scope trace metadata does not break existing chat rendering.

- [ ] **Step 4: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 6 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-core-tree-retrieval-quality-plan.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-user-configurable-models.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-frontend-design-plan.md`
- Current git status.
- Build output and any backend test output from Steps 1-3.

## Done Criteria

Phase 6 is complete when:

- Chat and preview show anchor-aware labels.
- Retrieval fallback is disclosed subtly when present.
- Document detail shows quality status and warnings.
- Chat request can carry explicit retrieval scope.
- Chat UI can display retrieval scope trace and expansion metadata when the backend provides it.
- Settings page supports model provider and route configuration.
- API keys are write-only from UI perspective.
- Frontend build passes.
- Backend tests pass if APIs changed.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Full document management redesign.
- New landing page or marketing UI.
- Model billing, quotas, or proxy administration.
- Legacy Office conversion UI.
