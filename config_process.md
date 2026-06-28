# PageChat Config Refactor Process

This file is the compact handoff log for model routing, LiteLLM provider normalization, and config fallback cleanup. Read it before each phase. At every phase start and completion, append a short status note.

## Baseline

- Branch: `codex/pagechat-ui-agent-runtime-integration`
- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Plan: `docs/superpowers/plans/2026-06-28-pagechat-model-routing-and-fallback-plan.zh.md`
- Rule: no subagents unless the user explicitly re-enables them.

## Current Status

- Phase: 7 - Config residue cleanup
- Status: Complete
- Notes: Removed unused evidence/PageIndex residue; retained `BIGMODEL_*` aliases for compatibility.

## Phase Log

### Phase 0 - Process Initialization

Start:
- Created `config_process.md`.
- Confirmed branch `codex/pagechat-ui-agent-runtime-integration`.
- Next: start Phase 1 with failing LiteLLM adapter tests.

End:
- Process file initialized and ready for per-phase handoff.

### Phase 1 - LiteLLM Provider Normalization

Start:
- Goal: normalize user-facing model ids into LiteLLM provider-aware model params at adapter boundary.
- RED target: `backend/tests/test_litellm_adapter.py`.

End:
- RED: `test_dashscope_model_is_prefixed_for_litellm` and `test_openai_compatible_model_is_prefixed_for_litellm` failed on bare model ids.
- GREEN: added adapter normalization and updated expectations.
- Verification: `test_litellm_adapter.py` -> 7 passed; `test_llm_timeout_defaults.py test_model_settings_api.py` -> 23 passed.

### Phase 2 - Provider Test Route Coverage

Start:
- Goal: ensure `POST /model-providers/{id}/test` uses the same LiteLLM normalization path.
- RED target: `backend/tests/test_model_settings_api.py`.

End:
- Added DashScope provider-test coverage through real `LiteLLMAdapter` path.
- Verification: `test_model_settings_api.py test_litellm_adapter.py` -> 23 passed.

### Phase 3 - Settings Provider Identity

Start:
- Goal: preserve `provider_id` in frontend model option values.
- RED target: `frontend/src/utils/modelProviderModels.test.ts`.

End:
- RED: duplicate-provider-label test failed because model options were strings.
- GREEN: model selects now store `provider_id::model_id` and render human labels.
- Verification: targeted settings tests -> 14 passed; frontend `npm test` -> 132 passed.

### Phase 4 - Disable Silent Environment Model Fallback

Start:
- Goal: missing user model routes fail by default instead of silently using env credentials.
- RED target: `backend/tests/test_model_settings_service.py`.

End:
- RED: missing `ModelRouteNotConfiguredError` and fallback gate caused target tests to fail.
- GREEN: added explicit route-missing exception and `ALLOW_ENV_MODEL_FALLBACK` gate.
- Verification: `test_model_settings_service.py test_llm_timeout_defaults.py` -> 19 passed.

### Phase 5 - Missing Model Route Chat/API Errors

Start:
- Goal: chat stream surfaces `MODEL_ROUTE_NOT_CONFIGURED` instead of stack traces or silent fallback.
- RED target: `backend/tests/test_chat_stream_api.py` and `frontend/src/stores/chat.test.ts`.

End:
- RED: missing-route SSE lacked `error_code`; frontend showed raw English exception.
- GREEN: added stable missing-route payload and store display mapping.
- Verification: `test_chat_stream_api.py` -> 8 passed; `chat.test.ts` -> 36 passed.

### Phase 6 - PageIndex / ModelGateway Route Enforcement

Start:
- Goal: PageIndex/model gateway fails clearly without a configured route unless env fallback is enabled.
- RED target: `backend/tests/test_model_gateway_settings.py` and `backend/tests/test_pageindex_model_routes.py`.

End:
- RED: user ModelGateway fell back without settings; PageIndex swallowed missing-route errors and dropped env routes.
- GREEN: enforced missing-route propagation and allowed explicit env route passthrough.
- Verification: `test_model_gateway_settings.py test_pageindex_model_routes.py` -> 16 passed.

### Phase 7 - Config Residue Cleanup

Start:
- Goal: remove only confirmed unused model fallback residue from `backend/app/core/config.py`.
- Scan target: suspicious model/evidence/PageIndex compatibility variables.

End:
- Scan: only candidate definitions existed in `config.py`; `BIGMODEL_*` aliases intentionally retained.
- Removed: `MULTITURN_MAX_EVIDENCE`, `EVIDENCE_REUSE_SIMILARITY_MIN`, `ALLOW_CROSS_SESSION_EVIDENCE_REUSE`, `PAGE_TEXT_SHORT_THRESHOLD`, `EFFECTIVE_PAGEINDEX_CONFIG`.
- Verification: `test_runtime_settings_service.py test_pageindex_model_routes.py test_model_gateway_settings.py` -> 20 passed.
