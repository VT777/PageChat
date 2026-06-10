# Phase 5 User-Configurable Model Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded model routing with backend model provider settings while preserving current defaults and call signatures.

**Architecture:** Add a settings persistence layer and a thin LiteLLM adapter beneath existing `app.core.llm` and `ModelGateway` boundaries. Keep existing environment configuration as fallback, make API keys write-only from the frontend perspective, and include model route/version in cache-sensitive operations.

**Tech Stack:** FastAPI backend, SQLite migrations or runtime settings JSON depending on approved persistence choice, LiteLLM, existing `app.core.llm`, `ModelGateway`, `runtime_settings_service.py`, pytest.

---

## Entry Criteria

Start after Phase 2. Phase 4 is not required.

Before storing user-owned model keys, confirm:

- JWT secret has production enforcement or an explicit deferral.
- User scope contracts from Phase 1 still pass.
- Model settings persistence choice is approved: per-user, admin-global, or both.

## Open Product Decisions

Resolve before implementation:

- Should model settings be per-user, admin-global, or both?
- Should API keys be encrypted at rest in v1?
- Which functions are configurable in v1?
  - General chat
  - Document Q&A
  - Query expansion
  - Index generation
  - Vision/OCR
- Should provider model lists be fetched live or entered manually?

Default recommendation:

- Start with per-user settings plus environment fallback.
- Store API keys encrypted if an app secret exists; otherwise keep a local-only development store and mark production encryption as required before deployment.
- Configure route slots: `general_chat`, `document_qa`, `query_expansion`, `indexing`, `vision`.
- Use provider presets plus editable model IDs.

## Files And Responsibilities

- Modify: `backend/app/core/config.py`
  - Add production environment detection if missing.
- Modify: `backend/app/api/auth.py` or app startup path
  - Fail startup in production when `JWT_SECRET` is missing.
- Modify: `backend/app/models/migrations.py`
  - Add model settings tables if SQLite persistence is chosen.
- Create: `backend/app/services/model_settings_service.py`
  - Provider config CRUD.
  - Key masking.
  - Effective settings resolution.
- Create: `backend/app/services/litellm_adapter.py`
  - Thin wrapper around LiteLLM calls.
  - Testable without network.
- Modify: `backend/app/core/llm.py`
  - Resolve effective model settings before calls.
  - Preserve current `chat_completion`, `async_chat_completion`, and scenario helpers where possible.
- Modify: `backend/app/services/model_gateway.py`
  - Replace hardcoded model routes with settings-backed routes.
- Create or modify: `backend/app/api/settings.py`
  - Provider preset, provider config, validation, and route mapping endpoints.
- Create: `backend/tests/test_model_settings_service.py`
- Create: `backend/tests/test_litellm_adapter.py`
- Create: `backend/tests/test_model_gateway_settings.py`
- Create: `backend/tests/test_model_settings_api.py`
- Create or modify: `backend/tests/test_auth_config.py`
  - Cover production JWT secret enforcement.

## Task 0: Enforce Production JWT Secret Configuration

**Files:**

- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/auth.py` or the central app startup module if startup validation lives there
- Modify: `backend/tests/test_auth_config.py`

- [ ] **Step 1: Write failing production-mode tests**

Cover:

- Development/test mode keeps the stable fallback secret.
- Production mode without `JWT_SECRET` and `SECRET_KEY` fails startup or config validation.
- Production mode with `JWT_SECRET` passes.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py -q
```

- [ ] **Step 3: Add environment mode detection**

Use the project's existing environment variable if one exists. If none exists, add one clearly:

```python
APP_ENV = os.getenv("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV in {"prod", "production"}
```

- [ ] **Step 4: Enforce production secret**

If `IS_PRODUCTION` and neither `JWT_SECRET` nor `SECRET_KEY` is configured, raise a startup/config error with a clear message.

Do not generate a random import-time secret.

- [ ] **Step 5: Run auth tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/core/config.py backend/app/api/auth.py backend/tests/test_auth_config.py
git commit -m "fix: enforce jwt secret in production"
```

## Task 1: Add Model Settings Persistence

**Files:**

- Modify: `backend/app/models/migrations.py`
- Create: `backend/app/services/model_settings_service.py`
- Create: `backend/tests/test_model_settings_service.py`

- [ ] **Step 1: Write failing service tests**

Cover:

- Save provider config.
- Read masked config without returning raw API key.
- Delete provider config.
- Resolve environment fallback when no user config exists.
- Reject missing provider or model route.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_model_settings_service.py -q
```

- [ ] **Step 3: Add persistence**

If SQLite is chosen, add tables:

- `model_provider_configs`
- `model_route_mappings`

If runtime JSON is chosen for v1, extend `runtime_settings_service.py` with user-scoped records.

- [ ] **Step 4: Implement service**

The service must never return raw API keys from read/list methods.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_model_settings_service.py tests/test_database_migrations.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/models/migrations.py backend/app/services/model_settings_service.py backend/tests/test_model_settings_service.py
git commit -m "feat: add model settings persistence"
```

## Task 2: Add LiteLLM Adapter

**Files:**

- Create: `backend/app/services/litellm_adapter.py`
- Modify: `backend/app/core/llm.py`
- Create: `backend/tests/test_litellm_adapter.py`

- [ ] **Step 1: Write adapter tests**

Monkeypatch LiteLLM calls. Do not call external providers.

Cover:

- Sync completion.
- Async completion.
- Streaming compatibility if current code needs it.
- Timeout propagation.
- Provider errors become controlled exceptions.

- [ ] **Step 2: Run tests and verify failure**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_litellm_adapter.py -q
```

- [ ] **Step 3: Implement thin adapter**

Keep the adapter small:

- Accept resolved provider config.
- Call LiteLLM.
- Return OpenAI-compatible response shape expected by current code.

- [ ] **Step 4: Wire `app.core.llm` behind feature flag or fallback**

Default should preserve existing behavior if no model settings exist.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_litellm_adapter.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/litellm_adapter.py backend/app/core/llm.py backend/tests/test_litellm_adapter.py
git commit -m "feat: add litellm call adapter"
```

## Task 3: Settings-Backed ModelGateway Routes

**Files:**

- Modify: `backend/app/services/model_gateway.py`
- Modify: `backend/app/core/llm.py`
- Create: `backend/tests/test_model_gateway_settings.py`

- [ ] **Step 1: Write routing tests**

Cover:

- Default route equals current behavior when no settings exist.
- `general_chat` uses configured route.
- `document_qa` uses configured route.
- Vision route rejects text-only model capability.
- Model route/version can be included in cache keys.

- [ ] **Step 2: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_model_gateway_settings.py -q
```

- [ ] **Step 3: Implement settings-backed routing**

Keep route names stable:

- `flash`
- `plus`
- `vision`

Map product functions to those routes or direct model configs.

- [ ] **Step 4: Update cache-sensitive keys**

Where query expansion or retrieval cache depends on model output, include route version or model settings fingerprint.

- [ ] **Step 5: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_model_gateway_settings.py tests/test_search_scope.py tests/test_cache_scope_keys.py -q
```

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/model_gateway.py backend/app/core/llm.py backend/tests/test_model_gateway_settings.py
git commit -m "feat: route models from settings"
```

## Task 4: Add Settings API

**Files:**

- Create or modify: `backend/app/api/settings.py`
- Modify: `backend/app/main.py` if router registration is needed
- Create: `backend/tests/test_model_settings_api.py`

- [ ] **Step 1: Write API tests**

Cover:

- List provider presets.
- Save provider config.
- Read masked provider config.
- Delete provider config.
- Save route mapping.
- Test connection uses monkeypatched adapter.
- User A cannot read User B settings.

- [ ] **Step 2: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_model_settings_api.py -q
```

- [ ] **Step 3: Implement endpoints**

Suggested endpoints:

- `GET /settings/model-providers/presets`
- `GET /settings/model-providers`
- `POST /settings/model-providers`
- `PUT /settings/model-providers/{provider_id}`
- `DELETE /settings/model-providers/{provider_id}`
- `POST /settings/model-providers/{provider_id}/test`
- `GET /settings/model-routes`
- `PUT /settings/model-routes`

- [ ] **Step 4: Run tests**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_model_settings_api.py tests/test_auth_api.py -q
```

If `tests/test_auth_api.py` does not exist:

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests -q -k "auth or model_settings"
```

- [ ] **Step 5: Commit**

```powershell
git add backend/app/api/settings.py backend/app/main.py backend/tests/test_model_settings_api.py
git commit -m "feat: add model settings api"
```

## Task 5: Final Verification And Completion Gate

- [ ] **Step 1: Run focused suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest tests/test_auth_config.py tests/test_model_settings_service.py tests/test_litellm_adapter.py tests/test_model_gateway_settings.py tests/test_model_settings_api.py tests/test_cache_scope_keys.py -q
```

- [ ] **Step 2: Run full backend suite**

```powershell
C:\Users\TT_WT\.local\bin\uv.exe run pytest -q
```

- [ ] **Step 3: Run completion gate audit**

Use `docs/superpowers/completion-gate-gap-audit.md`.

Inputs:

- This Phase 5 plan.
- `docs/superpowers/2026-06-10-next-phase-roadmap.md`
- `docs/superpowers/2026-06-10-phase-1-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-user-configurable-models.md`
- Current git status.
- Test output from Steps 1-2.

## Done Criteria

Phase 5 is complete when:

- Model provider settings are persisted under the approved scope.
- Production mode fails when JWT signing secret is missing.
- API keys are write-only from read/list endpoints.
- LiteLLM adapter is covered without network calls.
- Existing `.env` model behavior remains fallback.
- ModelGateway routes use settings when present.
- Cache-sensitive model operations include settings route/version where needed.
- Settings API is user-scoped and tested.
- Full backend suite passes.
- Completion gate passes or only records accepted P2 follow-ups.

## Out Of Scope

- Full frontend settings UI.
- LiteLLM Proxy deployment.
- Billing, quotas, virtual keys, or admin budget controls.
- Provider live model discovery unless explicitly approved.
