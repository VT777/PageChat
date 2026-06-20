# TOC Quality Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore TOC generation quality for the 13 AI Knowledge PDFs by making routing deterministic, mapping verifiable, and quality gates strict enough to reject visibly wrong TOCs.

**Architecture:** Keep the unified state machine: preprocess to `PageTextMap`, then choose exactly one TOC path: `embedded_toc`, `visible_toc_with_pages`, `visible_toc_no_pages`, or `content_outline`. Rule extraction remains a high-precision fast subpath only; failed rule validation must fall back to LLM extraction. Physical page mapping is a separate post-processing step and final output must use physical pages.

**Tech Stack:** Python, PyMuPDF, existing `pageindex` modules, pytest, real PDF fixtures under `D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`.

---

## Reference Inputs

- Architecture: `D:\projects\page_chat\docs\architecture\toc_generation_unified_architecture.md`
- Test baseline: `D:\projects\page_chat\docs\architecture\ai_knowledge_toc_test_baseline.md`
- Expected TOC reference: `D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`
- Real PDFs: `D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`
- Current E2E reports: `D:\projects\page_chat\eval0618\phase9-e2e-final-v2`

## Files To Modify

- Modify: `D:\projects\page_chat\backend\pageindex\visible_toc_rule_extractor.py`
  - Rule extraction acceptance, fallback metadata, divider-page mapping semantics.
- Modify: `D:\projects\page_chat\backend\pageindex\judge\content_page_mapper.py`
  - Printed page mapping protection, strong title anchor rules, weak `outline_marker` handling.
- Modify: `D:\projects\page_chat\backend\pageindex\code_toc_quality.py`
  - Code TOC reliability scoring across bookmarks, links, and sections.
- Modify: `D:\projects\page_chat\backend\app\services\pageindex_service.py`
  - State machine fallback, child expansion, LLM QC hard failure, diagnostics.
- Modify: `D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
  - Route-aware hard gates and long flat chapter handling.
- Modify/Create tests under `D:\projects\page_chat\backend\tests`
  - Unit tests for mapping, rule fallback, code TOC quality, quality gates.
- Modify/Create diagnostics under `D:\projects\page_chat\scripts`
  - E2E assertions against the expected TOC reference.

## Task 0: Lock The TOC Reference

- [ ] **Step 0.1: Review the reference file**

Open `D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`.

Expected: every T01-T13 document has route, key evidence, expected top-level ranges, and either locked source-visible TOC items or explicit child-expansion obligations.

- [ ] **Step 0.2: Convert locked reference items into a test fixture**

Create: `D:\projects\page_chat\backend\tests\fixtures\toc\ai_knowledge_expected_toc_reference.json`.

The fixture must include:

```json
{
  "T09": {
    "required_route": "text -> visible_toc_with_pages",
    "required_sections": ["main_toc", "figure_toc", "table_toc"],
    "must_have_nodes": [
      {"title": "1.3、估值：持续新高，最新估值7500 亿美元", "start_index": 7, "end_index": 8}
    ]
  }
}
```

- [ ] **Step 0.3: Add fixture validation tests**

Create: `D:\projects\page_chat\backend\tests\test_ai_knowledge_expected_toc_reference.py`.

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_ai_knowledge_expected_toc_reference.py -q
```

Expected: PASS.

- [ ] **Step 0.4: Commit**

```powershell
git add docs/architecture/ai_knowledge_expected_toc_reference.md backend/tests/fixtures/toc/ai_knowledge_expected_toc_reference.json backend/tests/test_ai_knowledge_expected_toc_reference.py
git commit -m "test: lock ai knowledge toc reference"
```

## Task 1: Make Rule Extraction High Precision

- [ ] **Step 1.1: Write failing tests for rule fallback**

Tests:

- T03 rule extraction must not accept weak page-number semantics when many logical pages exceed physical page count or title anchors collapse to one page.
- T08/T11 rule extraction must either preserve Chinese parenthetical child items or reject the rule result and fall back to LLM.
- T13 code TOC noise must not be accepted as high-quality embedded TOC.

Run:

```powershell
py -X utf8 -m pytest backend/tests/test_visible_toc_rule_extractor.py backend/tests/test_code_toc_quality.py -q
```

Expected before implementation: FAIL.

- [ ] **Step 1.2: Implement rule acceptance contract**

In `visible_toc_rule_extractor.py`:

- Keep rule parsing strict.
- Treat incomplete hierarchy as low confidence.
- Require catalog section completeness for main/figure/table split.
- If page-number semantics are ambiguous, preserve extracted titles but mark mapping as unresolved; do not accept as `prevalidated=True`.
- For `visible_toc_with_pages`, do not set `allow_child_expansion=False` when the parser only produced top-level nodes from a source-visible multi-level TOC.

- [ ] **Step 1.3: Ensure LLM fallback is reachable**

In `pageindex_service.py`:

- If rule extraction returns `None`, low confidence, or validation failure, call LLM TOC extraction on confirmed TOC pages.
- Do not switch to old layout/VLM TOC paths after `PageTextMap` exists.

- [ ] **Step 1.4: Verify real files**

Run T03, T08, T11, T13 diagnostics one by one.

Expected:

- T03: no accepted result with 10-37 collapsed to page 40.
- T08/T11: source-visible `(一)/(二)` children are present, or route uses LLM fallback to produce them.
- T13: noisy bookmarks/table cells do not pass as clean embedded TOC.

- [ ] **Step 1.5: Commit**

```powershell
git add backend/pageindex/visible_toc_rule_extractor.py backend/app/services/pageindex_service.py backend/tests
git commit -m "fix: require validated visible toc rule results"
```

## Task 2: Protect Physical Page Mapping

- [ ] **Step 2.1: Write failing tests for mapping**

Cases:

- T09 `1.3` must remain on physical page 7 when printed TOC already gives page 7 and page 7 contains the title.
- T03 weak `outline_marker` cannot count as a strong title anchor.
- T05 repeated divider page must be treated as the next section start, not `divider + 1`.

- [ ] **Step 2.2: Implement strong-anchor rules**

In `content_page_mapper.py`:

- Do not override `printed_page_offset` with `outline_marker`.
- Allow override only when direct title match is strong and improves consistency.
- Count only direct title/fuzzy-title matches as true anchors.
- Treat generic number-only marker matches as weak evidence.

- [ ] **Step 2.3: Fix no-page divider semantics**

In `visible_toc_rule_extractor.py`:

- For repeated section divider pages, start the next section at the divider page.
- Do not exclude divider pages from the section they introduce.
- Preserve one-page boundary overlap only when boundary text evidence supports it.

- [ ] **Step 2.4: Verify real files**

Expected:

- T05 ranges: 3-8, 9-15, 16-17, 18-21.
- T09 `1.3` range: 7-8 or 7-9 depending boundary evidence, but never 4.
- T03 no mass collapse to page 40.

- [ ] **Step 2.5: Commit**

```powershell
git add backend/pageindex/judge/content_page_mapper.py backend/pageindex/visible_toc_rule_extractor.py backend/tests
git commit -m "fix: protect printed page mapping anchors"
```

## Task 3: Implement Chapter-Internal LLM Expansion

- [ ] **Step 3.1: Write failing tests for shallow no-page TOCs**

Cases:

- T04/T07/T12 must not finish as only top-level nodes.
- Flat top-level is acceptable only if the source TOC itself is flat and the document does not need child expansion.

- [ ] **Step 3.2: Replace deterministic page-title child expansion**

In `pageindex_service.py`:

- For `visible_toc_no_pages`, after top-level anchors are mapped, pass each chapter range to LLM with per-page snippets.
- Use simple input: physical page number + first 200 characters from `PageTextMap`.
- LLM outputs child nodes with physical start pages only.
- Post-process child ranges with the same boundary rules as top-level nodes.

- [ ] **Step 3.3: Keep deterministic extraction as evidence only**

`page_outline_extractor.py` may provide candidate headings, but it cannot be the only child tree producer for long chapters.

- [ ] **Step 3.4: Verify real files**

Expected:

- T04: top-level ranges match 3-12, 13-34, 35-48, 49-60, 61-68, with chapter-internal children.
- T07: Part01-Part05 remain correctly mapped and include useful subnodes.
- T12:序言 + 第一章到第八章 remain mapped and include chapter-internal children.

- [ ] **Step 3.5: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/pageindex/page_outline_extractor.py backend/tests
git commit -m "feat: expand shallow toc chapters with llm snippets"
```

## Task 4: Strengthen Code TOC Quality

- [ ] **Step 4.1: Write failing tests for T13-style noisy bookmarks**

Reject:

- Pure numbers.
- Dates as titles.
- Organization names from table cells.
- Long body sentences inside appendix tables.
- Main TOC polluted by table rows.

- [ ] **Step 4.2: Evaluate all sections, not only main TOC**

In `code_toc_quality.py`:

- Score `main_toc`, `figure_toc`, and `table_toc` independently.
- Merge bookmarks and links only when section evidence is consistent.
- Reject bookmarks if visible TOC/link evidence shows cleaner section structure.

- [ ] **Step 4.3: Verify real files**

Expected:

- T06 remains accepted via link-based embedded TOC.
- T13 either produces clean embedded main/table/figure sections or falls back to visible TOC extraction.
- T11 embedded bookmarks are rejected if they omit required figure catalog.

- [ ] **Step 4.4: Commit**

```powershell
git add backend/pageindex/code_toc_quality.py backend/pageindex/code_toc_collector.py backend/tests
git commit -m "fix: reject noisy embedded toc sections"
```

## Task 5: Make Quality Gates Route-Aware

- [ ] **Step 5.1: Write hard-fail tests**

Hard fail:

- Many nodes collapse to one non-TOC page.
- Direct title-match rate below route threshold.
- Source-visible child items are missing.
- Long shallow chapters without completed child expansion.
- LLM QC verdict fail during tuning mode.

- [ ] **Step 5.2: Implement route-aware checks**

In `balanced_quality_gate.py` and `index_quality.py`:

- `visible_toc_with_pages`: require strong title anchors and no weak-marker dominance.
- `visible_toc_no_pages`: require top-level anchors and child expansion for long spans.
- `embedded_toc`: require semantic title cleanliness and section completeness.
- `content_outline`: validate physical ranges and title/content fidelity.

- [ ] **Step 5.3: Re-enable LLM QC hard failure while tuning**

In `pageindex_service.py`:

- If LLM QC returns `needs_repair=True` with hard reasons, fail in current tuning mode.
- Keep a config switch for future advisory mode.

- [ ] **Step 5.4: Commit**

```powershell
git add backend/pageindex/balanced_quality_gate.py backend/pageindex/index_quality.py backend/app/services/pageindex_service.py backend/tests
git commit -m "fix: fail unusable toc quality results"
```

## Task 6: End-To-End Verification

- [ ] **Step 6.1: Run all 13 documents one by one**

Run the E2E script in sequential mode. Record elapsed time per file.

Expected:

- No file fails unexpectedly.
- Any failure has a clear hard-fail reason tied to the reference file.
- Output route and TOC tree match the expected reference.

- [ ] **Step 6.2: Generate review artifacts**

Create:

- JSON report under `D:\projects\page_chat\eval0618`
- HTML tree review under `D:\projects\page_chat\eval0618`
- Diff report against `ai_knowledge_expected_toc_reference.md`

- [ ] **Step 6.3: Manual review checkpoint**

Stop and report:

- per-file route
- elapsed time
- quality status
- mismatches against reference
- links to generated JSON/HTML artifacts

- [ ] **Step 6.4: Commit**

```powershell
git add backend docs scripts
git commit -m "test: verify ai knowledge toc e2e quality"
```

Do not commit `eval0618` generated run artifacts unless the user explicitly asks for those reports to be versioned.

## Acceptance Criteria

- T03 no longer accepts rule-mapped TOC with mass page-40 collapse.
- T04/T07/T12 are not flat-only when chapter-internal structure is required.
- T05 repeated divider pages map as section starts.
- T08/T11 preserve source-visible `(一)/(二)` child items.
- T09 printed physical pages are not overwritten by weak outline markers.
- T13 noisy appendix/table rows do not become TOC titles.
- LLM QC fail can block final index generation during this tuning phase.
- The 13-file E2E report includes route, elapsed time, TOC tree, quality status, and reference diff.
