# PageChat Chat, Settings, and Library Picker UX Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复重生成上下文污染、侧边栏菜单裁切、模型供应商搜索框溢出、界面语言切换未全局生效，以及聊天输入框中文档/文件夹选择割裂的问题。

**Architecture:** 以现有 `codex/pagechat-ui-agent-runtime-integration` 分支为准，优先做前端状态和 UI 收口，必要时补充轻量后端接口但不重构 agent runtime。重生成逻辑在 `chat store` 里变成明确的“截断到目标问题并重新发送”；语言切换通过集中式 i18n 文案字典逐步替换硬编码；文件/文件夹选择合并为一个树状 library picker，复用现有 folder/document API。

**Tech Stack:** Vue 3, Pinia, Vue Router, Vitest, FastAPI existing endpoints, existing PageChat design system CSS.

---

## Current Branch And Constraints

- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Branch: `codex/pagechat-ui-agent-runtime-integration`
- Do not edit old worktrees: `fc17/page_chat`, `pagechat-frontend`, `D:\projects\page_chat`.
- Current worktree already has many uncommitted integration changes. Keep this optimization scoped and avoid unrelated formatting churn.
- Prefer frontend-only fixes unless backend persistence/API behavior is proven insufficient.

## Problem Analysis

### 1. Regenerate Keeps Old Context

Observed behavior:
- Regenerate from a user message or assistant answer appears to preserve later conversation content.
- UI can show duplicated user messages, as in the screenshot where the same prompt appears twice.

Likely root cause:
- `ChatView.vue` calls `regenerateUserMessage(message)` -> `chatStore.sendMessage(content)` without first truncating the active message list to the selected message boundary.
- `chatStore.regenerateMessage(message.id)` finds the related user message but may reuse the current full session state unless the store explicitly removes the target assistant message and every later message before sending.
- Backend receives a conversation id and continues the existing conversation, so if frontend does not persist the truncated state before regeneration, old messages can still be included in frontend state and/or backend history.

Desired behavior:
- Regenerate from a user message: remove that user message and every message after it, put the prompt back at that point, then send it as the next message.
- Regenerate from an assistant message: find the immediately preceding user prompt, remove the assistant message and everything after it, then resend that user prompt.
- Scroll/focus should move to the regenerated question area, not the bottom of stale history.
- The regenerated run should not inherit later messages as context.

### 2. Conversation History More Menu Is Clipped

Observed behavior:
- Lower sidebar history items open a menu, but menu content is clipped by a narrow sidebar boundary and requires scrolling.

Likely root cause:
- `AppShell.vue` sidebar/chat list containers use `overflow: hidden` / `overflow-y: auto` and the menu is rendered inside the scroll container.
- The menu is absolutely positioned relative to the chat item, so it cannot escape the scroll clipping context.

Desired behavior:
- Menu should be visible above the app chrome, regardless of the item position in the scroll list.
- It should either flip upward near the bottom or render through a portal/fixed-position layer.
- Sidebar should not show an extra “border box” feeling around history caused by clipping/stacking artifacts.

### 3. Model Provider Search Input Overflows

Observed behavior:
- Search box has a white rectangle/input area protruding past its rounded container.

Likely root cause:
- `.provider-search` and `.provider-search input` width/padding/box-sizing are not aligned.
- Native input background and focus styles may exceed the parent because the input is not `min-width: 0`, `width: 100%`, `box-sizing: border-box`, and transparent.

Desired behavior:
- Search container is a single rounded control.
- Input has transparent background, no internal white slab, and never overflows horizontally.
- Focus state uses the parent container, not the raw input rectangle.

### 4. English Language Selection Does Not Localize The App

Observed behavior:
- Settings language selector can choose English, but most app text stays mixed Chinese/English.

Likely root cause:
- There is currently no global i18n state or translation function.
- Text is hardcoded across `SettingsModal.vue`, `ChatView.vue`, `ChatComposer.vue`, `AppShell.vue`, `DocumentView.vue`, contracts, utility labels, and some error messages.
- Settings language value appears UI-local rather than a shared persisted preference that components consume reactively.

Desired behavior:
- Selecting English immediately changes all user-facing frontend chrome to English.
- Selecting 简体中文 immediately changes it back to Chinese.
- Preference persists per browser/user and is loaded before major UI renders.
- Backend-generated/model content is not translated by the frontend; only PageChat UI strings are localized.
- Start with the main product surfaces: sidebar, chat view, composer/actions, settings modal, document workbench common labels, provider settings, empty/loading/error states.

### 5. Select File And Select Folder Should Become One Library Picker

Observed behavior:
- Chat composer currently has separate “选择文件” and “选择文件夹” actions.
- When many documents exist, flat file selection is hard to disambiguate.
- User expects a hierarchical picker like the screenshots: search at top, current folder row/breadcrumb, document rows with checkboxes, folder rows that can be opened or selected.

Likely root cause:
- `ChatComposer.vue` has `pickerMode: 'file' | 'folder'`, separate document and folder lists, and document loading is flat-ish (`documentApi.list` with folder id and `include_subfolders: true`).
- Folder list uses `folderStore.folders`, not a navigable picker state with current folder, breadcrumb, and per-folder contents.

Desired behavior:
- Composer plus menu exposes one action: “Select Documents” or “选择文件/文件夹”.
- Picker supports folder navigation and selection in one surface:
  - search documents/folders;
  - show root/current path;
  - rows for folders and documents;
  - folders can be opened via row/chevron and selected via checkbox/button;
  - documents can be selected via checkbox;
  - selected chips persist in composer and session context.
- Selecting a folder sends folder scope with `include_subfolders: true`; selecting documents sends explicit `document_ids`.
- For mixed selection, document scope should stay explicit and folder scope should be included only if backend supports multiple folder scopes. If backend currently supports one folder id, UI should either allow one folder plus many documents or phase backend support separately.

---

## File Map

### Frontend State And Chat Behavior

- Modify: `frontend/src/stores/chat.ts`
  - Add explicit regeneration helpers that truncate messages/session state before sending.
  - Ensure persisted session data is updated after truncation and before new stream starts.
  - Add tests for user-message and assistant-message regeneration.

- Modify: `frontend/src/views/ChatView.vue`
  - Call store-level regeneration helpers instead of manually resending stale content.
  - Scroll to regenerated message anchor after truncation.
  - Keep pending rollback behavior separate from regenerate.

- Test: `frontend/src/stores/chat.test.ts`
- Test: `frontend/src/views/ChatView` coverage if current test setup supports it; otherwise add source-contract tests.

### Sidebar History Menu

- Modify: `frontend/src/components/layout/AppShell.vue`
  - Replace inline clipped menu with fixed-position menu coordinates or Vue `Teleport` to app root/body.
  - Add bottom-edge flip behavior.
  - Close on outside click, escape, route change, and scroll.

- Test: `frontend/src/components/layout/AppShell.contract.test.ts` or source-contract test if component mounting is heavy.

### Provider Search UI

- Modify: `frontend/src/components/settings/SettingsModal.vue`
  - Adjust `.provider-search` and input CSS.
  - Use `box-sizing: border-box`, `min-width: 0`, transparent input background, no input border/shadow.

- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`

### Global Localization

- Create: `frontend/src/i18n/messages.ts`
  - Translation dictionaries for `zh-CN` and `en`.
  - Keys for sidebar, chat, composer, settings, provider settings, document workbench common labels.

- Create: `frontend/src/stores/preferences.ts` or `frontend/src/composables/useI18n.ts`
  - Persist `language` to localStorage scoped to current user if feasible.
  - Expose `language`, `setLanguage`, and `t(key, params?)`.

- Modify: `frontend/src/components/settings/SettingsModal.vue`
  - Bind language selector to global preference.
  - Replace settings strings with `t()` for main sections.

- Modify: `frontend/src/components/layout/AppShell.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/components/chat/ChatComposer.vue`
- Modify: `frontend/src/views/DocumentView.vue` for high-frequency labels only in first pass.
- Modify: `frontend/src/ui/pagechatContracts.ts` only where constants are UI labels; keep stable ids unchanged.

- Test: `frontend/src/i18n/messages.test.ts`
- Test: update existing contract tests to assert English/Chinese switching hooks exist.

### Unified Library Picker

- Create: `frontend/src/components/chat/LibraryScopePicker.vue`
  - Owns current folder id, breadcrumb, search query, folder/document rows, selected ids.
  - Emits selected document/folder ids to composer.
  - Uses existing `folderApi.getContents` / `folderApi.getTree` / `documentApi.list` as available.

- Modify: `frontend/src/components/chat/ChatComposer.vue`
  - Replace `pickerMode: 'file' | 'folder'` with `showLibraryPicker`.
  - Merge `COMPOSER_ACTIONS` entries for file/folder into one action.
  - Keep selected document/folder chips and persistence behavior.

- Modify: `frontend/src/ui/pagechatContracts.ts`
  - Replace separate composer action labels with one `library` action.
  - Add helper contracts for picker labels and selection summary.

- Test: `frontend/src/components/chat/ChatComposer.contract.test.ts`
- Test: `frontend/src/components/chat/LibraryScopePicker.contract.test.ts`
- Test: `frontend/src/ui/pagechatContracts.test.ts`

### Backend Compatibility Check

- Inspect only unless needed:
  - `backend/app/api/folders.py`
  - `backend/app/api/documents.py`
  - `backend/app/services/agent_service.py`

- If backend only accepts one `folder_id`, defer multi-folder backend support to a separate task and constrain UI copy to “one folder at a time” for folder scope.

---

## Implementation Phases

### Phase 1: Regenerate Context Correctness

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/views/ChatView.vue`
- Test: `frontend/src/stores/chat.test.ts`

- [ ] Write failing tests for regenerating from a user message:
  - Given messages `[u1, a1, u2, a2]`, regenerating `u1` removes all messages from `u1` onward before sending `u1.content` again.
  - Persisted session should not contain stale `a1/u2/a2` after truncation.

- [ ] Write failing tests for regenerating from an assistant message:
  - Given `[u1, a1, u2, a2]`, regenerating `a2` keeps `[u1, a1]`, resends `u2.content`, and does not include old `a2`.

- [ ] Implement store helpers:
  - `regenerateFromUserMessage(messageId)`
  - `regenerateFromAssistantMessage(messageId)`
  - both use a shared `truncateForRegeneration(index)`.

- [ ] Update `ChatView.vue` handlers to use these helpers.

- [ ] Add scroll behavior:
  - after truncation, scroll to the regenerated user prompt/answer start rather than stale bottom.

- [ ] Run:
  - `npm.cmd test -- src/stores/chat.test.ts`
  - relevant chat contract tests.

### Phase 2: Sidebar More Menu Layering

**Files:**
- Modify: `frontend/src/components/layout/AppShell.vue`
- Test: add/update `frontend/src/components/layout/AppShell.contract.test.ts`

- [ ] Write a contract test that the chat history menu is rendered through a fixed/teleported layer, not inside the clipped chat item.

- [ ] Implement menu positioning:
  - capture trigger button `getBoundingClientRect()`;
  - render menu as `position: fixed`;
  - flip upward if bottom space is insufficient;
  - close on outside click, escape, scroll, or opening another menu.

- [ ] Remove/adjust clipping styles only where safe:
  - keep the chat history list scrollable;
  - do not allow child menus to be clipped.

- [ ] Run:
  - `npm.cmd test -- src/components/layout/AppShell.contract.test.ts`
  - `npm.cmd run build` if CSS changes are broad.

### Phase 3: Provider Search Control Polish

**Files:**
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Test: `frontend/src/components/settings/SettingsModal.contract.test.ts`

- [ ] Add/adjust source contract test asserting provider search input uses parent-contained styling classes.

- [ ] CSS changes:
  - `.provider-search { box-sizing: border-box; overflow: hidden; }`
  - `.provider-search input { width: 100%; min-width: 0; background: transparent; border: 0; box-shadow: none; }`
  - parent `:focus-within` owns border/ring.

- [ ] Verify visually in settings modal.

### Phase 4: Global Interface Language

**Files:**
- Create: `frontend/src/i18n/messages.ts`
- Create: `frontend/src/composables/useI18n.ts` or `frontend/src/stores/preferences.ts`
- Modify: `frontend/src/components/settings/SettingsModal.vue`
- Modify: `frontend/src/components/layout/AppShell.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/components/chat/ChatComposer.vue`
- Modify: `frontend/src/views/DocumentView.vue` for core labels.
- Test: new i18n tests and updated contract tests.

- [ ] Define minimal dictionary coverage for all visible strings in screenshots and main flows:
  - Settings title/subtitle/nav/section headers.
  - Provider search placeholder and buttons.
  - Chat composer actions, Thinking, Web Search, selected chips.
  - Sidebar New Chat, Chats, Documents, Settings, Export, Delete.
  - Document workbench common actions and empty/loading states.

- [ ] Add preference store/composable:
  - `language = 'zh-CN' | 'en'`;
  - localStorage persistence;
  - `t(key, params?)` fallback to English key or Chinese default.

- [ ] Wire Settings language selector to the global preference.

- [ ] Replace hardcoded strings incrementally in the main surfaces.

- [ ] Do not translate model answers, document names, filenames, provider names, or backend error detail text unless it maps to a known UI error code.

- [ ] Run:
  - `npm.cmd test -- src/i18n/messages.test.ts src/components/settings/SettingsModal.contract.test.ts src/components/chat/ChatComposer.contract.test.ts`
  - `npm.cmd run build`

### Phase 5: Unified Select File/Folder Library Picker

**Files:**
- Create: `frontend/src/components/chat/LibraryScopePicker.vue`
- Modify: `frontend/src/components/chat/ChatComposer.vue`
- Modify: `frontend/src/ui/pagechatContracts.ts`
- Test: `frontend/src/components/chat/ChatComposer.contract.test.ts`
- Test: `frontend/src/components/chat/LibraryScopePicker.contract.test.ts`
- Test: `frontend/src/ui/pagechatContracts.test.ts`

- [ ] Replace separate composer actions:
  - remove separate `file` and `folder` action display;
  - add one `library` action labeled `选择文件/文件夹` / `Select documents`.

- [ ] Implement picker layout:
  - top search input;
  - breadcrumb/current folder row;
  - folder rows with folder icon, file count when available, open chevron, select checkbox;
  - document rows with thumbnail/icon, page count/date, checkbox;
  - bottom action row showing selected count and confirm/cancel.

- [ ] Navigation rules:
  - clicking folder row/chevron opens folder;
  - clicking checkbox selects folder without opening;
  - back button returns to parent/root;
  - search filters current scope first; if backend search is needed, defer global search.

- [ ] Scope rules:
  - selected documents populate `documentIds`;
  - selected folder populates `folderIds`;
  - if backend supports one folder id only, disable selecting multiple folders and show concise helper text.

- [ ] Persist selected document/folder chips via existing chat store context logic.

- [ ] Run:
  - `npm.cmd test -- src/components/chat/ChatComposer.contract.test.ts src/components/chat/LibraryScopePicker.contract.test.ts src/ui/pagechatContracts.test.ts`

### Phase 6: Integrated QA

**Files:**
- No new production files unless bugs are found.
- Update QA notes if the repo convention requires it.

- [ ] Run frontend targeted tests:
  - `npm.cmd test -- src/stores/chat.test.ts src/components/settings/SettingsModal.contract.test.ts src/components/chat/ChatComposer.contract.test.ts src/ui/pagechatContracts.test.ts`

- [ ] Run full frontend build:
  - `npm.cmd run build`

- [ ] Browser QA checklist:
  - Regenerate from user message truncates context and scrolls to current regenerated question.
  - Regenerate from assistant answer truncates from the previous user prompt and does not keep old answer.
  - Sidebar lower history menu is not clipped.
  - Provider search input no longer overflows.
  - Settings language switch changes visible app chrome immediately.
  - Unified library picker can select a document inside a folder and a folder scope.
  - Selected scope persists when switching Documents -> Chat -> Documents -> Chat.

- [ ] If backend folder scope limitation blocks expected multi-folder behavior, write a separate backend plan instead of forcing frontend-only behavior.

---

## Risks And Decisions

- **Language localization can balloon.** Keep Phase 4 focused on app chrome and common states. Do not try to localize every legacy/demo string in the first pass.
- **Mixed folder + multiple folder scopes may exceed current backend contract.** Confirm before enabling multi-folder selection. Prefer honest UI constraints over silently dropping folder ids.
- **Regenerate must coordinate frontend and backend histories.** If frontend truncation alone does not update backend conversation history, add a backend endpoint or parameter for regeneration truncation. Do not mask the problem client-side only.
- **Menu clipping should not remove sidebar scroll.** Use fixed/teleport menu rather than making the whole sidebar overflow visible.

## Recommended Execution Order

1. Phase 1 first because regenerate context pollution can affect actual model answers.
2. Phase 2 and Phase 3 next because they are low-risk UI polish.
3. Phase 5 before Phase 4 if quick product utility is preferred.
4. Phase 4 can be broader; keep it incremental and test-driven.
