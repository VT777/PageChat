# Phase 2 Improvement Report

Date: 2026-06-10

## Executive Summary

Phase 2 stabilized the source-anchor and current multi-format evidence foundation.

The main outcome is that current non-PDF index paths now emit explicit `source_anchor.unit_type`, Markdown indexing no longer contains the DOCX-only fallback defect, a canonical adapter data model exists for later parser migration, source anchors can be resolved to bounded source content, non-PDF anchors propagate through search/tool outputs, and preview blocks now carry source anchors without breaking the frontend build.

Fresh verification after Phase 2:

- Phase 2 focused backend suite: `37 passed`
- Full backend suite: `293 passed, 8 skipped`
- Frontend compatibility build: passed from `frontend/` with `npm.cmd run build`
- Completion gate audit: passed with no P0/P1 gaps

## What Changed

### 1. Markdown Adapter Stabilization

Phase 2 removed a concrete Markdown adapter defect in `backend/app/services/multi_format_adapter.py`.

Implemented capabilities:

- Removed the Markdown fallback block that referenced DOCX-only `paragraphs`.
- Preserved the Markdown line-based fallback path.
- Added regression coverage for ATX headings, setext headings, code fences, no-heading Markdown, and line-anchor metadata.

Effect:

- Markdown indexing no longer risks failing by entering a DOCX-specific fallback path.
- Heading-like text inside fenced code blocks is not promoted as a TOC heading.
- Markdown nodes now expose line-based anchors consistently.

### 2. Current Non-PDF Anchor Normalization

Phase 2 normalized anchors emitted by the current adapter paths.

Implemented capabilities:

- TXT and Markdown anchors include `unit_type: "line"`.
- CSV and TSV anchors include `unit_type: "row_range"`.
- XLSX anchors include `unit_type: "row_range"` and `sheet` where known.
- DOCX anchors include `unit_type: "paragraph"`.
- PPTX anchors include `unit_type: "slide"` plus `start_slide` and `end_slide`.

Effect:

- Search, tools, preview, and future citation UI can distinguish lines, rows, paragraphs, slides, and pages without guessing from `start_index` / `end_index`.
- Existing compatibility fields remain present.

### 3. Canonical Adapter Data Structures

Phase 2 added the first canonical adapter package under `backend/app/services/format_adapters/`.

Implemented capabilities:

- `SourceAnchor`
- `ContentBlock`
- `IndexNode`
- `DocumentContent`
- `FormatCapabilities`
- `document_content_to_index()`

Effect:

- Phase 7 can migrate TXT/Markdown, table, DOCX, PPTX, and legacy conversion adapters toward a shared output contract.
- Current adapter behavior is not rewritten in Phase 2; the new structures are a target and compatibility layer.

### 4. Source Anchor Resolver

Phase 2 added `backend/app/services/source_anchor_resolver.py`.

Implemented capabilities:

- Resolves TXT and Markdown line ranges.
- Resolves CSV and TSV row ranges.
- Resolves XLSX sheet row ranges through the current ZIP/XML path.
- Resolves DOCX paragraph ranges through the current ZIP/XML path.
- Resolves PPTX slide ranges through the current ZIP/XML path.
- Returns explicit errors for unsupported anchor types.
- Returns an explicit `unsupported` response for PDF page anchors because PDF evidence remains handled by the existing page-content path.
- Bounds reads with maximum line, row, paragraph, and slide limits.

Effect:

- Non-PDF evidence can now be resolved by `source_anchor` instead of pretending every format is page-based.
- Resolver behavior is deterministic and covered by tests.
- Phase 7 can replace the current ZIP/XML Office resolution with richer parser-backed content without changing the resolver contract.

### 5. ToolExecutor Internal Integration

Phase 2 connected source-anchor resolution to `ToolExecutor` as an internal helper.

Implemented capabilities:

- Added `_resolve_source_anchor_content(doc, source_anchor)`.
- The helper resolves content from the current document file path and original document name.
- No new public agent tool was exposed in Phase 2.

Effect:

- Existing tool flows remain compatible.
- Later retrieval/planner work can resolve non-PDF evidence without changing the public tool catalog first.

### 6. Search And Tool Output Propagation

Phase 2 improved anchor propagation in `DocumentSearchService` and verified `ToolExecutor` output.

Implemented capabilities:

- Search preserves adapter-provided anchors.
- Search safely infers missing `unit_type` for legacy-style anchors when line, paragraph, row, slide, or page fields make the unit clear.
- Search trace output includes `source_anchor`, `display_label`, `retrieval_source`, `confidence`, and `why_selected`.
- `find_related_documents` preserves non-PDF matched segment anchors and display labels.
- Row-range display labels without a sheet now render as `document.csv rows x-y`.

Effect:

- Non-PDF matched segments can be cited and previewed with format-aware labels.
- Existing response fields such as `start_index` and `end_index` remain present.

### 7. Preview Anchor Compatibility

Phase 2 added source anchors to preview blocks without changing the existing preview shape.

Implemented capabilities:

- TXT preview blocks include line anchors.
- Markdown preview blocks include line anchors.
- CSV/TSV preview blocks include row anchors.
- XLSX sheet preview blocks include sheet row-range anchors.
- DOCX paragraph preview blocks include paragraph anchors.
- PPTX slide preview blocks include slide anchors.
- Frontend `preview.ts` now allows `ContentBlock.source_anchor` and includes `unit_type`, `start_slide`, and `end_slide` in `SourceAnchor`.

Effect:

- Preview consumers can locate non-PDF content through the same anchor contract used by search and tools.
- Existing frontend build remains compatible.

## Verification Evidence

Phase 2 focused backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_multi_format_adapter.py tests/test_format_adapter_base.py tests/test_source_anchor_resolution.py tests/test_non_pdf_source_anchors.py tests/test_content_extraction_source_anchors.py tests/test_find_related_documents_modes.py tests/test_retrieval_trace_contract.py tests/test_source_anchor_resolution_office.py tests/test_tool_executor_scope.py -q
```

Result:

```text
37 passed
```

Full backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
293 passed, 8 skipped
```

Frontend compatibility build:

```powershell
cd frontend
npm.cmd run build
```

Result:

```text
vite build completed successfully
```

Note: the first frontend build attempt failed with `spawn EPERM` under sandboxed execution. The same command passed after running with the required permission to spawn Vite/esbuild child processes.

## Completion Gate Audit

The completion gate defined in `docs/superpowers/completion-gate-gap-audit.md` was run after implementation.

Audit inputs:

- Latest user request.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/plans/2026-06-10-phase-2-source-anchor-multiformat-foundation.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- Current git status and recent commits.
- Current codebase state.
- Focused backend suite, full backend suite, and frontend build output.

Actual code scans performed:

```powershell
rg -n "ToolExecutor\(|search_service\.search\(|get_indexed_documents\(|get_document\(" backend/app backend/tests
rg -n "retrieval_source|source_anchor|confidence|why_selected|display_label|resolve_source_anchor|unit_type" backend/app backend/tests frontend/src/types
rg -n "start_paragraph" backend/app/services/multi_format_adapter.py
rg -n "for p in paragraphs" backend/app/services/multi_format_adapter.py
rg -n "unit_type" backend/app/services/multi_format_adapter.py backend/tests/test_multi_format_adapter.py
rg -n "source_anchor" backend/app/services/multi_format_adapter.py backend/app/services/content_extraction_service.py backend/app/services/search_service.py backend/app/services/source_anchor_resolver.py frontend/src/types/preview.ts
```

Audit result:

- No P0 gaps.
- No P1 gaps.
- No completion-blocking P2 gaps.

Audit note:

- `git status` reports a permission warning for `backend/.pytest-tmp/`. This is a local directory access warning during status scanning and did not affect test or build verification.

## Planning Impact

Phase 2 turns non-PDF evidence location into a shared contract:

- New adapter work should emit `source_anchor` with `format` and `unit_type`.
- Search and tools should preserve `source_anchor` and `display_label`.
- Preview blocks may carry `source_anchor` as additive metadata.
- `start_index` and `end_index` remain compatibility fields but should not be treated as the canonical location for non-PDF formats.
- Source resolution must remain bounded to the requested range.

This means later work can focus on quality, routing, and richer parsing instead of first inventing citation semantics for every format.

## Remaining Limitations

These are intentionally not solved in Phase 2:

- Full parser migration to dedicated TXT/Markdown, table, DOCX, PPTX, and legacy Office adapters.
- Rich DOCX table, image, style, and metadata extraction.
- Rich XLSX formula, merged-cell, chart, and large-sheet handling.
- Rich PPTX speaker-note and visual-heavy slide handling.
- Legacy `.doc`, `.xls`, and `.ppt` conversion.
- Exposing a new public `get_content_by_anchor` agent tool.
- Tree-first retrieval policy and quality gates.
- Frontend evidence UI redesign.

## Recommended Next Phases

### Phase 3: Tree Retrieval Quality Gates

Recommended scope:

- Add PDF index quality reports.
- Add evaluation fixtures and retrieval regression tests.
- Make tree-first retrieval policy explicit.
- Make fallback use visible and thresholded.

Why now:

- Phase 2 made evidence anchors consistent enough for quality measurement and source validation.

### Phase 7: Multi-Format Adapter Migration

Recommended scope:

- Migrate TXT/Markdown, CSV/TSV/XLSX, DOCX, and PPTX into canonical adapters.
- Reuse the `DocumentContent`, `IndexNode`, `ContentBlock`, and `SourceAnchor` contract.
- Replace current Office ZIP/XML resolver paths with parser-backed resolution where needed.

Why later:

- Phase 2 deliberately stabilized current paths first. Phase 7 can now migrate format families one at a time without changing the evidence contract.

### Phase 6: Frontend Evidence Integration

Recommended scope:

- Display anchor-aware labels in chat and preview.
- Use backend `display_label` when available.
- Fall back to frontend `SourceAnchor` formatting when needed.

Why later:

- Backend search, tool, and preview responses now expose the metadata the frontend needs.

## Suggested Immediate Follow-Ups

1. Start Phase 3 with the Phase 2 focused suite as a regression baseline.
2. In Phase 7, replace the current Office ZIP/XML extraction with parser-backed adapters while preserving `source_anchor` output.
3. Consider exposing anchor resolution as a public tool only after the retrieval planner can decide when source-anchor content is preferable to page-based content.
4. Keep row, line, paragraph, and slide labels consistent between backend `display_label` and frontend fallback formatting.
