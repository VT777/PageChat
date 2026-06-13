# Phase 8 Document Management Production Redesign Implementation Report

Date: 2026-06-11

## Summary

Phase 8 moved document management to a production workbench layout while preserving existing document workflows and preview contracts.

Implemented:

- Three-column document workbench: folders, dense document list, compact detail panel.
- Six-item dense page design with stable batch-mode selection space.
- Status strip with folder document count, recent update, and active indexing count.
- Compact detail panel with identity, basic attributes, index status, summary, and actions.
- Raw-only non-PDF preview mode so the modal right pane shows source content only.
- TOC summary hover behavior on the modal TOC.
- Frontend helper tests for workbench pagination, status labels, progress mapping, placeholders, and duration formatting.

## Field Availability Matrix

| Field | Availability | UI behavior |
| --- | --- | --- |
| Uploader | Missing | Neutral placeholder: `Not available`; backend follow-up required. |
| Uploaded time | Document list response | Uses `created_at`. |
| Updated time | Document list response | Uses `updated_at`. |
| Pages or word count | Document list response / missing word count | Uses `page_count`; word count remains unavailable. |
| Index mode | Document list / preview response | Uses `parse_execution_mode`, `parse_requested_mode`, or preview `route_decision.execution_mode`. |
| Processing duration | Document list / preview response | Uses `processing_duration`. |
| Last indexed time | Document list response | Uses `last_reindex_at`, falling back to `updated_at`. |
| TOC node count | Preview response | Uses `previewData.stats.node_count` after preview is loaded; otherwise prompts to open preview. |
| Summary coverage | Preview response | Uses `previewData.stats.summary_coverage` after preview is loaded. |
| Text character count | Preview response | Uses `previewData.stats.text_chars` after preview is loaded. |
| OCR page count | Missing | Neutral placeholder: `Not available`; backend follow-up required. |
| Full document summary | Document list / preview response | Uses `description`; placeholder when absent. |
| Optional `quality_report` | Document list / preview response | Shows status and score when present; neutral placeholder when absent. |

## No-Regression Notes

- Search, upload, folder selection, pagination, preview, reindex, delete, move, rename, processing-step dialog, and context menu entry points remain wired.
- Batch mode preserves selection, select-page, clear, move, reindex, delete, and download actions.
- Phase 6 evidence formatting utilities remain covered by `frontend/src/utils/evidence.test.ts`.
- Phase 7 source-anchor and preview types were preserved; `SourceAnchor`, `source_anchor`, and source-label display paths were not removed.
- Legacy Office behavior remains unchanged; no backend parser or conversion support was added.

## Preview Contract

The modal preview remains a modal.

- Left side: TOC and metadata.
- Right side: original document content only.
- TOC node summaries appear only via TOC hover popovers.
- `UniversalPreview` now accepts `rawOnly`; `TextViewer`, `MarkdownViewer`, and `DocxViewer` keep their internal TOC by default and hide it only when `rawOnly` is used by the document-management modal.

## Visual QA Evidence

Screenshots were captured with mocked document/folder/preview data:

- `docs/superpowers/qa/phase-8/desktop-workbench.png`
- `docs/superpowers/qa/phase-8/batch-mode.png`
- `docs/superpowers/qa/phase-8/preview-modal.png`
- `docs/superpowers/qa/phase-8/narrow-workbench.png`

QA states covered:

- Normal document list.
- Long file name and long folder path.
- Long detail-panel summary.
- Missing optional metadata placeholders.
- `completed`, `needs_review`, `processing:indexing`, and failed statuses.
- Batch mode with selected-action toolbar.
- Preview modal with raw-only right pane.
- Narrow desktop viewport.

Automated QA result:

- Raw-only preview check: passed.
- Narrow viewport overflow scan: no offenders.

## Verification

Passed:

```powershell
cd frontend
npm.cmd run test
```

Result: 3 test files passed, 14 tests passed.

```powershell
cd frontend
npm.cmd run build
```

Result: `vue-tsc` and Vite production build passed.

Backend tests were not rerun for Phase 8 because no backend API or parser behavior changed.

## Follow-Ups

Accepted backend follow-ups:

- Expose uploader/owner metadata for the detail panel.
- Expose OCR page count if OCR coverage becomes a required UI metric.

## Phase 8.2 Preview, Folder, and Status Follow-Up

Date: 2026-06-11

Implemented after the initial redesign:

- Added `normalizePreviewBlocks()` as the frontend bridge to the Phase 7 canonical preview contract.
- Expanded canonical `.xlsx` `sheet` blocks into renderable table rows for `TableViewer`.
- Updated `DocxViewer` to render DOCX `heading`, `paragraph`, and `table` blocks instead of filtering to paragraphs only.
- Kept PPTX slide rendering on canonical `slide` blocks and retained TXT/Markdown line-anchor behavior.
- Added `anchorFromCitation()` so non-PDF preview anchors can use format-specific defaults.
- Made chat evidence chips clickable and prioritized Phase 7 structured `source_anchor` when opening citation previews.
- Extended chat evidence collection to preserve `doc_id` / `docId` and `doc_name` / `document_name` from tool results.
- Restored folder creation in the redesigned document workbench by reusing `CreateFolderDialog` from the left pane plus button.
- Replaced the hard-coded detail-panel quality message with helper-derived wording, so `needs_review` no longer says the index is fully ready for Q&A/citation positioning.
- Replaced misleading detail placeholders with field-driven states such as `未提供`, `打开预览后统计`, and `未接入`.

Supported preview behavior after Phase 8.2:

| Format | Preview behavior |
| --- | --- |
| PDF | Existing PDF viewer, page anchors. |
| TXT | Text preview with line anchors. |
| Markdown | Markdown preview with line-aware anchors. |
| CSV / TSV | Table preview with row anchors. |
| XLSX | Canonical sheet rows expanded into table preview with sheet + row anchors. |
| DOCX | Structured text preview for headings, paragraphs, and tables with paragraph anchors. |
| PPTX | Content preview for extracted slides with slide anchors. |

Important limitations:

- DOCX preview is structured content rendering, not pixel-accurate Word layout.
- PPTX preview is text/notes extraction, not native slide visual rendering.
- XLSX preview prioritizes readable rows/columns and anchors; formulas, styles, and workbook layout fidelity remain out of scope.
- Legacy `.doc`, `.xls`, and `.ppt` remain unsupported until a conversion phase is added.
- Uploader and OCR page count still require backend fields to be exposed.

Additional verification:

```powershell
cd frontend
npm.cmd run test
```

Result: 3 test files passed, 27 tests passed.

```powershell
cd frontend
npm.cmd run build
```

Result: `vue-tsc` and Vite production build passed.

```powershell
uv run pytest backend\tests\test_text_markdown_adapters.py backend\tests\test_table_adapter.py backend\tests\test_word_adapter.py backend\tests\test_presentation_adapter.py -q
```

Result: 23 backend adapter tests passed.
