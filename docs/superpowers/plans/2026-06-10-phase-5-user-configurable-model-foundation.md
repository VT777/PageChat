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
- API key storage mode is approved: encrypted-at-rest, development-only plaintext, or external secret manager.
- A stable application secret exists if encrypted-at-rest storage is selected.
- Custom OpenAI-compatible providers are either explicitly allowed in v1 or deferred behind a later advanced setting.
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md` is available as the latest retrieval/evidence baseline.

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

### Decision Record Required Before Start

Before Task 1 begins, record the approved decisions in this section or in the Phase 5 completion notes. Do not leave these as implementation-time assumptions:

| Decision | Required before |
| --- | --- |
| Settings ownership: per-user, admin-global, or both | Any persistence schema or API shape is created |
| API key storage mode: encrypted, development-only plaintext, or external secret manager | Any provider config write endpoint is implemented |
| Secret source for encryption or production enforcement | Any production-capable model settings path is enabled |
| Configurable route slots for v1 | `ModelGateway` route mapping is changed |
| Custom OpenAI-compatible provider support | Provider preset API and frontend shape are finalized |
| Model list behavior: live discovery, curated presets, or manual IDs | Provider validation and settings UI are finalized |

If a decision is intentionally deferred, the implementation must fail closed in production and the completion gate must record the deferral explicitly.

### Implementation Decision Record (2026-06-11)

| Decision | Phase 5 implementation choice |
| --- | --- |
| Settings ownership | Per-user settings with existing environment fallback |
| API key storage mode | Development profile stores protected local values; production refuses model-key writes unless a stable `MODEL_SETTINGS_SECRET` or `SECRET_KEY` is available |
| Secret source | Environment-backed `MODEL_SETTINGS_SECRET` preferred, `SECRET_KEY` accepted for local compatibility; no import-time generated secret |
| Configurable route slots for v1 | `general_chat`, `document_qa`, `query_expansion`, `indexing`, `vision` |
| Custom OpenAI-compatible provider support | Allowed in v1 through `openai_compatible` provider config with editable `base_url` and model IDs |
| Model list behavior | Curated presets plus manual model IDs; no live provider model discovery in Phase 5 |

## Security Gate

Do not implement Tasks 1-4 for production use until these gate items are decided and recorded in this plan or a phase report:

- **Ownership:** settings are per-user, admin-global, or both.
- **Secret storage:** raw keys are encrypted at rest, stored only in a local development profile, or delegated to an external secret manager.
- **Secret source:** the encryption key or secret-manager configuration is environment-backed and not generated at import time.
- **Read behavior:** list/read endpoints return only masked key state and metadata, never raw API keys.
- **Validation behavior:** provider testing uses monkeypatched adapters in tests and never requires live provider calls in CI.
- **Fallback behavior:** when no user setting exists, current `.env`/Qwen behavior remains unchanged.

If any item is deferred, the implementation must fail closed in production and document the deferral in the completion gate.

## Phase 0 Hardening Status Audit

The source model-configuration plan included a broader architecture-hardening Phase 0. Before Phase 5 begins, record the status of each item below in the Phase 5 completion notes or an implementation kickoff note. Do not reopen completed Phase 1-4 work unless the audit finds a regression.

| Source hardening item | Expected status before Phase 5 implementation | Phase 5 action |
| --- | --- | --- |
| Upload filename normalization and safe storage names | Covered by the Phase 1 safety baseline if its report remains valid | Verify report status; only add follow-up if current code regressed |
| User scope mandatory for tool execution | Covered by Phase 1 safety baseline and Phase 4 scoped Agent retrieval | Verify focused scope tests still pass before model-route cache changes |
| Search scope cannot widen across users | Covered by Phase 1 safety baseline and Phase 4 folder-aware search filtering | Preserve user/scope boundaries when adding model-route fingerprints |
| Lightweight migrations and missing document columns | Covered by Phase 1 safety baseline if its report remains valid | Use the existing migration mechanism for model settings tables if SQLite persistence is selected |
| SQLite foreign keys and core indexes | Covered by Phase 1 safety baseline if its report remains valid | Do not weaken existing database initialization or migration behavior |
| Folder deletion cleans files, indexes, caches, and agent state | Covered by Phase 1 safety baseline if its report remains valid | Keep model settings independent from document cleanup unless cache keys change |
| JWT secret generated at import time | Not fully closed until this phase | Implement Task 0 before production-capable model-key storage |
| User-scoped cache keys | Covered by Phase 1 and Phase 4 for retrieval scope; model route is still new | Add model route/version or settings fingerprint where model output can affect cached behavior |
| Raw model API keys exposed through read/list APIs | New Phase 5 responsibility | Enforce write-only key behavior in service and API tests |
| User-owned model settings ownership | New Phase 5 decision | Record per-user, admin-global, or both before creating persistence schema |

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

Persist a provider config with enough metadata to support masking and rotation:

```json
{
  "provider_id": "provider-1",
  "user_id": "user-1",
  "provider": "openai_compatible",
  "base_url": "https://example.test/v1",
  "api_key_ciphertext": "...",
  "api_key_mask": "sk-...abcd",
  "validation_status": "untested",
  "created_at": "...",
  "updated_at": "..."
}
```

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
- Raw API keys are not included in exception messages or logs.

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
- Read/list responses never include raw API keys.
- Production mode rejects insecure key storage if encryption or an approved secret backend is required.

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
- `docs/superpowers/2026-06-10-phase-2-improvement-report.md`
- Source plan: `<source-plan-copy>\docs\superpowers\plans\2026-06-10-user-configurable-models.md`
- Current git status.
- Test output from Steps 1-2.

## Done Criteria

Phase 5 is complete when:

- Model provider settings are persisted under the approved scope.
- Production mode fails when JWT signing secret is missing.
- Production mode fails or refuses model-key writes when the approved secret-storage requirement is not satisfied.
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
