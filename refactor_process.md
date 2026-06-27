# PageChat LLM-Driven Agent Loop Refactor Process

This file is the handoff log for the LLM-driven Agent Loop refactor. Read it before starting or resuming work. Update it at the start and end of every phase so context compression can recover the current state.

## Baseline

- Branch: `codex/pagechat-ui-agent-runtime-integration`
- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Baseline checkpoint before refactor: `c551c12 chore(agent): checkpoint before llm-driven loop refactor`
- Primary plan: `docs/superpowers/plans/2026-06-27-pagechat-llm-driven-agent-loop-plan.zh.md`
- Execution order: Phase 1, Phase 2, Phase 3, Phase 6, Phase 7, Phase 4, Phase 5, Phase 8, Phase 9.

## Current Status

- Current phase: Flat Tool Loop Phase 0 - Baseline and plan registration.
- Status: In progress.
- Started at: 2026-06-27.
- Notes: A previous LLM-driven pass improved prompts/native tool-call parsing but kept the planner-shaped runtime. The new target is a true flat native tool-use loop: model turn -> tool calls -> tool results -> same model loop answer.

## Flat Tool Loop Refactor - 2026-06-27

Plan:
- `docs/superpowers/plans/2026-06-27-pagechat-flat-llm-tool-loop-refactor-plan.zh.md`

Start status:
- Branch confirmed: `codex/pagechat-ui-agent-runtime-integration`.
- Worktree confirmed: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`.
- Execution rule: update this section at the start and completion of every phase.
- Current task: register the new plan, then start Phase 1 with failing tests first.

### Flat Tool Loop Phase 1 - Provider-neutral model turn events

Start status:
- Started Phase 1 after baseline commit `7589059`.
- Goal: create provider-neutral model turn/event dataclasses with no planner/action concepts.
- TDD: first add `backend/tests/test_model_turn.py`, verify it fails because `app.agent.model_turn` does not exist, then add minimal implementation.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py -q`
  - failed as expected with `ModuleNotFoundError: No module named 'app.agent.model_turn'`.
- Added `backend/app/agent/model_turn.py` with `ModelToolCall`, `ModelToolCallDelta`, `ModelTextDelta`, and `ModelTurn`.
- GREEN test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py -q`
  - `3 passed`.
- Next phase: build compact model-facing tool result messages.

### Flat Tool Loop Phase 2 - Compact tool result messages

Start status:
- Started Phase 2 after commit `a896482`.
- Goal: convert PageChat tool results into compact OpenAI-compatible `role="tool"` messages plus UI metadata.
- TDD: add `backend/tests/test_tool_messages.py` first; expected initial failure is missing `app.agent.tool_messages`.
- Reuse `backend/app/agent/nodes.py::compact_tool_result` where practical, while adding missing `view_folder_structure` display metadata.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_messages.py -q`
  - failed as expected with `ModuleNotFoundError: No module named 'app.agent.tool_messages'`.
- Added `backend/app/agent/tool_messages.py` with `build_tool_result_message`.
- Model-facing tool message content now uses compact JSON and strips local paths, base64 payloads, raw OCR fields, embeddings, scores, and other oversized/sensitive keys.
- UI result reuses `compact_tool_result` so timeline metadata remains consistent.
- Added `view_folder_structure` display metadata in `compact_tool_result`.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_messages.py -q` -> `3 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_messages.py backend/tests/test_agent_run_event_protocol.py -q` -> `14 passed, 9 warnings`.
- Next phase: add boundary-only runtime policy.

### Flat Tool Loop Phase 3 - Boundary-only runtime policy

Start status:
- Started Phase 3 after commit `695ba2a`.
- Goal: create `RuntimeBoundaryPolicy` for tool availability, scope, web-search enablement, and argument repair only.
- Explicit non-goal: do not validate final-answer evidence sufficiency or prescribe retrieval routes.
- TDD: add `backend/tests/test_runtime_boundary_policy.py` first and verify missing-module failure.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_boundary_policy.py -q`
  - failed as expected with `ModuleNotFoundError: No module named 'app.agent.runtime_boundary_policy'`.
- Added `backend/app/agent/runtime_boundary_policy.py`.
- The new policy validates tool availability, disabled Web Search, document name/id repair, selected-scope document boundaries, and root folder normalization.
- It intentionally has no final-answer evidence sufficiency API.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_boundary_policy.py -q` -> `5 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py backend/tests/test_tool_messages.py backend/tests/test_runtime_boundary_policy.py -q` -> `11 passed`.
- Next phase: implement `ModelToolLoopRuntime` using a fake model and fake tool runner.

### Flat Tool Loop Phase 4 - ModelToolLoopRuntime foundation

Start status:
- Started Phase 4 after commit `0247e48`.
- Goal: implement the first real flat loop skeleton with fake model/tool runner tests.
- TDD: add `backend/tests/test_model_tool_loop_runtime.py` first; expected initial failure is missing `app.agent.model_tool_loop`.
- Scope: no provider integration yet; the runtime should operate on `ModelTurn`/`ModelToolCall` and append native assistant/tool messages.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py -q`
  - failed as expected with `ModuleNotFoundError: No module named 'app.agent.model_tool_loop'`.
- Added `backend/app/agent/model_tool_loop.py` with `ModelToolLoopRuntime` and `RuntimeStreamEvent`.
- Runtime now:
  - builds one flat message history with system/history/user messages,
  - accepts model-emitted `ModelToolCall`s,
  - validates them with `RuntimeBoundaryPolicy`,
  - executes tools through the injected runner,
  - appends native assistant `tool_calls` and `role="tool"` messages,
  - continues the same loop until final text is emitted as `answer_delta`.
- Tests cover one tool call then answer, greeting without tools, and multiple same-turn tool calls in model-provided order.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py -q` -> `3 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py backend/tests/test_tool_messages.py backend/tests/test_runtime_boundary_policy.py backend/tests/test_model_tool_loop_runtime.py -q` -> `14 passed`.
- Next phase: add native tool-calling model adapter.

### Flat Tool Loop Phase 5 - Native tool-calling model adapter

Start status:
- Started Phase 5 after commit `07b3f6b`.
- Goal: add a standalone `ToolCallingModelAdapter` that converts OpenAI-compatible native tool-call responses into `ModelTextDelta`, `ModelToolCallDelta`, and final `ModelTurn`.
- TDD: add `backend/tests/test_tool_calling_model_adapter.py` first; expected initial failure is missing `app.agent.tool_calling_model_adapter`.
- Scope: adapter only, no service wiring yet.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_calling_model_adapter.py -q`
  - failed as expected with `ModuleNotFoundError: No module named 'app.agent.tool_calling_model_adapter'`.
- Added `backend/app/agent/tool_calling_model_adapter.py`.
- Adapter calls the configured completion function with `stream=True`, native `tools`, `tool_choice="auto"`, `allow_deterministic_tools=True`, and `disable_thinking=True`.
- It parses:
  - non-streaming OpenAI-compatible `message.tool_calls`,
  - streaming `delta.tool_calls` into `ModelToolCallDelta` plus final `ModelTurn`,
  - streaming text deltas into `ModelTextDelta` plus final text `ModelTurn`.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_calling_model_adapter.py -q` -> `3 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py backend/tests/test_tool_messages.py backend/tests/test_runtime_boundary_policy.py backend/tests/test_model_tool_loop_runtime.py backend/tests/test_tool_calling_model_adapter.py -q` -> `17 passed`.
- Next phase: wire the new runtime behind an explicit runtime mode flag.

### Flat Tool Loop Phase 6 - Service runtime flag wiring

Start status:
- Started Phase 6 after commit `7010baf`.
- Goal: wire `ModelToolLoopRuntime` into `AgentService` behind `AGENT_RUNTIME_MODE=flat_tool_loop`, preserving legacy runtime as default rollback.
- TDD: add `backend/tests/test_agent_service_flat_loop_runtime.py` first and verify service still builds legacy runtime before config wiring.
- Scope: builder/stream event compatibility only; do not make flat loop default yet.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_flat_loop_runtime.py -q`
  - failed as expected because flat mode still returned `AgentLoopRuntime` and stream formatting only accepted legacy `event_type`.
- Added `AGENT_RUNTIME_MODE` config defaulting to `legacy_loop`.
- `AgentService.build_agent_loop_runtime` now returns `ModelToolLoopRuntime` when `AGENT_RUNTIME_MODE == "flat_tool_loop"` and keeps `AgentLoopRuntime` otherwise.
- `run_agent_stream` accepts both legacy `runtime_event.event_type` and flat `runtime_event.type` event shapes.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_flat_loop_runtime.py -q` -> `3 passed, 9 warnings`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_agent_service_loop_runtime.py -q` -> `10 passed, 9 warnings`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py backend/tests/test_tool_messages.py backend/tests/test_runtime_boundary_policy.py backend/tests/test_model_tool_loop_runtime.py backend/tests/test_tool_calling_model_adapter.py backend/tests/test_agent_service_flat_loop_runtime.py -q` -> `20 passed, 9 warnings`.
- Next phase: move route guidance into flat runtime prompt/tool contracts and remove hidden route-forcing behavior from the new path.

### Flat Tool Loop Phase 7 - Tool guidance without hidden routing

Start status:
- Started Phase 7 after commit `6cdb460`.
- Goal: keep the flat runtime model-driven while improving the system prompt, tool descriptions, and compact `next_steps` guidance.
- TDD: add `backend/tests/test_flat_loop_tool_guidance.py` first; expected initial failures should come from the current short flat-loop prompt and remaining fixed-route wording in tool contracts.
- Scope: no new planner, no evidence-sufficiency policy, and no forced tool chain.

Completion status:
- RED test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_loop_tool_guidance.py -q`
  - failed as expected for the short flat runtime prompt, fixed-route folder description, and nested route-like `next_steps`.
- Updated `ModelToolLoopRuntime` default prompt with model-driven principles: dynamic tool choice, information gaps, same-language answer, inline citations, concise progress, and no internal mechanics.
- Reworded key document tools so descriptions are affordances rather than fixed chains.
- Simplified `view_folder_structure`, `browse_documents`, `get_document_structure`, and `get_page_content` result `next_steps` into compact model guidance strings.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_loop_tool_guidance.py -q` -> `4 passed, 11 warnings`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_loop_tool_guidance.py backend/tests/test_agent_navigation_tools_contract.py -q` -> `28 passed, 69 warnings`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py backend/tests/test_tool_messages.py backend/tests/test_runtime_boundary_policy.py backend/tests/test_model_tool_loop_runtime.py backend/tests/test_tool_calling_model_adapter.py backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_flat_loop_tool_guidance.py -q` -> `24 passed, 11 warnings`.
- Static scan for old route wording in `backend/app` found no new flat-runtime route text; remaining `Return JSON` / `action.type` matches are legacy planner/classification/parsing prompts outside the flat runtime path.
- Next phase: adapt SSE/frontend timeline if current frontend still needs event contract changes for flat loop events.

### Flat Tool Loop Phase 8 - SSE events and frontend timeline

Start status:
- Started Phase 8 after commit `80906cc`.
- Goal: verify and complete frontend support for flat-loop stream events, especially `processing_delta`, `tool_call_delta`, `tool_started`, `tool_completed`, smooth `answer_delta`, and non-misleading result labels.
- TDD: inspect existing frontend tests first; add or tighten failing tests for any missing flat event behavior before implementation.
- Scope: no backend runtime routing changes in this phase.

Completion status:
- Existing frontend already declared and handled `processing_delta` / `tool_call_delta`, merged tool-call deltas into pending tool rows, preferred `result_label`, and collapsed processing details after answer streaming starts.
- Found backend flat runtime gap: `ModelToolCallDelta` was swallowed and final answer `ModelTextDelta`s were buffered until the whole model turn completed.
- RED backend test run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py -q`
  - failed as expected because final answer text streamed as one chunk and no `tool_call_delta` event was emitted.
- Updated `ModelToolLoopRuntime` to forward native `ModelToolCallDelta` as runtime `tool_call_delta` and stream final answer `ModelTextDelta` chunks as `answer_delta` without duplicating the final `ModelTurn` content.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py -q` -> `5 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py backend/tests/test_agent_service_flat_loop_runtime.py -q` -> `8 passed, 9 warnings`.
  - `npm.cmd test -- src/types/stream.contract.test.ts src/stores/chat.test.ts src/components/chat/RunTimeline.contract.test.ts src/components/chat/ToolTimelineItem.contract.test.ts` -> `4 passed test files, 41 passed tests`.
  - `npm.cmd test` in `frontend` -> `20 passed test files, 130 passed tests`.
  - `npm.cmd run build` in `frontend` -> completed successfully.
- Next phase: add API E2E tests for flat loop scenarios.

### Flat Tool Loop Phase 9 - API E2E scenarios

Start status:
- Started Phase 9 after commit `352a926`.
- Goal: add end-to-end coverage for flat tool loop behavior at the service/API stream boundary without relying on real external model calls.
- TDD: inspect existing API/service fixtures, then add failing E2E tests for greeting/no-tool, selected-scope inventory, and web/document tool event propagation before implementation if gaps are found.
- Scope: prefer deterministic fake model/tool execution; do not require live model provider credentials.

Completion status:
- Added `backend/tests/test_flat_tool_loop_e2e.py`.
- Covered:
  - ChatService forwarding of `processing_delta`, `tool_call_delta`, `tool_started`, `tool_completed`, `answer_delta`, and `run_completed`.
  - AgentService flat mode using a fake native tool-calling model to call `browse_documents` once for a selected folder inventory question, then stream the final answer.
- RED E2E run:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_tool_loop_e2e.py -q`
  - failed as expected because ChatService turned `processing_delta` into `run_failed` via unsupported PageChat event validation.
- Updated PageChat event contract to include `processing_delta` and `tool_call_delta`.
- Updated ChatService to forward `processing_delta` / `tool_call_delta` and preserve `tool_call_id` through started/completed events.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_tool_loop_e2e.py -q` -> `2 passed, 11 warnings`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_tool_loop_e2e.py backend/tests/test_agent_run_event_protocol.py backend/tests/test_chat_service_persistence.py backend/tests/test_chat_stream_api.py backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_model_tool_loop_runtime.py -q` -> `29 passed, 160 warnings`.
- Next phase: browser validation with the current worktree backend/frontend, then default switch if validation is acceptable.

### Flat Tool Loop Phase 10 - Browser/runtime validation

Start status:
- Started Phase 10 after commit `b0f0751`.
- Goal: validate the current worktree backend/frontend can run with flat-loop changes and that the browser-facing stream contract is no longer blocked by unsupported events.
- Scope: first confirm launched process source per `codex.md`; then run health/API smoke checks. Full manual browser validation may remain pending if login/model credentials or parsed document fixtures are not available in this automated pass.

Completion status:
- Checked existing ports:
  - `5173` was already running from `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration\frontend`.
  - `8000` was healthy but command-line source was ambiguous because it used the legacy venv/env fallback.
- Stopped existing `8000` / `5173` listeners and restarted:
  - frontend from current worktree on `http://localhost:5173`.
  - backend from current worktree backend directory using legacy Python/env fallback, with `AGENT_RUNTIME_MODE=flat_tool_loop`, on `http://localhost:8000`.
- Smoke checks:
  - `Invoke-RestMethod http://127.0.0.1:8000/health` -> `{"status":"ok"}`.
  - `Invoke-WebRequest http://127.0.0.1:5173/` -> HTTP `200`.
- Notes:
  - Backend log contains an older failed PowerShell launch attempt followed by successful app initialization.
  - Full manual browser scenarios from the plan were not completed in this automated pass because they require an authenticated browser session, configured model provider credentials, and known parsed document fixtures.
  - Do not switch the default runtime yet; keep `flat_tool_loop` explicit until manual browser/model validation is complete.
- Next phase: after manual validation, decide whether to make `flat_tool_loop` the default or fix remaining runtime issues first.

### Flat Tool Loop Phase 11 - QA thinking setting, citation contract, and default runtime

Start status:
- Started after user approved:
  - add a configurable thinking option in 问答设置,
  - fix model-facing inline citation guidance,
  - make `flat_tool_loop` the default runtime.
- Branch/worktree confirmed by `codex.md`: `codex/pagechat-ui-agent-runtime-integration` at `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`.
- TDD targets:
  - runtime settings expose and persist QA thinking mode with safe default `off`,
  - flat runtime adapter receives the configured thinking flag,
  - model-facing tool messages expose readable `[[display_label]]` citation markers and hide internal citation ids/keys,
  - config default runtime becomes `flat_tool_loop` while `legacy_loop` remains an explicit rollback.

Completion status:
- Added QA settings backed by `runtime_settings.json`:
  - default `qa_thinking_mode` is `off`,
  - supported values are `off`, `auto`, and `on`,
  - `GET /api/settings/qa` and `PUT /api/settings/qa` expose the setting.
- Added 问答设置 UI controls for model thinking mode and wired them through `settingsApi.getQaSettings` / `settingsApi.updateQaSettings`.
- `ToolCallingModelAdapter` now receives `disable_thinking` from QA settings; `off` disables provider-native thinking, `auto/on` allow it.
- Flat model-facing tool messages now expose readable `citation_marker` / `citation_markers` such as `[[Chongqing cases.pdf p.43]]`, hide `citation_key`, and include `search_within_document` as citable page evidence.
- `ModelToolLoopRuntime` prompt now explicitly requires inline `[[display_label]]` markers immediately after supported claims and forbids `[cite: ...]` / `citation_key` output.
- `AGENT_RUNTIME_MODE` config default is now `flat_tool_loop`; `AGENT_RUNTIME_MODE=legacy_loop` remains the rollback switch.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_settings_service.py backend/tests/test_runtime_settings_api.py backend/tests/test_tool_calling_model_adapter.py backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_tool_messages.py backend/tests/test_flat_loop_tool_guidance.py -q` -> `24 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_loop_runtime.py backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_model_tool_loop_runtime.py backend/tests/test_tool_calling_model_adapter.py backend/tests/test_tool_messages.py backend/tests/test_agent_citation_bindings.py backend/tests/test_flat_tool_loop_e2e.py backend/tests/test_agent_run_event_protocol.py -q` -> `45 passed`.
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_settings_service.py backend/tests/test_runtime_settings_api.py backend/tests/test_web_search_settings_api.py backend/tests/test_model_settings_api.py backend/tests/test_llm_timeout_defaults.py -q` -> `34 passed`.
  - Fresh combined backend regression on 2026-06-27 covering agent/provider/citation/settings/flat-loop suites -> `199 passed, 1330 warnings`.
  - `npm.cmd test` in `frontend` -> `20 passed test files, 131 tests`.
  - `npm.cmd run build` in `frontend` -> completed successfully.
- Next phase: restart backend/frontend from the current worktree and manually verify QA setting persistence plus a cited document answer in the browser.

## Phase Log

### Phase 1 - Architecture Audit And Production Path Confirmation

Start status:
- Started Phase 1.
- Read the primary plan.
- Need to inspect:
  - `backend/app/agent/loop_runtime.py`
  - `backend/app/agent/planner.py`
  - `backend/app/agent/policy.py`
  - `backend/app/prompts/__init__.py`
  - `backend/app/services/agent_service.py`
- Expected output: concise audit notes in this file before Phase 2 begins.

Completion status:
- Production path in `AgentService.build_agent_loop_runtime` constructs `StructuredLLMPlanner`, `AgentPolicy`, `AgentLoopRuntime`, and `_stream_graph_answer`.
- `PolicyGuidedPlanner` still exists in `backend/app/agent/loop_runtime.py` but appears test/fallback-only; `backend/tests/test_agent_service_loop_runtime.py` asserts runtime planner is not `PolicyGuidedPlanner`.
- `run_agent_stream` currently builds scope, selected scope summary, optional prior evidence, and then calls `build_agent_loop_runtime`; it does not call `_execute_initial_retrieval_plan` in the current main path.
- `_execute_initial_retrieval_plan` and older tests still exist; keep them in mind as legacy/retrieval-planner residue when simplifying architecture.
- Planner payload hides `document_registry` via `_compact_scope`, but `document_registry` remains in state scope for policy doc-name-to-doc-id repair.
- Final answer is currently split: planner chooses `answer` with empty content, then `AgentLoopRuntime` invokes `_stream_graph_answer`; this is a real model-responsibility split and should be revisited after prompt/policy cleanup.
- Current runtime events are `progress`, `tool_started`, `tool_completed`, and `answer_delta`; no separate `processing_delta` or `tool_call_delta` yet.
- Policy rejection appends a guardrail observation and retracts already streamed plan progress. This avoids final visible rejected thought, but frequent rejections still make the loop feel mechanical.
- Phase 1 produced no product code changes except this process log.

### Phase 2 - Prompt Rewrite Toward Model Autonomy

Start status:
- Started Phase 2.
- Goal: rewrite prompt constraints from workflow-like stages to model-autonomous principles.
- TDD target: backend planner prompt tests should fail first for old workflow language and pass after prompt rewrite.
- Files expected:
  - `backend/app/prompts/__init__.py`
  - `backend/app/agent/planner.py`
  - `backend/tests/test_agent_structured_llm_planner.py`

Completion status:
- Added RED tests for model-autonomous prompt behavior:
  - planner prompt must say the model decides whether to answer, clarify, or call tools.
  - planner prompt must not say `Choose the next single PageChat agent action`.
  - agent system prompt must not contain hardcoded `browse_documents -> ...` / `get_document_structure -> get_page_content -> answer` routes.
  - global prompt now uses `Model Autonomy` and `Tool Selection Principles`.
- Initial targeted test run failed as expected:
  - `4 failed, 12 passed`
- Implementation changed only prompt text in:
  - `backend/app/agent/planner.py`
  - `backend/app/prompts/__init__.py`
- Final targeted test command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_tree_first_retrieval_policy.py -q`
- Final result:
  - `16 passed, 9 warnings`

### Phase 3 - Policy As Boundary Guardrails

Start status:
- Started Phase 3.
- Goal: keep policy deterministic but stop it from planning routes for the model.
- TDD target: policy rejection observations should be neutral boundary feedback, not fixed tool-order instructions.
- Files expected:
  - `backend/app/agent/policy.py`
  - `backend/app/agent/loop_runtime.py`
  - `backend/tests/test_agent_policy.py`
  - `backend/tests/test_agent_loop_runtime.py`

Completion status:
- Added RED tests requiring policy to stop prescribing fixed retrieval routes.
- Generic document-evidence rejection now says:
  - `The final answer needs source evidence. Decide what information is missing and choose an available tool or ask a clarification.`
- Visual-only page evidence rejection now says:
  - `The available page evidence is marked visual_evidence_required. Use an image-capable tool before making visual or layout-dependent claims.`
- Policy still repairs scope/doc references, blocks disabled Web Search, blocks obvious repeat tool calls, and enforces evidence guardrails.
- Targeted test command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_policy.py backend/tests/test_agent_loop_runtime.py -q`
- Final result:
  - `27 passed`

### Phase 6 - Tool Contract Cleanup

Start status:
- Started Phase 6.
- Goal: make tool arguments/results easier for the model and UI to understand without becoming a hidden workflow.
- First focus:
  - `get_page_content` natural page range parsing.
  - `success/result_count/result_label/next_steps` consistency.
  - no Python exceptions in tool-facing page argument errors.
- Files expected:
  - `backend/app/agent/nodes.py`
  - tool schemas wherever defined.
  - relevant backend tool tests.

Completion status:
- Added RED tests for:
  - `get_page_content` accepting official-style multi-segment pages such as `1-3,8,10-12`.
  - invalid page ranges returning structured, friendly errors.
  - compact page results preserving `total_pages` and accurate `result_count/result_label`.
  - tool descriptions acting as agent affordances instead of fixed routes.
- Implemented:
  - multi-segment page parser with comma/range support.
  - compressed page range labels such as `1-3,8,10-12`.
  - friendly page parsing errors with `next_steps`.
  - compact result page counting from `returned_pages` labels rather than truncated items.
  - removed `Use it before reading pages` from `get_document_structure` schema description.
- Targeted tool contract command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_navigation_tools_contract.py -q`
- Result:
  - `24 passed, 67 warnings`
- Backend agent targeted regression command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_tree_first_retrieval_policy.py backend/tests/test_agent_policy.py backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_navigation_tools_contract.py -q`
- Result:
  - `67 passed, 67 warnings`

### Phase 7 - UI Processing / Thinking Area

Start status:
- Started Phase 7.
- Goal: render model processing and tool calls in one coherent area, default to stable runtime statuses when provider processing deltas are absent.
- First focus:
  - preserve existing frontend behavior while preparing event types for `processing_delta` / `tool_call_delta`.
  - ensure tool rows prefer action labels/result labels and do not show misleading `0 results`.
- Files expected:
  - `frontend/src/components/chat/RunTimeline.vue`
  - `frontend/src/components/chat/ToolTimelineItem.vue`
  - `frontend/src/views/ChatView.vue`
  - frontend contract tests.

Resume status:
- Resumed Phase 7 after context handoff.
- Confirmed branch/worktree with `codex.md`: `codex/pagechat-ui-agent-runtime-integration` at `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`.
- Current focus: add event/type/store support for `processing_delta` and `tool_call_delta`, keep UI simple, and avoid fake model thinking when no provider processing stream exists.

Completion status:
- Added frontend stream contract for `processing_delta` and `tool_call_delta`.
- Store now merges `processing_delta` chunks into a single visible `processing` progress step.
- Store now uses `tool_call_delta` to create/update the same pending tool row that `tool_started` continues, keyed by `tool_call_id` when available.
- Runtime label changed from fake hidden-thinking wording to `Processing...` / `Processing details`.
- Tool details can show partial parameters while a provider streams tool-call arguments.
- Targeted frontend test command:
  - `npm.cmd test -- src/types/stream.contract.test.ts src/stores/chat.test.ts src/components/chat/RunTimeline.contract.test.ts src/components/chat/ToolTimelineItem.contract.test.ts`
- Targeted result:
  - `4 passed test files, 40 passed tests`
- Full frontend test command:
  - `npm.cmd test`
- Full frontend result:
  - `20 passed test files, 128 passed tests`
- Frontend build command:
  - `npm.cmd run build`
- Frontend build result:
  - `vue-tsc && vite build` completed successfully.

### Phase 4 - Multi-tool Model Turn Support

Start status:
- Started Phase 4 after committing Phase 7 checkpoint `a7a7dce`.
- Goal: allow one model turn to return multiple tool calls while keeping the existing single-action path compatible.
- First focus:
  - inspect current `PlannerAction` / runtime execution shape.
  - add failing backend tests before changing runtime behavior.
  - keep policy as per-tool boundary validation, not a route planner.

Completion status:
- Added `ToolCallRequest` and `PlannerAction.call_tools(...)` while keeping `PlannerAction.call_tool(...)` compatible.
- Runtime now expands one model `call_tool` turn into one or more tool actions.
- Each tool action is validated independently by policy, then executed sequentially in model-provided order.
- Rejected tool calls become internal guardrail observations for the next model turn; they are not emitted as user-visible guardrail rows.
- Planner JSON parser now accepts `action.tool_calls[]` for independent same-turn tool calls and preserves the old `tool_name` / `arguments` path.
- Prompt schema now tells the model it may put independent tools in `action.tool_calls` rather than forcing extra planning rounds.
- RED tests initially failed because `PlannerAction.call_tools` / `action.tool_calls` did not exist.
- Targeted backend test command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_structured_llm_planner.py -q`
- Targeted result:
  - `20 passed`
- Backend agent regression command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_tree_first_retrieval_policy.py backend/tests/test_agent_policy.py backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_navigation_tools_contract.py -q`
- Backend agent regression result:
  - `69 passed, 67 warnings`

### Phase 5 - Native Tool Calling Adapter

Start status:
- Started Phase 5 after committing Phase 4 checkpoint `5e6cc80`.
- Goal: introduce a minimal native tool-calling adapter path when provider capability is available, while preserving JSON fallback for providers that do not support it.
- First focus:
  - audit current LLM/provider integration and capability storage.
  - identify where tools schema can be passed safely.
  - add tests before changing provider/planner behavior.

Completion status:
- Audited current provider path:
  - `chat_by_scenario` / `async_chat_completion` already support `tools`, `tool_choice`, and provider capability checks.
  - JSON planner fallback was the production planner path before this phase.
- Structured planner now passes native tools with `tool_choice=auto` and `allow_deterministic_tools=True`.
- If a provider returns native `message.tool_calls`, planner converts them to `PlannerAction.call_tools(...)`.
- If a provider streams `delta.tool_calls`, planner emits `tool_call_delta` events and reconstructs the final tool action.
- Runtime forwards planner `tool_call_delta` / `processing_delta` events to SSE-compatible runtime events.
- If native tool calls are absent, planner keeps the existing JSON fallback behavior.
- RED tests initially failed because tools were not forwarded, native tool calls were not parsed, and runtime ignored `tool_call_delta`.
- Targeted backend test command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_structured_llm_planner.py -q`
- Targeted result:
  - `23 passed`
- Backend provider/agent regression command:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_tree_first_retrieval_policy.py backend/tests/test_agent_policy.py backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_provider_protocol_selection.py backend/tests/test_model_gateway_settings.py backend/tests/test_llm_timeout_defaults.py backend/tests/test_litellm_adapter.py -q`
- Backend provider/agent regression result:
  - `99 passed, 67 warnings`

### Phase 8 - Answer And Citation Behavior

Start status:
- Started Phase 8 after committing Phase 5 checkpoint `aaba058`.
- Goal: tighten citation identity and preview behavior without overbuilding citation generation.
- First focus:
  - audit backend citation/source binding and frontend citation click handling.
  - ensure repeated same source can reuse citation identity.
  - ensure web citations open URLs directly rather than document preview.
  - avoid forced citations when no evidence source exists.

Resume status:
- Resumed Phase 8 on branch `codex/pagechat-ui-agent-runtime-integration`.
- Confirmed `codex.md` still points to this worktree as the correct integration branch.
- Audit notes:
  - backend already ignores web citations when appending a missing document citation suffix.
  - frontend already opens web citations with `window.open(...)` instead of the preview drawer.
  - remaining gap: backend/frontend citation dedupe still depends too much on display labels or document names, so the same source can become multiple numbered references when labels differ.

Completion status:
- Backend citation identity now dedupes by web URL or document id + source anchor before falling back to document name.
- Document inventory/list records without a precise page/line/row/slide/paragraph anchor remain non-citation evidence and do not create inline references.
- Frontend inline citation numbering now reuses the same number when labels differ only by file extension, such as `report.pdf p.3` and `report p.3`.
- Chat store citation/evidence dedupe now uses source identity instead of display label where possible.
- Updated stale event-protocol test expectations for the current native tool-calling planner prompt/flags.
- RED tests initially failed for backend citation identity and frontend numbering/evidence dedupe, then passed after implementation.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_tree_first_retrieval_policy.py backend/tests/test_agent_policy.py backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_provider_protocol_selection.py backend/tests/test_model_gateway_settings.py backend/tests/test_llm_timeout_defaults.py backend/tests/test_litellm_adapter.py backend/tests/test_agent_citation_bindings.py backend/tests/test_agent_run_event_protocol.py backend/tests/test_chat_run_repository.py backend/tests/test_citation_binding.py -q` -> `138 passed, 67 warnings`
  - `npm.cmd test` in `frontend` -> `20 passed test files, 130 passed tests`
  - `npm.cmd run build` in `frontend` -> completed successfully

### Phase 9 - Regression And Acceptance

Start status:
- Started after Phase 8 checkpoint `cb66480`.
- Goal: run final acceptance scenarios and inspect any remaining product-level gaps before finishing the refactor branch.
- Planned checks:
  - run backend agent/provider/citation regression set.
  - run frontend tests and production build.
  - inspect runtime prompts/tool contracts for remaining hardcoded workflow language.
  - summarize any remaining manual/browser validation gaps.

Completion status:
- Updated the manual QA verifier to align with the LLM-driven loop: document scenarios require document tool evidence and citations, but no longer require a fixed `browse_documents -> search_within_document -> get_page_content` chain.
- Added/updated verifier tests so model-chosen document tool paths pass when they provide document evidence and citations.
- Static scan for old fixed-chain production text found no matches in `backend/app`, `backend/scripts`, or active tests. Remaining matches are historical/design-plan docs and tests asserting old prompt text is absent.
- Verification:
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_structured_llm_planner.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_tree_first_retrieval_policy.py backend/tests/test_agent_policy.py backend/tests/test_agent_loop_runtime.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_provider_protocol_selection.py backend/tests/test_model_gateway_settings.py backend/tests/test_llm_timeout_defaults.py backend/tests/test_litellm_adapter.py backend/tests/test_agent_citation_bindings.py backend/tests/test_agent_run_event_protocol.py backend/tests/test_chat_run_repository.py backend/tests/test_citation_binding.py backend/tests/test_pagechat_real_document_scenarios.py -q` -> `147 passed, 67 warnings`
  - `npm.cmd test` in `frontend` -> `20 passed test files, 130 passed tests`
  - `npm.cmd run build` in `frontend` -> completed successfully
  - `D:\projects\page_chat\backend\venv\Scripts\python.exe backend\scripts\verify_pagechat_agent_runtime.py --dry-run --document-name "重庆案例.pdf"` -> printed the expected four-scenario verification plan
- Manual browser/model validation was not run in this phase because it requires a live logged-in browser session, a selected parsed Chongqing document id, and configured model provider credentials.
