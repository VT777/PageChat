# Phase 3 Improvement Report

Date: 2026-06-10

Push verification: 2026-06-11 Asia/Shanghai

## Executive Summary

Phase 3 made tree retrieval quality measurable and made the preferred retrieval behavior explicit.

The main outcome is that PDF index payloads can now carry a `quality_report`, weak-but-usable indexes are represented as measurable metadata instead of being silently treated as equivalent to strong indexes, document APIs expose quality metadata as optional additive fields, regression fixtures exist for retrieval quality drift, and the agent prompt now states a tree-first retrieval policy with visible fallback expectations.

Fresh verification after Phase 3:

- Phase 3 focused backend suite: `19 passed`
- Full backend suite: `308 passed, 8 skipped`
- `git diff --check`: passed with only LF/CRLF warnings
- Completion gate audit: passed with no P0/P1/P2 blocking gaps
- Pushed commit: `e8ce754 feat: add phase 2 and 3 retrieval foundations`

## What Changed

### 1. Index Quality Report Builder

Phase 3 added quality-report generation in `backend/pageindex/quality_validation.py`.

Implemented capabilities:

- Added `build_index_quality_report(index_payload, page_count=None)`.
- Computes `status`, `score`, `node_count`, `max_depth`, `page_range_coverage`, `duplicate_title_ratio`, `empty_summary_ratio`, `unmapped_pages`, `anchor_confidence`, visual page counts, and warnings.
- Marks empty or unusable trees as `failed:indexing`.
- Marks weak but usable trees as `needs_review`.
- Keeps strong trees as `completed`.

Effect:

- Tree quality is now inspectable as structured data.
- Regression tests can reason about quality drift without relying on subjective answer wording.
- `needs_review` is stored in `quality_report.status`, not promoted to the database document status in this phase.

### 2. Quality Report Persistence On PDF Index Payloads

Phase 3 connected the quality report to index persistence in `backend/app/services/pageindex_service.py`.

Implemented capabilities:

- Added `TREE_HIGH_CONFIDENCE_THRESHOLD = 0.65`.
- Added `TREE_FALLBACK_CONFIDENCE_THRESHOLD = 0.35`.
- Added `_attach_index_quality_report()`.
- Attached `quality_report` before saving PDF index JSON payloads.
- Preserved compatibility for old indexes without `quality_report`.
- Preserved existing document status semantics for weak but usable indexes.

Effect:

- New PDF index payloads can include quality metadata.
- Legacy index payloads without quality metadata still load normally.
- Current list/detail/status workflows are not forced to understand a new top-level document status before the frontend is ready.

Audit note:

- The completion scan found a gap where a PDF payload produced by `_generate_index_v2()` could carry `doc_name` without a separate `format` field. `_attach_index_quality_report()` now treats payloads with `doc_name` or `document_name` ending in `.pdf` as PDF payloads, and the behavior is covered by tests.

### 3. Document API Quality Metadata

Phase 3 exposed index quality metadata through the document response path.

Implemented capabilities:

- Added optional `quality_report` to `DocumentResponse`.
- Loaded `quality_report` from index metadata in `_load_index_meta_brief()`.
- Attached `quality_report` in `_attach_parse_meta()`.
- Kept the field optional and nullable.

Effect:

- Existing clients that ignore the field remain compatible.
- Phase 6 can display quality state without changing the backend contract first.
- Missing `quality_report` means "not measured yet" rather than failure.

### 4. Evaluation Fixtures And Regression Tests

Phase 3 added deterministic evaluation fixtures under `backend/tests/fixtures/evaluation/`.

Implemented capabilities:

- Added fixture policy documentation in `README.md`.
- Added `queries.json` with expected query metadata.
- Added index-quality regression tests.
- Added retrieval-quality regression tests.
- Avoided network calls, external model calls, and large binary fixtures.

Effect:

- Retrieval quality can be checked in the normal backend test suite.
- Future fixture additions have a documented policy.
- Expected anchors and unit types are now part of regression coverage.

### 5. Tree-First Retrieval Policy

Phase 3 made the retrieval policy explicit in `backend/app/prompts/__init__.py`.

Implemented capabilities:

- The prompt instructs selected-document flows to use `get_document_structure before get_page_content`.
- Broad-library flows use `find_related_documents` only to identify candidate documents before structure inspection.
- Factual answers should fetch source content before final answer.
- `keyword_fallback` and `visual_summary` are reserved for empty, low-confidence, `needs_review`, or explicitly broad keyword-search scenarios.
- Material fallback contribution should be disclosed with uncertainty.

Effect:

- Agent behavior is guided toward tree-first evidence gathering.
- Fallback behavior is not hidden as if it were normal tree retrieval.
- The policy is covered by tests that check constants and prompt contract text.

## Verification Evidence

Phase 3 focused backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pdf_index_quality_gates.py tests/test_document_quality_report_api.py tests/test_index_quality_regression.py tests/test_retrieval_quality_regression.py tests/test_retrieval_trace_contract.py tests/test_tree_first_retrieval_policy.py -q
```

Result:

```text
19 passed, 51 warnings
```

Full backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
308 passed, 8 skipped, 77 warnings
```

Note:

- One full-suite run produced a single transient failure in `tests/test_index_queue.py::test_start_index_process_queues_when_worker_busy`.
- The failure was investigated as a thread scheduling race: the queue state reached `running=1` before the monkeypatched `started.append()` executed.
- The individual test passed on rerun, and the full backend suite passed on the next run.
- No production code was changed for that unrelated flaky test.

Whitespace check:

```powershell
git diff --check
```

Result:

```text
passed with only LF/CRLF warnings
```

## Completion Gate Audit

The completion gate defined in `docs/superpowers/completion-gate-gap-audit.md` was run after Phase 3 implementation.

Audit inputs:

- Latest user request.
- `docs/superpowers/plans/2026-06-10-phase-3-tree-retrieval-quality-gates.md`
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- Current codebase state.
- Focused backend suite output.
- Full backend suite output.
- Actual code scan output.

Actual code scans performed included:

```powershell
rg -n "quality_report|TREE_HIGH_CONFIDENCE_THRESHOLD|tree-first retrieval policy|get_document_structure before get_page_content|build_index_quality_report|queries.json" backend docs frontend
rg -n "quality_report" backend/app backend/pageindex backend/tests frontend/src/types
rg -n "TREE_HIGH_CONFIDENCE_THRESHOLD|TREE_FALLBACK_CONFIDENCE_THRESHOLD|keyword_fallback|visual_summary|disclose fallback evidence" backend/app backend/tests
rg -n "build_index_quality_report|page_range_coverage|duplicate_title_ratio|empty_summary_ratio|failed:indexing|needs_review" backend/pageindex backend/tests
rg -n "fixtures/evaluation|expected_unit_type|allow_fallback" backend/tests docs/superpowers
```

Audit result:

- No P0 gaps.
- No P1 gaps.
- No completion-blocking P2 gaps.

Audit note:

- `git status` reports a permission warning for `backend/.pytest-tmp/`. This is a local directory access warning during status scanning and did not affect verification.

## Planning Impact

Phase 3 establishes quality gates as additive metadata rather than disruptive workflow state.

This means later phases should assume:

- `quality_report` is the canonical first-stage quality signal.
- `quality_report.status = "needs_review"` can be displayed by the frontend without changing document lifecycle status.
- Search and answer logic should treat weak index quality as a reason to disclose fallback evidence.
- New retrieval fixtures should stay deterministic and small enough for the normal backend suite.
- Thresholds are conservative starting points and should be tuned only with additional evaluation evidence.

## Remaining Limitations

These are intentionally not solved in Phase 3:

- Full frontend display of quality status.
- Aggressive quality threshold tuning.
- Replacing PageIndex tree generation.
- Persisting denormalized quality columns in SQLite.
- Public UI controls for fallback strategy.
- A public `get_content_by_anchor` tool.
- Rich non-PDF parser migration.
- Production dashboarding for quality trends.

### Follow-Up Ownership

| Limitation | Follow-up owner |
| --- | --- |
| Full frontend display of quality status | Phase 6: frontend evidence and settings integration |
| Aggressive quality threshold tuning | Future evaluation work after more fixtures or production samples exist |
| Replacing PageIndex tree generation | Not scheduled; preserve current PDF path unless a later quality effort justifies replacement |
| Persisting denormalized quality columns in SQLite | Future backend/API filtering work only if list filtering or reporting needs it |
| Public UI controls for fallback strategy | Phase 6 or later, after fallback metadata is visible and stable |
| A public `get_content_by_anchor` tool | Phase 7 if non-PDF anchor resolution needs direct tool access |
| Rich non-PDF parser migration | Phase 7: multi-format adapter migration |
| Production dashboarding for quality trends | Future operations/observability phase |

## Recommended Next Phases

### Phase 4: Folder-Aware Agent Retrieval

Recommended scope:

- Extend chat scope from single document selection to folders and selected document sets.
- Keep retrieval trace metadata explicit when scope expands.
- Preserve tree-first behavior inside each selected document.

Why now:

- Phase 3 makes tree quality visible, which helps folder-scope retrieval decide when to trust structure and when to disclose fallback evidence.

### Phase 6: Frontend Evidence And Settings Integration

Recommended scope:

- Display `quality_report.status`, score, warnings, and source labels.
- Treat unknown or missing quality report values as neutral optional metadata.
- Surface fallback evidence without making normal answers noisy.

Why next for UI:

- The backend now exposes enough metadata for a useful, non-breaking frontend quality display.

## Commit And Push

The Phase 3 implementation was pushed as part of:

```text
e8ce754 feat: add phase 2 and 3 retrieval foundations
```

Branch:

```text
vt_0610 -> origin/vt_0610
```
