# PageChat Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved PageChat design demo and `DESIGN_SYSTEM.md` into the real Vue frontend for chat, documents, and settings.

**Architecture:** Add a shared authenticated app shell and a small UI contract layer for navigation, settings sections, document icons, composer actions, and inline tool summaries. Refactor the three core views to consume those contracts while keeping existing stores and backend APIs.

**Tech Stack:** Vue 3, Vite, Pinia, Vitest, lucide-vue-next, existing REST/SSE APIs.

---

### Task 1: UI Contract Layer

**Files:**
- Create: `frontend/src/ui/pagechatContracts.ts`
- Test: `frontend/src/ui/pagechatContracts.test.ts`

- [ ] Write failing tests for product name, app navigation, settings nav, composer actions, parse mode ordering, web search modes, document file tone mapping, and inline tool summaries.
- [ ] Run `npm test -- src/ui/pagechatContracts.test.ts` from `frontend` and confirm the tests fail because the module does not exist.
- [ ] Implement the smallest contract module that passes the tests.
- [ ] Re-run the focused test and then the full Vitest suite.

### Task 2: Shared App Shell

**Files:**
- Create: `frontend/src/components/layout/AppShell.vue`
- Modify: `frontend/src/style.css`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] Add PageChat CSS tokens and shared utility classes.
- [ ] Build the global left sidebar and topbar using the contract layer.
- [ ] Remove duplicated page-local sidebars and old KnowClaw branding from authenticated pages.
- [ ] Keep existing chat/session/document stores wired through the shell.

### Task 3: Core Page Refactors

**Files:**
- Create: `frontend/src/components/chat/InlineToolStep.vue`
- Create: `frontend/src/components/chat/ChatComposer.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/views/SettingsView.vue`

- [ ] Replace chat tool cards with one inline expandable step per tool call.
- [ ] Replace the composer toolbar with a plus menu for image, web search, file, and folder context.
- [ ] Rework Documents into a full-width list with stable `root` breadcrumb, default checkboxes, folder rows, and no right detail pane.
- [ ] Keep document preview as TOC/Info left tabs plus preview-only right pane.
- [ ] Rework Settings into a large Dify-like workspace with only the approved PageChat sections.

### Task 4: Verification

**Files:**
- Modify as needed based on verification findings.

- [ ] Run `npm test`.
- [ ] Run `npm run build`.
- [ ] Start `npm run dev` and inspect chat, documents, and settings in a browser.
- [ ] Fix any build, runtime, or visible layout issues before reporting status.
