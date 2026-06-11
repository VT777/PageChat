# Phase 8 Document Management Production Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the document management design direction into production UI while preserving existing workflows and backend contracts.

**Architecture:** Reuse existing document, folder, preview, and context-menu components. Implement the three-column workbench layout, denser document list, compact detail panel, batch mode behavior, and preview modal improvements incrementally, with build verification after each task.

**Tech Stack:** Vue frontend, Vite, Pinia stores, existing API client, `DocumentView.vue`, document and folder components, preview components.

---

## Entry Criteria

Start after Phase 7 is complete or explicitly accepted as the current baseline.

Required baselines:

- Phase 6 evidence labels, retrieval scope controls, settings integration, and optional `quality_report` display are available.
- Phase 7 canonical non-PDF adapters, canonical preview extraction, and source-anchor labels are available.
- Phase 7 legacy Office decision is preserved: `.doc`, `.xls`, and `.ppt` remain rejected unless Phase 7b conversion support is implemented and tested first.

Required backend fields should be confirmed before implementing the right detail panel:

- Uploader.
- Uploaded time.
- Updated time.
- Pages or word count.
- Index mode.
- Processing duration.
- Last indexed time.
- TOC node count.
- Summary coverage.
- Text character count.
- OCR page count.
- Full document summary.
- Optional `quality_report`.

If some fields are unavailable, implement graceful placeholders and record backend follow-ups.

Before editing production UI, record a field availability matrix for:

- `backend/app/models/schemas.py`
- `backend/app/api/documents.py`
- `frontend/src/stores/document.ts`
- `frontend/src/api/index.ts`
- `frontend/src/views/DocumentView.vue`

Classify each desired detail-panel field as:

- Available from document list response.
- Available from document preview/detail response.
- Derivable from existing index metadata.
- Missing and covered by a placeholder.
- Missing and requiring a backend follow-up.

Before visual implementation, prepare sample states for QA:

- Long file name.
- Long folder path.
- Long document summary.
- Missing optional metadata fields.
- `completed`, `needs_review`, `indexing`, and error statuses.
- Batch mode with multiple selected documents.

## Files And Responsibilities

- Modify: `frontend/src/views/DocumentView.vue`
  - Main production document management layout.
- Modify: `frontend/src/components/document/FileTypeIcon.vue` only if needed
  - Preserve file type color language.
- Modify: `frontend/src/components/folder/FolderTree.vue` only if needed
  - Keep folder navigation compatible.
- Modify: `frontend/src/components/document/DocumentContextMenu.vue` only if needed
  - Preserve row actions.
- Modify: `frontend/src/components/preview/UniversalPreview.vue`
  - Keep preview modal source-only behavior.
- Modify: `frontend/src/components/PdfReferenceViewer.vue` only if needed
  - Preserve PDF preview.
- Modify: `frontend/src/stores/document.ts`
  - Support list state, batch selection, current folder stats, and detail metadata.
- Modify: `frontend/src/stores/folder.ts`
  - Support selected folder state and counts if needed.
- Modify: `frontend/src/api/index.ts`
  - Add missing document metadata fields if backend exposes them.

## Task 0: Entry Audit And Field Matrix

**Files:**

- Read: `backend/app/models/schemas.py`
- Read: `backend/app/api/documents.py`
- Read: `frontend/src/stores/document.ts`
- Read: `frontend/src/api/index.ts`
- Read: `frontend/src/views/DocumentView.vue`

- [ ] **Step 1: Confirm current baselines**

Record that Phase 6 frontend contracts and Phase 7 canonical preview/source-anchor contracts are the starting point for the redesign.

- [ ] **Step 2: Build the document metadata matrix**

For each desired detail-panel field, record whether it is available from the list response, preview/detail response, derived index metadata, or unavailable.

- [ ] **Step 3: Decide placeholder behavior**

For unavailable fields, define neutral placeholders and backend follow-ups. Do not invent values in the UI.

- [ ] **Step 4: Preserve no-regression constraints**

List the existing document workflows and preview/source-label behaviors that Task 1 through Task 4 must preserve.

## Task 1: Three-Column Workbench Layout

**Files:**

- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/stores/document.ts`
- Modify: `frontend/src/stores/folder.ts`

- [ ] **Step 1: Identify current layout dependencies**

Read current `DocumentView.vue`, document store, and folder store before editing.

- [ ] **Step 2: Preserve existing workflows**

List workflows that must still work:

- Search.
- Upload.
- Folder selection.
- Sort.
- Batch mode.
- List/grid toggle if already present.
- Pagination.
- Preview.
- Reindex.
- Delete.
- Move.

- [ ] **Step 3: Implement three-column layout**

Columns:

- Left: folder list.
- Center: document list.
- Right: document detail.

Keep the top toolbar:

- Back action.
- Page title.
- Search.
- Upload.

- [ ] **Step 4: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/views/DocumentView.vue frontend/src/stores/document.ts frontend/src/stores/folder.ts
git commit -m "feat: add document workbench layout"
```

## Task 2: Dense Document List And Batch Mode

**Files:**

- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/stores/document.ts`
- Modify: `frontend/src/components/document/DocumentContextMenu.vue` if needed

- [ ] **Step 1: Implement status strip**

Non-batch mode should show:

- Current folder document count.
- Recent update time.
- Active indexing task count.

- [ ] **Step 2: Implement stable row structure**

Each document row should show:

- File type icon.
- File name.
- Folder/type/size metadata.
- Summary.
- Status.
- Page count.
- Updated time.
- Owner.
- Hover actions.

- [ ] **Step 3: Implement batch mode without layout jump**

Reserve checkbox space in both modes.

Batch strip actions:

- Select current page.
- Clear selection.
- Move.
- Reindex.
- Delete.

- [ ] **Step 4: Keep page size stable**

Use 6 documents per page for the current list design unless existing pagination constraints require another value.

- [ ] **Step 5: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/DocumentView.vue frontend/src/stores/document.ts frontend/src/components/document/DocumentContextMenu.vue
git commit -m "feat: refine document list and batch mode"
```

## Task 3: Compact Detail Panel

**Files:**

- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/stores/document.ts`

- [ ] **Step 1: Add detail sections**

Order:

1. Document identity.
2. Basic attributes.
3. Index status.
4. Full document summary.
5. Actions.

- [ ] **Step 2: Add index status metrics**

Show available fields:

- Current state.
- Index mode.
- Processing duration.
- Last indexed time.
- Progress line.
- TOC node count.
- Summary coverage.
- Text character count.
- OCR page count.
- Index usability note.

- [ ] **Step 3: Make only summary body scroll**

The right detail panel should fit the default page height. If summary is long, only summary body scrolls.

- [ ] **Step 4: Add actions**

Actions:

- Open preview.
- Reindex.

Buttons must not overflow the right panel.

- [ ] **Step 5: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/views/DocumentView.vue frontend/src/stores/document.ts
git commit -m "feat: add compact document detail panel"
```

## Task 4: Preview Modal Behavior

**Files:**

- Modify: `frontend/src/components/preview/UniversalPreview.vue`
- Modify: `frontend/src/components/TocTree.vue` if used by preview
- Modify: `frontend/src/components/document/TocTree.vue` if used by document module

- [ ] **Step 1: Preserve modal preview**

Do not replace the modal with a full page.

- [ ] **Step 2: Keep original content clean**

Right side should show original document content only.

Node summaries should not appear in the original-content area.

- [ ] **Step 3: Add TOC summary hover**

Show node summaries through hover popovers on TOC nodes.

- [ ] **Step 4: Run build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/preview/UniversalPreview.vue frontend/src/components/TocTree.vue frontend/src/components/document/TocTree.vue
git commit -m "feat: refine document preview modal"
```

## Task 5: Visual QA And Completion Gate

- [ ] **Step 1: Run frontend build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 2: Manual responsive QA**

Check:

- Desktop default viewport.
- Narrow desktop.
- Mobile width if supported by current app shell.
- Text does not overflow buttons or panels.
- Batch mode does not squeeze row content.
- Detail panel actions do not overflow.
- Preview modal shows source content only.
- Long file names and folder paths truncate or wrap cleanly.
- Long summaries scroll only inside the intended summary area.
- Switching between batch and non-batch mode does not change row height or squeeze primary metadata.
- Empty, loading, error, and no-selection states are visually stable.

Capture screenshots or recorded QA notes for:

- Document list with normal data.
- Document list with long names/paths.
- Right detail panel with long summary.
- Batch mode.
- Preview modal.
- Narrow viewport.

- [ ] **Step 3: Run backend tests only if API fields changed**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 4: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 8 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-3-improvement-report.md`
- `docs/superpowers/2026-06-11-phase-4-improvement-report.md`
- `docs/superpowers/plans/2026-06-11-phase-4-gap-closure.md`
- `docs/superpowers/2026-06-11-phase-5-and-5-1-execution-report.md`
- `docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md`
- `docs/superpowers/2026-06-11-phase-6-implementation-report.md`
- `docs/superpowers/2026-06-11-phase-7-implementation-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-frontend-design-plan.md`
- Current git status.
- Build output, manual QA notes, and any backend test output from Steps 1-3.

## Done Criteria

Phase 8 is complete when:

- Document management uses the production three-column workbench layout.
- Document list is dense, stable, and supports non-batch and batch states.
- File type colors follow existing `FileTypeIcon.vue` language.
- Detail panel shows identity, attributes, index status, full summary, and actions.
- Preview modal keeps TOC on the left and original content on the right.
- Phase 6 evidence labels and Phase 7 canonical preview/source-anchor labels are not regressed.
- The field availability matrix records real, derived, placeholder, and backend-follow-up fields.
- Frontend build passes.
- Manual responsive QA is recorded with screenshots or explicit notes for the required states.
- Long text, batch mode, and detail-panel scrolling are verified against overflow and layout-shift regressions.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Model settings UI.
- Chat UI redesign beyond scope controls and evidence labels.
- Backend parser changes.
- Landing page or marketing redesign.
