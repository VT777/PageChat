# Phase 5 Improvement Report

Date: 2026-06-11

## Executive Summary

Phase 5 established the backend foundation for user-configurable model providers while preserving the current environment-based Qwen/DashScope defaults.

The main outcome is that production JWT signing now fails closed without an environment-backed secret, model provider settings can be persisted per user, API keys are write-only from read/list endpoints, LiteLLM has a thin testable adapter, model routes can be resolved through settings, and model-sensitive cache paths now include route/version information where Phase 5 touched model output.

Fresh verification after Phase 5:

- Phase 5 focused backend suite: `39 passed`
- Full backend suite: `369 passed, 8 skipped`
- Completion gate audit: conditional pass with no P0/P1 gaps
- Completion gate P2 follow-up: deep PageIndex indexing calls still need full per-user route integration in a later slice

## Product Decisions Recorded

Phase 5 used the default implementation choices recorded in the Phase 5 plan.

Implemented decisions:

- Settings ownership: per-user settings with environment fallback.
- API key storage: development profile stores protected local values; production refuses model-key writes unless a stable `MODEL_SETTINGS_SECRET` or `SECRET_KEY` exists.
- Secret source: environment-backed secrets only; no import-time generated production secret.
- Configurable route slots: `general_chat`, `document_qa`, `query_expansion`, `indexing`, and `vision`.
- Custom provider support: `openai_compatible` providers are allowed in v1 through editable `base_url` and model IDs.
- Model list behavior: curated presets plus manual model IDs; live provider model discovery is deferred.

## What Changed

### 1. Production JWT Secret Enforcement

Phase 5 closed the Phase 1 limitation around production JWT signing secrets.

Implemented capabilities:

- Added `APP_ENV` / production-mode detection in `backend/app/core/config.py`.
- Added `resolve_jwt_secret()`.
- Development and test mode keep the stable local fallback secret.
- Production mode refuses to use the development fallback when both `JWT_SECRET` and `SECRET_KEY` are missing.

Effect:

- Local sessions remain stable across backend reloads.
- Production startup/config validation fails closed instead of silently signing tokens with a development secret.
- Auth code continues to import one configured `JWT_SECRET` value.

### 2. Model Settings Persistence

Phase 5 added a SQLite-backed model settings layer under the existing migration system.

Implemented capabilities:

- Added `model_provider_configs`.
- Added `model_route_mappings`.
- Added per-user provider config CRUD in `backend/app/services/model_settings_service.py`.
- Added route resolution for configured routes and environment fallback routes.
- Added route version fingerprints for configured and fallback routes.
- Added cross-user provider overwrite protection when a provider ID is supplied internally.

Effect:

- Model settings have an explicit user ownership boundary.
- Existing `.env` model behavior remains the fallback when no user route exists.
- Future frontend settings UI can call stable backend APIs instead of writing directly to runtime config files.

### 3. API Key Write-Only Behavior

Phase 5 made provider API keys write-only from the frontend perspective.

Implemented capabilities:

- Provider config read/list methods return `api_key_mask`, not raw keys.
- API responses do not include raw `api_key`.
- Provider connection tests can decrypt the stored key server-side for the outbound test call.
- Production mode rejects model-key writes when no stable storage secret is available.

Effect:

- Saved API keys can be rotated or deleted without exposing raw values back to the browser.
- Production deployments cannot accidentally accept BYOK secrets into an insecure local-only storage mode.
- Tests cover both raw-key non-exposure and production rejection behavior.

### 4. LiteLLM Adapter

Phase 5 added a thin LiteLLM adapter in `backend/app/services/litellm_adapter.py`.

Implemented capabilities:

- Sync completion wrapper.
- Async completion wrapper.
- Timeout forwarding.
- OpenAI-compatible `api_key` and `api_base` parameter mapping.
- Controlled provider errors through `ModelProviderError`.
- Raw API key redaction in adapter error messages.
- Lazy LiteLLM import so tests can monkeypatch the call layer even when the local environment has not installed the package.

Effect:

- Provider calls are isolated behind a small boundary that can be tested without network access.
- Existing OpenAI-compatible response expectations can be preserved while moving call sites incrementally.
- Provider exceptions are less likely to leak credentials into logs or API responses.

### 5. LLM Boundary Integration

Phase 5 extended `backend/app/core/llm.py` without removing the existing call signatures.

Implemented capabilities:

- `chat_completion()` and `async_chat_completion()` can accept a resolved `provider_config`.
- Calls without `provider_config` continue to use the existing OpenAI-compatible `.env` client.
- `chat_by_scenario()` can resolve per-user settings when `user_id` is provided.
- Scenario-to-route mapping covers `chat`, `qa`, `query_expansion`, `index`, `node_summary`, and `relevance`.

Effect:

- Existing code can continue using the old API.
- New settings-backed code can opt in by passing `user_id` or a resolved provider config.
- The Agent document-Q&A path can use per-user `document_qa` settings while preserving environment fallback behavior.

### 6. Settings-Backed ModelGateway Routes

Phase 5 made `ModelGateway` able to resolve configured routes.

Implemented capabilities:

- `ModelGateway` accepts an optional model settings service and `user_id`.
- `general_chat` routes can use configured models.
- `document_qa` routes can use configured models.
- Vision routes reject configured models that are not marked vision-capable.
- Default flash/plus route behavior remains unchanged when no settings service or user setting exists.

Effect:

- The existing flash/plus policy remains the routing layer.
- User settings can replace model IDs and provider configuration below that policy.
- Vision downgrade safety remains explicit.

### 7. Model-Sensitive Cache Keys

Phase 5 extended cache behavior where model output can affect cached results.

Implemented capabilities:

- Search-result cache methods accept an optional `route_version`.
- Query expansion cache keys include `(user_id, route_version, query)`.
- Query expansion resolves the user `query_expansion` route where available.
- Query expansion falls back to the existing `qwen-turbo` behavior if route resolution fails.

Effect:

- Changing a user's query expansion model no longer reuses cached expansions from an older route.
- Existing cache call sites remain source-compatible because `route_version` is optional.
- The audit-discovered cache gap was closed before completion.

### 8. Settings API

Phase 5 extended the existing settings router while preserving PageIndex runtime settings.

Implemented endpoints:

- `GET /api/settings/model-providers/presets`
- `GET /api/settings/model-providers`
- `POST /api/settings/model-providers`
- `DELETE /api/settings/model-providers/{provider_id}`
- `POST /api/settings/model-providers/{provider_id}/test`
- `GET /api/settings/model-routes`
- `PUT /api/settings/model-routes`

Effect:

- The frontend has a backend contract for provider setup and route mapping.
- Provider settings are user-scoped through the existing `require_auth` dependency.
- Read/list endpoints return masked metadata only.

## Test Coverage Added

New or expanded tests:

- `backend/tests/test_auth_config.py`
- `backend/tests/test_model_settings_service.py`
- `backend/tests/test_litellm_adapter.py`
- `backend/tests/test_model_gateway_settings.py`
- `backend/tests/test_model_settings_api.py`
- `backend/tests/test_llm_timeout_defaults.py`
- `backend/tests/test_search_scope.py`
- `backend/tests/test_database_migrations.py`

Covered behaviors:

- Production JWT secret enforcement.
- Development JWT fallback stability.
- Model settings migrations.
- Provider config save/list/delete.
- Provider config masking and raw-key non-exposure.
- Cross-user provider isolation.
- Environment fallback route resolution.
- Missing provider/model route rejection.
- LiteLLM sync/async adapters without network calls.
- Adapter timeout forwarding and error key redaction.
- Settings-backed `ModelGateway` routes.
- Vision model capability rejection.
- Query expansion route-version cache separation.
- Settings API user isolation and production insecure-storage rejection.

## Verification Evidence

Phase 5 focused backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py tests/test_model_settings_service.py tests/test_litellm_adapter.py tests/test_model_gateway_settings.py tests/test_model_settings_api.py tests/test_cache_scope_keys.py tests/test_search_scope.py tests/test_llm_timeout_defaults.py -q
```

Result:

```text
39 passed
```

Full backend suite:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

Result:

```text
369 passed, 8 skipped
```

Diff hygiene:

```powershell
git diff --check -- backend/app backend/tests docs/superpowers/plans/2026-06-10-phase-5-user-configurable-model-foundation.md
```

Result:

```text
No whitespace errors. Git reported LF-to-CRLF working-copy warnings only.
```

## Completion Gate Audit

The completion gate defined in `docs/superpowers/completion-gate-gap-audit.md` was run after implementation.

Audit inputs:

- Latest user request.
- `docs/superpowers/plans/2026-06-10-phase-5-user-configurable-model-foundation.md`
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- Source plan: `D:\projects\page_chat - 副本\docs\superpowers\plans\2026-06-10-user-configurable-models.md`
- Current git status and recent commits.
- Current codebase state.
- Focused backend suite and full backend suite output.

Actual code scans performed included:

```powershell
rg -n "JWT_SECRET|SECRET_KEY|secrets\.token_hex|dev-only-change-me|MODEL_SETTINGS_SECRET" backend/app backend/tests
rg -n "api_key_ciphertext|api_key_mask|api_key|_unprotect_api_key|provider_config" backend/app backend/tests
rg -n "ModelGateway\(|route_version|model_route|model_provider|LiteLLMAdapter|litellm|chat_completion\(|async_chat_completion\(" backend/app backend/tests
rg -n "_resolve_query_expansion_route|route_version|provider_config|_query_cache" backend/app/services/search_service.py backend/tests/test_search_scope.py
rg -n "get_search_result\(|set_search_result\(|get_llm_response\(|set_llm_response\(" backend/app backend/tests
rg -n "chat_by_scenario\(|async_chat_completion\(|ModelGateway\(" backend/app/services backend/tests
```

Audit result:

- No P0 gaps.
- No P1 gaps.
- Conditional pass with one P2 follow-up.

P2 follow-up:

- Deep PageIndex indexing and verification calls still include direct `async_chat_completion()` paths. Phase 5 covered Agent document Q&A, `ModelGateway`, query expansion, settings API, and cache-sensitive query expansion. Full indexing route integration should be handled as a later backend slice before the frontend exposes indexing model controls as a production guarantee.

## Planning Impact

Phase 5 turns model selection into a backend-owned contract:

- Provider credentials are server-side settings, not frontend-readable state.
- Settings are user-scoped.
- Environment configuration remains the default fallback.
- Model routes have stable route slot names.
- Route versions can be included in cache-sensitive model-output paths.
- LiteLLM is now an internal adapter boundary rather than a cross-cutting dependency.

This means Phase 6 frontend work can build a Settings UI against real backend endpoints, while later backend work can continue moving remaining direct model call sites behind user-aware route resolution.

## Remaining Limitations

These are intentionally not fully solved in Phase 5:

- Full frontend model settings UI.
- Live provider model discovery.
- Standalone LiteLLM Proxy deployment.
- Billing, quotas, provider budgets, or virtual keys.
- Full PageIndex indexing-route integration for every direct model call.
- Strong production-grade key management beyond environment-backed local encryption/refusal behavior.
- Admin-global model settings.

## Recommended Next Phases

### Phase 5.1: Indexing Route Closure

Recommended scope:

- Route PageIndex indexing, node summary, verification, and vision-like indexing calls through user-aware model settings where a user context is available.
- Add regression tests for `indexing` route selection.
- Decide how background jobs preserve user model settings when queued.

Why next:

- The backend foundation exists.
- The completion gate identified this as a P2 follow-up before frontend UI promises full indexing configurability.

### Phase 6: Frontend Settings And Evidence Integration

Recommended scope:

- Add provider config UI.
- Add route mapping UI for the Phase 5 route slots.
- Display masked key state only.
- Use backend provider presets and manual model ID entry.
- Preserve the evidence/scope UI work already planned for Phase 6.

Why next:

- Settings API endpoints now exist and are covered.
- Frontend can integrate without inventing persistence or key-handling behavior.

## Suggested Immediate Follow-Ups

1. Create a small Phase 5.1 gap-closure plan for PageIndex indexing-route integration.
2. Start Phase 6 frontend settings UI against the new `/api/settings/model-providers/*` and `/api/settings/model-routes` endpoints.
3. Keep provider live model discovery deferred until basic BYOK setup and route mapping are usable.
4. Decide whether production should require `MODEL_SETTINGS_SECRET` specifically instead of accepting `SECRET_KEY` as a compatibility fallback.
