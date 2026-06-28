# Settings + Library UX Optimization Process

## Working Rules
- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Branch: `codex/pagechat-ui-agent-runtime-integration`
- Plan: `docs/superpowers/plans/2026-06-28-pagechat-chat-settings-library-ux-optimization-plan.zh.md`
- Before each phase: read this file, then append a short START entry.
- After each phase: read this file, then append a short DONE entry with tests and next step.
- Keep entries concise and factual.

## Timeline
- 2026-06-28 START: Created process tracker. Next: Phase 1 regenerate context correctness.
- 2026-06-28 Phase 1 START: Fix regenerate to truncate stale context before resending user prompt.
- 2026-06-28 Phase 1 DONE: Regenerate truncates stale frontend/backend context; tests passed: frontend chat.test.ts (45), backend chat scope+persistence+stream API (32). Next: Phase 2 sidebar menu layering.
- 2026-06-28 Phase 2 START: Move chat history more menu out of clipped sidebar scroll context.
- 2026-06-28 Phase 2 DONE: Chat history more menu now uses body Teleport/fixed positioning; test passed: AppShell.contract.test.ts. Next: Phase 3 provider search polish.
- 2026-06-28 Phase 3 START: Fix model provider search input overflow and focus styling.
- 2026-06-28 Phase 3 DONE: Provider search input is contained with parent focus styling; test passed: SettingsModal.contract.test.ts (13). Next: Phase 4 global language switch.
- 2026-06-28 Phase 4 START: Add global i18n preference and wire main app chrome/settings/composer labels.
- 2026-06-28 Phase 4 DONE: Added i18n store and wired language selection to shell/settings/composer chrome; tests passed: i18n + AppShell/SettingsModal/ChatComposer contracts (20), frontend build. Next: Phase 5 unified picker.
- 2026-06-28 Phase 5 START: Replace separate file/folder composer actions with one navigable library picker.
- 2026-06-28 Phase 5 DONE: Composer actions now use one library picker entry; picker supports folder navigation and mixed document/folder selection. Tests passed: ChatComposer.contract, LibraryScopePicker.contract, pagechatContracts (25); frontend build passed. Next: Phase 6 integrated QA.
- 2026-06-28 Phase 6 START: Run integrated targeted frontend tests and build for regenerate/menu/search/i18n/library changes.
- 2026-06-28 Phase 6 DONE: Integrated frontend targeted tests passed: chat store, SettingsModal, ChatComposer, LibraryScopePicker, AppShell, i18n, pagechatContracts (88); frontend build passed. Next: manual browser QA/restart if user wants live verification.
