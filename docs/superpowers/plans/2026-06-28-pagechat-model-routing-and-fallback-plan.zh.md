# PageChat Model Routing And Fallback Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents unless the user explicitly re-enables them.

**Goal:** Fix LiteLLM provider routing for user-selected models and stop silently using backend default models when a user has not configured model routes.

**Architecture:** Keep user-facing model ids raw in the database and normalize them only at the provider boundary. Treat environment models as an explicit development fallback, not as product behavior. Return clear configuration errors when a required model route is missing.

**Tech Stack:** FastAPI, SQLite, LiteLLM, OpenAI-compatible providers, Vue settings/chat UI, pytest, Vitest.

---

## Current Findings

- `LLM_FLASH_MODEL` and `LLM_PLUS_MODEL` are still used by `MODEL_CONFIG`, `ModelSettingsService.ENV_ROUTE_MODELS`, and `ModelGateway._model_for`.
- The current LiteLLM error happens because PageChat stores `provider_config.provider = "dashscope"` but calls LiteLLM with bare `model = "qwen3.7-max-2026-06-08"`.
- LiteLLM requires a provider-aware model, such as `dashscope/qwen3.7-max-2026-06-08` or `openai/qwen3.7-max-2026-06-08`, or an equivalent explicit provider parameter.
- If the user has no route, the backend can still call `LLM_API_KEY / LLM_BASE_URL / LLM_MODEL` from environment fallback. This should be opt-in only.
- Switching models in Settings does persist and affect new backend runs in the normal single-provider path:
  - `SettingsModal.vue` builds `model_route_mappings`,
  - `PUT /api/settings/model-routes` saves them,
  - `chat_by_scenario(..., user_id=...)` resolves the current user's route.
- Two important gaps remain:
  - route changes can still fail at runtime until LiteLLM receives provider-aware model params,
  - frontend model option values are display-label based, so two configured providers with the same label can save the wrong `provider_id`.
- Suspicious config leftovers to review after behavior changes:
  - `MULTITURN_MAX_EVIDENCE`
  - `EVIDENCE_REUSE_SIMILARITY_MIN`
  - `ALLOW_CROSS_SESSION_EVIDENCE_REUSE`
  - `BIGMODEL_API_KEY`
  - `BIGMODEL_BASE_URL`
  - `BIGMODEL_OCR_MODEL`
  - `PAGE_TEXT_SHORT_THRESHOLD`
  - `EFFECTIVE_PAGEINDEX_CONFIG`
  - OCR threshold/timeout variables that are defined but not externally referenced.

## File Map

- Modify: `backend/app/services/litellm_adapter.py`
  - Own LiteLLM-specific model/provider normalization.
- Modify: `backend/app/core/llm.py`
  - Stop silent environment fallback for chat/scenario calls unless explicitly enabled.
- Modify: `backend/app/services/model_settings_service.py`
  - Make route resolution able to distinguish user route, environment fallback, and missing route.
- Modify: `backend/app/services/model_gateway.py`
  - Apply the same missing-route behavior for PageIndex/model-gateway paths.
- Modify: `backend/app/api/chat.py` and possibly `backend/app/services/chat_service.py`
  - Surface route-missing errors as clear user-facing stream/API errors.
- Modify: `backend/app/api/settings.py`
  - Ensure provider connection tests go through normalized LiteLLM params.
- Modify: `frontend/src/stores/chat.ts` or current chat error renderer if needed
  - Show a concise "configure model first" message.
- Modify: `frontend/src/components/settings/SettingsModal.vue`
  - Make missing route state obvious in model route UI if backend returns route errors.
  - Preserve `provider_id` in model option values so switching models always saves the intended provider.
- Modify: `frontend/src/utils/modelProviderModels.ts`
  - Stop encoding provider identity only as a human display label.
- Test: `backend/tests/test_litellm_adapter.py`
- Test: `backend/tests/test_model_settings_service.py`
- Test: `backend/tests/test_llm_timeout_defaults.py`
- Test: `backend/tests/test_model_gateway_settings.py`
- Test: `backend/tests/test_model_settings_api.py`
- Test: `backend/tests/test_chat_stream_api.py`
- Test: relevant frontend store/settings tests.
- Docs: `codex.md`

---

### Task 1: Add LiteLLM Provider Normalization

**Files:**
- Modify: `backend/app/services/litellm_adapter.py`
- Test: `backend/tests/test_litellm_adapter.py`

- [ ] **Step 1: Write failing tests for provider-aware model params**

Add tests covering:

```python
def test_dashscope_model_is_prefixed_for_litellm(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.litellm_adapter.litellm.acompletion",
        fake_acompletion,
    )

    asyncio.run(
        LiteLLMAdapter().acompletion(
            provider_config={
                "provider": "dashscope",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-secret",
                "model": "qwen3.7-max-2026-06-08",
            },
            messages=[{"role": "user", "content": "hi"}],
        )
    )

    assert calls[0]["model"] == "dashscope/qwen3.7-max-2026-06-08"
```

Also test:
- `openai_compatible` becomes `openai/<model>`.
- already-prefixed `dashscope/qwen-plus` is not double-prefixed.
- API keys are still redacted in errors.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_litellm_adapter.py -q
```

Expected: new tests fail because model is still passed as the raw id.

- [ ] **Step 3: Implement normalization at adapter boundary**

Add a small helper in `litellm_adapter.py`, for example:

```python
_LITELLM_PROVIDER_PREFIX = {
    "dashscope": "dashscope",
    "openai": "openai",
    "openai_compatible": "openai",
    "environment": "openai",
    "deepseek": "openai",
    "moonshot": "openai",
    "zhipuai": "openai",
    "siliconflow": "openai",
    "volcengine_ark": "openai",
    "google_gemini": "openai",
    "ollama": "openai",
}
```

Rules:
- Do not change the database model id.
- If model already has a provider prefix, keep it.
- For DashScope, prefer `dashscope/<model>`.
- For OpenAI-compatible endpoints, use `openai/<model>` with `api_base`.
- Keep `api_key`, `api_base`, `stream`, `timeout`, and extra params unchanged.
- Do not add a broad provider abstraction here; this helper is only for LiteLLM.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_litellm_adapter.py backend/tests/test_llm_timeout_defaults.py backend/tests/test_model_settings_api.py -q
```

Commit:

```powershell
git add backend/app/services/litellm_adapter.py backend/tests/test_litellm_adapter.py backend/tests/test_llm_timeout_defaults.py backend/tests/test_model_settings_api.py
git commit -m "fix(model): normalize litellm provider models"
```

---

### Task 2: Make Provider Test Use The Same Normalized Path

**Files:**
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_model_settings_api.py`

- [ ] **Step 1: Add failing API tests for DashScope provider test**

Add a test where provider is `dashscope`, selected model is `qwen3.7-max-2026-06-08`, and the fake adapter receives normalized model params.

- [ ] **Step 2: Verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_api.py -q
```

- [ ] **Step 3: Keep settings API thin**

Do not duplicate provider normalization in `settings.py`; it should call `LiteLLMAdapter` and rely on Task 1.

- [ ] **Step 4: Run and commit**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_api.py backend/tests/test_litellm_adapter.py -q
```

Commit:

```powershell
git add backend/app/api/settings.py backend/tests/test_model_settings_api.py
git commit -m "test(settings): cover provider test model normalization"
```

---

### Task 3: Preserve Provider Identity In Settings Model Options

**Files:**
- Modify: `frontend/src/utils/modelProviderModels.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Test: `frontend/src/utils/modelProviderModels.test.ts`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`

- [ ] **Step 1: Write failing tests for duplicate providers**

Add a test with two configured providers that share the same display label, for example two DashScope credentials:

```ts
it('keeps provider identity when two providers share a label', () => {
  const options = buildAvailableModelOptions(
    [
      { provider_id: 'dash-a', provider: 'dashscope' },
      { provider_id: 'dash-b', provider: 'dashscope' },
    ],
    {
      'dash-a': [{ id: 'qwen-plus' }],
      'dash-b': [{ id: 'qwen3.7-max-2026-06-08' }],
    },
    () => 'Alibaba Cloud Bailian / Tongyi',
  )

  expect(options).toContainEqual(
    expect.objectContaining({
      providerId: 'dash-b',
      modelId: 'qwen3.7-max-2026-06-08',
    }),
  )
})
```

The exact return shape can differ, but it must carry `providerId` separately from the display label.

- [ ] **Step 2: Run test and confirm failure**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
```

Expected: failure because options are currently strings like `Label: model`.

- [ ] **Step 3: Replace string-only model options with structured options**

Use a structured option type, for example:

```ts
interface ModelSelectOption {
  value: string // `${provider_id}::${model_id}`
  label: string // human readable label
  providerId: string
  providerLabel: string
  modelId: string
  capabilities: ModelCapability[]
}
```

Rules:
- `<select>` value should be stable and machine-readable.
- UI text should stay human-readable.
- Saving routes must parse `providerId` and `modelId` from the selected option, not from display labels.
- Loading saved routes should reconstruct the same stable value from `route.provider_id` and `route.model`.
- Existing single-provider behavior must stay unchanged visually.

- [ ] **Step 4: Run frontend tests and commit**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
npm.cmd test
```

Commit:

```powershell
git add frontend/src/utils/modelProviderModels.ts frontend/src/utils/modelProviderModels.test.ts frontend/src/components/settings/SettingsModal.vue frontend/src/components/settings/SettingsModal.contract.test.ts
git commit -m "fix(settings): preserve provider identity in model routes"
```

---

### Task 4: Disable Silent Environment Model Fallback By Default

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/llm.py`
- Modify: `backend/app/services/model_settings_service.py`
- Test: `backend/tests/test_model_settings_service.py`
- Test: `backend/tests/test_llm_timeout_defaults.py`

- [ ] **Step 1: Add config flag test**

Add tests for:
- default `ALLOW_ENV_MODEL_FALLBACK` is `False`,
- when no user route exists, scenario calls fail with a clear route-missing error,
- when `ALLOW_ENV_MODEL_FALLBACK=True`, existing environment fallback still works for local/dev use.

- [ ] **Step 2: Add an explicit exception**

Create a small exception, for example:

```python
class ModelRouteNotConfiguredError(RuntimeError):
    def __init__(self, route_slot: str):
        super().__init__(
            f"Model route '{route_slot}' is not configured. Configure it in Settings."
        )
        self.route_slot = route_slot
```

Place it near model route resolution code, not in UI/API code.

- [ ] **Step 3: Update route resolution**

Change route resolution so missing user route is not silently converted to environment config unless `ALLOW_ENV_MODEL_FALLBACK` is true.

Important:
- Do not remove `LLM_FLASH_MODEL` / `LLM_PLUS_MODEL` yet.
- Do not break tests that explicitly opt into fallback.
- Keep environment fallback available for local debugging only.

- [ ] **Step 4: Run and commit**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_service.py backend/tests/test_llm_timeout_defaults.py -q
```

Commit:

```powershell
git add backend/app/core/config.py backend/app/core/llm.py backend/app/services/model_settings_service.py backend/tests/test_model_settings_service.py backend/tests/test_llm_timeout_defaults.py
git commit -m "fix(model): require configured user model routes"
```

---

### Task 5: Surface Missing Model Routes Clearly In Chat/API

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `frontend/src/stores/chat.ts`
- Test: `backend/tests/test_chat_stream_api.py`
- Test: `frontend/src/stores/chat.test.ts`

- [ ] **Step 1: Add failing stream test**

Simulate no user route and `ALLOW_ENV_MODEL_FALLBACK=False`.

Expected stream behavior:
- no generic LiteLLM stack trace,
- user-facing error says model route is not configured,
- error includes route slot such as `document_qa` or `general_chat`.

- [ ] **Step 2: Update backend error mapping**

Catch `ModelRouteNotConfiguredError` at the chat stream boundary and emit a stable error payload, for example:

```json
{
  "type": "run_failed",
  "error_code": "MODEL_ROUTE_NOT_CONFIGURED",
  "route_slot": "document_qa",
  "message": "请先在设置页配置问答模型。"
}
```

- [ ] **Step 3: Update frontend display**

Show a concise action-oriented message in the assistant area. Do not show stack traces.

- [ ] **Step 4: Run and commit**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_chat_stream_api.py -q
cd frontend
npm.cmd test -- src/stores/chat.test.ts
```

Commit:

```powershell
git add backend/app/api/chat.py backend/app/services/chat_service.py backend/tests/test_chat_stream_api.py frontend/src/stores/chat.ts frontend/src/stores/chat.test.ts
git commit -m "fix(chat): show missing model route errors"
```

---

### Task 6: Apply The Same Rule To PageIndex / ModelGateway

**Files:**
- Modify: `backend/app/services/model_gateway.py`
- Modify: `backend/app/services/pageindex_service.py` if needed
- Test: `backend/tests/test_model_gateway_settings.py`
- Test: `backend/tests/test_pageindex_model_routes.py`

- [ ] **Step 1: Add failing tests**

Cover:
- PageIndex model gateway fails clearly when required route is missing.
- Environment fallback works only when explicitly enabled.
- User-configured route still works.

- [ ] **Step 2: Implement minimal route enforcement**

Reuse the same route-missing exception and config flag from Task 3.

- [ ] **Step 3: Run and commit**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_gateway_settings.py backend/tests/test_pageindex_model_routes.py -q
```

Commit:

```powershell
git add backend/app/services/model_gateway.py backend/app/services/pageindex_service.py backend/tests/test_model_gateway_settings.py backend/tests/test_pageindex_model_routes.py
git commit -m "fix(pageindex): require configured model routes"
```

---

### Task 7: Clean Up Confirmed Config Residue

**Files:**
- Modify: `backend/app/core/config.py`
- Modify tests that referenced removed config, if any.

- [ ] **Step 1: Re-run static reference scan**

Run:

```powershell
rg -n "MULTITURN_MAX_EVIDENCE|EVIDENCE_REUSE_SIMILARITY_MIN|ALLOW_CROSS_SESSION_EVIDENCE_REUSE|BIGMODEL_API_KEY|BIGMODEL_BASE_URL|BIGMODEL_OCR_MODEL|PAGE_TEXT_SHORT_THRESHOLD|EFFECTIVE_PAGEINDEX_CONFIG" backend/app backend/tests -g "*.py"
```

- [ ] **Step 2: Remove only variables with no external runtime use**

Safe initial candidates:
- `MULTITURN_MAX_EVIDENCE`
- `EVIDENCE_REUSE_SIMILARITY_MIN`
- `ALLOW_CROSS_SESSION_EVIDENCE_REUSE`
- `PAGE_TEXT_SHORT_THRESHOLD`
- `EFFECTIVE_PAGEINDEX_CONFIG`

Handle separately:
- `BIGMODEL_*` aliases: remove only if no historical import path needs them.
- OCR thresholds/timeouts: keep until OCR code is audited; they may become part of OCR settings.

- [ ] **Step 3: Run and commit**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_settings_service.py backend/tests/test_pageindex_model_routes.py backend/tests/test_model_gateway_settings.py -q
```

Commit:

```powershell
git add backend/app/core/config.py backend/tests
git commit -m "chore(config): remove unused model fallback residue"
```

---

### Task 8: Regression And Browser E2E

**Files:**
- Modify: `codex.md`
- Modify: this plan's progress notes if execution requires a handoff.

- [ ] **Step 1: Backend regression**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_litellm_adapter.py backend/tests/test_model_settings_api.py backend/tests/test_model_settings_service.py backend/tests/test_llm_timeout_defaults.py backend/tests/test_model_gateway_settings.py backend/tests/test_pageindex_model_routes.py backend/tests/test_chat_stream_api.py -q
```

- [ ] **Step 2: Frontend regression**

Run:

```powershell
cd frontend
npm.cmd test
npm.cmd run build
```

- [ ] **Step 3: Browser E2E**

Use current `codex.md` startup rules.

Verify:
- no model route -> chat shows "configure model first",
- configured DashScope route with model `qwen3.7-max-2026-06-08` no longer throws `LLM Provider NOT provided`,
- two providers with the same display label save and reload the exact selected `provider_id`,
- provider test updates validation state visibly,
- document QA still streams with flat tool loop,
- citations and preview still work.

- [ ] **Step 4: Update docs and commit**

Update `codex.md` to document:
- `ALLOW_ENV_MODEL_FALLBACK=false` default,
- how to enable env fallback for local debugging,
- LiteLLM provider normalization behavior.

Commit:

```powershell
git add codex.md docs/superpowers/plans/2026-06-28-pagechat-model-routing-and-fallback-plan.zh.md
git commit -m "docs(model): document routing fallback cleanup"
```

---

## Acceptance Criteria

- Selecting `qwen3.7-max-2026-06-08` under DashScope does not produce `LLM Provider NOT provided`.
- User-selected models keep clean display ids in UI.
- Settings model selection stores provider identity by `provider_id`, not by display label.
- Switching a model in Settings affects subsequent runs for that route slot.
- LiteLLM receives provider-aware model params at the adapter boundary.
- A user with no configured route cannot silently consume backend default model credentials.
- Missing model route errors are understandable and point to Settings.
- Environment model fallback is available only behind an explicit development flag.
- Confirmed unused config variables are removed or documented as intentionally retained.
