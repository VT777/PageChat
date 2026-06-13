# Phase 8.1 Audit Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining audit gaps after Phase 8 so the document workbench preserves search state during polling, keeps the legacy Office support boundary honest in the frontend, and removes user-visible mojibake from production UI paths.

**Architecture:** Keep the Phase 8 document workbench layout intact. Patch narrowly at the frontend state, preview, citation, and UI-copy boundaries; do not reopen backend parser work or add legacy Office conversion. Add focused tests for state preservation and support-boundary helpers, then run the normal frontend and backend verification gates.

**Tech Stack:** Vue 3, Pinia, Vite/Vitest, FastAPI backend contracts, existing document/preview/chat components.

---

## Why This Plan Exists

The post-Phase-8 audit found that the main roadmap has been implemented and verified, but three concrete gaps remain:

- The current frontend no longer includes the visual demo baseline from the 2026-06-10 frontend design work, and production screens have drifted from that design direction.
- The document store does not persist the active search query for polling, so a processing-status refresh can replace filtered search results with an unfiltered page.
- The backend still rejects legacy `.doc`, `.xls`, and `.ppt`, but frontend preview/citation paths still treat those extensions as supported.
- Several user-visible strings in frontend preview and TOC paths are mojibake, which makes the production UI feel broken even when behavior is technically correct.

This plan is a gap-closure slice. It must not add legacy Office conversion, redesign the document workbench, change backend upload allowlists, or refactor the canonical adapter layer.

## Current Verification Baseline

Latest audit verification from 2026-06-11:

- Focused backend suite: `54 passed`
- Full backend suite from `backend/`: `412 passed, 8 skipped`
- Frontend tests from `frontend/`: `14 passed`
- Frontend production build from `frontend/`: passed
- `git diff --check -- frontend/src backend/app backend/tests docs/superpowers`: no whitespace errors, LF/CRLF warnings only

Known working tree context:

- Phase 8 frontend files are modified but not committed.
- `docs/superpowers/2026-06-11-phase-8-implementation-report.md` and `docs/superpowers/qa/phase-8/` are untracked.
- `git status` reports a local permission warning for `backend/.pytest-tmp/`; this has not affected tests.

## Scope

In scope:

- Restore the design demo reference route/file from `D:\projects\page_chat - 副本\frontend\src\views\DesignDemoView.vue`.
- Audit production document, settings, and main chat screens against that demo and record exact alignment tasks.
- Preserve active document search/filter state during status polling.
- Align frontend legacy Office handling with backend rejection behavior.
- Replace mojibake text in touched frontend production UI paths.
- Repair non-PDF preview display for Markdown, TXT, spreadsheet, DOCX, and PPTX using the existing backend `/content` contract.
- Add focused Vitest coverage for helper-level behavior.
- Run frontend tests/build and full backend suite.

Out of scope:

- Adding `.doc`, `.xls`, or `.ppt` upload support.
- LibreOffice conversion.
- Backend parser changes.
- Document workbench redesign beyond bug fixes.
- Model settings changes.
- Retrieval planner changes.

## Files And Responsibilities

- Modify: `frontend/src/stores/document.ts`
  - Persist active list filters used by polling.
  - Keep current folder, search query, page size, and subfolder setting in sync.
- Create/Restore: `frontend/src/views/DesignDemoView.vue`
  - Keep the original visual demo available as `/design-demo` for side-by-side design QA.
- Modify: `frontend/src/router/index.ts`
  - Restore the `/design-demo` route.
- Create: `docs/superpowers/2026-06-11-phase-8-1-design-alignment-audit.md`
  - Record differences between the restored demo and production document/settings/chat screens.
- Modify: `frontend/src/utils/documentWorkbench.ts`
  - Add small helper(s) for supported preview extensions or legacy Office messaging if needed.
  - Keep helpers pure and covered by Vitest.
- Modify: `frontend/src/utils/documentWorkbench.test.ts`
  - Cover active search-state and legacy support-boundary helpers.
- Modify: `frontend/src/components/preview/UniversalPreview.vue`
  - Stop treating `.doc`, `.xls`, and `.ppt` as supported preview formats.
  - Replace mojibake loading/error/unsupported text with clear production copy.
- Modify: `frontend/src/views/ChatView.vue`
  - Stop treating `.doc`, `.xls`, and `.ppt` as supported source-preview formats.
  - Use a clear unsupported-format fallback instead of attempting PDF preview.
- Modify: `frontend/src/components/document/TocTree.vue`
  - Replace mojibake page labels with clear page labels.
  - Keep TOC summary hover behavior.
- Modify if needed: `frontend/src/components/preview/TextViewer.vue`
- Modify if needed: `frontend/src/components/preview/MarkdownViewer.vue`
- Modify if needed: `frontend/src/components/preview/DocxViewer.vue`
  - Replace user-visible mojibake only where encountered.

## Task 0: Restore Design Demo Baseline And Record Alignment Audit

**Files:**

- Create/Restore: `frontend/src/views/DesignDemoView.vue`
- Modify: `frontend/src/router/index.ts`
- Create: `docs/superpowers/2026-06-11-phase-8-1-design-alignment-audit.md`

- [ ] **Step 1: Restore the demo file**

Copy the original demo from:

```text
D:\projects\page_chat - 副本\frontend\src\views\DesignDemoView.vue
```

to:

```text
frontend/src/views/DesignDemoView.vue
```

Do not use it as production code directly. It is the visual reference.

- [ ] **Step 2: Restore the demo route**

Add a route in `frontend/src/router/index.ts`:

```ts
{
  path: '/design-demo',
  name: 'design-demo',
  component: () => import('@/views/DesignDemoView.vue'),
}
```

- [ ] **Step 3: Write the design alignment audit**

Create:

```text
docs/superpowers/2026-06-11-phase-8-1-design-alignment-audit.md
```

Include:

- Demo source path.
- Current production files compared.
- Document management differences.
- Settings page differences.
- Main chat/home screen differences.
- Items that should be removed from production because they were not in the demo/design direction.
- Items that should stay because later phases intentionally added them, such as evidence labels or model settings.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/views/DesignDemoView.vue frontend/src/router/index.ts docs/superpowers/2026-06-11-phase-8-1-design-alignment-audit.md
git commit -m "docs: restore frontend design demo baseline"
```

## Task 1: Preserve Search And Folder State During Polling

**Files:**

- Modify: `frontend/src/stores/document.ts`
- Modify: `frontend/src/utils/documentWorkbench.test.ts`

- [ ] **Step 1: Write failing store or helper test**

Add focused coverage proving that after a fetch with a search query, the next polling refresh uses the same query and page size.

If testing the Pinia store directly is too heavy for the current test setup, extract a pure helper that records list query state and test that helper first.

Expected behavior:

```ts
expect(nextListParams.search).toBe('risk')
expect(nextListParams.page_size).toBe(6)
expect(nextListParams.folder_id).toBe('folder-a')
expect(nextListParams.include_subfolders).toBe(false)
```

- [ ] **Step 2: Run the focused frontend test and verify failure**

Run:

```powershell
cd frontend
npm.cmd run test -- src/utils/documentWorkbench.test.ts
```

Expected: FAIL before implementation if the test exercises current polling-state behavior.

- [ ] **Step 3: Store active list filters in `fetchDocuments()`**

Update `fetchDocuments()` so it records:

- `searchQuery.value`
- `currentFolderId.value`
- current `include_subfolders`
- `currentPageSize.value`

Implementation direction:

```ts
const currentIncludeSubfolders = ref(false)

async function fetchDocuments(
  page = 1,
  search?: string,
  folder_id?: string | null,
  include_subfolders = false,
  pageSize = 20,
) {
  loading.value = true
  currentPageSize.value = pageSize
  searchQuery.value = search ?? ''
  currentFolderId.value = folder_id ?? null
  currentIncludeSubfolders.value = include_subfolders
  ...
}
```

Then use `currentIncludeSubfolders.value` in the polling request instead of hardcoding `true`.

- [ ] **Step 4: Run focused frontend tests**

Run:

```powershell
cd frontend
npm.cmd run test -- src/utils/documentWorkbench.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/stores/document.ts frontend/src/utils/documentWorkbench.ts frontend/src/utils/documentWorkbench.test.ts
git commit -m "fix: preserve document list filters while polling"
```

## Task 2: Align Legacy Office Frontend Boundary With Backend

**Files:**

- Modify: `frontend/src/components/preview/UniversalPreview.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/utils/documentWorkbench.ts`
- Modify: `frontend/src/utils/documentWorkbench.test.ts`

- [ ] **Step 1: Write failing support-boundary tests**

Add helper tests for file-type support:

```ts
expect(isPreviewSupported('.docx')).toBe(true)
expect(isPreviewSupported('.xlsx')).toBe(true)
expect(isPreviewSupported('.pptx')).toBe(true)
expect(isPreviewSupported('.doc')).toBe(false)
expect(isPreviewSupported('.xls')).toBe(false)
expect(isPreviewSupported('.ppt')).toBe(false)
```

Also test the legacy Office message:

```ts
expect(unsupportedPreviewMessage('.doc')).toContain('docx')
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
cd frontend
npm.cmd run test -- src/utils/documentWorkbench.test.ts
```

Expected: FAIL before implementation if the helpers do not exist.

- [ ] **Step 3: Add pure support helpers**

In `documentWorkbench.ts`, add:

```ts
const SUPPORTED_PREVIEW_EXTENSIONS = new Set([
  '.txt',
  '.md',
  '.markdown',
  '.csv',
  '.tsv',
  '.xlsx',
  '.docx',
  '.pptx',
])

const LEGACY_OFFICE_EXTENSIONS = new Set(['.doc', '.xls', '.ppt'])

export function isPreviewSupported(fileType?: string): boolean {
  return SUPPORTED_PREVIEW_EXTENSIONS.has((fileType || '').toLowerCase())
}

export function isLegacyOfficeFile(fileType?: string): boolean {
  return LEGACY_OFFICE_EXTENSIONS.has((fileType || '').toLowerCase())
}

export function unsupportedPreviewMessage(fileType?: string): string {
  if (isLegacyOfficeFile(fileType)) {
    return 'Legacy Office files are not supported yet. Save the file as .docx, .xlsx, or .pptx and upload it again.'
  }
  return `Preview is not supported for this file type: ${fileType || 'unknown'}`
}
```

- [ ] **Step 4: Update `UniversalPreview.vue`**

Use only current backend-supported extensions:

- `.txt`
- `.md`
- `.markdown`
- `.csv`
- `.tsv`
- `.xlsx`
- `.docx`
- `.pptx`

Remove `.doc`, `.xls`, and `.ppt` from supported branches.

- [ ] **Step 5: Update `ChatView.vue` citation preview routing**

For legacy `.doc`, `.xls`, and `.ppt`, do not route to `UniversalPreview` and do not fall back to PDF preview. Show or record an unsupported-format error state using the shared helper message.

- [ ] **Step 6: Run focused frontend tests**

Run:

```powershell
cd frontend
npm.cmd run test -- src/utils/documentWorkbench.test.ts src/utils/evidence.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/components/preview/UniversalPreview.vue frontend/src/views/ChatView.vue frontend/src/utils/documentWorkbench.ts frontend/src/utils/documentWorkbench.test.ts
git commit -m "fix: align legacy office preview support with backend"
```

## Task 3: Replace User-Visible Mojibake Text

**Files:**

- Modify: `frontend/src/components/preview/UniversalPreview.vue`
- Modify: `frontend/src/components/document/TocTree.vue`
- Modify if needed: `frontend/src/components/preview/TextViewer.vue`
- Modify if needed: `frontend/src/components/preview/MarkdownViewer.vue`
- Modify if needed: `frontend/src/components/preview/DocxViewer.vue`

- [ ] **Step 1: Scan visible frontend text**

Run:

```powershell
rg -n "涓|鍔|鏂|绗|椤|閿|鐩|鑾|鏄|澶|濂|鈥|�" frontend/src/components frontend/src/views frontend/src/stores frontend/src/utils
```

Review only user-visible strings and comments in touched files. Comments can be cleaned opportunistically when adjacent to edited code, but the priority is rendered text.

- [ ] **Step 2: Replace visible strings in `UniversalPreview.vue`**

Use clear copy:

- Loading: `Loading document content...`
- Unsupported: `Preview is not supported for this file type: ...`
- Generic error: `Failed to load document content`

- [ ] **Step 3: Replace visible page labels in `TocTree.vue`**

Use:

```vue
Page {{ node.start_page }}
<span v-if="node.end_page && node.end_page !== node.start_page">
  - {{ node.end_page }}
</span>
```

- [ ] **Step 4: Run the mojibake scan again**

Run:

```powershell
rg -n "涓|鍔|鏂|绗|椤|閿|鐩|鑾|鏄|澶|濂|鈥|�" frontend/src/components/preview frontend/src/components/document/TocTree.vue frontend/src/views/DocumentView.vue
```

Expected: no user-visible mojibake remains in touched production UI paths.

- [ ] **Step 5: Run frontend tests and build**

Run:

```powershell
cd frontend
npm.cmd run test
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/preview/UniversalPreview.vue frontend/src/components/document/TocTree.vue frontend/src/components/preview frontend/src/utils/documentWorkbench.test.ts
git commit -m "fix: replace corrupted preview ui text"
```

## Task 4: Repair Non-PDF Preview Display

**Files:**

- Modify: `frontend/src/components/preview/UniversalPreview.vue`
- Modify: `frontend/src/components/preview/TextViewer.vue`
- Modify: `frontend/src/components/preview/MarkdownViewer.vue`
- Modify: `frontend/src/components/preview/TableViewer.vue`
- Modify: `frontend/src/components/preview/DocxViewer.vue`
- Modify: `frontend/src/components/preview/PptxViewer.vue`
- Modify: `frontend/src/utils/documentWorkbench.ts`
- Modify: `frontend/src/utils/documentWorkbench.test.ts`

- [ ] **Step 1: Add failing preview-data tests**

Add pure helper tests proving backend canonical blocks can be normalized for:

- TXT line/paragraph blocks.
- Markdown heading/paragraph blocks.
- CSV/XLSX row blocks.
- DOCX paragraph/table blocks.
- PPTX slide blocks.

Expected test shape:

```ts
expect(normalizePreviewBlocks({ format: 'txt', blocks: [...] })).toHaveLength(1)
expect(formatPreviewKind('.xlsx')).toBe('table')
expect(formatPreviewKind('.pptx')).toBe('pptx')
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```powershell
cd frontend
npm.cmd run test -- src/utils/documentWorkbench.test.ts
```

Expected: FAIL before helper implementation.

- [ ] **Step 3: Implement preview format helpers**

Centralize extension-to-preview-kind logic so `UniversalPreview.vue` and chat citation preview do not maintain divergent format maps.

- [ ] **Step 4: Fix viewer assumptions**

Repair each viewer so it renders canonical `ContentBlock` output from `/api/documents/{id}/content`:

- TXT: render `text`, `paragraph`, and `heading` blocks.
- Markdown: render markdown content from canonical blocks without requiring a nested frontend-only shape.
- Table: render `table_row` blocks and show row/column labels with valid HTML.
- DOCX: render `paragraph`, `heading`, and table blocks.
- PPTX: render `slide` blocks.

- [ ] **Step 5: Run frontend tests and build**

Run:

```powershell
cd frontend
npm.cmd run test
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 6: Run backend content extraction suite**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_content_extraction_canonical.py backend\tests\test_content_extraction_source_anchors.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/components/preview frontend/src/utils/documentWorkbench.ts frontend/src/utils/documentWorkbench.test.ts
git commit -m "fix: render canonical non-pdf previews"
```

## Task 5: Verification Sweep And Completion Gate

**Files:**

- No source changes expected unless verification finds a regression.

- [ ] **Step 1: Run frontend tests**

Run:

```powershell
cd frontend
npm.cmd run test
```

Expected: `14 passed` or higher if new tests were added.

- [ ] **Step 2: Run frontend production build**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: `vue-tsc` and Vite build pass.

- [ ] **Step 3: Run focused backend regression**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_safe_upload_filenames.py backend\tests\test_content_extraction_canonical.py backend\tests\test_content_extraction_source_anchors.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full backend suite**

Run:

```powershell
cd backend
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Expected: PASS with known skips.

- [ ] **Step 5: Run diff hygiene**

Run:

```powershell
git diff --check -- frontend/src backend/app backend/tests docs/superpowers
```

Expected: no whitespace errors. LF/CRLF warnings are acceptable if no whitespace errors are reported.

- [ ] **Step 6: Run completion gate audit**

Use:

```text
docs/superpowers/completion-gate-gap-audit.md
```

Inputs:

- Latest user request.
- This Phase 8.1 plan.
- `docs/superpowers/plans/2026-06-10-phase-8-document-management-production-redesign.md`
- `docs/superpowers/2026-06-11-phase-8-implementation-report.md`
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-11-phase-7-implementation-report.md`
- Source plan: `D:\projects\page_chat - 副本\docs\superpowers\plans\2026-06-10-frontend-design-plan.md`
- Current git status.
- Test and build output from Steps 1-5.

## Done Criteria

Phase 8.1 is complete when:

- Polling preserves the active document search query, folder scope, include-subfolders flag, current page, and page size.
- Frontend preview and chat citation routing no longer imply support for `.doc`, `.xls`, or `.ppt`.
- Markdown, TXT, spreadsheet, DOCX, and PPTX previews render canonical backend content.
- Legacy Office unsupported messaging is clear and consistent with the backend support boundary.
- User-visible mojibake is removed from the touched preview and TOC UI paths.
- Frontend tests pass.
- Frontend build passes.
- Focused backend regression passes.
- Full backend suite passes.
- Completion gate passes or records only accepted P2 follow-ups.

## Follow-Up Candidates

These are not required for Phase 8.1:

- Phase 7b legacy Office conversion through LibreOffice.
- Backend owner/uploader metadata for the Phase 8 detail panel.
- Backend OCR page count metadata for the Phase 8 detail panel.
- A broader i18n/localization pass for all frontend copy.
- Removing stale private parser helpers from `multi_format_adapter.py`.
