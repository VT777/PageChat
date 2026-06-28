# User Isolation, History, Settings, and Processing Process

Plan: `docs/superpowers/plans/2026-06-28-pagechat-user-isolation-history-settings-processing-plan.zh.md`

## Status Log

- 2026-06-28 Phase 1 start: Begin user-scoped frontend chat cache. Current known root cause is global localStorage keys shared by all authenticated users.
- 2026-06-28 Phase 1 end: Added user-scoped chat localStorage namespace and login/logout integration. Verification passed: `npm.cmd test -- src/stores/user.test.ts src/stores/chat.test.ts` (40 tests).
- 2026-06-28 Phase 2 start: Make backend conversation list/messages the source of truth after login. Target root cause: local sessions currently load before backend and can preserve stale partial records.
- 2026-06-28 Phase 2 end: Added backend conversation hydration, backend-first message loading for durable conversation ids, and inaccessible-cache cleanup. Verification passed: `npm.cmd test -- src/stores/user.test.ts src/stores/chat.test.ts` (43 tests).
- 2026-06-28 Phase 3 start: Add backend defense-in-depth for message listing/export so repository calls can be scoped by conversation owner.
- 2026-06-28 Phase 3 end: Added `list_messages_for_user` and wired chat messages/export endpoints through it. Verification passed: `python -m pytest backend/tests/test_chat_run_repository.py backend/tests/test_chat_history_persistence.py -q` (10 tests; existing deprecation warnings only).
- 2026-06-28 Phase 4 start: Remove fake/default model choices from settings and show only configured provider models.
- 2026-06-28 Phase 4 end: Removed hard-coded model defaults/fallback options and added empty select states for unconfigured routes. Verification passed: `npm.cmd test -- src/components/settings/SettingsModal.contract.test.ts`; `npm.cmd run build`.
- 2026-06-28 Phase 5 start: Persist QA thinking mode per user instead of global runtime settings. Red test already confirms user B currently inherits user A's mode.
- 2026-06-28 Phase 5 end: Added `user_runtime_settings` migration/service, moved `/api/settings/qa` to current-user storage, and passed user QA thinking mode into agent runtime paths. Verification passed: `python -m pytest backend/tests/test_model_settings_api.py backend/tests/test_database_migrations.py backend/tests/test_runtime_settings_api.py backend/tests/test_agent_service_flat_loop_runtime.py -q` (32 tests; existing warnings only).
- 2026-06-28 Phase 6 start: Preserve compact folder names/tree in agent tool observations so folder inventory questions can be answered from tool results.
- 2026-06-28 Phase 6 end: `browse_documents` compact results now keep folder names/paths/counts, `view_folder_structure` keeps a sanitized tree, and model tool messages preserve those fields while stripping local paths. Verification passed: `python -m pytest backend/tests/test_agent_run_event_protocol.py backend/tests/test_tool_messages.py backend/tests/test_folder_tools.py -q` (24 tests; existing warnings only).
- 2026-06-28 Phase 7 start: Add concise Processing details notes to the flat LLM-driven tool loop without exposing hidden chain-of-thought or duplicating final answers.
- 2026-06-28 Phase 7 end: Flat loop now emits a deterministic short `processing_delta` before each tool starts, with user-language wording and no final-answer duplication. Verification passed: `python -m pytest backend/tests/test_model_tool_loop_runtime.py backend/tests/test_flat_tool_loop_e2e.py -q`; `npm.cmd test -- src/components/chat/RunTimeline.contract.test.ts`.
