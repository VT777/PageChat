# PageChat 模型路由审计与原生 Reasoning 展示改进计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模型配置切换可验证、可审计，并把对话过程改为只展示模型真实 reasoning 与真实工具执行，取消后端伪造的思考文案，同时把 thinking 开关移到对话输入区。

**Architecture:** 保留当前 `flat_tool_loop`，不回退到 planner/policy。模型路由在调用边界统一解析并记录到 `agent_runs` 与结构化日志；reasoning 只来自供应商原生流式字段，工具动作只展示实际 tool call；thinking 开关从设置页迁移到对话输入区，并作为本轮请求参数进入后端。

**Tech Stack:** FastAPI, SQLite, LiteLLM/OpenAI-compatible streaming, Vue 3, Pinia, pytest, Vitest/contract tests, existing PageChat SSE timeline.

---

## 当前分支与安全规则

- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Branch: `codex/pagechat-ui-agent-runtime-integration`
- 开始执行前必须读取 `codex.md`，确认后端和前端都从当前 worktree 启动。
- 不要在 `fc17/page_chat`、`pagechat-frontend`、`D:\projects\page_chat` 里实现本计划。
- 每个 phase 完成后运行对应测试；核心后端 phase 完成后提交一次。
- 不引入 LangGraph，不重建 agent loop，不重新包装 planner。

## 目标行为

1. 模型配置可确认生效：
   - 每次 LLM 调用都能知道 `user_id / scenario / route_slot / provider_id / provider / model / route_version / source`。
   - 每个 chat run 记录实际使用的问答模型。
   - OCR、解析、问答、query expansion 的模型切换都可以通过测试和日志验证。

2. Reasoning 展示必须真实：
   - 如果供应商流里有 `reasoning_content` 或等价字段，则流式展示。
   - 如果供应商不支持或本次未返回 reasoning，则不展示 reasoning 区块。
   - 不再把后端固定文案伪装成模型思考。
   - 工具执行仍展示，但只作为真实 tool call timeline。

3. Thinking 开关移到对话输入区：
   - 设置页取消“问答 thinking”配置项。
   - 对话输入框下方增加轻量开关。
   - 开关控制当前请求是否允许模型 thinking/reasoning。
   - 该开关可以记住用户偏好，但优先作为本轮请求参数传给后端。

## 非目标

- 不展示隐藏链式思维或后端自行总结的伪 reasoning。
- 不把供应商不支持 reasoning 的模型强行包装出“思考中”。
- 不把工具动作改成大段解释；工具 timeline 只表达真实调用、参数和结果。
- 不要求所有供应商都支持 reasoning；不支持时正常回答即可。
- 不改变文档解析、搜索、OCR 核心算法。

## 现状根因摘要

- `model_route_mappings` 已经保存用户路由，但 `agent_runs.provider_id/model` 当前没有写入，导致运行审计缺失。
- `chat_by_scenario()` 会按场景解析路由，LiteLLM adapter 会在边界转换 provider 前缀，但缺少统一观测日志。
- `ModelToolLoopRuntime` 已经是扁平 LLM-driven loop，模型会自主返回 tool calls。
- 当前 `processing_delta` 来自 `_processing_note_for_tool()` 固定文案，不是模型 reasoning。
- `ToolCallingModelAdapter` 当前只提取 `delta.content` 和 `delta.tool_calls`，没有提取 `reasoning_content`。
- `qa_thinking_mode` 已有用户设置，但位置在设置页，且即使打开，也没有真正把 reasoning 流展示出来。

---

## Phase 1: 模型路由审计与运行记录

**目标：** 让每次模型调用和每个 chat run 都能追踪实际模型，先解决“切换到底有没有生效”的可验证性。

**Files:**
- Modify: `backend/app/core/llm.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/chat_run_repository.py`
- Modify: `backend/app/models/migrations.py`
- Test: `backend/tests/test_model_route_observability.py`
- Test: `backend/tests/test_chat_run_repository.py`

- [ ] Step 1: 新增失败测试：保存 `document_qa` 路由后，创建 chat run 时 `agent_runs.provider_id/model/protocol` 不应为空。
- [ ] Step 2: 新增失败测试：切换同一用户的 `document_qa` 模型后，下一次 run 记录新 `provider_id/model/route_version`。
- [ ] Step 3: 在模型解析结果中保留 `provider_id`。如果当前 `resolve_route()` 没返回 `provider_id`，补齐查询字段和返回结构。
- [ ] Step 4: 在 `chat_by_scenario()` 或更靠近调用边界的位置返回/记录 resolved route metadata，不泄露 API key。
- [ ] Step 5: 在 `ChatService.ensure_run()` 创建 run 时写入本轮实际 QA route。若模型调用前才能确定 route，则先创建 run，再在首次解析后 update run metadata。
- [ ] Step 6: 增加结构化日志，格式固定为：`llm_call user_id=... scenario=... route_slot=... provider_id=... provider=... model=... source=... route_version=... stream=... tools=...`。
- [ ] Step 7: 运行测试：`D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_route_observability.py backend/tests/test_chat_run_repository.py -q`。
- [ ] Step 8: 提交：`git commit -m "feat: record model route metadata for chat runs"`。

**验收标准：** 数据库中最近的 `agent_runs` 能看到真实 `provider_id/model`；日志能明确显示每次 LLM 调用走了哪个 route。

---

## Phase 2: 模型配置切换校验与防错

**目标：** 防止“供应商 A 下选了供应商 B 的模型”或配置无效但仍被用于核心任务。

**Files:**
- Modify: `backend/app/services/model_settings_service.py`
- Modify: `backend/app/api/settings.py`
- Modify: `frontend/src/utils/modelProviderModels.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Test: `backend/tests/test_model_settings_service.py`
- Test: `backend/tests/test_model_settings_api.py`
- Test: `frontend/src/utils/modelProviderModels.test.ts`

- [ ] Step 1: 新增失败测试：保存 route 时，若 `provider_id` 不属于当前用户，应拒绝。
- [ ] Step 2: 新增失败测试：保存 route 时，若模型不在该 provider 已获取/自定义模型列表里，应返回可理解错误，除非显式保存为 custom model。
- [ ] Step 3: 新增失败测试：provider `validation_status=invalid` 时，核心 route 保存或使用要给出警告/阻断策略。建议保存允许但运行阻断，避免用户误以为配置可用。
- [ ] Step 4: 后端保存 route 时校验 `provider_id` 与用户、模型归属、能力字段。
- [ ] Step 5: 前端选择模型时只展示该 provider 下已获取或用户手动添加的模型，不展示默认干扰项。
- [ ] Step 6: 前端保存后立即重新拉取 routes，确保 UI 与后端实际状态一致。
- [ ] Step 7: 运行：`D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_settings_service.py backend/tests/test_model_settings_api.py -q`。
- [ ] Step 8: 运行：`npm.cmd test -- src/utils/modelProviderModels.test.ts src/components/settings/SettingsModal.contract.test.ts`。
- [ ] Step 9: 提交：`git commit -m "fix: validate model routes against provider models"`。

**验收标准：** 切换供应商/模型后，下一次调用记录对应模型；错误配置不会静默进入 agent runtime。

---

## Phase 3: 原生 Reasoning 流式事件

**目标：** 支持供应商原生 reasoning 流，完全停止伪造模型思考。

**Files:**
- Modify: `backend/app/agent/model_turn.py`
- Modify: `backend/app/agent/tool_calling_model_adapter.py`
- Modify: `backend/app/agent/model_tool_loop.py`
- Modify: `backend/app/agent/events.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_tool_calling_model_adapter.py`
- Test: `backend/tests/test_model_tool_loop.py`
- Test: `backend/tests/test_chat_stream_reasoning.py`

- [ ] Step 1: 新增事件模型，例如 `ModelReasoningDelta(delta: str)` 和 SSE `reasoning_delta`。
- [ ] Step 2: 新增失败测试：模拟 OpenAI-compatible chunk 中的 `delta.reasoning_content`，adapter 应产出 `ModelReasoningDelta`。
- [ ] Step 3: 兼容常见字段但不臆造：按顺序探测 `reasoning_content`、`reasoning`、`thinking`；没有就不产出事件。
- [ ] Step 4: `ModelToolLoopRuntime` 收到 `ModelReasoningDelta` 时转发 `reasoning_delta`，不写入 final answer。
- [ ] Step 5: 删除或停用 `_processing_note_for_tool()` 对 `processing_delta` 的伪 thought 用法。工具执行仍保留 `tool_started/tool_completed/tool_call_delta`。
- [ ] Step 6: `ChatService` 将 `reasoning_delta` 累积到 `thinking_content`，但只保存真实模型 reasoning。
- [ ] Step 7: 如果供应商未返回 reasoning，则不发送空 reasoning 区块。
- [ ] Step 8: 运行：`D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_calling_model_adapter.py backend/tests/test_model_tool_loop.py backend/tests/test_chat_stream_reasoning.py -q`。
- [ ] Step 9: 提交：`git commit -m "feat: stream native model reasoning deltas"`。

**验收标准：** 支持 reasoning 的模型会在前端实时出现真实 reasoning；不支持的模型只显示工具调用和答案，不显示伪思考。

---

## Phase 4: 对话输入区 Thinking 开关

**目标：** 把 thinking 控制从设置页迁移到对话输入区，并作用于当前请求。

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/components/chat/*`（实际输入框组件，以当前代码为准）
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/agent_service.py`
- Test: `frontend/src/stores/chat.test.ts`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`
- Test: `backend/tests/test_chat_api.py`

- [ ] Step 1: 新增失败测试：chat 请求体携带 `thinking_enabled=true/false` 时，后端传给 `AgentService` 的 `disable_thinking` 与之相反。
- [ ] Step 2: 前端输入框下方增加轻量 Thinking 开关，默认读取用户上次选择或后端偏好。
- [ ] Step 3: 发送消息时把开关值作为本轮请求参数，例如 `thinking_enabled`。
- [ ] Step 4: 设置页移除问答 thinking 配置项，保留模型选择、Web Search 等真正的系统配置。
- [ ] Step 5: 后端支持请求级覆盖：若传入 `thinking_enabled`，优先使用；未传入时才读取用户偏好/默认值。
- [ ] Step 6: 开关打开但模型未返回 reasoning 时，前端不展示“空 thinking”，也不显示失败；只正常展示工具和答案。
- [ ] Step 7: 运行：`npm.cmd test -- src/stores/chat.test.ts src/components/settings/SettingsModal.contract.test.ts`。
- [ ] Step 8: 运行：`D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_chat_api.py -q`。
- [ ] Step 9: 提交：`git commit -m "feat: move thinking control to chat composer"`。

**验收标准：** 用户在对话框里能一键控制本轮是否启用 thinking；设置页不再出现对应项。

---

## Phase 5: 前端 Timeline 还原真实执行过程

**目标：** 前端展示模型真实 reasoning、真实工具调用、最终答案，三者边界清晰。

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/types/stream.ts`
- Modify: `frontend/src/components/chat/RunTimeline.vue`
- Modify: `frontend/src/components/chat/ToolTimelineItem.vue`
- Test: `frontend/src/types/stream.contract.test.ts`
- Test: `frontend/src/stores/chat.test.ts`
- Test: `frontend/src/components/chat/RunTimeline.contract.test.ts`

- [ ] Step 1: 新增 stream contract 测试：`reasoning_delta` 是合法事件类型。
- [ ] Step 2: store 支持累积 `reasoningSteps` 或 `thinkingContent`，来源只允许 `reasoning_delta`。
- [ ] Step 3: `processing_delta` 不再被当作 thought 展示；如果后端仍发送旧事件，也只作为兼容的非 reasoning 状态处理。
- [ ] Step 4: RunTimeline 中按顺序展示：reasoning 流、tool call、tool result、answer。不要用后端固定文案填充 reasoning。
- [ ] Step 5: 支持模型 reasoning 结束后自动折叠，用户可展开；如果无 reasoning，则不渲染该区块。
- [ ] Step 6: 工具动作展示真实名称、参数摘要、结果摘要，不加大段解释。
- [ ] Step 7: 运行：`npm.cmd test -- src/types/stream.contract.test.ts src/stores/chat.test.ts src/components/chat/RunTimeline.contract.test.ts`。
- [ ] Step 8: 运行：`npm.cmd run build`。
- [ ] Step 9: 提交：`git commit -m "feat: render native reasoning and tool timeline"`。

**验收标准：** 页面上不再出现后端伪 thought；支持 reasoning 的模型能流式显示原生 reasoning；工具链路与答案顺序自然。

---

## Phase 6: 端到端验证与回归

**目标：** 用真实数据确认模型切换、reasoning 展示、工具执行、OCR 路由都符合预期。

**Files:**
- Modify: `docs/superpowers/qa/` 下新增或更新验证记录。
- No production code unless E2E reveals blocker.

- [ ] Step 1: 按 `codex.md` 重启后端和前端，确认 Source/Branch 正确。
- [ ] Step 2: 登录 `admin@pagechat.ai`，配置一个支持 tool calling 的 QA 模型，发送“你好”，确认不调用文档工具。
- [ ] Step 3: 打开 Thinking 开关，使用支持 reasoning 的模型提问文档问题，确认 reasoning 流式出现。
- [ ] Step 4: 换成不支持 reasoning 的模型，确认没有伪 thinking 区块，但工具调用和答案正常。
- [ ] Step 5: 切换 `document_qa` 模型后提问，查询 `agent_runs` 和日志，确认记录的新模型生效。
- [ ] Step 6: 切换 `vision` 模型后重新解析图片型 PDF，确认 OCR 路由使用新模型；未配置时明确失败提示。
- [ ] Step 7: 测试供应商/模型配置错误：错误 provider-model 组合不能静默运行。
- [ ] Step 8: 写入 QA 记录，包含命令、账号、模型、问题、预期、结果。
- [ ] Step 9: 提交：`git commit -m "test: document model routing and reasoning e2e"`。

**验收标准：** 浏览器中可观察到真实 agent 过程；数据库和日志可证明模型切换生效；不支持 reasoning 的供应商不显示伪思考。

---

## 风险与取舍

- 不同供应商 reasoning 字段不统一。解决方式：只兼容已观测字段，不猜测、不造假。
- 部分模型即使开启 thinking 也不会返回 reasoning。产品表现应是“无 reasoning 区块”，不是错误。
- 工具调用前模型可能输出普通 content。当前计划不把普通 content 当 reasoning；否则会污染最终答案。后续如需“可见进度”，应另行设计专用协议。
- 路由审计需要避免记录 API key；日志和数据库只记录 provider/model/route metadata。

## 推荐执行顺序

1. Phase 1：先补模型路由审计，否则后面无法证明切换是否生效。
2. Phase 3：再接原生 reasoning 流，解决“伪思考”的核心问题。
3. Phase 4 + Phase 5：完成对话输入区开关和前端展示。
4. Phase 2：模型配置防错可与 Phase 1 并行，但建议在 E2E 前完成。
5. Phase 6：最后做真实端到端验证。
