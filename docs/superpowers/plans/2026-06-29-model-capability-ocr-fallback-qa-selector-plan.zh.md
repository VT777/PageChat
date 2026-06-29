# Model Capability, OCR Fallback, and QA Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 PageChat 的模型能力标签、问答模型路由、图片页证据返回策略保持一致，并让用户在问答设置中按供应商和真实能力选择模型。

**Architecture:** 后端作为模型能力的唯一事实来源，前端只展示后端返回的规范化能力，不再做模型名启发式推断。工具执行时读取当前用户的 `document_qa` 路由能力：QA 模型有 vision 时返回图片证据；QA 模型无 vision 时返回已解析 OCR 文本作为证据 fallback。

**Tech Stack:** FastAPI, SQLite, aiosqlite, LiteLLM adapter, Vue 3, TypeScript, Vitest, pytest.

---

## 背景与边界

当前实现里，模型能力有三层来源：

- 供应商 `/models` 原始返回：少数供应商可能带 `capabilities`、`features`、上下文长度等字段。
- 后端启发式：当供应商只返回模型 id 时，后端按模型名猜测 `vision`、`reasoning`、`embedding` 等能力。
- 前端启发式：`frontend/src/utils/modelProviderModels.ts` 再次按模型名推断能力，导致 UI 上不同模型标签看起来趋同，且可能和后端路由保存结果不一致。

本次改造的产品边界：

- 前端不再保留能力启发式；所有能力标签都来自后端返回。
- 后端返回能力时必须标记来源，避免把推断能力伪装成厂家真实状态。
- 不引入复杂模型目录服务，先用“供应商元数据优先 + 少量后端 known catalog + 保守 unknown”。
- 如果用户选择的问答模型没有 vision，图片页不应强制要求模型看图；应返回 OCR 文本证据。
- 如果图片页没有 OCR 文本且 QA 模型无 vision，应返回清晰、可行动的错误。

## 文件结构

**后端能力规范化**

- Modify: `backend/app/services/model_settings_service.py`
  - 规范化模型能力返回结构。
  - 增加 `capability_source` / `capability_sources` 字段。
  - route 保存时根据后端模型能力写入 `supports_vision` 等字段。
- Modify: `backend/app/api/settings.py`
  - 保存 route 时不信任前端传入的 `supports_vision`，改由后端根据模型能力解析。
- Test: `backend/tests/test_model_settings_service.py`
- Test: `backend/tests/test_model_settings_api.py`

**图片页 OCR fallback**

- Modify: `backend/app/services/tool_executor.py`
  - `ToolExecutor` 增加当前 QA 模型能力上下文，例如 `qa_supports_vision`。
  - `get_page_content` 针对视觉页按 QA 能力返回图片引用或 OCR 文本。
- Modify: `backend/app/services/agent_service.py` 或 `backend/app/agent/model_tool_loop.py`
  - 创建 `ToolExecutor` 时注入当前 `document_qa` route 的 `supports_vision`。
- Modify: `backend/app/services/document_keyword_locator.py`
  - `search_within_document` 命中 OCR/图片页时，同步支持 non-vision fallback 的紧凑 OCR snippet。
- Test: `backend/tests/test_agent_navigation_tools_contract.py`
- Test: `backend/tests/test_document_keyword_locator.py`
- Test: `backend/tests/test_flat_loop_tool_guidance.py`

**前端展示和选择器**

- Modify: `frontend/src/types/modelSettings.ts`
  - 增加模型能力来源字段类型。
- Modify: `frontend/src/utils/modelProviderModels.ts`
  - 删除前端模型名推断。
  - 所有 builder 只使用后端返回的 `capabilities`。
  - QA 模型选项按供应商分组。
- Modify: `frontend/src/components/settings/SettingsModal.vue`
  - 模型供应商列表展示后端能力标签和来源状态。
  - 问答设置页改为按供应商分组的模型选择 UI，并显示能力标签、上下文长度。
  - 非 vision QA 模型可选，但提示“图片页将使用 OCR 文本”。
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`
- Test: `frontend/src/utils/modelProviderModels.test.ts`

---

### Task 1: 后端模型能力返回结构成为唯一事实来源

**Files:**
- Modify: `backend/app/services/model_settings_service.py`
- Test: `backend/tests/test_model_settings_service.py`

- [ ] **Step 1: 写 failing tests**

新增测试覆盖：

```python
def test_provider_metadata_capabilities_are_marked_as_provider_metadata():
    payload = {"data": [{"id": "model-a", "capabilities": ["vision", "function_calling"]}]}
    models = _normalize_provider_models(payload)
    assert models[0]["capabilities"] == ["vision", "tool_calling"]
    assert models[0]["capability_source"] == "provider_metadata"


def test_models_without_metadata_do_not_get_frontend_style_fake_tags():
    payload = {"data": [{"id": "plain-text-model"}]}
    models = _normalize_provider_models(payload)
    assert models[0]["capabilities"] == ["llm"]
    assert models[0]["capability_source"] in {"known_catalog", "inferred", "unknown"}
    assert models[0]["supports_vision"] is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_service.py -q
```

Expected: 新增测试失败，因为当前没有清晰的能力来源字段，且默认能力可能包含 `tool_calling`。

- [ ] **Step 3: 实现最小后端能力规范化**

在 `model_settings_service.py` 中保留 `MODEL_CAPABILITY_ORDER`，但调整策略：

- 厂商明确返回能力字段：`capability_source = "provider_metadata"`。
- 自定义模型：`capability_source = "custom"`。
- 后端 known catalog 命中：`capability_source = "known_catalog"`。
- 仅模型名弱推断：`capability_source = "inferred"`。
- 完全未知：只标 `["llm"]`，`capability_source = "unknown"`。

注意：不再把所有未知聊天模型默认标成 `tool_calling`，除非 known catalog 或 provider metadata 明确支持。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_service.py -q
```

Expected: PASS.

- [ ] **Step 5: 提交**

```powershell
git add backend/app/services/model_settings_service.py backend/tests/test_model_settings_service.py
git commit -m "feat(settings): normalize backend model capability sources"
```

---

### Task 2: 路由保存时以后端模型能力为准

**Files:**
- Modify: `backend/app/services/model_settings_service.py`
- Modify: `backend/app/api/settings.py`
- Test: `backend/tests/test_model_settings_api.py`
- Test: `backend/tests/test_model_settings_service.py`

- [ ] **Step 1: 写 failing tests**

新增测试覆盖：

```python
def test_save_route_mapping_derives_vision_from_selected_model():
    # provider has two models: text-only and vision
    # saving document_qa to vision model persists supports_vision=True
    # saving document_qa to text model persists supports_vision=False
```

```python
def test_save_route_mapping_ignores_frontend_supports_vision_override():
    # frontend sends supports_vision=True for text-only model
    # backend route still stores supports_vision=False
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_api.py backend/tests/test_model_settings_service.py -q
```

Expected: 新增测试失败，因为当前 route 保存仍可能使用前端传来的 `supports_vision`。

- [ ] **Step 3: 实现 route 能力解析**

在 `ModelSettingsService.save_route_mapping()` 内：

- 根据 `provider_id + model` 查询后端已知模型能力。
- 如果模型存在于 remote/custom 列表，使用该模型能力覆盖 `supports_vision / supports_tool_calling / supports_structured_output`。
- 如果模型列表暂不可用，保守处理：`supports_vision=False`，`supports_tool_calling=True` 仅对 provider metadata 或 known catalog 明确支持时为真。
- 保留 `supports_responses_api` 仍由 provider 能力决定。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_api.py backend/tests/test_model_settings_service.py -q
```

Expected: PASS.

- [ ] **Step 5: 提交**

```powershell
git add backend/app/services/model_settings_service.py backend/app/api/settings.py backend/tests/test_model_settings_api.py backend/tests/test_model_settings_service.py
git commit -m "fix(settings): derive route capabilities on the backend"
```

---

### Task 3: get_page_content 支持 non-vision QA 的 OCR fallback

**Files:**
- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/agent/model_tool_loop.py`
- Modify: `backend/app/services/agent_service.py` if executor construction lives there for legacy paths
- Test: `backend/tests/test_agent_navigation_tools_contract.py`
- Test: `backend/tests/test_flat_loop_tool_guidance.py`

- [ ] **Step 1: 写 failing tests**

新增测试覆盖：

```python
def test_visual_page_content_returns_image_refs_for_vision_qa_model():
    executor = ToolExecutor(..., qa_supports_vision=True)
    result = await executor.execute("get_page_content", {"doc_id": "doc-a", "pages": "4"})
    page = result["data"]["pages"][0]
    assert page["visual_evidence_required"] is True
    assert page["text"] == ""
    assert page["images"]
```

```python
def test_visual_page_content_returns_ocr_text_for_text_only_qa_model():
    executor = ToolExecutor(..., qa_supports_vision=False)
    result = await executor.execute("get_page_content", {"doc_id": "doc-a", "pages": "4"})
    page = result["data"]["pages"][0]
    assert page["visual_evidence_required"] is False
    assert page["text_source"] == "ocr_text_fallback"
    assert "OCR text" in page["text"]
```

```python
def test_visual_page_without_ocr_and_text_only_qa_model_returns_actionable_error():
    executor = ToolExecutor(..., qa_supports_vision=False)
    result = await executor.execute("get_page_content", {"doc_id": "doc-a", "pages": "5"})
    page = result["data"]["pages"][0]
    assert page["error_code"] == "OCR_TEXT_UNAVAILABLE_FOR_TEXT_QA"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_flat_loop_tool_guidance.py -q
```

Expected: non-vision OCR fallback 测试失败，因为当前逻辑固定隐藏 OCR 文本。

- [ ] **Step 3: 实现 ToolExecutor 能力上下文**

在 `ToolExecutor.__init__()` 增加参数：

```python
qa_supports_vision: bool = True
```

在 `_get_single_page_info()` 中：

- `has_visual and qa_supports_vision=True`：保持当前视觉证据行为。
- `has_visual and qa_supports_vision=False and text_content.strip()`：返回 OCR/text fallback。
- `has_visual and qa_supports_vision=False and not text_content.strip()`：返回 page-level error，附 `next_steps`。

返回字段建议：

```python
{
  "visual_evidence_required": False,
  "text_source": "ocr_text_fallback",
  "has_visual_content": True,
  "text": "...",
  "images": [...],
  "fallback_reason": "qa_model_without_vision"
}
```

不要返回 base64，不要返回 OCR 全文之外的额外大字段；仍然遵守 `MAX_TEXT_PAGE_CHARS`。

- [ ] **Step 4: 在 agent runtime 创建 ToolExecutor 时注入 QA route 能力**

查找 `ToolExecutor(...)` 创建点：

- `backend/app/agent/model_tool_loop.py`
- `backend/app/services/agent_service.py`

使用当前 run 已解析的 `document_qa` route：

```python
qa_supports_vision=bool(provider_config.get("supports_vision"))
```

如果没有 route，保守为 `False`，避免无 vision 模型收到图片证据后无法处理。

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_flat_loop_tool_guidance.py -q
```

Expected: PASS.

- [ ] **Step 6: 提交**

```powershell
git add backend/app/services/tool_executor.py backend/app/agent/model_tool_loop.py backend/app/services/agent_service.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_flat_loop_tool_guidance.py
git commit -m "feat(agent): use ocr text fallback for non-vision qa models"
```

---

### Task 4: search_within_document 同步支持 OCR fallback

**Files:**
- Modify: `backend/app/services/document_keyword_locator.py`
- Modify: `backend/app/services/tool_executor.py`
- Test: `backend/tests/test_document_keyword_locator.py`

- [ ] **Step 1: 写 failing tests**

新增测试：

```python
def test_keyword_locator_returns_ocr_snippet_for_text_only_qa_model():
    result = locate_keywords_in_index(index_data=..., query="alpha", doc_id="doc-a", doc_name="a.pdf", qa_supports_vision=False)
    match = result["matches"][0]
    assert match["visual_evidence_required"] is False
    assert match["snippet"]
    assert match["text_source"] == "ocr_text_fallback"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_document_keyword_locator.py -q
```

Expected: FAIL，因为当前 locator 对视觉页固定省略 OCR snippet。

- [ ] **Step 3: 实现参数透传**

- `locate_keywords_in_index(..., qa_supports_vision: bool = True)`。
- vision QA：保持当前 `visual_evidence_required=true`。
- non-vision QA：返回 OCR snippet，标记 `text_source="ocr_text_fallback"`。
- `ToolExecutor._search_within_document()` 传入 `self.qa_supports_vision`。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_document_keyword_locator.py -q
```

Expected: PASS.

- [ ] **Step 5: 提交**

```powershell
git add backend/app/services/document_keyword_locator.py backend/app/services/tool_executor.py backend/tests/test_document_keyword_locator.py
git commit -m "feat(agent): align document search with qa vision capability"
```

---

### Task 5: 前端删除模型能力启发式，只展示后端能力

**Files:**
- Modify: `frontend/src/types/modelSettings.ts`
- Modify: `frontend/src/utils/modelProviderModels.ts`
- Test: `frontend/src/utils/modelProviderModels.test.ts`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`

- [ ] **Step 1: 写 failing tests**

新增测试：

```ts
it('does not infer capabilities from model name on the frontend', () => {
  const model = { id: 'qwen-vl-plus', capabilities: [] }
  expect(modelCapabilityBadges(model)).toEqual([])
})

it('uses backend capabilities exactly for model badges', () => {
  const model = { id: 'plain-model', capabilities: ['llm', 'vision'] as const }
  expect(modelCapabilityBadges(model)).toEqual(['LLM', 'VISION'])
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
```

Expected: FAIL，因为当前前端仍会按模型名推断。

- [ ] **Step 3: 删除前端能力推断**

在 `frontend/src/utils/modelProviderModels.ts`：

- 删除或改造 `inferModelCapabilities()`，使其只做能力字段清洗，不根据模型 id 添加能力。
- `providerCapabilityBadges()` 只聚合后端 `capabilities`。
- `buildOcrModelOptions()` 只接受后端标记了 `ocr` 或 `vision` 的模型。
- `buildQaModelOptions()` 只接受后端标记了 `llm` 或 `vision` 的模型。

保留 `formatModelContextBadge()`，但上下文长度必须来自后端字段。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
```

Expected: PASS.

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/types/modelSettings.ts frontend/src/utils/modelProviderModels.ts frontend/src/utils/modelProviderModels.test.ts frontend/src/components/settings/SettingsModal.contract.test.ts
git commit -m "fix(settings): show backend model capabilities only"
```

---

### Task 6: 问答设置页按供应商分组并展示能力标签

**Files:**
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `frontend/src/utils/modelProviderModels.ts`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`
- Test: `frontend/src/utils/modelProviderModels.test.ts`

- [ ] **Step 1: 写 failing tests**

新增测试：

```ts
it('builds qa model groups by provider with model capability metadata', () => {
  const groups = buildQaModelGroups(providers, providerModels, providerLabel)
  expect(groups[0].providerLabel).toBe('Alibaba Cloud Bailian / Tongyi')
  expect(groups[0].models[0].capabilities).toContain('vision')
})
```

Contract test 检查 `SettingsModal.vue`：

- 包含 `qaModelGroups`。
- 问答设置不再是单层 `v-for="model in qaModelOptions"`。
- 模型行展示 `model-capabilities`。
- 非 vision 模型提示 OCR fallback。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
```

Expected: FAIL.

- [ ] **Step 3: 实现分组 builder**

新增：

```ts
export interface ModelSelectGroup {
  providerId: string
  providerLabel: string
  models: ModelSelectOption[]
}
```

`buildQaModelGroups()` 返回按 provider 分组的模型列表，模型能力直接来自后端 `capabilities`。

- [ ] **Step 4: 改造 SettingsModal 问答模型 UI**

用分组模型卡片或分组列表替代单层 select：

- 供应商标题：provider logo + provider label。
- 模型行：模型名 + 能力标签 + context badge。
- 当前选中状态清晰。
- 非 vision 模型显示小提示：“图片页将使用 OCR 文本证据”。

保存仍写入原有 `qaSettings.model` 值，保持后端接口不变。

- [ ] **Step 5: 运行测试和构建**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
npm.cmd run build
```

Expected: PASS / build success.

- [ ] **Step 6: 提交**

```powershell
git add frontend/src/components/settings/SettingsModal.vue frontend/src/utils/modelProviderModels.ts frontend/src/utils/modelProviderModels.test.ts frontend/src/components/settings/SettingsModal.contract.test.ts
git commit -m "feat(settings): group qa models by provider capabilities"
```

---

### Task 7: 端到端回归

**Files:**
- No production file unless a regression is found.
- Test: backend and frontend focused suites.

- [ ] **Step 1: 后端 focused tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_service.py backend/tests/test_model_settings_api.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_document_keyword_locator.py backend/tests/test_flat_loop_tool_guidance.py -q
```

Expected: PASS.

- [ ] **Step 2: 前端 focused tests + build**

Run:

```powershell
cd frontend
npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts
npm.cmd run build
```

Expected: PASS / build success.

- [ ] **Step 3: 手工验证**

按 `codex.md` 启动：

```text
C:\Users\TT_WT\Desktop\start-backend.bat
C:\Users\TT_WT\Desktop\start-frontend.bat
```

检查：

- 后端启动窗口 Source 是 `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`。
- 设置页模型供应商里，不同模型能力标签不再凭前端模型名统一生成。
- 问答设置按供应商分组展示模型，并带能力标签。
- 选择 text-only QA 模型后询问图片页内容，工具返回 OCR 文本证据。
- 选择 vision QA 模型后询问图片页内容，工具返回图片引用并允许模型看图。

- [ ] **Step 4: 最终提交**

如果 Task 7 发现补丁：

```powershell
git add <changed-files>
git commit -m "test: verify model capabilities and qa ocr fallback"
```

---

## 风险与处理

- 供应商 `/models` 多数不返回真实能力：后端必须显示 `capability_source`，不要把推断结果当绝对真实。
- OpenAI-compatible 自定义模型需要用户显式配置能力：自定义模型的 `capability_source` 为 `custom`。
- 非 vision QA 使用 OCR 文本会损失版面和图像细节：UI 需要提示“图片页将使用 OCR 文本”，agent prompt/tool result 也要说明。
- 旧 route 里已有错误的 `supports_vision`：保存路由后会被新后端逻辑修正；必要时可提供一次性修复脚本，但本计划先不引入迁移脚本。

## 不做的事

- 不引入外部模型能力数据库服务。
- 不让前端按模型名推断能力。
- 不把 OCR 全文、大图 base64 或本地路径塞进工具文本结果。
- 不强制所有 QA 模型必须 vision；text-only QA 是受支持路径。
