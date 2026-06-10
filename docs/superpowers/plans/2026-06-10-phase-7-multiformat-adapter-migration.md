# Phase 7 Multi-Format Adapter Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the multi-format adapter rewrite so TXT, Markdown, CSV/TSV, XLSX, DOCX, and PPTX share canonical parsing, preview, search, citation, and table-analysis data.

**Architecture:** Keep the mature PDF path unchanged. Migrate non-PDF formats one family at a time into `backend/app/services/format_adapters/`, using canonical `DocumentContent`, `IndexNode`, `ContentBlock`, and `SourceAnchor` outputs introduced in Phase 2.

**Tech Stack:** FastAPI backend, canonical format adapter package, `multi_format_adapter.py` compatibility facade, `ContentExtractionService`, `TableAnalysisService`, `DocumentSearchService`, pytest, `charset-normalizer`, `openpyxl`, `python-docx`, `python-pptx`.

---

## Entry Criteria

Start after Phase 2 is complete.

Required:

- Canonical adapter dataclasses exist.
- Existing adapters emit `unit_type` in anchors.
- Source-anchor resolver has tests for line/row anchors and explicit Office behavior.
- Full backend suite passes after Phase 2.
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md` is available as the adapter-contract baseline.

## Parsing Limits And Safety Rules

All new adapters must be bounded and deterministic.

Initial limits should be conservative and configurable where practical:

- Maximum rows indexed per table chunk.
- Maximum table chunks per sheet.
- Maximum sheets indexed per workbook before summary-only fallback.
- Maximum text characters per DOCX/PPTX node.
- Maximum slides inspected per PPTX before summary-only fallback.
- Maximum source-anchor resolver range for lines, rows, paragraphs, and slides.

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
- Modify: `backend/requirements.txt`
  - Add parser dependencies only when needed.
- Create: `backend/tests/test_text_markdown_adapters.py`
- Create: `backend/tests/test_table_adapter.py`
- Create: `backend/tests/test_word_adapter.py`
- Create: `backend/tests/test_presentation_adapter.py`
- Create: `backend/tests/test_content_extraction_canonical.py`
- Create: `backend/tests/test_legacy_office_conversion.py`

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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_text_markdown_adapters.py -q
```

- [ ] **Step 4: Implement adapters**

TXT should chunk by paragraphs first and line ranges second.

Markdown should use headings as tree boundaries and preserve code fences as content.

- [ ] **Step 5: Delegate from compatibility facade**

`generate_multi_format_index(file_path)` must keep its public API stable.

- [ ] **Step 6: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_text_markdown_adapters.py tests/test_multi_format_adapter.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_table_adapter.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_table_adapter.py tests/test_table_analysis_service.py tests/test_multi_format_adapter.py tests/test_source_anchor_resolution_office.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_word_adapter.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_word_adapter.py tests/test_multi_format_adapter.py tests/test_source_anchor_resolution_office.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_presentation_adapter.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_presentation_adapter.py tests/test_multi_format_adapter.py tests/test_source_anchor_resolution_office.py -q
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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_content_extraction_canonical.py -q
```

- [ ] **Step 3: Use canonical blocks**

Prefer adapter `ContentBlock` output. Keep direct extraction fallback only for old indexes or emergency compatibility.

- [ ] **Step 4: Run tests and frontend build**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_content_extraction_canonical.py -q
cd frontend
npm.cmd run build
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/content_extraction_service.py backend/app/api/documents.py backend/tests/test_content_extraction_canonical.py
git commit -m "feat: use canonical blocks for non-pdf preview"
```

## Task 6: Legacy Office Conversion Path

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
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_legacy_office_conversion.py -q
```

Tests should verify that deleting a converted legacy document removes both the uploaded source and converted artifact.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/format_adapters/detector.py backend/app/services/format_adapters/converter.py backend/app/core/config.py backend/app/services/document_service.py backend/app/api/documents.py backend/tests/test_legacy_office_conversion.py
git commit -m "feat: add legacy office conversion path"
```

## Task 7: Final Verification And Completion Gate

- [ ] **Step 1: Run focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_text_markdown_adapters.py tests/test_table_adapter.py tests/test_word_adapter.py tests/test_presentation_adapter.py tests/test_content_extraction_canonical.py tests/test_legacy_office_conversion.py tests/test_multi_format_adapter.py tests/test_table_analysis_service.py tests/test_source_anchor_resolution_office.py -q
```

- [ ] **Step 2: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 3: Run frontend build**

```powershell
cd frontend
npm.cmd run build
```

- [ ] **Step 4: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 7 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-multi-format-document-support-plan.md`
- Current git status.
- Test and build output from Steps 1-3.

## Done Criteria

Phase 7 is complete when:

- TXT, Markdown, CSV, TSV, XLSX, DOCX, and PPTX use canonical adapter outputs.
- `multi_format_adapter.py` remains a compatibility facade.
- Preview extraction uses canonical blocks where available.
- Table aggregation uses the table adapter dataset.
- Source-anchor resolver handles line, row, paragraph, and slide anchors with real parser-backed content.
- Large and malformed non-PDF files have bounded behavior and controlled errors.
- Visual-heavy DOCX/PPTX content is explicitly flagged instead of silently treated as fully extracted text.
- Legacy `.doc`, `.xls`, and `.ppt` remain rejected unless conversion support is enabled and tested.
- Focused and full backend tests pass.
- Frontend build passes.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Rewriting PDF PageIndex generation.
- Frontend production redesign.
- Model provider settings.
- Automatic OCR/VLM for visual-heavy DOCX/PPTX content.
