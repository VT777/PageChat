# Phase 5 And Phase 5.1 Execution Report

Date: 2026-06-11

## Executive Summary

Phase 5 and Phase 5.1 completed the backend model-configuration foundation and closed the PageIndex indexing-route gap found by the Phase 5 completion gate.

The combined result is that users can now have server-side, per-user model provider settings; model API keys are write-only from read/list endpoints; model calls can route through LiteLLM-backed provider configs; Agent/document-Q&A, query expansion, ModelGateway routes, and PageIndex indexing paths can use user-aware model routes where user settings exist; and existing environment-based Qwen/DashScope behavior remains the fallback.

Final verification after Phase 5.1:

- Phase 5.1 focused backend suite: `25 passed`
- Indexing regression suite: `34 passed, 4 skipped`
- Full backend suite: `379 passed, 8 skipped`
- Diff hygiene: no whitespace errors; Git reported LF-to-CRLF working-copy warnings only
- Final commit: `f3fb13d feat: add user-configurable model routing foundation`
- Pushed branch: `vt_0610 -> origin/vt_0610`

## Scope Completed

### Phase 5: User-Configurable Model Foundation

Phase 5 established the backend foundation for user-configurable model providers.

Implemented capabilities:

- Production JWT signing fails closed when no environment-backed secret exists.
- Per-user model provider settings are stored in SQLite migrations.
- Provider API keys are write-only from frontend read/list endpoints.
- Production model-key writes are refused unless stable secret material is configured.
- LiteLLM is wrapped behind a thin testable adapter.
- `chat_completion()` and `async_chat_completion()` can accept `provider_config`.
- `chat_by_scenario()` can resolve user-aware route settings.
- `ModelGateway` can resolve settings-backed `general_chat`, `document_qa`, and `vision` routes.
- Query expansion resolves the `query_expansion` route and scopes cache keys by route version.
- Settings API endpoints expose provider presets, provider configs, connection tests, and route mappings.

Key files:

- `backend/app/core/config.py`
- `backend/app/core/llm.py`
- `backend/app/models/migrations.py`
- `backend/app/api/settings.py`
- `backend/app/services/model_settings_service.py`
- `backend/app/services/litellm_adapter.py`
- `backend/app/services/model_gateway.py`
- `backend/app/services/search_service.py`

### Phase 5.1: Indexing Route Closure

Phase 5.1 closed the accepted Phase 5 P2 follow-up around deep PageIndex indexing calls.

Implemented capabilities:

- Upload indexing jobs preserve authenticated `user_id`.
- Reindex jobs preserve authenticated `user_id`.
- Queued and non-queued indexing paths pass `user_id` into `_generate_index_async()`.
- `PageIndexService` accepts optional user context.
- PageIndex text model calls use the configured `indexing` route when available.
- PageIndex vision enrichment uses the configured `vision` route when available.
- Missing user settings preserve existing environment fallback behavior.
- Tree-search cache keys include indexing route version where user model settings affect output.
- Generated index payloads include sanitized `model_routes` metadata where available.
- Route metadata excludes API keys, ciphertext, and provider secrets.

Key files:

- `backend/app/api/documents.py`
- `backend/app/services/pageindex_service.py`
- `backend/tests/test_index_queue_user_context.py`
- `backend/tests/test_pageindex_model_routes.py`
- `docs/superpowers/plans/2026-06-11-phase-5-1-indexing-route-closure.md`

## Product Decisions Preserved

The implementation follows the Phase 5 decision record:

- Settings ownership: per-user settings with environment fallback.
- API key storage: development profile stores protected local values; production refuses model-key writes unless a stable `MODEL_SETTINGS_SECRET` or `SECRET_KEY` exists.
- Secret source: environment-backed secrets only; no import-time generated production secret.
- Configurable route slots: `general_chat`, `document_qa`, `query_expansion`, `indexing`, and `vision`.
- Custom provider support: `openai_compatible` providers are allowed in v1 through editable `base_url` and model IDs.
- Model list behavior: curated presets plus manual model IDs; live provider model discovery remains deferred.

## Verification Evidence

### Phase 5 Verification

Focused Phase 5 suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py tests/test_model_settings_service.py tests/test_litellm_adapter.py tests/test_model_gateway_settings.py tests/test_model_settings_api.py tests/test_cache_scope_keys.py tests/test_search_scope.py tests/test_llm_timeout_defaults.py -q
```

Result:

```text
39 passed
```

Full backend suite after Phase 5:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
369 passed, 8 skipped
```

Phase 5 completion gate:

- Conditional pass
- No P0 gaps
- No P1 gaps
- One accepted P2 follow-up: deep PageIndex indexing calls still needed full per-user route integration

### Phase 5.1 Verification

Focused Phase 5.1 suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_index_queue_user_context.py tests/test_pageindex_model_routes.py tests/test_model_gateway_settings.py tests/test_llm_timeout_defaults.py tests/test_search_scope.py -q
```

Result:

```text
25 passed
```

Indexing regression suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_fast_light_doc_summary.py tests/test_node_filler_summary_budget.py tests/test_ocr_pipeline.py tests/test_pageindex_route_decision.py tests/test_pdf_index_quality_gates.py tests/test_index_timeout_partial_save.py -q
```

Result:

```text
34 passed, 4 skipped
```

Full backend suite after Phase 5.1:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
379 passed, 8 skipped
```

Diff hygiene:

```powershell
git diff --check -- backend/app backend/tests docs/superpowers
```

Result:

```text
No whitespace errors. Git reported LF-to-CRLF working-copy warnings only.
```

## Actual Code Scans Performed

The final Phase 5.1 audit used real scans rather than memory-based review.

PageIndex model-call scan:

```powershell
rg -n "async_chat_completion\(|chat_completion\(|ModelGateway\(" backend/app/services/pageindex_service.py backend/tests
```

Result summary:

- Remaining `async_chat_completion()` calls in `pageindex_service.py` are limited to:
  - `check_query_appearance()`, which now accepts `provider_config`
  - `_indexing_completion()`, the central route-aware helper
- Remaining `ModelGateway()` calls in `pageindex_service.py` are limited to:
  - `_build_model_gateway()`, the central vision gateway helper

Index job user-context scan:

```powershell
rg -n "start_index_process\(|_enqueue_index_job\(|_run_index_job\(|_generate_index_async\(" backend/app/api/documents.py backend/tests
```

Result summary:

- Upload and reindex entry points pass authenticated `user_id`.
- Queue payloads preserve `user_id`.
- Worker and non-queued thread paths pass `user_id` into `_generate_index_async()`.
- `_generate_index_async()` constructs `PageIndexService(user_id=user_id)`.

Route metadata and secret scan:

```powershell
rg -n "provider_config|route_version|resolve_route\(.*indexing|resolve_route\(.*vision|model_routes|api_key|api_key_ciphertext|MODEL_SETTINGS_SECRET" backend/app/services/pageindex_service.py backend/tests/test_pageindex_model_routes.py
```

Result summary:

- PageIndex writes sanitized `model_routes` metadata.
- PageIndex does not persist `api_key` or `api_key_ciphertext`.
- Raw key strings appear only in tests that verify metadata sanitization and adapter behavior.

## Commit And Push

Committed:

```text
f3fb13d feat: add user-configurable model routing foundation
```

Pushed:

```text
origin/vt_0610
```

Push result:

```text
f219756..f3fb13d  vt_0610 -> vt_0610
```

## Planning Impact

Phase 5 and Phase 5.1 together make model configuration a backend-owned contract:

- Provider credentials stay server-side.
- Settings are user-scoped.
- Environment defaults remain the fallback.
- Route slots are stable and backend-defined.
- Query expansion and PageIndex tree-search caches account for route versions.
- PageIndex indexing and vision-like enrichment paths no longer bypass user model settings when user routes exist.

Phase 6 can now build frontend model settings UI against the Phase 5 APIs. The Phase 6 plan still needs to keep UI behavior honest:

- Evidence labels, quality display, and chat scope UI can proceed independently.
- Model settings UI can include route mapping.
- Index generation controls are now allowed to be treated as production-backed only after this Phase 5.1 verification baseline.

## Remaining Limitations

The following remain out of scope after Phase 5 and Phase 5.1:

- Full frontend model settings UI.
- Live provider model discovery.
- Standalone LiteLLM Proxy deployment.
- Billing, quotas, provider budgets, or virtual keys.
- Admin-global model settings.
- Stronger production key management beyond environment-backed local encryption/refusal behavior.
- Provider capability catalog beyond the current explicit vision-capable flag.

## Recommended Next Phase

Proceed to Phase 6 frontend evidence and settings integration.

Recommended order:

1. Evidence labels and source preview anchor display.
2. Document quality display.
3. Chat scope controls.
4. Model provider settings UI.
5. Route mapping UI, including indexing route controls backed by the Phase 5.1 verification baseline.
