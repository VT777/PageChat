# PageChat Answer Rendering Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the main chat answer rendering from ad-hoc Markdown HTML into a Dify-inspired, reusable, polished answer renderer with better tables, code blocks, links, images, and inline citations.

**Architecture:** Extract assistant answer rendering out of `ChatView.vue` into focused components and utilities. Keep the first phase lightweight: continue using `marked` and existing citation binding, but introduce a stable renderer boundary and answer prose styles so future migration to `streamdown` or chart components is straightforward.

**Tech Stack:** Vue 3, TypeScript, `marked`, existing PageChat citation utilities, Vitest contract tests, Vite build.

---

## Reference Findings From Dify

Dify uses a dedicated Markdown stack instead of rendering Markdown inline inside the chat page:

- `D:\projects\dify\web\app\components\base\markdown\index.tsx`
  - Chat answers use a reusable `<Markdown />` wrapper with a stable `markdown-body` class.
- `D:\projects\dify\web\app\components\base\markdown\streamdown-wrapper.tsx`
  - Uses `streamdown` for streaming Markdown, GFM, math, sanitize, URL transform, and custom components.
- `D:\projects\dify\web\app\components\base\markdown-blocks\code-block.tsx`
  - Code blocks are custom-rendered with language headers, copy buttons, Shiki highlighting, Mermaid, ECharts, SVG, and error boundaries.
- `D:\projects\dify\web\app\styles\markdown.css`
  - Tables, links, code, images, and streamdown table wrappers have complete visual rules.
- `D:\projects\dify\web\app\styles\plugins\typography-config.js`
  - Typography tokens centralize prose colors, spacing, table borders, links, and inline code.

PageChat should not copy all complexity at once. The right first step is a "Dify-lite" renderer: component boundary now, richer Markdown styles now, optional streaming renderer and chart blocks later.

---

## File Structure

- Create: `frontend/src/components/chat/AssistantMarkdownRenderer.vue`
  - Owns assistant Markdown rendering, citation replacement, web link decoration, and click event forwarding.
- Create: `frontend/src/components/chat/AssistantMarkdownRenderer.contract.test.ts`
  - Locks renderer responsibilities and prevents logic from drifting back into `ChatView.vue`.
- Create: `frontend/src/utils/answerMarkdown.ts`
  - Pure helpers for Markdown rendering, citation placeholders, citation buttons, web source decorations, and optional post-processing wrappers.
- Create: `frontend/src/utils/answerMarkdown.test.ts`
  - Unit tests for Markdown/citation/table/link transformations.
- Modify: `frontend/src/views/ChatView.vue`
  - Replace inline rendering functions and `v-html` block with `AssistantMarkdownRenderer`.
  - Keep citation preview behavior and existing click handling through emitted events.
- Modify: `frontend/src/views/ChatView.vue` styles or create `frontend/src/components/chat/assistant-markdown.css`
  - Add answer prose styles for headings, paragraphs, lists, tables, code, blockquotes, links, images, citations.

---

## Task 1: Extract Pure Markdown Rendering Helpers

**Files:**
- Create: `frontend/src/utils/answerMarkdown.ts`
- Create: `frontend/src/utils/answerMarkdown.test.ts`
- Modify: `frontend/src/views/ChatView.vue`

- [ ] **Step 1: Write failing tests for citation placeholders**

Test cases:
- plain Markdown renders through `marked`
- document citation placeholders become inline citation buttons
- web links that match evidence URLs become web citation buttons
- unsafe content is not expanded beyond current behavior

Run:

```bash
cd frontend
npm.cmd test -- src/utils/answerMarkdown.test.ts
```

Expected: FAIL because `answerMarkdown.ts` does not exist.

- [ ] **Step 2: Implement minimal helper module**

Move these responsibilities out of `ChatView.vue`:

- `renderMarkdown`
- `escapeHtml`
- `contentWithCitationPlaceholders`
- citation button HTML construction
- web source button decoration

Keep function inputs explicit. Do not import Pinia stores into this utility.

- [ ] **Step 3: Run helper tests**

Run:

```bash
cd frontend
npm.cmd test -- src/utils/answerMarkdown.test.ts
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/utils/answerMarkdown.ts frontend/src/utils/answerMarkdown.test.ts
git commit -m "refactor(frontend): extract assistant markdown helpers"
```

---

## Task 2: Create AssistantMarkdownRenderer Component

**Files:**
- Create: `frontend/src/components/chat/AssistantMarkdownRenderer.vue`
- Create: `frontend/src/components/chat/AssistantMarkdownRenderer.contract.test.ts`
- Modify: `frontend/src/views/ChatView.vue`

- [ ] **Step 1: Write failing contract test**

Contract expectations:
- component accepts `message`, `documents`, and `content`
- component emits citation/web-source click events instead of owning preview state
- component renders a single `.assistant-markdown` root
- `ChatView.vue` no longer owns Markdown parsing helpers

Run:

```bash
cd frontend
npm.cmd test -- src/components/chat/AssistantMarkdownRenderer.contract.test.ts
```

Expected: FAIL because component does not exist.

- [ ] **Step 2: Implement component with current behavior preserved**

Renderer should:
- compute bound citations using existing citation utilities
- call pure `answerMarkdown` helpers
- render with `v-html`
- emit `citation-click` and `web-source-click`
- keep existing inline citation button `data-*` attributes

- [ ] **Step 3: Replace ChatView inline block**

In `frontend/src/views/ChatView.vue`:
- remove local Markdown render helper functions where possible
- replace:

```vue
<div class="assistant-content" v-html="renderMessageMarkdown(message)" />
```

with:

```vue
<AssistantMarkdownRenderer
  class="assistant-content"
  :message="message"
  :documents="documentStore.documents"
  @citation-click="..."
  @web-source-click="..."
/>
```

Keep current preview behavior unchanged.

- [ ] **Step 4: Run targeted tests**

```bash
cd frontend
npm.cmd test -- src/components/chat/AssistantMarkdownRenderer.contract.test.ts src/utils/answerMarkdown.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/AssistantMarkdownRenderer.vue frontend/src/components/chat/AssistantMarkdownRenderer.contract.test.ts frontend/src/views/ChatView.vue
git commit -m "refactor(frontend): isolate assistant markdown renderer"
```

---

## Task 3: Add Dify-Lite Answer Prose Styles

**Files:**
- Modify: `frontend/src/components/chat/AssistantMarkdownRenderer.vue`
- Modify or Create: `frontend/src/components/chat/assistant-markdown.css`
- Modify: `frontend/src/views/ChatView.vue` only if style import placement requires it

- [ ] **Step 1: Write failing contract/style test**

Test for selectors or source contracts:
- `.assistant-markdown`
- table wrapper style or table selectors
- heading selectors
- blockquote selectors
- code block selectors
- image wrapper selectors
- inline citation selectors remain present

Run:

```bash
cd frontend
npm.cmd test -- src/components/chat/AssistantMarkdownRenderer.contract.test.ts
```

Expected: FAIL for missing style selectors.

- [ ] **Step 2: Add answer prose styles**

Style rules:
- body font: slightly larger than current if needed, consistent with PageChat UI
- `h1/h2/h3`: compact chat-scale headings, no giant document headings
- `p`: stable bottom margin
- `ul/ol/li`: readable indentation and nested spacing
- `blockquote`: subtle left rail and muted background
- `table`: full width inside horizontal scroll wrapper where possible; if no wrapper, style direct tables safely
- `th`: muted text, medium weight, no wrapping by default
- `td`: secondary text, stable padding, border separators
- `pre`: rounded block with border and horizontal scroll
- inline `code`: subtle chip, not too dark
- `img`: max width, rounded corners, contained layout
- `a`: PageChat accent underline on hover

Keep cards out of cards. The answer should feel like text, not a dashboard panel.

- [ ] **Step 3: Add table post-processing if needed**

If raw `marked` output cannot wrap tables, add a small helper in `answerMarkdown.ts`:

```ts
export function wrapMarkdownTables(html: string): string
```

It should wrap only top-level `<table>` occurrences into:

```html
<div class="answer-table-wrap">...</div>
```

Avoid brittle parsing beyond this small transformation.

- [ ] **Step 4: Run tests**

```bash
cd frontend
npm.cmd test -- src/components/chat/AssistantMarkdownRenderer.contract.test.ts src/utils/answerMarkdown.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/AssistantMarkdownRenderer.vue frontend/src/components/chat/assistant-markdown.css frontend/src/utils/answerMarkdown.ts frontend/src/utils/answerMarkdown.test.ts
git commit -m "style(frontend): polish assistant markdown rendering"
```

---

## Task 4: Add Code Block Enhancement Without Heavy Chart Runtime

**Files:**
- Create: `frontend/src/components/chat/AnswerCodeBlock.vue` if current Markdown strategy supports component injection later
- Or modify CSS-only code blocks in `AssistantMarkdownRenderer.vue`
- Test: `frontend/src/utils/answerMarkdown.test.ts`

- [ ] **Step 1: Keep this phase lightweight**

Do not add Mermaid/ECharts yet. First add:
- language label detection from `language-*`
- copy button only if feasible without fragile DOM surgery
- better code block CSS

If component injection is awkward with `marked + v-html`, skip copy button in this phase and document it for the streamdown phase.

- [ ] **Step 2: Add test for fenced code language preservation**

Run:

```bash
cd frontend
npm.cmd test -- src/utils/answerMarkdown.test.ts
```

Expected: PASS after implementation.

- [ ] **Step 3: Commit**

```bash
git add frontend/src
git commit -m "style(frontend): improve assistant code block presentation"
```

---

## Task 5: Evaluate Streamdown / Chart Block Upgrade

**Files:**
- Create: `docs/superpowers/plans/2026-06-29-pagechat-streaming-markdown-renderer-followup.zh.md` if needed

- [ ] **Step 1: Decide whether current marked renderer is enough**

Acceptance checks:
- streaming text no longer visually jumps
- partial Markdown does not produce ugly broken tables most of the time
- final tables/code/images are readable

- [ ] **Step 2: If not enough, write a separate plan**

Possible follow-up:
- introduce a Vue-compatible streaming Markdown renderer, or wrap a parser pipeline that handles incomplete Markdown better
- add Mermaid rendering
- add ECharts JSON block rendering
- add error boundaries / fallback for chart blocks

Do not mix this with the first renderer extraction unless the lightweight approach is clearly insufficient.

---

## Task 6: End-to-End Visual Verification

**Files:**
- No production files unless fixes are needed.

- [ ] **Step 1: Prepare sample answers**

Use one conversation or mocked stream containing:
- paragraph answer with inline citations
- long Markdown table
- nested bullet list
- code block
- blockquote
- image link
- web source link

- [ ] **Step 2: Verify in browser**

Run frontend dev server if needed:

```bash
cd frontend
npm.cmd run dev -- --host 127.0.0.1
```

Check:
- no text overlap
- table does not overflow chat column
- citation buttons still open preview
- web citations open browser links
- code block readable
- answer actions remain aligned

- [ ] **Step 3: Run final verification**

```bash
cd frontend
npm.cmd test -- src/utils/answerMarkdown.test.ts src/components/chat/AssistantMarkdownRenderer.contract.test.ts
npm.cmd run build
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src docs/superpowers/plans
git commit -m "feat(frontend): upgrade assistant answer rendering"
```

---

## Acceptance Criteria

- Assistant answers render through a dedicated renderer component, not direct Markdown helper functions in `ChatView.vue`.
- Tables are visually compact, aligned, scrollable when wide, and do not break chat layout.
- Code blocks are readable and visually consistent with PageChat.
- Inline document citations still open the right-side preview.
- Web citations remain link-like and open externally.
- The renderer is ready for a later streamdown/Mermaid/ECharts upgrade without another large `ChatView.vue` rewrite.
- Frontend targeted tests and production build pass.

