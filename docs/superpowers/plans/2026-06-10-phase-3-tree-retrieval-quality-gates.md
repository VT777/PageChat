# Phase 3 Tree Retrieval Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tree retrieval quality measurable by adding index quality reports, conservative quality gates, and regression fixtures.

**Architecture:** Keep tree-first retrieval as the preferred evidence path. Store quality reports in index JSON first, avoid schema expansion unless frontend filtering requires it, and add tests that measure index structure, anchor coverage, fallback rate, and retrieval hit behavior.

**Tech Stack:** FastAPI backend, `PageIndexService`, `backend/pageindex/quality_validation.py`, SQLite document metadata, index JSON files, pytest fixtures.

---

## Entry Criteria

Start this phase only after Phase 2 is complete.

Required inputs:

- Non-PDF anchors include `unit_type`.
- Source-anchor display labels work.
- Search and tool outputs preserve source anchors.
- Full backend suite passes after Phase 2.

## Files And Responsibilities

- Modify: `backend/pageindex/quality_validation.py`
  - Add quality report builder and conservative scoring helpers.
- Modify: `backend/app/services/pageindex_service.py`
  - Attach `quality_report` to generated index JSON.
  - Set usable-but-weak PDF indexes to `needs_review` only if status semantics are confirmed.
- Modify: `backend/app/services/document_service.py`
  - Persist or expose quality report metadata if needed.
- Modify: `backend/app/models/schemas.py`
  - Add optional quality report fields for document detail responses if needed.
- Create: `backend/tests/test_pdf_index_quality_gates.py`
  - Unit tests for report scoring and status decisions.
- Create: `backend/tests/fixtures/evaluation/README.md`
  - Explain evaluation fixture policy.
- Create: `backend/tests/fixtures/evaluation/queries.json`
  - Fixed retrieval queries and expected anchors.
- Create: `backend/tests/test_index_quality_regression.py`
  - Regression tests for expected node and anchor quality.
- Create: `backend/tests/test_retrieval_quality_regression.py`
  - Regression tests for retrieval hit behavior.
- Create: `backend/tests/test_tree_first_retrieval_policy.py`
  - Tests for retrieval call order, fallback threshold behavior, and fallback disclosure metadata.

## Quality Report Contract

Preferred first storage location: index JSON under `quality_report`.

```json
{
  "status": "completed",
  "score": 0.91,
  "node_count": 48,
  "max_depth": 4,
  "page_range_coverage": 0.96,
  "duplicate_title_ratio": 0.03,
  "empty_summary_ratio": 0.0,
  "unmapped_pages": [2, 3],
  "anchor_confidence": 0.9,
  "visual_required_pages": 12,
  "visual_success_pages": 11,
  "warnings": []
}
```

Initial statuses:

- `completed`: usable and quality gates pass.
- `needs_review`: usable but one or more quality gates are weak.
- `failed:indexing`: unusable index.

If document status changes would break existing UI or workflows, keep database status as `completed` and store `quality_report.status = "needs_review"` until Phase 6.

## Task 1: Define Quality Report Builder

**Files:**

- Modify: `backend/pageindex/quality_validation.py`
- Create: `backend/tests/test_pdf_index_quality_gates.py`

- [ ] **Step 1: Write failing unit tests**

Cover:

- Good tree returns `completed`.
- Empty tree returns `failed:indexing`.
- Low page coverage returns `needs_review`.
- Duplicate/noisy titles lower score.
- Empty summaries lower score.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pdf_index_quality_gates.py -q
```

- [ ] **Step 3: Implement report builder**

Add a pure function:

```python
def build_index_quality_report(index_payload: dict, page_count: int | None = None) -> dict:
    ...
```

Keep thresholds conservative:

- `page_range_coverage < 0.7` -> `needs_review`
- `node_count == 0` -> `failed:indexing`
- `empty_summary_ratio > 0.5` -> `needs_review`
- `duplicate_title_ratio > 0.35` -> `needs_review`

- [ ] **Step 4: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pdf_index_quality_gates.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/pageindex/quality_validation.py backend/tests/test_pdf_index_quality_gates.py
git commit -m "feat: add index quality report builder"
```

## Task 2: Attach Quality Report To Index Output

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/tests/test_pdf_index_quality_gates.py`

- [ ] **Step 1: Add integration test**

Test that generated or saved index payloads include `quality_report`.

- [ ] **Step 2: Run test and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pdf_index_quality_gates.py -q
```

- [ ] **Step 3: Attach report before saving index JSON**

Call `build_index_quality_report()` after structure generation and before index persistence.

Do not change PDF extraction logic.

- [ ] **Step 4: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pdf_index_quality_gates.py tests/test_retrieval_trace_contract.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/tests/test_pdf_index_quality_gates.py
git commit -m "feat: persist index quality reports"
```

## Task 3: Add Evaluation Fixtures

**Files:**

- Create: `backend/tests/fixtures/evaluation/README.md`
- Create: `backend/tests/fixtures/evaluation/queries.json`
- Create: `backend/tests/test_index_quality_regression.py`
- Create: `backend/tests/test_retrieval_quality_regression.py`

- [ ] **Step 1: Create fixture README**

Document:

- Fixture purpose.
- How to add new documents.
- Expected query format.
- Rule that fixtures must remain small and deterministic.

- [ ] **Step 2: Add query manifest**

Start with synthetic or existing lightweight fixtures.

Example:

```json
[
  {
    "id": "markdown_heading_lookup",
    "format": "markdown",
    "query": "Where is the deployment checklist?",
    "expected_title_contains": "Deployment",
    "expected_unit_type": "line"
  }
]
```

- [ ] **Step 3: Write regression tests**

Tests should assert:

- Required nodes exist.
- Anchors have correct unit types.
- Retrieval returns expected document or node in top results.
- Fallback rate is recorded.

- [ ] **Step 4: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_index_quality_regression.py tests/test_retrieval_quality_regression.py -q
```

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/fixtures/evaluation backend/tests/test_index_quality_regression.py backend/tests/test_retrieval_quality_regression.py
git commit -m "test: add retrieval quality regression fixtures"
```

## Task 4: Add Tree-First Retrieval Policy

**Files:**

- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/services/pageindex_service.py`
- Modify: `backend/app/prompts/__init__.py`
- Create: `backend/tests/test_tree_first_retrieval_policy.py`

- [ ] **Step 1: Write failing policy tests**

Cover:

- Selected document question inspects tree structure before source content.
- Broad library question finds candidate documents before inspecting structure.
- Fallback is allowed only when tree results are empty, low confidence, marked `needs_review`, or the user explicitly asks for broad keyword search.
- Fallback evidence keeps `retrieval_source` as `keyword_fallback` or `visual_summary`.
- Final evidence metadata exposes that fallback contributed when it did.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_tree_first_retrieval_policy.py -q
```

- [ ] **Step 3: Define policy constants**

Add conservative constants near the retrieval decision code:

```python
TREE_HIGH_CONFIDENCE_THRESHOLD = 0.65
TREE_FALLBACK_CONFIDENCE_THRESHOLD = 0.35
```

If the existing code already has thresholds, reuse them instead of adding duplicates.

- [ ] **Step 4: Update Agent/tool prompt**

The prompt should instruct the agent to:

- Prefer document structure before source content when a document is selected.
- Use search only to identify candidate documents when no document is selected.
- Fetch source content before final answer.
- Mention uncertainty when fallback evidence materially contributes.

- [ ] **Step 5: Implement policy guardrails**

Keep behavior additive and compatible:

- Do not remove existing tools.
- Do not block manual user requests for keyword search.
- Add metadata that explains fallback usage.

- [ ] **Step 6: Run focused tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_tree_first_retrieval_policy.py tests/test_retrieval_trace_contract.py tests/test_tools_prompt_catalog.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/agent_service.py backend/app/services/tool_executor.py backend/app/services/pageindex_service.py backend/app/prompts/__init__.py backend/tests/test_tree_first_retrieval_policy.py
git commit -m "feat: enforce tree-first retrieval policy"
```

## Task 5: Final Verification And Completion Gate

- [ ] **Step 1: Run focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pdf_index_quality_gates.py tests/test_index_quality_regression.py tests/test_retrieval_quality_regression.py tests/test_retrieval_trace_contract.py tests/test_tree_first_retrieval_policy.py -q
```

- [ ] **Step 2: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 3: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 3 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-core-tree-retrieval-quality-plan.md`
- Current git status.
- Test output from Steps 1-2.

## Done Criteria

Phase 3 is complete when:

- Every new index payload can include `quality_report`.
- Quality report builder is covered by unit tests.
- Weak but usable indexes have a measurable status.
- Regression fixtures exist and can detect retrieval quality drift.
- Tree-first retrieval policy is explicit and covered by call-order/fallback tests.
- Fallback usage is visible through retrieval metadata and prompt behavior.
- Focused and full backend tests pass.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Full frontend display of quality status.
- Aggressive threshold tuning.
- Replacing PageIndex tree generation.
- Persisting quality report columns in SQLite unless necessary.
