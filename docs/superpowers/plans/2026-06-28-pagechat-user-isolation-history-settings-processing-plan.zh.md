# PageChat User Isolation, History, Settings, and Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents unless the user explicitly re-enables them.

**Goal:** Fix user data isolation, durable chat history, configured-only model settings, folder-name tool results, and Processing details visibility.

**Architecture:** Treat the backend database as the source of truth for authenticated user data. Frontend localStorage becomes a user-scoped draft/cache layer only, never a cross-user conversation source. Agent tool observations must preserve compact but answerable metadata, and Processing details should show concise model-visible progress without exposing internal mechanics.

**Tech Stack:** Vue 3 + Pinia frontend, FastAPI backend, SQLite persistence, SSE chat streaming, LiteLLM/OpenAI-compatible tool calling.

---

## Root Cause Summary

- Frontend chat storage keys are global: `pagechat_chat_sessions`, `pagechat_sessions_data`, `pagechat_document_contexts`, and `pagechat_draft_composer_text`.
- Chat page restores localStorage only and does not hydrate `/api/chat/conversations` on mount.
- `loadConversation()` prefers stale local session messages over backend messages.
- Settings modal initializes with hard-coded example model values and fallback options before async user configuration loads.
- QA thinking/pageindex runtime settings are stored globally in `backend/data/runtime_settings.json`, not per user.
- Tool result compaction drops `folders` and `tree`, so the model sees counts but not folder names.
- Flat model tool loop streams answer text and tool-call deltas, but does not emit concise processing notes for tool decisions or provider reasoning fields.

---

## File Map

- Modify: `frontend/src/stores/chat.ts`
  - User-scoped localStorage keys.
  - Backend-first conversation list hydration.
  - Safe local draft/session cache behavior.
  - Conversation load fallback rules.
- Modify: `frontend/src/views/ChatView.vue`
  - Initialize chat from backend after auth is ready.
- Modify: `frontend/src/stores/user.ts`
  - Expose stable current user id for cache namespace and clear user-sensitive stores on logout.
- Modify: `frontend/src/components/settings/SettingsModal.vue`
  - Remove fake default model options.
  - Add loading/empty states for configured-only models.
  - Avoid transient default route display.
- Modify: `backend/app/api/chat.py`
  - Harden message listing/export with user_id scoped repository calls.
- Modify: `backend/app/services/chat_run_repository.py`
  - Add user-scoped message query variant.
- Modify: `backend/app/api/settings.py`
  - Decide whether QA runtime settings remain global or move to user-scoped settings.
- Modify: `backend/app/services/runtime_settings_service.py` or create a DB-backed user settings service
  - Persist QA thinking mode per user if product expects per-user behavior.
- Modify: `backend/app/agent/nodes.py`
  - Preserve compact folder/tree entries in tool results.
- Modify: `backend/app/agent/tool_messages.py`
  - Ensure compact folder results passed to model include names, ids, paths, and counts.
- Modify: `backend/app/agent/model_tool_loop.py`
  - Emit concise processing notes around model tool decisions.
- Modify: `backend/app/agent/tool_calling_model_adapter.py`
  - Optionally extract provider reasoning deltas when available and allowed.
- Test: `frontend/src/stores/chat.test.ts`
- Test: `frontend/src/components/settings/SettingsModal*.test.ts` if present; otherwise add focused component/store tests.
- Test: `backend/tests/test_chat_user_isolation.py`
- Test: `backend/tests/test_agent_tool_results.py`
- Test: `backend/tests/test_agent_flat_tool_loop.py`

---

## Phase 1: User-Scoped Chat Storage

**Goal:** Stop cross-user localStorage bleed immediately.

- [ ] Write failing frontend tests in `frontend/src/stores/chat.test.ts`:
  - user A sessions are not visible after switching to user B.
  - document contexts and draft composer text are scoped by user id.
  - logout does not leave the next user with previous user chat state.
- [ ] Implement storage namespace helpers in `frontend/src/stores/chat.ts`, for example:
  - `pagechat:${userId}:chat_sessions`
  - `pagechat:${userId}:sessions_data`
  - `pagechat:${userId}:document_contexts`
  - `pagechat:${userId}:draft_composer_text`
- [ ] Add a migration rule:
  - do not automatically import old global keys into an authenticated user.
  - optionally keep old keys untouched for manual recovery only.
- [ ] Update `frontend/src/stores/user.ts` logout flow to clear active in-memory chat state.
- [ ] Run:
  - `npm test -- frontend/src/stores/chat.test.ts`
- [ ] Commit:
  - `fix(chat): scope local chat cache by user`

## Phase 2: Backend-First Conversation History

**Goal:** Make durable backend conversations the source of truth after login.

- [ ] Write failing frontend tests:
  - ChatView/store loads conversation list from `chatApi.getConversations()` after login.
  - stale local session with one message does not override backend full messages.
  - 404/unauthorized backend conversation is removed from local view instead of recreated from `firstMessage`.
- [ ] Add store action in `frontend/src/stores/chat.ts`:
  - `hydrateConversationsFromBackend()`
  - maps backend `id/title/updated_at` to sidebar conversation metadata.
  - preserves local draft only for current user and only when no backend active conversation is selected.
- [ ] Update `frontend/src/views/ChatView.vue`:
  - wait for auth user state.
  - load backend conversations first.
  - restore last active only if it belongs to the current user and exists in backend or is an unsent draft.
- [ ] Change `loadConversation()`:
  - fetch backend messages for backend conversation ids first.
  - use local cache only as temporary rendering cache after backend identity is confirmed.
  - avoid fallback to single `firstMessage` for backend ids that fail authorization.
- [ ] Run:
  - `npm test -- frontend/src/stores/chat.test.ts`
- [ ] Commit:
  - `fix(chat): hydrate conversations from backend source of truth`

## Phase 3: Backend User-Isolation Hardening

**Goal:** Add defense in depth so internal calls cannot accidentally read another user's messages.

- [ ] Write backend tests in `backend/tests/test_chat_user_isolation.py`:
  - user A cannot list user B messages.
  - export rejects cross-user conversation id.
  - repository user-scoped message query returns empty/404 for wrong user.
- [ ] Add `list_messages_for_user(conversation_id, user_id)` or equivalent in `backend/app/services/chat_run_repository.py`.
- [ ] Update `backend/app/api/chat.py` list/export paths to use the user-scoped repository method.
- [ ] Keep existing API-level ownership checks.
- [ ] Run:
  - `pytest backend/tests/test_chat_user_isolation.py -q`
- [ ] Commit:
  - `fix(chat): harden conversation message reads by user`

## Phase 4: Configured-Only Model Settings

**Goal:** Remove fake model choices and stop transient default UI states.

- [ ] Write settings tests:
  - no configured providers means model selects show an empty/configure-first state.
  - hard-coded `OpenAI Compatible: gpt-4.1` does not appear unless user configured it.
  - saved route is displayed only after route/provider/model data is loaded.
- [ ] Update `frontend/src/components/settings/SettingsModal.vue`:
  - initialize `ocrSettings.model`, `parsingSettings.model`, and `qaSettings.model` to empty string.
  - remove `fallbackModelOptions()` usage for OCR/parsing/QA selects.
  - show loading state while provider models/routes load.
  - show “请先配置模型供应商” empty state when no configured model exists.
- [ ] Confirm provider model lists come only from saved providers.
- [ ] Run:
  - `npm test -- frontend/src/components/settings`
  - if no component tests exist, add targeted tests and run them.
- [ ] Commit:
  - `fix(settings): show only configured model options`

## Phase 5: User-Scoped QA Runtime Settings Decision

**Goal:** Make QA thinking behavior predictable across logout/login.

- [ ] Decide and document product behavior:
  - recommended: QA thinking mode is user-scoped.
  - pageindex parsing mode may remain global only if it controls server-wide parsing behavior.
- [ ] If user-scoped:
  - add SQLite table or extend existing settings table for `qa_thinking_mode`.
  - update `backend/app/api/settings.py` GET/PUT `/api/settings/qa` to read/write current user.
  - update `backend/app/services/agent_service.py` to resolve thinking mode by `user_id`.
- [ ] Tests:
  - user A thinking mode does not affect user B.
  - logout/login reloads the same user's setting without transient default overwrite.
- [ ] Run:
  - `pytest backend/tests/test_settings*.py -q`
- [ ] Commit:
  - `fix(settings): persist qa thinking mode per user`

## Phase 6: Folder Tool Result Contract

**Goal:** Let the model answer folder-name questions from tool observations.

- [ ] Write backend tests in `backend/tests/test_agent_tool_results.py`:
  - `browse_documents` compact result includes `folders` with `id/name/path/child_count/document_count`.
  - `view_folder_structure` compact result includes root `tree.children` names.
  - model-facing tool message includes folder names but not sensitive local paths.
- [ ] Update `backend/app/agent/nodes.py`:
  - include compact `folders` for `browse_documents`.
  - include compact `tree` for `view_folder_structure`.
  - keep result labels concise.
- [ ] Update `backend/app/agent/tool_messages.py` if needed:
  - preserve folder ids/names/paths/counts through `_compact_for_model`.
  - keep list caps small, for example first 8 folders and first 8 children per node.
- [ ] Run:
  - `pytest backend/tests/test_agent_tool_results.py -q`
- [ ] Commit:
  - `fix(agent): preserve folder names in tool observations`

## Phase 7: Processing Details Content

**Goal:** Show concise processing content, not only raw tool actions.

- [ ] Write backend/frontend tests:
  - when the model chooses a tool, UI receives a short processing note before or alongside tool execution.
  - processing notes are concise and in the user's language.
  - final answer text is not duplicated into Processing details.
- [ ] Update `backend/app/agent/model_tool_loop.py`:
  - before executing a tool call, emit `processing_delta` such as `正在查看文件夹结构。`
  - derive wording from tool name and arguments, not from hidden chain-of-thought.
  - keep model autonomy: do not reintroduce planner stages.
- [ ] Update `backend/app/agent/tool_calling_model_adapter.py`:
  - if provider streams safe reasoning summaries, map them to `processing_delta` only when QA thinking mode is `auto/on`.
  - do not expose raw private chain-of-thought.
- [ ] Verify `frontend/src/components/chat/RunTimeline.vue` already renders processing and tool entries in sequence.
- [ ] Run:
  - `pytest backend/tests/test_agent_flat_tool_loop.py -q`
  - `npm test -- frontend/src/components/chat/RunTimeline.contract.test.ts`
- [ ] Commit:
  - `feat(agent): show concise processing details in flat loop`

## Phase 8: End-to-End Regression

**Goal:** Prove the reported bugs are fixed together.

- [ ] Start backend and frontend according to `codex.md`.
- [ ] Test with two users:
  - user A creates conversation and selects files.
  - logout.
  - user B logs in and sees no user A conversations, drafts, or selected documents.
  - user A logs back in and sees complete conversation history.
- [ ] Test configured-only settings:
  - no provider configured: no fake model options.
  - provider configured: models appear after loading and selected routes persist.
- [ ] Test folder query:
  - ask “当前有哪些文件夹？”
  - answer includes folder names.
- [ ] Test Processing details:
  - ask a document question that needs tools.
  - Processing details shows concise processing notes and tool calls.
- [ ] Run full focused test set:
  - backend user isolation/settings/tool tests.
  - frontend chat/settings/timeline tests.
- [ ] Commit:
  - `test: cover user isolation and processing regressions`

## Acceptance Criteria

- Different users never see each other's conversations, draft contexts, selected documents, or local cached messages.
- Re-login restores the current user's durable backend conversations with complete user and assistant messages.
- Old local fallback records do not override backend messages.
- Settings model dropdowns only show configured provider models.
- QA thinking mode behaves consistently after logout/login.
- Folder listing answers include names, not just counts.
- Processing details include concise processing notes plus tool calls, without exposing raw hidden reasoning.

