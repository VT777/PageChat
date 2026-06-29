# Phase 5.1 Indexing Route Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Phase 5 P2 gap by routing PageIndex indexing, node-summary, verification, and vision-like indexing model calls through user-aware model settings when a user context exists.

**Architecture:** Carry `user_id` from upload/reindex entry points into background indexing jobs, let `PageIndexService` resolve the Phase 5 `indexing` and `vision` route slots through `ModelSettingsService`, and keep environment Qwen/DashScope behavior as fallback. Do not add Phase 6 frontend UI in this slice.

**Tech Stack:** FastAPI backend, SQLite/aiosqlite, existing `ModelSettingsService`, `ModelGateway`, `app.core.llm`, `PageIndexService`, pytest.

---

## Why This Plan Exists

Phase 5 completed the backend model-settings foundation and passed the completion gate with one accepted P2 follow-up:

- Deep PageIndex indexing and verification calls still include direct `async_chat_completion()` paths.
- Background indexing jobs currently preserve `doc_id`, `file_path`, and `mode_override`, but not the authenticated user's model-settings context.
- `PageIndexService` currently creates direct LLM calls and a bare `ModelGateway()` without `user_id` or `model_settings_service`.

This plan closes that gap before Phase 6 exposes indexing model controls as a production guarantee.

## Entry Criteria

Start after Phase 5 is present in the working tree:

- `backend/app/services/model_settings_service.py` exists.
- `backend/app/services/litellm_adapter.py` exists.
- `backend/app/core/llm.py` supports `provider_config`.
- `backend/app/services/model_gateway.py` accepts `model_settings_service` and `user_id`.
- Phase 5 report exists at `docs/superpowers/2026-06-11-phase-5-improvement-report.md`.

Do not start Phase 6 frontend model-settings UI in this plan.

## Scope

In scope:

- Preserve authenticated `user_id` through upload and reindex indexing jobs.
- Resolve the `indexing` route for PageIndex text model calls.
- Resolve the `vision` route for PageIndex visual enrichment calls.
- Keep environment fallback when no user route exists or no user context is available.
- Add tests proving configured indexing/vision routes are used.
- Add tests proving background jobs preserve user context.
- Add tests proving fallback remains stable.
- Record route/version metadata in generated index output where practical and non-breaking.

Out of scope:

- Frontend model settings UI.
- Live provider model discovery.
- LiteLLM Proxy.
- Billing, quotas, budgets, or virtual keys.
- Reworking PageIndex internals beyond the call boundaries needed for routing.
- Changing retrieval authorization semantics.

## Current Code Findings To Address

- `backend/app/services/pageindex_service.py:161`
  - `PageIndexService.__init__` has no `user_id` or model-settings dependency.
- `backend/app/api/documents.py:305`
  - `_run_index_job()` accepts only `doc_id`, `file_path`, and `mode_override`.
- `backend/app/api/documents.py:378`
  - `_enqueue_index_job()` stores only `doc_id`, `file_path`, and `mode_override`.
- `backend/app/api/documents.py:423`
  - `start_index_process()` cannot receive or forward `user_id`.
- `backend/app/api/documents.py:820`
  - upload starts indexing without user context.
- `backend/app/api/documents.py:1091`
  - reindex starts indexing without user context.
- `backend/app/services/pageindex_service.py:80`
  - `check_query_appearance()` calls `async_chat_completion()` without provider settings.
- `backend/app/services/pageindex_service.py:478`
  - fast/light document summary calls `async_chat_completion()` without provider settings.
- `backend/app/services/pageindex_service.py:754`
  - visual enrichment creates bare `ModelGateway()`.
- `backend/app/services/pageindex_service.py:1174`
  - node summary generation calls `async_chat_completion()` without provider settings.
- `backend/app/services/pageindex_service.py:2107`
  - TOC generation calls `async_chat_completion()` without provider settings.
- `backend/app/services/pageindex_service.py:4445`
  - search/relevance verification calls hardcoded `qwen3.6-flash`.
- `backend/app/services/pageindex_service.py:4696`
  - document retrieval expert call uses direct `async_chat_completion()`.

## Files And Responsibilities

- Modify: `backend/app/api/documents.py`
  - Extend indexing job payloads with `user_id`.
  - Forward `current_user["id"]` from upload and reindex entry points.
  - Preserve test helpers for queue state.
- Modify: `backend/app/services/pageindex_service.py`
  - Add optional `user_id` and route resolver support.
  - Resolve `indexing` route once per indexing operation where possible.
  - Use resolved provider config for direct text LLM calls.
  - Create settings-aware `ModelGateway` for vision calls.
  - Preserve environment fallback when settings cannot be resolved.
  - Add non-breaking route metadata to generated index output where practical.
- Modify if needed: `backend/app/core/llm.py`
  - Prefer existing `chat_by_scenario()` or `provider_config` paths.
  - Avoid widening signatures unless PageIndex needs a small helper.
- Create: `backend/tests/test_pageindex_model_routes.py`
  - Focused unit tests for PageIndex indexing/vision route use and fallback.
- Modify: `backend/tests/test_index_timeout_partial_save.py` or create a small new queue test file
  - Cover indexing queue user context preservation.
- Modify if needed: `backend/tests/test_model_gateway_settings.py`
  - Add only route-slot regression if PageIndex uses `ModelGateway` differently.
- Modify: `docs/superpowers/2026-06-10-next-phase-roadmap.md`
  - Record that Phase 5.1 must complete before Phase 6 treats indexing controls as production-ready.
- Optional modify: `docs/superpowers/plans/2026-06-10-phase-6-frontend-evidence-settings-integration.md`
  - Add an entry guard that indexing route UI is disabled/deferred unless Phase 5.1 is complete.

## Design Notes

### Route Resolution

Use the Phase 5 service contract:

- `ModelSettingsService.resolve_route(user_id, "indexing")`
- `ModelSettingsService.resolve_route(user_id, "vision")`

If `user_id` is missing, if route resolution fails, or if a route falls back to environment settings, PageIndex should keep the existing environment behavior.

### Background Job Context

The indexing queue should preserve the user who initiated the job:

```python
_index_queue: list[tuple[str, str, Optional[str], Optional[str]]] = []
```

or use a small dataclass if that is clearer:

```python
@dataclass(frozen=True)
class IndexJob:
    doc_id: str
    file_path: str
    mode_override: str | None = None
    user_id: str | None = None
```

Prefer the dataclass if the surrounding changes stay small. It makes future queue changes less brittle.

### PageIndex Service Context

Add optional context without breaking existing tests:

```python
class PageIndexService:
    def __init__(self, user_id: str | None = None):
        self.user_id = user_id
        self.opt = self._build_opt()
```

Then add focused helper methods:

```python
async def _resolve_model_route(self, route_slot: str) -> dict[str, Any]:
    ...

async def _indexing_completion(self, *, messages: list[dict], model: str | None = None, **kwargs):
    ...
```

The helper should pass `provider_config` into `async_chat_completion()` when a user route is available.

### Vision Calls

When PageIndex uses `ModelGateway`, construct it with user-aware settings:

```python
gateway = await self._build_model_gateway()
```

The helper should return a default `ModelGateway()` if user settings cannot be resolved.

### Route Metadata

Where PageIndex writes final index JSON, add additive metadata such as:

```json
{
  "model_routes": {
    "indexing": {
      "source": "user",
      "model": "custom-index-model",
      "route_version": "..."
    },
    "vision": {
      "source": "environment",
      "model": "qwen3.6-plus",
      "route_version": "..."
    }
  }
}
```

Do not include API keys or provider secrets in index files.

## Task 1: Preserve User Context In Index Jobs

**Files:**

- Modify: `backend/app/api/documents.py`
- Test: `backend/tests/test_index_queue_user_context.py`

- [ ] **Step 1: Write failing queue-context tests**

Create tests that monkeypatch `_run_index_job` or `_generate_index_async` and assert:

- Upload calls `start_index_process(..., user_id=current_user["id"])`.
- Reindex calls `start_index_process(..., user_id=current_user["id"])`.
- Queued jobs pass `user_id` from `_enqueue_index_job()` to `_run_index_job()`.
- Non-queued jobs pass `user_id` into `_generate_index_async()`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_index_queue_user_context.py -q
```

Expected: fail because job payloads do not carry `user_id`.

- [ ] **Step 3: Add user-aware job payload**

Update:

- `_index_queue`
- `_run_index_job()`
- `_index_queue_worker()`
- `_enqueue_index_job()`
- `start_index_process()`
- `_generate_index_async()`

Keep `user_id` optional to preserve legacy/background callers.

- [ ] **Step 4: Forward authenticated user from API entry points**

Update upload and reindex paths to call:

```python
start_index_process(doc.id, doc.file_path, mode_override=mode_override, user_id=user_id)
```

and:

```python
start_index_process(doc_id, doc.file_path, mode_override=mode_override, user_id=current_user["id"])
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_index_queue_user_context.py tests/test_index_timeout_partial_save.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/api/documents.py backend/tests/test_index_queue_user_context.py backend/tests/test_index_timeout_partial_save.py
git commit -m "fix: preserve user context for indexing jobs"
```

## Task 2: Add PageIndex Model Route Helpers

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_pageindex_model_routes.py`

- [ ] **Step 1: Write failing route-helper tests**

Cover:

- `PageIndexService(user_id="user-a")` resolves `indexing` through `ModelSettingsService`.
- `_indexing_completion()` passes `provider_config` and configured model to `async_chat_completion()`.
- Missing `user_id` uses the existing model and no `provider_config`.
- Route-resolution failure falls back to existing behavior without crashing indexing.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py -q
```

Expected: fail because PageIndex has no route helper.

- [ ] **Step 3: Add optional user context to PageIndexService**

Add:

```python
def __init__(self, user_id: str | None = None):
    self.user_id = user_id
    self._model_route_cache: dict[str, dict[str, Any]] = {}
    self.opt = self._build_opt()
```

- [ ] **Step 4: Add route resolution helper**

Implement a small helper that opens `DB_PATH`, calls `ModelSettingsService.resolve_route()`, caches by route slot, and returns `None` on failure.

Do not expose raw API keys in logs or index metadata.

- [ ] **Step 5: Add completion helper**

Implement `_indexing_completion()` that:

- Resolves `indexing`.
- Uses `route["model"]` and `provider_config=route` when available.
- Falls back to the passed model or existing model behavior when no user route exists.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/tests/test_pageindex_model_routes.py
git commit -m "feat: add pageindex model route helpers"
```

## Task 3: Route Direct PageIndex Text LLM Calls

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_pageindex_model_routes.py`

- [ ] **Step 1: Write failing direct-call regression tests**

Cover at least these call families with monkeypatched completions:

- Fast/light document summary uses `indexing` route.
- Node summary generation uses `indexing` route.
- TOC generation uses `indexing` route.
- Verification/relevance helpers use `indexing` route or a documented fallback when no service context is available.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py -q
```

Expected: fail because direct calls bypass the route helper.

- [ ] **Step 3: Replace direct service-method calls**

For PageIndex methods that already have `self`, replace direct `async_chat_completion()` with:

```python
await self._indexing_completion(...)
```

Keep timeout and generation parameters unchanged unless the route helper requires passing them through.

- [ ] **Step 4: Handle module-level verification helpers**

For module-level helpers such as `check_query_appearance()` and `verify_candidate_nodes()`, choose the smallest compatible change:

- Add optional `user_id` and `provider_config` parameters, or
- Call them through a `PageIndexService` wrapper where user context is available.

Avoid breaking existing callers that pass only `(query, node_text, model)`.

- [ ] **Step 5: Run direct-call tests**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py tests/test_fast_light_doc_summary.py tests/test_node_filler_summary_budget.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/tests/test_pageindex_model_routes.py
git commit -m "feat: route pageindex text model calls"
```

## Task 4: Route PageIndex Vision Calls

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_pageindex_model_routes.py`
- Possibly modify: `backend/tests/test_model_gateway_settings.py`

- [ ] **Step 1: Write failing vision-route tests**

Cover:

- PageIndex visual enrichment constructs `ModelGateway` with `user_id`.
- Configured `vision` route is used for vision enrichment.
- Text-only configured vision route raises the same controlled error as `ModelGateway`.
- Missing user route keeps environment fallback.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py tests/test_model_gateway_settings.py -q
```

Expected: fail because PageIndex creates bare `ModelGateway()`.

- [ ] **Step 3: Add gateway helper**

Add a PageIndex helper that constructs `ModelGateway` with:

- `model_settings_service`
- `user_id`

when user context exists, and returns default `ModelGateway()` otherwise.

- [ ] **Step 4: Replace bare `ModelGateway()`**

Replace `gateway = ModelGateway()` inside PageIndex visual enrichment paths with the helper.

- [ ] **Step 5: Run vision-focused tests**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py tests/test_ocr_pipeline.py tests/test_pageindex_route_decision.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/tests/test_pageindex_model_routes.py backend/tests/test_model_gateway_settings.py
git commit -m "feat: route pageindex vision model calls"
```

## Task 5: Add Safe Route Metadata To Index Output

**Files:**

- Modify: `backend/app/services/pageindex_service.py`
- Test: `backend/tests/test_pageindex_model_routes.py`
- Possibly modify: `backend/tests/test_pdf_index_quality_gates.py`

- [ ] **Step 1: Write failing metadata tests**

Cover:

- Generated index output can include `model_routes.indexing.route_version`.
- Generated index output can include `model_routes.vision.route_version` when vision is used.
- Metadata never includes `api_key`, `api_key_ciphertext`, or provider secrets.
- Existing index consumers tolerate missing `model_routes`.

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py -q
```

Expected: fail because metadata is not yet recorded.

- [ ] **Step 3: Add metadata helper**

Add a helper that returns sanitized route metadata:

```python
{
    "source": route.get("source"),
    "model": route.get("model"),
    "route_version": route.get("route_version"),
    "route_slot": route.get("route_slot"),
}
```

Never serialize API keys.

- [ ] **Step 4: Attach metadata to final index output**

Attach metadata where final index JSON is assembled and persisted. Keep the field additive.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_pageindex_model_routes.py tests/test_pdf_index_quality_gates.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/pageindex_service.py backend/tests/test_pageindex_model_routes.py backend/tests/test_pdf_index_quality_gates.py
git commit -m "feat: record pageindex model route metadata"
```

## Task 6: Update Roadmap Guards

**Files:**

- Modify: `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- Modify if needed: `docs/superpowers/plans/2026-06-10-phase-6-frontend-evidence-settings-integration.md`

- [ ] **Step 1: Add post-Phase-5 baseline**

Record that Phase 5 is complete with a Phase 5.1 indexing-route closure follow-up.

- [ ] **Step 2: Add Phase 6 guard**

State that Phase 6 may implement evidence, quality, scope, and non-indexing model settings UI, but must not present indexing model controls as production-ready until Phase 5.1 is complete.

- [ ] **Step 3: Add completion gate input**

Add this Phase 5.1 plan and the Phase 5 report as required inputs for future Phase 6 completion gate audits.

- [ ] **Step 4: Run markdown diff check**

Run:

```powershell
git diff --check -- docs/superpowers/2026-06-10-next-phase-roadmap.md docs/superpowers/plans/2026-06-10-phase-6-frontend-evidence-settings-integration.md docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit**

```powershell
git add docs/superpowers/2026-06-10-next-phase-roadmap.md docs/superpowers/plans/2026-06-10-phase-6-frontend-evidence-settings-integration.md docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md
git commit -m "docs: add phase 5.1 indexing route closure plan"
```

## Task 7: Final Verification And Completion Gate

- [ ] **Step 1: Run Phase 5.1 focused backend suite**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_index_queue_user_context.py tests/test_pageindex_model_routes.py tests/test_model_gateway_settings.py tests/test_llm_timeout_defaults.py tests/test_search_scope.py -q
```

Expected: pass.

- [ ] **Step 2: Run indexing regression suite**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_fast_light_doc_summary.py tests/test_node_filler_summary_budget.py tests/test_ocr_pipeline.py tests/test_pageindex_route_decision.py tests/test_pdf_index_quality_gates.py tests/test_index_timeout_partial_save.py -q
```

Expected: pass.

- [ ] **Step 3: Run full backend suite**

Run:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Expected: pass.

- [ ] **Step 4: Run diff hygiene**

Run:

```powershell
git diff --check -- backend/app backend/tests docs/superpowers
```

Expected: no whitespace errors.

- [ ] **Step 5: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- Latest user request.
- `docs/superpowers/2026-06-11-phase-5-improvement-report.md`
- This Phase 5.1 plan.
- `docs/superpowers/plans/2026-06-10-phase-5-user-configurable-model-foundation.md`
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- Source plan: `D:\projects\page_chat - 副本\docs\superpowers\plans\2026-06-10-user-configurable-models.md`
- Current git status.
- Test output from Steps 1-4.

Required audit scans:

```powershell
rg -n "async_chat_completion\(|chat_completion\(|ModelGateway\(" backend/app/services/pageindex_service.py backend/tests
rg -n "start_index_process\(|_enqueue_index_job\(|_run_index_job\(|_generate_index_async\(" backend/app/api/documents.py backend/tests
rg -n "provider_config|route_version|resolve_route\(.*indexing|resolve_route\(.*vision|model_routes" backend/app/services/pageindex_service.py backend/tests
rg -n "api_key|api_key_ciphertext|MODEL_SETTINGS_SECRET" backend/app/services/pageindex_service.py backend/tests/test_pageindex_model_routes.py
```

## Done Criteria

Phase 5.1 is complete when:

- Upload indexing jobs preserve authenticated `user_id`.
- Reindex jobs preserve authenticated `user_id`.
- Queued and non-queued indexing paths pass user context into `_generate_index_async()`.
- `PageIndexService` accepts optional user context without breaking legacy callers.
- PageIndex text model calls use the configured `indexing` route when available.
- PageIndex vision enrichment uses the configured `vision` route when available.
- Missing user settings preserve existing environment fallback behavior.
- Route/version metadata is recorded in index output without secrets.
- No PageIndex call path logs or persists raw provider API keys.
- Focused Phase 5.1 tests pass.
- Indexing regression tests pass.
- Full backend suite passes.
- Completion gate passes or records only explicitly accepted P2 documentation follow-ups.

## Rollback Notes

If a production issue appears after this slice:

- Existing environment fallback should allow disabling user route mappings without code rollback.
- Deleting a user's `indexing` or `vision` route mapping should return indexing to environment defaults.
- If queue payload changes cause runtime issues, temporarily call `start_index_process(..., user_id=None)` to restore Phase 5 behavior while preserving the new optional signatures.

## Phase 6 Guard

Until this plan is implemented and verified, Phase 6 must not claim full indexing model configurability in the UI. Phase 6 may still proceed with:

- Evidence labels.
- Source preview anchor display.
- Document quality display.
- Chat scope controls.
- Model settings UI for `general_chat`, `document_qa`, `query_expansion`, and `vision` if those backend paths remain covered by Phase 5 behavior.

Index generation controls should be hidden, disabled, or clearly deferred until Phase 5.1 passes its completion gate.
