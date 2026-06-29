# Model Provider Settings Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PageChat 设置弹窗里的模型供应商配置、模型能力展示、API Key 状态、连接测试和功能模型路由生效问题。

**Architecture:** 前端继续以 `SettingsModal.vue` 为设置页入口，新增/扩展小型工具函数承载筛选、能力统计、模型选项过滤和自动测试状态，避免把复杂逻辑塞进模板。后端复用现有 `ModelSettingsService`、`OCRSettingsService` 和 route mapping，补齐测试状态持久化、模型能力推断和路由生效回归。

**Tech Stack:** Vue 3 + Pinia/Vitest + FastAPI + SQLite + pytest + existing PageChat settings APIs.

---

## Scope And Current Findings

- 搜索框现在没有绑定 `v-model`，`providerRows` 不过滤，所以搜索不可用；CSS 上固定宽度在窄空间会溢出。
- API Key 保存后前端清空输入框，但没有用 `api_key_mask` 做占位/状态提示，用户会以为没填。
- “测试模型”字段和单独测试按钮仍暴露给用户；后端 `/test` 必须传 `model`，但测试应由当前 API Key + 自动选择模型触发。
- 未保存供应商没有 provider_id，因此无法走现有 `/model-providers/{id}/test`；应保存/更新后自动拉模型并测试，测试过程显示 loading/success/error。
- Available models 没有滚动容器，且只展示 id/source，缺少 vision、embedding、tool calling 等能力统计。
- 供应商头部静态 `LLM/Vision/Embedding/Tool Calling` 标签不需要，移除。
- OCR 模型选择应只展示 VLM/OCR 能力模型；解析/问答模型选择继续基于可用模型，但必须通过 route mapping 保存并被后端解析使用。
- 后端已有 `resolve_route()` 和 OCR resolver，但前端设置页当前未完整加载/保存 route/ocr routes。

## Task 1: Frontend Provider List Search And Layout

**Files:**
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`
- Test: `frontend/src/utils/modelProviderRows.test.ts`

- [ ] Add `providerSearchQuery` state and filter provider rows by provider label/provider/base URL.
- [ ] Bind search input with `v-model`.
- [ ] Make `.section-header` and `.provider-search` use `min-width: 0` and responsive width so the search box never crosses the panel border.
- [ ] Add contract tests checking `v-model="providerSearchQuery"` and filtered rows.

## Task 2: API Key Mask And Auto Test Flow

**Files:**
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `frontend/src/api/index.ts`
- Modify: `backend/app/api/settings.py`
- Modify: `backend/app/services/model_settings_service.py`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`
- Test: `backend/tests/test_model_settings_api.py`
- Test: `backend/tests/test_model_settings_service.py`

- [ ] Show saved `api_key_mask` as encrypted/masked state in the API Key placeholder and helper text.
- [ ] Remove visible “测试模型” input.
- [ ] Replace explicit model-test UX with save/update flow that automatically fetches models and tests the first usable model.
- [ ] Add backend service method to mark provider validation status as `valid`/`invalid`.
- [ ] Change `/model-providers/{id}/test` so `model` is optional; if missing, backend fetches `/models` and uses the first model id.
- [ ] Add UI loading/success/error state for testing, and refresh provider list after test so status is not stuck at `untested`.

## Task 3: Available Models Capability Display

**Files:**
- Modify: `frontend/src/types/modelSettings.ts`
- Modify: `frontend/src/utils/modelProviderModels.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `backend/app/services/model_settings_service.py`
- Test: `frontend/src/utils/modelProviderModels.test.ts`
- Test: `backend/tests/test_model_settings_service.py`
- Test: `backend/tests/test_model_settings_api.py`

- [ ] Normalize provider model metadata into capabilities: `llm`, `vision`, `embedding`, `tool_calling`, `ocr`.
- [ ] Infer capabilities from model id patterns where remote metadata is sparse.
- [ ] Render capability chips inside each model row.
- [ ] Add a scrollable `.model-list-body` so Available models can scroll inside the expanded provider panel.
- [ ] Remove static provider header capability tags.

## Task 4: Model Options For OCR, Parsing, QA

**Files:**
- Modify: `frontend/src/utils/modelProviderModels.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Test: `frontend/src/utils/modelProviderModels.test.ts`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`

- [ ] Build separate computed option lists:
  - `ocrModelOptions`: only `vision` or `ocr` capability.
  - `parsingModelOptions`: all LLM/vision-capable models.
  - `qaModelOptions`: prioritize vision-capable models but allow LLM models.
- [ ] Wire OCR settings select to `ocrModelOptions`; parsing and QA to their own lists.
- [ ] Keep sensible fallback options if no configured provider models have been fetched.

## Task 5: Persist And Verify Functional Model Routes

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `backend/tests/test_model_settings_service.py`
- Modify: `backend/tests/test_ocr_resolver.py`
- Add or update frontend contract tests.

- [ ] Load existing `/model-routes` and `/ocr-routes` on modal mount.
- [ ] Save parsing model to `indexing`, QA model to `document_qa`, OCR model to OCR route/profile where possible.
- [ ] Verify backend `resolve_route(user_id, "document_qa")` returns the configured provider/model.
- [ ] Verify backend OCR resolver uses configured OCR profile/route for `page_text`.
- [ ] Show save status for route settings.

## Task 6: Regression, Build, Restart

**Files:**
- No production files expected unless tests reveal gaps.

- [ ] Run backend targeted tests:
  `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend\tests\test_model_settings_service.py backend\tests\test_model_settings_api.py backend\tests\test_ocr_resolver.py -q`
- [ ] Run frontend targeted tests:
  `npm.cmd test -- src/components/settings/SettingsModal.contract.test.ts src/utils/modelProviderRows.test.ts src/utils/modelProviderModels.test.ts`
- [ ] Run frontend build: `npm.cmd run build`
- [ ] Run `git diff --check`.
- [ ] Restart backend using `C:\Users\TT_WT\Desktop\start-backend.bat` and verify `/health`.
