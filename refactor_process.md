# PageChat LLM-Driven Agent Loop Refactor Process

This file is the handoff log for the LLM-driven Agent Loop refactor. Read it before starting or resuming work. Update it at the start and end of every phase so context compression can recover the current state.

## Baseline

- Branch: `codex/pagechat-ui-agent-runtime-integration`
- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Baseline checkpoint before refactor: `c551c12 chore(agent): checkpoint before llm-driven loop refactor`
- Primary plan: `docs/superpowers/plans/2026-06-27-pagechat-llm-driven-agent-loop-plan.zh.md`
- Execution order: Phase 1, Phase 2, Phase 3, Phase 6, Phase 7, Phase 4, Phase 5, Phase 8, Phase 9.

## Current Status

- Current phase: Phase 7 - UI Processing / Thinking Area.
- Status: Completed.
- Started at: 2026-06-27.
- Notes: Phase 7 completed. Next phase is Phase 4 multi-tool model turn support.

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
