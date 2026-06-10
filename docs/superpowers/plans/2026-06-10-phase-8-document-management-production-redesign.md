# Phase 8 Document Management Production Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the document management design direction into production UI while preserving existing workflows and backend contracts.

**Architecture:** Reuse existing document, folder, preview, and context-menu components. Implement the three-column workbench layout, denser document list, compact detail panel, batch mode behavior, and preview modal improvements incrementally, with build verification after each task.

**Tech Stack:** Vue frontend, Vite, Pinia stores, existing API client, `DocumentView.vue`, document and folder components, preview components.

---

## Entry Criteria

Start after Phase 6 if evidence labels and quality fields are already integrated.

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
- Frontend build passes.
- Manual responsive QA is recorded.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Model settings UI.
- Chat UI redesign beyond scope controls and evidence labels.
- Backend parser changes.
- Landing page or marketing redesign.
