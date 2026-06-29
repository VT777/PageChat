# Model Route + Reasoning UI QA

Date: 2026-06-28
Branch: `codex/pagechat-ui-agent-runtime-integration`
Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`

## Commands

- `npm.cmd test -- src/stores/chat.test.ts src/components/chat/ChatComposer.contract.test.ts src/components/settings/SettingsModal.contract.test.ts`
- `npm.cmd test -- src/types/stream.contract.test.ts src/stores/chat.test.ts src/components/chat/RunTimeline.contract.test.ts`
- `npm.cmd run build`
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_chat_stream_api.py backend/tests/test_chat_stream_reasoning.py backend/tests/test_tool_calling_model_adapter.py backend/tests/test_model_route_observability.py -q`
- `D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_agent_run_event_protocol.py backend/tests/test_flat_tool_loop_e2e.py -q`

## Results

- Frontend request-level `thinking_enabled` payload tests passed.
- Settings modal no longer exposes QA thinking controls.
- Frontend stream contract accepts `reasoning_delta`.
- Chat store accumulates native reasoning into assistant `thinking` only.
- `RunTimeline` renders native reasoning separately from processing/tool rows.
- Production frontend build completed successfully.
- Backend chat stream, reasoning adapter, route observability, and flat-loop regressions passed.

## Local Service Check

- Backend `/health` returned `{"status":"ok"}` on `http://127.0.0.1:8000/health`.
- Frontend returned HTTP 200 on `http://127.0.0.1:5173`.
- Backend command used the legacy Python/env fallback allowed by `codex.md`; startup script path and frontend process point to the current integration worktree.
