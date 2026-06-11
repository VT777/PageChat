# Phase 7 Multi-Format Adapter Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the multi-format adapter rewrite so TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX share canonical parsing, preview, search, citation, and table-analysis data.

**Architecture:** Keep the mature PDF path unchanged. Migrate non-PDF formats one family at a time into `backend/app/services/format_adapters/`, using canonical `DocumentContent`, `IndexNode`, `ContentBlock`, and `SourceAnchor` outputs introduced in Phase 2.

**Tech Stack:** FastAPI backend, canonical format adapter package, `multi_format_adapter.py` compatibility facade, `ContentExtractionService`, `TableAnalysisService`, `DocumentSearchService`, pytest, `charset-normalizer`, `openpyxl`, `python-docx`, `python-pptx`.

---

## Entry Criteria

Start after Phase 6 is complete and its working tree state is either committed or explicitly accepted as the current implementation baseline.

Required:

- Canonical adapter dataclasses exist in `backend/app/services/format_adapters/base.py`.
- `backend/app/services/format_adapters/__init__.py` exports the canonical adapter model.
- Existing non-PDF paths emit `unit_type` in anchors.
- Source-anchor resolver has tests for line/row anchors and explicit Office behavior.
- Phase 6 frontend evidence, preview, quality, scope, and settings contracts are available as the UI baseline.
- Full backend suite passes after Phase 6.
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md` is available as the adapter-contract baseline.
- `docs/superpowers/2026-06-11-phase-6-implementation-report.md` is available as the current frontend and verification baseline.

Do not rebuild the canonical base layer during Phase 7 unless a gap is found. Phase 7 should migrate concrete format adapters onto the existing canonical model and preserve `multi_format_adapter.py` as the compatibility facade.

Before implementation starts, check `git status --short`. If Phase 6 files are still uncommitted, either commit them first or record that Phase 7 is intentionally building on that dirty baseline. Do not mix unrelated Phase 6 frontend/settings cleanup into Phase 7 adapter commits.

## Phase 6 Contracts To Preserve

Phase 7 changes backend parsing internals, but it must not regress the frontend contracts made visible in Phase 6.

Preserve these response semantics:

- Prefer backend `display_label` when present.
- Keep `source_anchor` additive and format-aware.
- Preserve `retrieval_source`, `confidence`, and `why_selected` metadata through search and tool results.
- Keep `quality_report` optional and additive.
- Keep retrieval scope trace metadata independent from parser migration.
- Do not expose model provider secrets or route metadata secrets when adapter output includes model route metadata.

For user-visible evidence, the same labels should remain valid after migration:

- PDF: `report.pdf p.12-15`
- Markdown/TXT: `notes.md lines 20-42`
- DOCX: `contract.docx paragraphs 10-18`
- CSV/TSV/XLSX: `sales.xlsx Sheet1 rows 2-80`
- PPTX: `deck.pptx slide 7`

## End-To-End Migration Contract

Each migrated format is not complete when its adapter tests pass alone. It is complete only when the same canonical output can flow through:

- Index generation via `generate_multi_format_index(file_path)`.
- Preview extraction through `ContentExtractionService`.
- Source-anchor resolution through `source_anchor_resolver.py`.
- Search/index metadata preservation through `SearchService` where applicable.
- Agent/tool evidence resolution through `ToolExecutor` without breaking existing PDF `get_page_content`.
- Phase 6 frontend citation and preview labels without requiring frontend schema rewrites.

For each fixture family, add or update tests that compare index anchors and preview anchors for the same source content. This guards against parser drift returning one location in retrieval and a different location in preview.

## Parsing Limits And Safety Rules

All new adapters must be bounded and deterministic.

Initial limits should be conservative and configurable where practical:

- `MULTIFORMAT_MAX_ROWS_PER_CHUNK`: maximum rows indexed per table chunk.
- `MULTIFORMAT_MAX_TABLE_CHUNKS_PER_SHEET`: maximum table chunks per sheet.
- `MULTIFORMAT_MAX_SHEETS_PER_WORKBOOK`: maximum sheets indexed per workbook before summary-only fallback.
- `MULTIFORMAT_MAX_TEXT_CHARS_PER_NODE`: maximum text characters per TXT/Markdown/DOCX/PPTX node.
- `MULTIFORMAT_MAX_SLIDES_PER_DECK`: maximum slides inspected per PPTX before summary-only fallback.
- `SOURCE_ANCHOR_MAX_RANGE_UNITS`: maximum source-anchor resolver range for lines, rows, paragraphs, and slides.

If these are implemented as settings, place them with the existing backend configuration style. If they are implemented as module constants first, keep the names consistent so they can be promoted to configuration later without changing test intent.

Error handling rules:

- Corrupt files should return a controlled indexing error, not an unhandled parser exception.
- Large files should degrade to schema/sample/summary nodes before exhausting memory.
- Office ZIP/XML files should be treated as untrusted input. Tests should cover malformed archives and missing expected XML parts when practical.
- Parser warnings should be stored as metadata or quality flags when they affect evidence completeness.

Visual-heavy Office content should use a consistent metadata flag:

```json
{
  "needs_visual_enhancement": true,
  "visual_reason": "slide has little text and multiple image shapes"
}
```

Do not claim complete extraction for DOCX/PPTX content that is mainly images, charts, or embedded objects.

## Files And Responsibilities

- Create: `backend/app/services/format_adapters/text_adapter.py`
  - TXT encoding detection and line/paragraph chunks.
- Create: `backend/app/services/format_adapters/markdown_adapter.py`
  - Markdown heading tree, setext headings, code fence handling, line anchors.
- Create: `backend/app/services/format_adapters/table_adapter.py`
  - CSV/TSV/XLSX parsing, schema metadata, row-range nodes, aggregation datasets.
- Create: `backend/app/services/format_adapters/word_adapter.py`
  - DOCX headings, paragraphs, tables, paragraph anchors.
- Create: `backend/app/services/format_adapters/presentation_adapter.py`
  - PPTX slide text, tables, notes when available, visual-heavy flags.
- Create: `backend/app/services/format_adapters/detector.py`
  - Extension and future MIME/signature detection.
- Create: `backend/app/services/format_adapters/converter.py`
  - Future LibreOffice detection and legacy conversion path.
- Modify: `backend/app/services/multi_format_adapter.py`
  - Delegate to canonical adapters while preserving `generate_multi_format_index(file_path)`.
- Modify: `backend/app/services/content_extraction_service.py`
  - Use canonical blocks for preview.
- Modify: `backend/app/services/table_analysis_service.py`
  - Use table adapter datasets.
- Modify: `backend/app/services/source_anchor_resolver.py`
  - Replace explicit Office unsupported responses with real parser-backed resolution.
- Modify as needed: `backend/app/services/search_service.py`
  - Preserve canonical `source_anchor`, `display_label`, `retrieval_source`, `confidence`, and `why_selected` through indexed search segments.
- Modify as needed: `backend/app/services/tool_executor.py`
  - Resolve non-PDF source anchors without regressing existing `get_page_content` compatibility.
- Modify as needed: `backend/app/services/pageindex_service.py`
  - Ensure non-PDF indexing routes through the compatibility facade and keeps route/cache metadata additive.
- Modify: `backend/requirements.txt`
  - Add parser dependencies only when needed.
- Create: `backend/tests/test_text_markdown_adapters.py`
- Create: `backend/tests/test_table_adapter.py`
- Create: `backend/tests/test_word_adapter.py`
- Create: `backend/tests/test_presentation_adapter.py`
- Create: `backend/tests/test_content_extraction_canonical.py`
- Create if Task 6 is accepted into the main phase: `backend/tests/test_legacy_office_conversion.py`
- Modify as needed: `backend/tests/test_non_pdf_source_anchors.py`
- Modify as needed: `backend/tests/test_retrieval_trace_contract.py`
- Modify as needed: `backend/tests/test_retrieval_quality_regression.py`

## Task 1: Migrate TXT And Markdown

**Files:**

- Create: `backend/app/services/format_adapters/text_adapter.py`
- Create: `backend/app/services/format_adapters/markdown_adapter.py`
- Modify: `backend/app/services/multi_format_adapter.py`
- Modify: `backend/requirements.txt`
- Create: `backend/tests/test_text_markdown_adapters.py`

- [ ] **Step 1: Add dependency if absent**

Add:

```text
charset-normalizer
```

- [ ] **Step 2: Write failing adapter tests**

Cover:

- UTF-8 TXT.
- Non-UTF-8 TXT where fixture generation is practical.
- Markdown ATX headings.
- Markdown setext headings.
- Markdown code fences.
- Markdown without headings.
- Line `source_anchor` and `unit_type`.

- [ ] **Step 3: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_text_markdown_adapters.py -q
```

- [ ] **Step 4: Implement adapters**

TXT should chunk by paragraphs first and line ranges second.

Markdown should use headings as tree boundaries and preserve code fences as content.

- [ ] **Step 5: Delegate from compatibility facade**

`generate_multi_format_index(file_path)` must keep its public API stable.

- [ ] **Step 6: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_text_markdown_adapters.py backend\tests\test_multi_format_adapter.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/format_adapters/text_adapter.py backend/app/services/format_adapters/markdown_adapter.py backend/app/services/multi_format_adapter.py backend/tests/test_text_markdown_adapters.py backend/requirements.txt
git commit -m "feat: migrate text and markdown adapters"
```

## Task 2: Migrate CSV/TSV/XLSX And Table Aggregation

**Files:**

- Create: `backend/app/services/format_adapters/table_adapter.py`
- Modify: `backend/app/services/multi_format_adapter.py`
- Modify: `backend/app/services/table_analysis_service.py`
- Modify: `backend/app/services/source_anchor_resolver.py`
- Modify: `backend/requirements.txt`
- Create: `backend/tests/test_table_adapter.py`
- Modify: `backend/tests/test_table_analysis_service.py`
- Modify: `backend/tests/test_source_anchor_resolution_office.py`

- [ ] **Step 1: Add dependency if absent**

Add:

```text
openpyxl
```

- [ ] **Step 2: Write failing table adapter tests**

Cover:

- CSV headers and rows.
- TSV delimiter.
- XLSX single sheet.
- XLSX multiple sheets.
- Empty rows.
- Numeric type inference.
- Sheet and row-range source anchors.
- XLSX anchor resolution returns row content.
- Large-sheet chunk limits.
- Corrupt or unsupported workbook errors are controlled.

- [ ] **Step 3: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_table_adapter.py -q
```

- [ ] **Step 4: Implement table adapter**

Expose:

- Index nodes for retrieval.
- `ContentBlock` rows or row ranges for preview.
- Deterministic datasets for aggregation.

- [ ] **Step 5: Update `TableAnalysisService`**

Replace duplicated CSV/XLSX parsing with table adapter calls.

- [ ] **Step 6: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_table_adapter.py backend\tests\test_table_analysis_service.py backend\tests\test_multi_format_adapter.py backend\tests\test_source_anchor_resolution_office.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/format_adapters/table_adapter.py backend/app/services/multi_format_adapter.py backend/app/services/table_analysis_service.py backend/app/services/source_anchor_resolver.py backend/tests/test_table_adapter.py backend/tests/test_table_analysis_service.py backend/tests/test_source_anchor_resolution_office.py backend/requirements.txt
git commit -m "feat: unify table document parsing"
```

## Task 3: Migrate DOCX

**Files:**

- Create: `backend/app/services/format_adapters/word_adapter.py`
- Modify: `backend/app/services/multi_format_adapter.py`
- Modify: `backend/app/services/source_anchor_resolver.py`
- Modify: `backend/requirements.txt`
- Create: `backend/tests/test_word_adapter.py`
- Modify: `backend/tests/test_source_anchor_resolution_office.py`

- [ ] **Step 1: Add dependency if absent**

Add:

```text
python-docx
```

- [ ] **Step 2: Write DOCX fixture tests**

Generate fixtures in tests with `python-docx`.

Cover:

- Heading styles.
- Numbered heading fallback.
- Tables.
- No-heading documents.
- Long sections that need splitting.
- Paragraph anchors.
- DOCX anchor resolution returns paragraph content.
- Image-heavy documents set `needs_visual_enhancement` without pretending image content was extracted.
- Corrupt DOCX errors are controlled.

- [ ] **Step 3: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_word_adapter.py -q
```

- [ ] **Step 4: Implement DOCX adapter**

Extract:

- Core metadata.
- Paragraphs.
- Heading levels.
- Tables.
- Image references or image counts.

- [ ] **Step 5: Delegate from compatibility facade and resolver**

`generate_multi_format_index()` should use the DOCX adapter.

`resolve_source_anchor()` should resolve paragraph ranges.

- [ ] **Step 6: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_word_adapter.py backend\tests\test_multi_format_adapter.py backend\tests\test_source_anchor_resolution_office.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/format_adapters/word_adapter.py backend/app/services/multi_format_adapter.py backend/app/services/source_anchor_resolver.py backend/tests/test_word_adapter.py backend/tests/test_source_anchor_resolution_office.py backend/requirements.txt
git commit -m "feat: add docx canonical adapter"
```

## Task 4: Migrate PPTX

**Files:**

- Create: `backend/app/services/format_adapters/presentation_adapter.py`
- Modify: `backend/app/services/multi_format_adapter.py`
- Modify: `backend/app/services/source_anchor_resolver.py`
- Modify: `backend/requirements.txt`
- Create: `backend/tests/test_presentation_adapter.py`
- Modify: `backend/tests/test_source_anchor_resolution_office.py`

- [ ] **Step 1: Add dependency if absent**

Add:

```text
python-pptx
```

- [ ] **Step 2: Write PPTX fixture tests**

Generate fixtures in tests with `python-pptx`.

Cover:

- Title and body text.
- Tables.
- Empty slides.
- Visual-heavy slides.
- Slide anchors.
- PPTX anchor resolution returns slide text.
- Slide-count or text-size limits are enforced.
- Corrupt PPTX errors are controlled.

- [ ] **Step 3: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_presentation_adapter.py -q
```

- [ ] **Step 4: Implement PPTX adapter**

Extract:

- Slide title.
- Shape text.
- Table text.
- Speaker notes when available.
- Visual enhancement flags.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_presentation_adapter.py backend\tests\test_multi_format_adapter.py backend\tests\test_source_anchor_resolution_office.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/format_adapters/presentation_adapter.py backend/app/services/multi_format_adapter.py backend/app/services/source_anchor_resolver.py backend/tests/test_presentation_adapter.py backend/tests/test_source_anchor_resolution_office.py backend/requirements.txt
git commit -m "feat: add pptx canonical adapter"
```

## Task 5: Unify Preview Extraction

**Files:**

- Modify: `backend/app/services/content_extraction_service.py`
- Modify: `backend/app/api/documents.py`
- Create: `backend/tests/test_content_extraction_canonical.py`

- [ ] **Step 1: Write preview tests**

Ensure each non-PDF format returns canonical blocks and source anchors.

- [ ] **Step 2: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_content_extraction_canonical.py -q
```

- [ ] **Step 3: Use canonical blocks**

Prefer adapter `ContentBlock` output. Keep direct extraction fallback only for old indexes or emergency compatibility.

- [ ] **Step 4: Run tests and frontend build**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_content_extraction_canonical.py -q
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/content_extraction_service.py backend/app/api/documents.py backend/tests/test_content_extraction_canonical.py
git commit -m "feat: use canonical blocks for non-pdf preview"
```

## Task 6: Legacy Office Conversion Path (P2 / Phase 7b)

This task is optional for the main Phase 7 migration. The main Phase 7 can complete with legacy `.doc`, `.xls`, and `.ppt` still rejected, as long as current whitelisted formats are migrated and verified.

Only execute this task in the main Phase 7 if Tasks 1-5 are complete, focused/full verification is healthy, and there is capacity to test conversion, cleanup, and user-facing rejection behavior. Otherwise, record it as an accepted P2 follow-up or split it into a Phase 7b plan.

**Files:**

- Create: `backend/app/services/format_adapters/detector.py`
- Create: `backend/app/services/format_adapters/converter.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/document_service.py`
- Modify: `backend/app/api/documents.py`
- Create: `backend/tests/test_legacy_office_conversion.py`

- [ ] **Step 1: Write detection tests**

Cover `.doc`, `.xls`, and `.ppt` as unsupported unless conversion is enabled.

- [ ] **Step 2: Implement converter detection**

Detect LibreOffice headless availability without failing app startup.

- [ ] **Step 3: Implement conversion path**

Store converted artifacts under a controlled directory such as:

```text
backend/data/converted/
```

Converted artifacts must be linked to the source document ID so document deletion and reindex cleanup can remove them.

- [ ] **Step 4: Add whitelist entries only after conversion tests pass**

Only then allow:

- `.doc`
- `.xls`
- `.ppt`

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_legacy_office_conversion.py -q
```

Tests should verify that deleting a converted legacy document removes both the uploaded source and converted artifact.

If LibreOffice is unavailable in the local environment, tests should still verify the controlled rejection path and must not add legacy extensions to `ALLOWED_EXTENSIONS`.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/format_adapters/detector.py backend/app/services/format_adapters/converter.py backend/app/core/config.py backend/app/services/document_service.py backend/app/api/documents.py backend/tests/test_legacy_office_conversion.py
git commit -m "feat: add legacy office conversion path"
```

## Task 7: Final Verification And Completion Gate

- [ ] **Step 1: Run focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_text_markdown_adapters.py backend\tests\test_table_adapter.py backend\tests\test_word_adapter.py backend\tests\test_presentation_adapter.py backend\tests\test_content_extraction_canonical.py backend\tests\test_legacy_office_conversion.py backend\tests\test_multi_format_adapter.py backend\tests\test_table_analysis_service.py backend\tests\test_source_anchor_resolution_office.py -q
```

If Task 6 is deferred to Phase 7b, omit `backend\tests\test_legacy_office_conversion.py` from this command and record the deferral in the completion gate.

- [ ] **Step 2: Run retrieval and citation contract suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest backend\tests\test_non_pdf_source_anchors.py backend\tests\test_retrieval_trace_contract.py backend\tests\test_retrieval_quality_regression.py backend\tests\test_content_extraction_source_anchors.py -q
```

Expected coverage:

- Search results preserve canonical source anchors and display labels.
- Tool execution can resolve non-PDF anchors into bounded source content.
- Preview blocks and index nodes agree on line, row, paragraph, and slide anchors for representative fixtures.
- Phase 6 evidence label expectations remain valid.

- [ ] **Step 3: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 4: Run frontend build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 7 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-3-improvement-report.md`
- `docs/superpowers/2026-06-11-phase-4-improvement-report.md`
- `docs/superpowers/2026-06-11-phase-5-and-5-1-execution-report.md`
- `docs/superpowers/2026-06-11-phase-6-implementation-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-multi-format-document-support-plan.md`
- Current git status.
- Test and build output from Steps 1-4.

## Done Criteria

Phase 7 is complete when:

- TXT, Markdown, CSV, TSV, XLSX, DOCX, and PPTX use canonical adapter outputs.
- `multi_format_adapter.py` remains a compatibility facade.
- Preview extraction uses canonical blocks where available.
- Table aggregation uses the table adapter dataset.
- Source-anchor resolver handles line, row, paragraph, and slide anchors with real parser-backed content.
- Search and tool evidence preserve canonical `source_anchor` and `display_label` metadata.
- Phase 6 citation and source preview labels still work for migrated non-PDF formats.
- Index anchors and preview anchors are checked against the same fixtures for representative non-PDF formats.
- Large and malformed non-PDF files have bounded behavior and controlled errors.
- Visual-heavy DOCX/PPTX content is explicitly flagged instead of silently treated as fully extracted text.
- Legacy `.doc`, `.xls`, and `.ppt` remain rejected unless conversion support is enabled, tested, and cleanup-safe.
- Focused and full backend tests pass.
- Frontend build passes.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Rewriting PDF PageIndex generation.
- Frontend production redesign.
- Model provider settings.
- Automatic OCR/VLM for visual-heavy DOCX/PPTX content.
