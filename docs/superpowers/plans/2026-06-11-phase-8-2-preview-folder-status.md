# Phase 8.2 Preview, Folder Creation, and Status Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the frontend correctly consume the existing Phase 7 canonical multi-format contract in document management and chat citation previews, restore folder creation in the redesigned document workbench, and replace misleading hard-coded index detail text with field-driven status.

**Architecture:** Treat Phase 7 as the backend parsing and source-anchor authority. Keep `UniversalPreview` as the single frontend preview surface for all non-PDF formats, and make format viewers correctly render the canonical backend block shapes already returned by `/api/documents/{id}/content`. Keep document workbench UI aligned with the existing demo design while reconnecting folder operations and replacing detail-card placeholders with deterministic helper functions.

**Tech Stack:** Vue 3, Pinia, TypeScript, Vitest, FastAPI, existing content adapter services.

---

## File Structure

- Modify: `frontend/src/utils/documentWorkbench.ts`
  - Add pure helpers for preview block normalization, detail metrics, quality/index wording, and workbench folder counts.
- Modify: `frontend/src/utils/documentWorkbench.test.ts`
  - Add regression tests for Excel `sheet` block expansion, DOCX heading/table visibility, detail metrics, and index status wording.
- Modify: `frontend/src/components/preview/TableViewer.vue`
  - Render both `table_row` blocks and canonical `.xlsx` `sheet` blocks.
- Modify: `frontend/src/components/preview/DocxViewer.vue`
  - Render `paragraph`, `heading`, and `table` blocks with stable paragraph anchors.
- Modify: `frontend/src/components/preview/PptxViewer.vue`
  - Keep existing `slide` support, add empty/error-safe rendering and clearer anchor handling if needed.
- Modify: `frontend/src/components/preview/UniversalPreview.vue`
  - Normalize backend content once before handing it to viewers and show actionable empty states.
- Modify: `frontend/src/views/ChatView.vue`
  - Prefer structured citation/source anchors when available; use text citation parsing only as fallback.
- Modify: `frontend/src/views/DocumentView.vue`
  - Restore folder creation in the demo-aligned left pane.
  - Replace detail-panel hard-coded placeholders with helper-derived field values.
- Use existing: `frontend/src/components/folder/CreateFolderDialog.vue`
  - Reuse for folder creation; do not create a new modal unless the existing one cannot fit.
- Backend check only unless tests expose a regression against the Phase 7 contract:
  - `backend/app/api/documents.py`
  - `backend/app/services/content_extraction_service.py`
  - `backend/app/services/format_adapters/*.py`

## Existing Contract To Preserve

This plan must not re-open the multi-format abstraction work. The current authority is:

- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/plans/2026-06-10-phase-7-multiformat-adapter-migration.md`
- `docs/superpowers/2026-06-11-phase-7-implementation-report.md`

Phase 7 already established:

- Canonical adapters for TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX.
- Canonical `DocumentContent`, `ContentBlock`, `IndexNode`, and `SourceAnchor` backend outputs.
- `/api/documents/{id}/content` attempts canonical preview extraction for supported non-PDF formats.
- Parser-backed source-anchor resolution for line, row, paragraph, and slide anchors.
- Legacy `.doc`, `.xls`, and `.ppt` remain rejected unless Phase 7b implements conversion.

Therefore Phase 8.2 is primarily a frontend-consumption and UI-restoration plan:

- Fix frontend renderers that filter out valid canonical blocks such as XLSX `sheet`, DOCX `heading`, and DOCX `table`.
- Preserve and use canonical `source_anchor` wherever available.
- Only change backend code if investigation proves the backend is violating the Phase 7 contract.

---

### Task 1: Adapt Frontend Normalization To Phase 7 Canonical Preview Blocks

**Files:**
- Modify: `frontend/src/utils/documentWorkbench.ts`
- Test: `frontend/src/utils/documentWorkbench.test.ts`

- [ ] **Step 1: Write failing tests for canonical preview block normalization**

Add tests showing that:
- `.xlsx` content with the Phase 7 canonical `sheet` block becomes renderable table rows.
- `.docx` `heading` blocks remain visible, not filtered out.
- `.docx` Phase 7 canonical `table` blocks become visible document sections.
- Existing `table_row` and `slide` behavior remains unchanged.

Example test shape:

```ts
it('expands xlsx sheet blocks into renderable table rows', () => {
  const blocks = normalizePreviewBlocks({
    format: 'xlsx',
    blocks: [{
      id: 'sheet_1',
      type: 'sheet',
      content: {
        name: 'Orders',
        rows: [
          { row_number: 1, cells: [{ col: 1, value: 'order_id' }] },
          { row_number: 2, cells: [{ col: 1, value: 'SO-10001' }] },
        ],
      },
      source_anchor: { format: 'xlsx', unit_type: 'row_range', sheet: 'Orders', start_row: 1, end_row: 2 },
      metadata: { sheet_name: 'Orders' },
    }],
    metadata: {},
  })

  expect(blocks).toEqual([
    expect.objectContaining({ type: 'table_row', rowNumber: 1, sheet: 'Orders' }),
    expect.objectContaining({ type: 'table_row', rowNumber: 2, sheet: 'Orders' }),
  ])
})
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd D:\projects\page_chat\frontend
npm.cmd run test -- src/utils/documentWorkbench.test.ts
```

Expected: failure because `sheet` blocks are not expanded.

- [ ] **Step 3: Implement normalization helpers**

Add or extend frontend-only helpers:
- `normalizePreviewBlocks(content)`
  - Preserve existing Phase 7 `table_row` and `slide`.
  - Convert Phase 7 `sheet` blocks into frontend-renderable `table_row` rows with:
    - `type: 'table_row'`
    - `rowNumber`
    - `sheet`
    - `cells: [{ col: string, value: string }]`
    - `source_anchor` including `sheet`, `start_row`, `end_row`
  - Preserve `paragraph`, `heading`, `table`, `text` blocks as normalized blocks with anchors.
- `previewContentMetrics(content)`
  - Return `rowCount`, `lineCount`, `paragraphCount`, `slideCount`, `textChars`, `tocNodes`, `summaryCoverage`.

- [ ] **Step 4: Run helper tests**

Run:

```bash
npm.cmd run test -- src/utils/documentWorkbench.test.ts
```

Expected: all tests pass.

---

### Task 2: Fix Excel/CSV/Table Preview Rendering Against Phase 7 Blocks

**Files:**
- Modify: `frontend/src/components/preview/TableViewer.vue`
- Test: `frontend/src/utils/documentWorkbench.test.ts`

- [ ] **Step 1: Confirm current Excel failure manually**

Use a known `.xlsx` document such as `sales_orders.xlsx`.

Check:

```powershell
$login = Invoke-RestMethod -Uri http://127.0.0.1:5173/api/auth/login -Method Post -ContentType 'application/json' -Body (@{email='2991920802@qq.com'; password='bfdxbfdj0813'} | ConvertTo-Json)
Invoke-RestMethod -Uri 'http://127.0.0.1:5173/api/documents/d6ff30c9/content' -Headers @{Authorization="Bearer $($login.token)"}
```

Expected current evidence: Phase 7 correctly returns `blocks[0].type === "sheet"` for XLSX, but the frontend viewer currently displays no table rows because it only renders `table_row`.

- [ ] **Step 2: Update `TableViewer` to use normalized rows**

Implementation rule:
- Do not change backend table adapters for this issue.
- Do not inspect raw `sheet` blocks ad hoc inside `TableViewer`.
- Use `normalizePreviewBlocks(props.content)` and trust it to produce `table_row`.
- Display sheet name in the toolbar when present.
- Keep row click emitting `sheet` if available:

```ts
const anchor: SourceAnchor = {
  format: props.content.format,
  unit_type: 'row_range',
  sheet: row.sheet,
  start_row: rowNumber,
  end_row: rowNumber,
}
```

- [ ] **Step 3: Verify in both entry points**

Manual:
- Open `/documents`.
- Open preview for `sales_orders.xlsx`.
- Confirm rows and columns render.
- In chat, click a citation for an `.xlsx` document if present; otherwise send a query likely to cite `sales_orders.xlsx`, then click the citation.

Automated smoke:

```bash
npm.cmd run build
```

Expected: build passes.

---

### Task 3: Fix DOCX, Markdown, TXT, and PPTX Viewer Completeness

**Files:**
- Modify: `frontend/src/components/preview/DocxViewer.vue`
- Modify: `frontend/src/components/preview/MarkdownViewer.vue` only if anchor handling fails.
- Modify: `frontend/src/components/preview/TextViewer.vue` only if anchor handling fails.
- Modify: `frontend/src/components/preview/PptxViewer.vue` only if empty-state or anchor issues are observed.
- Test: `frontend/src/utils/documentWorkbench.test.ts`

- [ ] **Step 1: Add regression tests for visible DOCX blocks**

Test that normalized DOCX blocks include:
- `heading`
- `paragraph`
- `table`

Expected current failure: `DocxViewer` filters only `paragraph`, so headings/tables are not displayed by the UI.

- [ ] **Step 2: Update `DocxViewer` block mapping**

Replace `paragraphs` computed with a document block list:
- Render `heading` with heading style and paragraph number.
- Render `paragraph` as normal paragraph.
- Render `table` as compact table with rows.
- Keep `source_anchor.start_paragraph` as primary anchor.

Rules:
- Do not drop blocks just because `block.type !== 'paragraph'`.
- If `metadata.paragraph_number` is missing, derive from `source_anchor.start_paragraph` or list order.

- [ ] **Step 3: Check Markdown/TXT anchor behavior**

Inspect these real content responses:
- `XSS.md`
- `CSRF.txt`

Confirm:
- `TextViewer` can scroll to `start_line`.
- `MarkdownViewer` can scroll to nearest block for `start_line`.

Only patch if observed failing.

- [ ] **Step 4: Check PPTX behavior**

Confirm `.pptx` content returns `slide` blocks and `PptxViewer` renders them.

Only patch if:
- Empty deck renders as a broken view.
- `initialAnchor.start_slide` does not navigate.

- [ ] **Step 5: Verify**

Run:

```bash
npm.cmd run test -- src/utils/documentWorkbench.test.ts
npm.cmd run build
```

Manual smoke:
- Document preview: `.txt`, `.md`, `.xlsx`, `.docx`, `.pptx`.
- Chat citation preview: at least `.txt` or `.md`, plus `.xlsx` if citations exist.

---

### Task 4: Preserve Phase 7 Structured Anchors in Chat Citation Preview

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Inspect: `frontend/src/stores/chat.ts`
- Inspect: `frontend/src/utils/evidence.ts`

- [ ] **Step 1: Trace available citation data**

Find where answer citations/evidence are stored and rendered.

Search:

```bash
rg -n "sourceAnchor|source_anchor|citation|renderMarkdown|handleCitationClick|openSourcePreview" frontend/src/views/ChatView.vue frontend/src/stores/chat.ts frontend/src/utils
```

- [ ] **Step 2: Add helper for anchor selection**

Create or extend a helper in `frontend/src/utils/documentWorkbench.ts`:

```ts
export function anchorFromCitation(input: {
  fileType: string
  sourceAnchor?: Record<string, unknown> | null
  positionType?: string
  position?: string | number
}): SourceAnchor
```

Priority:
1. If `sourceAnchor` exists, normalize and use it.
2. Else use explicit `line/row/para/slide/p`.
3. Else use format-specific fallback:
   - PDF: page 1
   - TXT/MD: line 1
   - CSV/XLSX: row 1
   - DOCX: paragraph 1
   - PPTX: slide 1

- [ ] **Step 3: Write tests for anchor selection**

Cases:
- `.xlsx` + source anchor with `sheet` keeps sheet.
- `.docx` + `para.7` becomes `start_paragraph: 7`.
- `.pptx` + `slide.2` becomes slide 2.
- `.md` + legacy `p.5` maps to `start_line: 5`, not PDF page.

- [ ] **Step 4: Wire `ChatView` to helper**

Replace scattered per-format anchor construction in `ChatView.vue` with the helper.

Do not change visual layout in this task.

- [ ] **Step 5: Verify**

Run:

```bash
npm.cmd run test -- src/utils/documentWorkbench.test.ts
npm.cmd run build
```

Manual:
- Click PDF citation.
- Click non-PDF citation.
- Confirm right panel uses `PdfReferenceViewer` for PDF and `UniversalPreview` for non-PDF.

---

### Task 5: Restore Folder Creation in Demo-Aligned Workbench

**Files:**
- Modify: `frontend/src/views/DocumentView.vue`
- Use: `frontend/src/components/folder/CreateFolderDialog.vue`
- Existing store: `frontend/src/stores/folder.ts`

- [ ] **Step 1: Add folder creation state**

In `DocumentView.vue`:

```ts
import CreateFolderDialog from '@/components/folder/CreateFolderDialog.vue'

const showCreateFolderDialog = ref(false)
const createFolderParentId = ref<string | null>(null)

function openCreateFolder(parentId: string | null = folderStore.currentFolderId) {
  createFolderParentId.value = parentId
  showCreateFolderDialog.value = true
}

async function handleFolderCreated() {
  await folderStore.fetchFolderTree()
  await folderStore.fetchFolders()
}
```

- [ ] **Step 2: Add demo-style trigger**

Use existing `surface-head` more button or replace with a plus icon button:

```vue
<button class="icon-btn" aria-label="新建文件夹" title="新建文件夹" @click="openCreateFolder(folderStore.currentFolderId)">
  <Plus class="h-4 w-4" />
</button>
```

Keep visual language aligned with the demo: same `icon-btn`, no old sidebar frame.

- [ ] **Step 3: Mount existing dialog**

Add near the other modals:

```vue
<CreateFolderDialog
  v-model:open="showCreateFolderDialog"
  :parent-id="createFolderParentId"
  @created="handleFolderCreated"
/>
```

- [ ] **Step 4: Verify**

Manual:
- Click plus in left pane.
- Create a folder.
- Confirm it appears in the left pane.
- Select it and confirm document list filters.

Build:

```bash
npm.cmd run build
```

---

### Task 6: Replace Hard-Coded Detail Status Text With Real Field Mapping

**Files:**
- Modify: `frontend/src/utils/documentWorkbench.ts`
- Modify: `frontend/src/utils/documentWorkbench.test.ts`
- Modify: `frontend/src/views/DocumentView.vue`

- [ ] **Step 1: Write tests for detail status helpers**

Add helpers:

```ts
export function qualityDisplay(report?: QualityReport | null): {
  label: string
  tone: 'ok' | 'warning' | 'error' | 'muted'
  message: string
}

export function documentDetailMetrics(input: {
  doc: DocumentLike
  previewStats?: PreviewStats | null
  qualityReport?: QualityReport | null
}): Array<{ label: string; value: string; state: 'ready' | 'pending' | 'missing' }>
```

Test expectations:
- `needs_review` says “需要复核”，not “可用于问答和引用定位”.
- Missing OCR says “未接入”, not pretending loaded.
- Missing word count says “打开预览后统计” or “未生成”, not `Not available`.
- `quality_report.node_count` can fill TOC nodes before preview if available.

- [ ] **Step 2: Implement helper logic**

Mapping:
- `quality_report.status === 'completed'`
  - label: `已通过`
  - message: `索引已完成，可用于问答和引用定位`
- `needs_review`
  - label: `需复核`
  - message from warning count or `索引完成但质量检查提示需要复核`
- `failed:*`
  - label: `失败`
  - message: use `doc.error_message` if present
- missing report
  - label: `未生成`
  - message: `暂无质量报告`

Metric priority:
- TOC nodes: `previewStats.node_count` > `quality_report.node_count` > `打开预览后统计`
- Summary coverage: `previewStats.summary_coverage` > derive from `quality_report.empty_summary_ratio` if present > `打开预览后统计`
- Text chars: `previewStats.text_chars` > `打开预览后统计`
- OCR pages: backend field if added later > `未接入`
- Pages / words: page count + text chars; if text chars missing use `打开预览后统计`

- [ ] **Step 3: Update `DocumentView` detail panel**

Remove hard-coded:
- `admin` uploader if no real field should become `未提供`
- `Needs review，索引可用于问答和引用定位`
- `Not available` in `页数 / 字数` where a better pending label exists.

Use helper outputs for all detail card labels and messages.

- [ ] **Step 4: Verify screenshot state**

Manual:
- Select a document with `quality_report.status = needs_review`.
- Confirm message says it needs review.
- Open preview.
- Confirm TOC/text metrics update if preview stats exist.

Automated:

```bash
npm.cmd run test -- src/utils/documentWorkbench.test.ts
npm.cmd run build
```

---

### Task 7: End-to-End Regression Sweep

**Files:**
- No new files unless bugs are found.

- [ ] **Step 1: Run frontend unit tests**

```bash
cd D:\projects\page_chat\frontend
npm.cmd run test
```

Expected: all frontend tests pass.

- [ ] **Step 2: Run frontend build**

```bash
npm.cmd run build
```

Expected: `vue-tsc` and Vite build pass.

- [ ] **Step 3: Run backend focused tests**

```bash
cd D:\projects\page_chat
uv run pytest backend\tests\test_text_markdown_adapters.py backend\tests\test_table_adapter.py backend\tests\test_word_adapter.py backend\tests\test_presentation_adapter.py -q
```

Expected: all focused adapter tests pass.

- [ ] **Step 4: Manual browser smoke checklist**

Open `http://127.0.0.1:5173/documents`.

Check:
- PDF preview still works.
- TXT preview opens and scrolls.
- Markdown preview opens and headings render.
- XLSX preview shows rows/columns.
- DOCX preview shows headings, paragraphs, and tables if present.
- PPTX preview shows slides.
- Folder creation works from redesigned left pane.
- Detail panel no longer says misleading “Needs review, 索引可用于问答和引用定位”.
- Chat right citation preview still opens PDF.
- Chat right citation preview opens at least one non-PDF source.

- [ ] **Step 5: Update implementation report**

Modify:
- `docs/superpowers/2026-06-11-phase-8-implementation-report.md`

Record:
- What was fixed.
- Which formats are fully supported.
- Which formats are text-only extraction rather than native visual rendering.
- Remaining backend gaps, especially OCR page count/uploader/word count if not exposed by API.

---

## Risk Notes

- PPTX preview is text/notes extraction, not native slide rendering. Treat it as “content preview,” not pixel-accurate PowerPoint rendering.
- DOCX preview is structured text/table preview, not Word layout rendering.
- Excel preview should prioritize row/column readability and anchors; formulas/styles are out of scope for this pass.
- Chat citation accuracy depends on preserving Phase 7 structured `source_anchor`. The frontend fallback can improve behavior but cannot infer exact source positions when the answer only says `p.x` for non-PDF content.
- Any backend change in this phase must be justified as a Phase 7 contract regression, not as a new abstraction.

## Suggested Execution Order

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7

This order restores broken preview functionality first, then reconnects missing workbench operations, then makes status messaging truthful.
