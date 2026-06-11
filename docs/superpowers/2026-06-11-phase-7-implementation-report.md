# Phase 7 Implementation Report

Date: 2026-06-11

## Executive Summary

Phase 7 completed the main multi-format adapter migration for TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX.

The backend now has concrete canonical adapters under `backend/app/services/format_adapters/` for the supported non-PDF formats. The public `generate_multi_format_index(file_path)` API remains compatible with the older index dictionary shape, but its public entry point now delegates to canonical `DocumentContent`, `IndexNode`, and `ContentBlock` outputs.

Preview extraction and table aggregation were also moved onto canonical adapter outputs where available. This reduces parser drift between indexing, preview, aggregation, source anchors, search evidence, and tool evidence.

Final verification after completion-gate gap closure:

- Phase 7 focused backend suite: `42 passed`
- Retrieval and citation contract suite: `14 passed`
- Full backend suite: `412 passed, 8 skipped`
- Frontend production build: passed
- Completion gate result: pass, with no P0/P1 gaps

Gap closure completed after independent review:

- Table aggregation citations now preserve canonical `source_anchor` and `display_label` metadata.
- Legacy `.doc`, `.xls`, and `.ppt` formats remain rejected and are covered by upload validation tests.

## Scope Completed

### 1. Canonical Text And Markdown Adapters

Implemented capabilities:

- Added `text_adapter.py` for TXT decoding, line blocks, paragraph-first index chunks, and line source anchors.
- Added `markdown_adapter.py` for ATX headings, setext headings, code-fence-safe parsing, heading trees, fallback blocks, and line source anchors.
- Preserved the legacy `multi_format_adapter.py` public index response shape while adding canonical adapter metadata.

Key files:

- `backend/app/services/format_adapters/text_adapter.py`
- `backend/app/services/format_adapters/markdown_adapter.py`
- `backend/app/services/multi_format_adapter.py`
- `backend/tests/test_text_markdown_adapters.py`

### 2. Canonical Table Adapter

Implemented capabilities:

- Added `table_adapter.py` for CSV, TSV, and XLSX parsing.
- Emitted canonical row-range index nodes and preview blocks.
- Exposed deterministic table datasets for aggregation.
- Added schema inference for numeric and string columns.
- Added conservative table limits:
  - `MULTIFORMAT_MAX_ROWS_PER_CHUNK`
  - `MULTIFORMAT_MAX_TABLE_CHUNKS_PER_SHEET`
  - `MULTIFORMAT_MAX_SHEETS_PER_WORKBOOK`
- Preserved row provenance in table datasets so aggregation citations can include canonical anchors and display labels.
- Returned controlled parse errors for corrupt XLSX input.

Key files:

- `backend/app/services/format_adapters/table_adapter.py`
- `backend/app/services/table_analysis_service.py`
- `backend/tests/test_table_adapter.py`
- `backend/tests/test_table_analysis_service.py`

### 3. Canonical DOCX Adapter

Implemented capabilities:

- Added `word_adapter.py` for DOCX paragraph extraction, heading detection, numbered heading fallback, table blocks, and paragraph anchors.
- Added visual-heavy metadata for documents that contain embedded media but little text.
- Added bounded text extraction with `MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE`.
- Returned controlled parse errors for corrupt DOCX input.

Key files:

- `backend/app/services/format_adapters/word_adapter.py`
- `backend/tests/test_word_adapter.py`
- `backend/tests/test_source_anchor_resolution_office.py`

### 4. Canonical PPTX Adapter

Implemented capabilities:

- Added `presentation_adapter.py` for PPTX slide text, speaker notes, empty slide handling, and slide anchors.
- Added visual-heavy metadata for slides with little text and visual shapes.
- Added bounded deck and text limits:
  - `MULTIFORMAT_MAX_SLIDES_PER_DECK`
  - `MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE`
- Returned controlled parse errors for corrupt PPTX input.

Key files:

- `backend/app/services/format_adapters/presentation_adapter.py`
- `backend/tests/test_presentation_adapter.py`
- `backend/tests/test_source_anchor_resolution_office.py`

### 5. Canonical Preview Extraction

Implemented capabilities:

- `ContentExtractionService.extract_content()` now attempts canonical extraction for TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX before falling back to legacy preview paths.
- Preview blocks are generated from canonical `ContentBlock` outputs where available.
- Added tests comparing representative index anchors and preview anchors for the same source fixtures.
- Removed the stale internal `.xls` supported-format entry so legacy Office support is not implied.

Key files:

- `backend/app/services/content_extraction_service.py`
- `backend/tests/test_content_extraction_canonical.py`
- `backend/tests/test_content_extraction_source_anchors.py`

### 6. Legacy Office Boundary

Implemented capabilities:

- Kept `.doc`, `.xls`, and `.ppt` out of `ALLOWED_EXTENSIONS`.
- Kept the document content API supported-format set limited to current whitelisted formats.
- Added upload validation coverage proving legacy Office formats remain rejected.

Task 6 from the Phase 7 plan remains deferred as Phase 7b/P2. No LibreOffice conversion path was added in the main Phase 7 slice.

Key files:

- `backend/app/core/config.py`
- `backend/app/api/documents.py`
- `backend/tests/test_safe_upload_filenames.py`

## Product Decisions Preserved

Phase 7 preserved earlier phase contracts:

- The mature PDF PageIndex path was not rewritten.
- `multi_format_adapter.py` still exposes `generate_multi_format_index(file_path)` and returns legacy-compatible index dictionaries.
- `source_anchor` remains additive and format-aware.
- Search and tool evidence contracts for `source_anchor`, `display_label`, `retrieval_source`, `confidence`, and `why_selected` remain covered by regression tests.
- Phase 6 frontend evidence labels and preview source labels continue to work without a frontend schema rewrite.
- Legacy `.doc`, `.xls`, and `.ppt` are still rejected unless conversion support is implemented and tested later.

## Verification Evidence

### Initial RED Verification

The new Phase 7 adapter tests were written before implementation and initially failed during collection because the canonical adapter modules did not exist.

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_text_markdown_adapters.py backend\tests\test_table_adapter.py backend\tests\test_word_adapter.py backend\tests\test_presentation_adapter.py backend\tests\test_content_extraction_canonical.py -q
```

Initial result:

```text
4 collection errors for missing canonical adapter modules
```

### Phase 7 Focused Suite

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_text_markdown_adapters.py backend\tests\test_table_adapter.py backend\tests\test_word_adapter.py backend\tests\test_presentation_adapter.py backend\tests\test_content_extraction_canonical.py backend\tests\test_multi_format_adapter.py backend\tests\test_table_analysis_service.py backend\tests\test_source_anchor_resolution_office.py backend\tests\test_safe_upload_filenames.py -q
```

Result:

```text
42 passed
```

### Retrieval And Citation Contract Suite

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_non_pdf_source_anchors.py backend\tests\test_retrieval_trace_contract.py backend\tests\test_retrieval_quality_regression.py backend\tests\test_content_extraction_source_anchors.py -q
```

Result:

```text
14 passed
```

### Full Backend Suite

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
412 passed, 8 skipped
```

Warnings were limited to existing dependency and deprecation warnings, including PyPDF2, Pydantic V1-style validators, FastAPI/Starlette coroutine checks, and Python datetime deprecations.

### Frontend Build

```powershell
cd frontend
npm.cmd run build
```

Result:

```text
vue-tsc and vite build passed
```

Note: the build needed to be rerun outside the sandbox because Vite/esbuild failed inside the sandbox with `spawn EPERM`.

## Actual Code Scans Performed

The completion audit used real scans rather than memory-based review.

Canonical adapter and facade scan:

```powershell
rg -n "_extract_txt\(|_extract_markdown\(|_extract_csv_like\(|_extract_xlsx\(|_extract_docx\(|_extract_pptx\(|parse_text\(|parse_markdown\(|parse_table\(|parse_docx\(|parse_pptx\(|document_content_to_index|canonical_" backend\app backend\tests
```

Result summary:

- `generate_multi_format_index()` now delegates to canonical adapters at the public entry point.
- The old parser helpers remain in `multi_format_adapter.py` but are no longer used by the public entry point.
- Tests assert canonical adapter metadata for text, markdown, table, DOCX, and PPTX paths.

Evidence metadata scan:

```powershell
rg -n "source_anchor|display_label|retrieval_source|confidence|why_selected|quality_report" backend\app backend\tests frontend\src
```

Result summary:

- Search and tool evidence still preserve `source_anchor`, `display_label`, `retrieval_source`, `confidence`, and `why_selected`.
- Phase 6 frontend code still consumes evidence labels and optional quality reports.
- Table aggregation citations now include `source_anchor` and `display_label`.

Legacy Office boundary scan:

```powershell
rg -n "\.xls|\.doc\b|\.ppt\b" backend\app\core\config.py backend\app\services\content_extraction_service.py backend\app\api\documents.py backend\app\services\document_service.py backend\tests\test_safe_upload_filenames.py
```

Result summary:

- `.doc`, `.xls`, and `.ppt` are not present in upload or content API allowlists.
- The only legacy Office hits are the explicit rejection test cases.

Parsing limit scan:

```powershell
rg -n "MULTIFORMAT_MAX_ROWS_PER_CHUNK|MULTIFORMAT_MAX_TABLE_CHUNKS_PER_SHEET|MULTIFORMAT_MAX_SHEETS_PER_WORKBOOK|MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE|MULTIFORMAT_MAX_SLIDES_PER_DECK|MAX_TEXT_LINES|MAX_TABLE_ROWS|MAX_PARAGRAPHS|MAX_SLIDES" backend\app\services\format_adapters backend\app\services\source_anchor_resolver.py
```

Result summary:

- New adapters have bounded row, sheet, slide, and text limits.
- Existing source-anchor resolver range limits remain in place for lines, rows, paragraphs, and slides.

## Independent Review And Gap Closure

An independent review found no P0 issues and two P1 gaps before final completion:

1. Table aggregation citations did not yet include canonical `source_anchor` and `display_label`.
2. Legacy `.doc`, `.xls`, and `.ppt` rejection was present in code but not locked by tests.

Both were fixed before final completion:

- `TableAnalysisService.aggregate()` now emits `source_anchor` and `display_label` in citations.
- `table_adapter.py` keeps table-level source anchors in public table datasets.
- `test_table_analysis_service.py` covers citation metadata and row provenance with skipped rows.
- `test_safe_upload_filenames.py` covers legacy Office rejection.

After these fixes:

- P1 closure focused tests: `6 passed`
- Phase 7 focused suite: `42 passed`
- Retrieval and citation contract suite: `14 passed`
- Full backend suite: `412 passed, 8 skipped`
- Frontend build: passed

## Completion Gate Result

The Phase 7 completion gate used:

- Latest user request.
- Phase 7 implementation plan.
- Next phase roadmap.
- Phase 1 through Phase 6 reports.
- Source multi-format support plan from `D:\projects\page_chat - 副本\docs\superpowers\plans\2026-06-10-multi-format-document-support-plan.md`.
- Current git status and recent commits.
- Current codebase state.
- Fresh focused, regression, full backend, and frontend build output.
- Actual `rg` project scans.
- Independent code-review feedback and P1 closure verification.

Findings:

- P0: none.
- P1: none after gap closure.
- P2: stale legacy parser helpers remain in `multi_format_adapter.py`.
- P2: canonical preview extraction still has an emergency fallback to older preview paths.

Decision:

- Phase 7 can be declared complete under the completion gate because required verification passed and no P0/P1 gaps remain.
- Task 6 legacy Office conversion is intentionally deferred to Phase 7b/P2.

## Working Tree Notes

At report time, the working tree includes Phase 7 backend adapter changes plus the pre-existing Phase 6/frontend/settings changes that were accepted as the current baseline for this work.

Notable Phase 7 files:

- `backend/app/services/format_adapters/text_adapter.py`
- `backend/app/services/format_adapters/markdown_adapter.py`
- `backend/app/services/format_adapters/table_adapter.py`
- `backend/app/services/format_adapters/word_adapter.py`
- `backend/app/services/format_adapters/presentation_adapter.py`
- `backend/app/services/format_adapters/__init__.py`
- `backend/app/services/multi_format_adapter.py`
- `backend/app/services/content_extraction_service.py`
- `backend/app/services/table_analysis_service.py`
- `backend/requirements.txt`
- `backend/tests/test_text_markdown_adapters.py`
- `backend/tests/test_table_adapter.py`
- `backend/tests/test_word_adapter.py`
- `backend/tests/test_presentation_adapter.py`
- `backend/tests/test_content_extraction_canonical.py`
- `backend/tests/test_table_analysis_service.py`
- `backend/tests/test_safe_upload_filenames.py`

Git reported a permission warning while scanning `backend/.pytest-tmp/`; this did not affect implementation or verification.

## Remaining Limitations

The following remain out of scope after Phase 7:

- Legacy `.doc`, `.xls`, and `.ppt` conversion.
- LibreOffice detection and converted artifact cleanup.
- OCR/VLM extraction for visual-heavy DOCX/PPTX content.
- Removing stale private parser helpers from `multi_format_adapter.py`.
- Turning parser limits into runtime configuration.
- Browser-driven upload and preview smoke tests with real Office files.

## Recommended Next Phase

Proceed to Phase 8: Document Management Production Redesign, unless the team wants to split out Phase 7b first for legacy Office conversion.

Recommended Phase 7b focus if chosen:

1. Add explicit detector and converter modules.
2. Detect LibreOffice availability without failing startup.
3. Keep `.doc`, `.xls`, and `.ppt` rejected when conversion is unavailable.
4. Store converted artifacts under a controlled directory.
5. Ensure document deletion and folder deletion remove converted artifacts.
6. Add focused conversion, rejection, and cleanup tests before adding legacy extensions to `ALLOWED_EXTENSIONS`.
