# PageChat Product Behavior Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the PageChat product behavior closure pass: production document-library behavior, persistent chat sessions, better streaming/thinking interactions, high-quality previews, clickable citations, and smarter agent tool use.

**Architecture:** Treat the backend database as the source of truth for conversations and document data, while keeping frontend localStorage as an immediate cache/draft layer only. Keep document browsing non-recursive by default, remove production demo fallbacks, bind answer citations to source anchors, and reuse the existing document preview components in a chat-side reference drawer. Improve agent behavior through planner intent routing, citation binding, and clearer tool trace metadata rather than adding a new retrieval stack.

**Tech Stack:** FastAPI, aiosqlite, existing PageChat Agent/ToolExecutor, Vue 3, Pinia, PDF.js, Vitest, pytest, Vite.

---

## Requirements Source

This plan implements the user-approved 2026-06-25 behavior review:

1. Slightly increase and unify UI typography.
2. Document root must show only current-folder contents, not recursive descendants.
3. Clear demo/display data and disable production demo preview/sample entries.
4. Preserve every conversation when navigating away/back; selected conversations open at their latest content; streaming follows output until the user scrolls away; the user can interrupt generation; finished generation lands at the start of the latest answer.
5. Improve file preview clarity.
6. Show thinking content while streaming, then collapse to `Thought for a moment` with optional expansion.
7. Make citations clickable and open a right-side preview drawer that jumps to the cited page/source anchor.
8. Improve agent prompt/tool-chain behavior so replies feel more deliberate, grounded, and reasonable.

## Current Branch And Worktree

Work in:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
git status --short --branch
```

Expected branch:

```text
## codex/pagechat-product-behavior-closure...origin/codex/pagechat-product-behavior-closure
```

Do not implement this plan in `C:\Users\TT_WT\.codex\worktrees\fc17\page_chat`; that worktree is the agent-tool branch.

## File Structure

### Frontend production document library

- Modify `frontend/src/utils/documentWorkbench.ts`
  - Change workbench folder browsing so root does not include subfolders by default.
- Modify `frontend/src/utils/documentWorkbench.test.ts`
  - Lock the non-recursive root behavior.
- Modify `frontend/src/views/DocumentView.vue`
  - Remove production use of `DEMO_LIBRARY_DOCUMENTS`, `DEMO_LIBRARY_FOLDERS`, sample preview, and automatic demo fallback.
  - Keep real document preview and future citation preview behavior intact.
- Modify `frontend/src/components/chat/ChatComposer.vue`
  - Remove production picker fallback to demo library documents/folders.
- Modify `frontend/src/ui/demoLibrary.ts`
  - Keep only for isolated design/demo routes if still needed; production views must not import it.
- Modify `frontend/src/ui/demoLibrary.test.ts`
  - Either narrow tests to demo-only helpers or remove production expectations.

### Backend document list scope

- Modify `backend/app/api/documents.py`
  - Set `include_subfolders` default to `False`.
- Modify `backend/app/services/document_service.py`
  - Preserve current-folder-only behavior for `folder_id=None` and `include_subfolders=False`.
- Create or modify `backend/tests/test_document_list_scope.py`
  - Cover root non-recursive listing and explicit recursive listing.

### Chat persistence, streaming, and interaction

- Modify `frontend/src/api/index.ts`
  - Extend `chatApi.stream` to accept `AbortSignal`.
  - Reuse existing `chatApi.getMessages` for backend-backed loading.
- Modify `frontend/src/stores/chat.ts`
  - Make backend conversation messages the source of truth when loading saved conversations.
  - Keep localStorage as a cache and draft store.
  - Add generation abort state and `stopGeneration()`.
  - Preserve document/folder contexts per session.
- Modify `frontend/src/stores/chat.test.ts`
  - Add failing tests for backend hydration, id migration, local cache fallback, and abort.
- Modify `frontend/src/components/layout/AppShell.vue`
  - Await async conversation loading before routing display settles.
- Modify `frontend/src/views/ChatView.vue`
  - Add sticky/follow scroll state, stop control, thinking block, citation click handling, and right-side reference drawer.
- Create `frontend/src/components/chat/ThinkingBlock.vue`
  - Encapsulate streaming/finished thinking UI.
- Create `frontend/src/components/chat/CitationPreviewDrawer.vue`
  - Reuse `PdfReferenceViewer` and `UniversalPreview`.
- Create `frontend/src/utils/chatScroll.ts`
  - Small pure helpers for near-bottom detection and answer-start target calculation.
- Create `frontend/src/utils/citations.ts`
  - Parse `[[document.pdf p.3]]` markers and bind them to backend/client evidence.
- Create tests:
  - `frontend/src/utils/chatScroll.test.ts`
  - `frontend/src/utils/citations.test.ts`

### Preview clarity

- Modify `frontend/src/components/PdfReferenceViewer.vue`
  - Render canvas at device-pixel-ratio resolution while preserving CSS size.
  - Expose `scrollToPage` for drawer consumers.
- Modify `frontend/src/components/PdfViewer.vue` if it uses the same low-DPI pattern.
- Create `frontend/src/utils/pdfRenderScale.ts`
  - Pure helper for CSS size and backing-store scale.
- Create `frontend/src/utils/pdfRenderScale.test.ts`
  - Lock retina/high-DPI math.

### Backend citation bindings and smarter agent flow

- Create `backend/app/services/document_keyword_locator.py`
  - Deterministic in-document keyword/phrase locator used by `search_within_document`.
  - It must not call BM25, rerank, embeddings, query expansion, or broad document search.
  - It may use OCR/page text for matching, but visual/OCR pages must not expose OCR text to the model.
- Modify `backend/app/services/agent_service.py`
  - Add citation bindings to `done` payload.
  - Avoid duplicate planner/tool calls where initial evidence already satisfies a locating request.
  - Add optional citation repair pass when tool-backed answers contain no document citation.
- Modify `backend/app/services/retrieval_planner.py`
  - Add query intent classification.
  - Prefer `search_within_document` for selected-document locating/keyword questions.
  - Prefer `aggregate_tables` for table aggregation after browsing scoped table docs.
- Modify `backend/app/prompts/__init__.py`
  - Tighten tool decision framework and answer style rules.
- Modify `backend/app/services/tool_executor.py`
  - Route `search_within_document` through the deterministic keyword locator.
  - Ensure tool results expose concise labels, source anchors, visual flags, and next-step guidance for client traces.
- Create `backend/app/services/citation_binding_service.py`
  - Parse final answer citation markers and bind them to document IDs/source anchors from tool evidence.
- Create tests:
  - `backend/tests/test_document_keyword_locator.py`
  - `backend/tests/test_agent_citation_bindings.py`
  - Update `backend/tests/test_retrieval_planner.py`
  - Update `backend/tests/test_agent_retrieval_planner_integration.py`
  - Update `backend/tests/test_tools_prompt_catalog.py`
  - Update `backend/tests/test_agent_navigation_tools_contract.py`

## Acceptance Criteria

- Empty libraries show empty production states, not sample documents/folders.
- Root library lists only root-level folders and root-level documents.
- Explicit recursive search/browse still works.
- Chat history persists after navigating to Documents and back, after selecting a conversation, and after refresh when backend conversation data exists.
- New chats and selected document/folder contexts remain isolated per conversation/draft.
- User can stop a streaming response; the UI stops loading and the backend stream is cancelled.
- Streaming follows new content until the user scrolls away; it does not yank the viewport while the user is reading older content.
- Thinking text is visible during generation and collapsible after completion.
- Citations in answer text are clickable inline elements.
- Clicking a PDF citation opens a right-side drawer and jumps to the cited page.
- Clicking a non-PDF citation opens the same drawer and jumps/highlights the line, row, paragraph, or slide anchor when supported.
- PDF preview is visibly sharper on high-DPI screens.
- Agent tool choice is more intentional: locating questions use `search_within_document` when a document is selected; `search_within_document` is deterministic keyword/phrase matching, not BM25/rerank; document QA still fetches source pages; visual/OCR pages can be matched by OCR text but only return image/page references to the model; web search stays gated by user/settings.
- Backend tests, frontend tests, and frontend build pass.

---

### Task 0: Baseline Guardrails

**Files:**
- Read: `docs/pagechat_integration_development_guide.md`
- Read: `docs/superpowers/plans/2026-06-25-pagechat-anysearch-api-web-search-plan.zh.md`
- Read: `docs/superpowers/plans/2026-06-25-pagechat-screenshot-upload-multimodal-chat-plan.zh.md`
- No code changes.

- [ ] **Step 1: Verify branch and clean status**

Run:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
git status --short --branch
```

Expected: branch is `codex/pagechat-product-behavior-closure`. If unrelated files are dirty, inspect before editing and do not overwrite user changes.

- [ ] **Step 2: Run focused baseline suites**

Run:

```powershell
py -m pytest backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_retrieval_planner.py backend/tests/test_agent_retrieval_planner_integration.py backend/tests/test_tools_prompt_catalog.py -q
cd frontend
npm.cmd test -- --run frontend/src/stores/chat.test.ts frontend/src/utils/documentWorkbench.test.ts frontend/src/ui/pagechatContracts.test.ts
```

Expected: current known baseline passes. If a failure appears, record it in the task notes before continuing.

- [ ] **Step 3: Commit not required**

This task is a baseline checkpoint only.

---

### Task 1: Production Document Library Data Correctness

**Files:**
- Modify: `backend/app/api/documents.py`
- Modify: `frontend/src/utils/documentWorkbench.ts`
- Modify: `frontend/src/views/DocumentView.vue`
- Modify: `frontend/src/components/chat/ChatComposer.vue`
- Modify: `frontend/src/ui/demoLibrary.ts`
- Test: `backend/tests/test_document_list_scope.py`
- Test: `frontend/src/utils/documentWorkbench.test.ts`
- Test: `frontend/src/ui/demoLibrary.test.ts`

- [ ] **Step 1: Write failing backend root-scope test**

Create `backend/tests/test_document_list_scope.py` if it does not exist. Use an in-memory DB and `DocumentService.list_documents()` directly to avoid FastAPI auth setup.

Required behavior:

```python
async def test_root_document_list_is_not_recursive_by_default(tmp_path):
    # Insert one root document and one child-folder document for the same user.
    # Call list_documents(folder_id=None, include_subfolders=False, user_id="user-a").
    # Assert only the root document is returned.
```

Also add:

```python
async def test_root_document_list_can_be_recursive_when_explicit(tmp_path):
    # Same fixture.
    # Call list_documents(folder_id=None, include_subfolders=True, user_id="user-a").
    # Assert both root and child documents are returned.
```

- [ ] **Step 2: Write failing frontend workbench test**

In `frontend/src/utils/documentWorkbench.test.ts`, change/add:

```ts
it('does not include subfolders for root workbench browsing by default', () => {
  expect(workbenchIncludeSubfolders(null)).toBe(false)
  expect(workbenchIncludeSubfolders('folder-a')).toBe(false)
})
```

- [ ] **Step 3: Write failing production-demo test**

In `frontend/src/ui/demoLibrary.test.ts`, add a production-mode guard:

```ts
it('does not auto-populate production document views with demo library data', () => {
  expect(shouldShowDemoLibrary({
    loading: false,
    folderCount: 0,
    documentCount: 0,
    searchQuery: '',
  })).toBe(false)
})
```

If `demoLibrary.ts` remains needed by `DesignDemoView.vue`, keep demo data exportable but make `shouldShowDemoLibrary()` return `false` for production callers.

- [ ] **Step 4: Run tests and verify they fail**

Run:

```powershell
py -m pytest backend/tests/test_document_list_scope.py -q
cd frontend
npm.cmd test -- --run frontend/src/utils/documentWorkbench.test.ts frontend/src/ui/demoLibrary.test.ts
```

Expected: tests fail on root recursive/default demo behavior.

- [ ] **Step 5: Implement root non-recursive defaults**

In `backend/app/api/documents.py`, change:

```python
include_subfolders: bool = Query(True, description="是否包含子文件夹")
```

to:

```python
include_subfolders: bool = Query(False, description="是否包含子文件夹")
```

In `frontend/src/utils/documentWorkbench.ts`, make `workbenchIncludeSubfolders()` always return `false` for folder browsing:

```ts
export function workbenchIncludeSubfolders(_folderId: string | null): boolean {
  return false
}
```

If search later needs recursive behavior, pass a separate explicit flag from search-specific code, not from the default workbench browser.

- [ ] **Step 6: Remove production demo fallback**

In `frontend/src/views/DocumentView.vue`:

- Remove imports from `@/ui/demoLibrary` except any demo-only route that remains outside production.
- Replace `showingDemoLibrary`, `displayDocuments`, `currentFolders`, and sample preview branches with real store data only.
- Delete sample-preview table rendering from the production document preview modal.
- Empty state should show `No documents in this folder` or localized product copy, not sample content.

In `frontend/src/components/chat/ChatComposer.vue`:

- Remove `useDemoPickerData`.
- Use `documentStore.documents` and `folderStore.folders` only.
- If no files exist, show an empty picker state.

- [ ] **Step 7: Run focused tests**

Run:

```powershell
py -m pytest backend/tests/test_document_list_scope.py backend/tests/test_folder_search_scope.py -q
cd frontend
npm.cmd test -- --run frontend/src/utils/documentWorkbench.test.ts frontend/src/ui/demoLibrary.test.ts
npm.cmd run build
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/app/api/documents.py backend/tests/test_document_list_scope.py frontend/src/utils/documentWorkbench.ts frontend/src/utils/documentWorkbench.test.ts frontend/src/views/DocumentView.vue frontend/src/components/chat/ChatComposer.vue frontend/src/ui/demoLibrary.ts frontend/src/ui/demoLibrary.test.ts
git commit -m "fix(documents): use production library data only"
```

---

### Task 2: Backend-Backed Chat Session Persistence

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/components/layout/AppShell.vue`
- Test: `frontend/src/stores/chat.test.ts`

- [ ] **Step 1: Write failing tests for backend hydration**

In `frontend/src/stores/chat.test.ts`, mock `chatApi.getMessages`.

Add a test for loading a conversation whose local session cache is missing:

```ts
it('hydrates a backend conversation when local session data is missing', async () => {
  localStorage.setItem('pagechat_chat_sessions', JSON.stringify([{
    id: 'backend-a',
    title: 'Backend chat',
    firstMessage: 'original',
    timestamp: 1,
    messageCount: 2,
  }]))
  vi.mocked(chatApi.getMessages).mockResolvedValueOnce({
    data: [
      { id: 'u1', role: 'user', content: 'question', thinking: '', agent_steps: [], attachments: [], created_at: '2026-06-25T00:00:00Z' },
      { id: 'a1', role: 'assistant', content: 'answer', thinking: 'thinking', agent_steps: [], attachments: [], created_at: '2026-06-25T00:00:01Z' },
    ],
  } as any)

  const store = useChatStore()
  store.loadConversationsFromStorage({ restoreLastActive: false, restoreDraft: false })

  await expect(store.loadConversation('backend-a')).resolves.toBe(true)
  expect(store.messages.map((message) => message.content)).toEqual(['question', 'answer'])
  expect(store.conversationId).toBe('backend-a')
})
```

Add a test that backend-id migration keeps full messages under the backend ID:

```ts
it('saves migrated backend conversations under the backend id without dropping messages', async () => {
  const store = useChatStore()
  store.currentSessionId = 'session-temp'
  store.messages.push(message('u1', 'user', 'question'), message('a1', 'assistant', 'answer'))
  store.saveCurrentSession()

  store.handleEnvelope({ event: 'conversation', data: { conversation_id: 'backend-a' } })

  const restored = useChatStore()
  restored.loadConversationsFromStorage({ restoreLastActive: true, restoreDraft: false })
  expect(restored.currentSessionId).toBe('backend-a')
  expect(restored.messages.map((item) => item.content)).toEqual(['question', 'answer'])
})
```

- [ ] **Step 2: Run tests and verify they fail**

```powershell
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd test -- --run frontend/src/stores/chat.test.ts
```

Expected: async load/hydration behavior is not implemented or not awaited.

- [ ] **Step 3: Make conversation loading async**

In `frontend/src/stores/chat.ts`:

- Change `loadConversation(sessionId: string)` to `async function loadConversation(sessionId: string): Promise<boolean>`.
- First try `loadStoredSession(sessionId)`.
- If missing/incomplete and `sessionId` looks like a backend conversation id, call `chatApi.getMessages(sessionId)`.
- Normalize backend messages into the `Message` interface:

```ts
function normalizeBackendMessage(raw: any): Message {
  return {
    id: String(raw.id),
    role: raw.role === 'assistant' ? 'assistant' : 'user',
    content: String(raw.content || ''),
    thinking: String(raw.thinking || raw.thinking_content || ''),
    toolSteps: Array.isArray(raw.agent_steps) ? raw.agent_steps : [],
    isLoading: raw.status === 'streaming',
    timestamp: raw.created_at ? new Date(raw.created_at).getTime() : Date.now(),
    attachments: Array.isArray(raw.attachments) ? raw.attachments : [],
  }
}
```

- Remove or restrict the current fallback that synthesizes a conversation from `conversation.firstMessage`; use it only if backend hydration fails and there is no other data.
- Always call `saveCurrentSession()` after successful backend hydration.

- [ ] **Step 4: Preserve cache during backend-id migration**

In `syncBackendConversationId()`:

- Save active `messages.value` under `backendConversationId`.
- Delete the old temp session only after the backend session entry is written.
- Ensure `conversations.value` contains exactly one row for the backend id.
- Ensure `lastActiveSessionId` is set to the backend id.

- [ ] **Step 5: Await conversation loading in shell**

In `frontend/src/components/layout/AppShell.vue`:

```ts
async function openConversation(conversationId: string) {
  openChatMenuId.value = null
  await chatStore.loadConversation(conversationId)
  router.push('/')
}
```

If TypeScript complains about event handler promise returns, wrap with `void openConversation(...)` in the template or define a non-async wrapper.

- [ ] **Step 6: Run focused tests**

```powershell
cd frontend
npm.cmd test -- --run frontend/src/stores/chat.test.ts
npm.cmd run build
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/api/index.ts frontend/src/stores/chat.ts frontend/src/stores/chat.test.ts frontend/src/components/layout/AppShell.vue
git commit -m "fix(chat): hydrate conversations from backend messages"
```

---

### Task 3: Streaming Follow, Stop, And Viewport Behavior

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/utils/chatScroll.ts`
- Test: `frontend/src/stores/chat.test.ts`
- Test: `frontend/src/utils/chatScroll.test.ts`
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat_stream_cancellation.py`

- [ ] **Step 1: Write pure scroll helper tests**

Create `frontend/src/utils/chatScroll.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { isNearBottom, shouldFollowStream } from './chatScroll'

describe('chat scroll helpers', () => {
  it('treats the viewport as near bottom within a small threshold', () => {
    expect(isNearBottom({ scrollTop: 900, clientHeight: 100, scrollHeight: 1008 }, 16)).toBe(true)
    expect(isNearBottom({ scrollTop: 850, clientHeight: 100, scrollHeight: 1008 }, 16)).toBe(false)
  })

  it('does not force-follow when the user has intentionally scrolled away', () => {
    expect(shouldFollowStream({ isGenerating: true, userPinnedAway: true, nearBottom: false })).toBe(false)
    expect(shouldFollowStream({ isGenerating: true, userPinnedAway: false, nearBottom: true })).toBe(true)
  })
})
```

- [ ] **Step 2: Write frontend abort test**

In `frontend/src/stores/chat.test.ts`, add:

```ts
it('aborts an in-flight stream when stopGeneration is called', async () => {
  let signal: AbortSignal | undefined
  vi.mocked(chatApi.stream).mockImplementationOnce((payload: any, options?: { signal?: AbortSignal }) => {
    signal = options?.signal
    return Promise.resolve(new Response(new ReadableStream()))
  })
  const store = useChatStore()
  const pending = store.sendMessage('stop me')
  store.stopGeneration()
  await pending
  expect(signal?.aborted).toBe(true)
  expect(store.isLoading).toBe(false)
})
```

- [ ] **Step 3: Write backend cancellation test**

Create `backend/tests/test_chat_stream_cancellation.py` with a focused unit test around the generator helper if one is extracted. If testing the route directly is too heavy, first extract a small helper from `backend/app/api/chat.py`:

```python
def cancel_task_if_running(task):
    if not task.done():
        task.cancel()
        return True
    return False
```

Then test:

```python
def test_cancel_task_if_running_cancels_active_task(event_loop):
    task = event_loop.create_task(asyncio.sleep(60))
    assert cancel_task_if_running(task) is True
    assert task.cancelled() or task.cancelling()
```

- [ ] **Step 4: Run tests and verify failures**

```powershell
py -m pytest backend/tests/test_chat_stream_cancellation.py -q
cd frontend
npm.cmd test -- --run frontend/src/utils/chatScroll.test.ts frontend/src/stores/chat.test.ts
```

- [ ] **Step 5: Implement frontend abort plumbing**

In `frontend/src/api/index.ts`, change `chatApi.stream` to:

```ts
stream: (data: ChatStreamPayload, options?: { signal?: AbortSignal }) => {
  // existing headers
  return fetch('/api/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
    signal: options?.signal,
  })
}
```

In `frontend/src/stores/chat.ts`:

- Add `const activeController = ref<AbortController | null>(null)`.
- In `sendMessage`, create a controller and pass `signal`.
- Add:

```ts
function stopGeneration() {
  activeController.value?.abort()
  activeController.value = null
  isLoading.value = false
  updateLastMessage({ isLoading: false })
  saveCurrentSession()
}
```

- In `catch`, if `error.name === 'AbortError'`, do not overwrite partial assistant content with an error message.

- [ ] **Step 6: Implement scroll-follow behavior**

Create `frontend/src/utils/chatScroll.ts`:

```ts
export interface ScrollMetrics {
  scrollTop: number
  clientHeight: number
  scrollHeight: number
}

export function isNearBottom(metrics: ScrollMetrics, threshold = 32): boolean {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold
}

export function shouldFollowStream(input: {
  isGenerating: boolean
  userPinnedAway: boolean
  nearBottom: boolean
}): boolean {
  if (!input.isGenerating) return input.nearBottom
  return !input.userPinnedAway && input.nearBottom
}
```

In `frontend/src/views/ChatView.vue`:

- Track `userPinnedAway`.
- On scroll, set `userPinnedAway = !isNearBottom(...)` while generating.
- Replace unconditional `watch(messageSignature, scrollToBottom)` with conditional follow.
- Before sending, record the new assistant message element id after it appears.
- On generation completion, scroll to the start of the newest assistant answer, not necessarily the absolute bottom.
- Add a stop button near the composer or streaming assistant block, calling `chatStore.stopGeneration()`.

- [ ] **Step 7: Cancel backend producer on disconnected stream**

In `backend/app/api/chat.py`:

- Add a helper to cancel active producer tasks.
- In `event_generator.finally`, set inactive and cancel the producer task if it is still running.
- Let `asyncio.CancelledError` propagate cleanly.

- [ ] **Step 8: Run focused tests and build**

```powershell
py -m pytest backend/tests/test_chat_stream_cancellation.py -q
cd frontend
npm.cmd test -- --run frontend/src/utils/chatScroll.test.ts frontend/src/stores/chat.test.ts
npm.cmd run build
```

- [ ] **Step 9: Commit**

```powershell
git add backend/app/api/chat.py backend/tests/test_chat_stream_cancellation.py frontend/src/api/index.ts frontend/src/stores/chat.ts frontend/src/stores/chat.test.ts frontend/src/views/ChatView.vue frontend/src/utils/chatScroll.ts frontend/src/utils/chatScroll.test.ts
git commit -m "feat(chat): support interruptible streaming scroll"
```

---

### Task 4: Thinking UI And Typography Scale

**Files:**
- Modify: `frontend/src/style.css`
- Modify: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/components/chat/ThinkingBlock.vue`
- Test: `frontend/src/components/chat/ThinkingBlock.test.ts`

- [ ] **Step 1: Write ThinkingBlock tests**

Create `frontend/src/components/chat/ThinkingBlock.test.ts` using Vue Test Utils if already installed; otherwise keep the behavior in a pure helper test. Required behavior:

- Streaming state shows the thinking content.
- Finished state defaults collapsed and displays `Thought for a moment`.
- Clicking expands and shows thinking content.

Example:

```ts
it('collapses completed thinking behind a summary label', async () => {
  const wrapper = mount(ThinkingBlock, {
    props: { content: 'read structure, then fetch page 3', streaming: false },
  })
  expect(wrapper.text()).toContain('Thought for a moment')
  expect(wrapper.text()).not.toContain('read structure')
  await wrapper.get('button').trigger('click')
  expect(wrapper.text()).toContain('read structure')
})
```

- [ ] **Step 2: Run test and verify failure**

```powershell
cd frontend
npm.cmd test -- --run frontend/src/components/chat/ThinkingBlock.test.ts
```

- [ ] **Step 3: Implement ThinkingBlock**

Create `frontend/src/components/chat/ThinkingBlock.vue`:

- Props:
  - `content: string`
  - `streaming: boolean`
- During streaming:
  - Show compact label `Thinking` and visible content body.
- After streaming:
  - Default collapsed.
  - Button text `Thought for a moment`.
  - Toggle expanded body.
- Keep typography consistent with assistant text, not tiny meta text.

- [ ] **Step 4: Replace static thinking line**

In `frontend/src/views/ChatView.vue`, replace:

```vue
<div v-if="message.thinking" class="thinking-line">
  <Sparkles />
  <span>Thought for a moment</span>
</div>
```

with:

```vue
<ThinkingBlock
  v-if="message.thinking"
  :content="message.thinking"
  :streaming="message.isLoading && !message.content"
/>
```

Adjust the streaming condition if content and thinking can overlap for the selected model.

- [ ] **Step 5: Increase unified typography**

In `frontend/src/style.css`, add root typography variables:

```css
--kc-font-xs: 12px;
--kc-font-sm: 13px;
--kc-font-body: 14.5px;
--kc-font-ui: 14px;
--kc-font-title: 16px;
--kc-line-body: 23px;
--kc-line-ui: 20px;
```

Then update key components:

- `frontend/src/views/ChatView.vue`
  - assistant content: `14.5px / 23px`
  - user bubble: `14px / 21px`
  - tool trace: not below `12.5px`
- `frontend/src/components/layout/AppShell.vue`
  - chat history row: at least `13px`
- `frontend/src/views/DocumentView.vue`
  - file row title: `13.5px` or `14px`
  - metadata: `12.5px`
- `frontend/src/components/settings/SettingsModal.vue`
  - body text: `13.5px` or `14px`

Do not scale fonts with viewport width.

- [ ] **Step 6: Run tests and build**

```powershell
cd frontend
npm.cmd test -- --run frontend/src/components/chat/ThinkingBlock.test.ts
npm.cmd run build
```

- [ ] **Step 7: Manual visual check**

Start frontend if needed:

```powershell
cd frontend
npm.cmd run dev
```

Check:

- Chat page no longer feels tiny.
- Document list still fits enough rows.
- Settings modal stays balanced and not crowded.

- [ ] **Step 8: Commit**

```powershell
git add frontend/src/style.css frontend/src/views/ChatView.vue frontend/src/components/chat/ThinkingBlock.vue frontend/src/components/chat/ThinkingBlock.test.ts frontend/src/components/layout/AppShell.vue frontend/src/views/DocumentView.vue frontend/src/components/settings/SettingsModal.vue
git commit -m "feat(chat): show thinking details with unified typography"
```

---

### Task 5: Clickable Citations And Reference Preview Drawer

**Files:**
- Create: `backend/app/services/citation_binding_service.py`
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_agent_citation_bindings.py`
- Modify: `frontend/src/types/stream.ts`
- Modify: `frontend/src/stores/chat.ts`
- Create: `frontend/src/utils/citations.ts`
- Test: `frontend/src/utils/citations.test.ts`
- Create: `frontend/src/components/chat/CitationPreviewDrawer.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/components/PdfReferenceViewer.vue`
- Modify: `frontend/src/components/preview/UniversalPreview.vue`

- [ ] **Step 1: Write backend citation binding tests**

Create `backend/tests/test_agent_citation_bindings.py`:

```python
from app.services.citation_binding_service import bind_answer_citations


def test_bind_answer_citations_uses_exact_doc_name_and_page_anchor():
    answer = "收入增长来自华东区域 [[sales.pdf p.3]]。"
    evidence = [
        {
            "tool_name": "get_page_content",
            "result": {
                "data": {
                    "doc_id": "doc-sales",
                    "doc_name": "sales.pdf",
                    "pages": [
                        {
                            "page": 3,
                            "display_label": "sales.pdf p.3",
                            "source_anchor": {"format": "pdf", "unit_type": "page", "start_page": 3, "end_page": 3},
                        }
                    ],
                }
            },
        }
    ]
    bindings = bind_answer_citations(answer, evidence)
    assert bindings[0]["marker"] == "[[sales.pdf p.3]]"
    assert bindings[0]["doc_id"] == "doc-sales"
    assert bindings[0]["source_anchor"]["start_page"] == 3
```

Add a non-PDF anchor case for `xlsx rows`, `docx paragraph`, or `pptx slide` if existing tool results expose those anchors.

- [ ] **Step 2: Write frontend citation parser tests**

Create `frontend/src/utils/citations.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { parseCitationMarkers, bindCitationMarkers } from './citations'

describe('citations', () => {
  it('parses inline document page markers', () => {
    expect(parseCitationMarkers('增长来自华东 [[sales.pdf p.3]]。')).toEqual([
      expect.objectContaining({ marker: '[[sales.pdf p.3]]', documentName: 'sales.pdf', page: 3 }),
    ])
  })

  it('binds markers to backend citation bindings first', () => {
    const result = bindCitationMarkers('A [[sales.pdf p.3]]', [{
      marker: '[[sales.pdf p.3]]',
      doc_id: 'doc-sales',
      source_anchor: { format: 'pdf', unit_type: 'page', start_page: 3 },
    } as any], [])
    expect(result[0].docId).toBe('doc-sales')
  })
})
```

- [ ] **Step 3: Run tests and verify failures**

```powershell
py -m pytest backend/tests/test_agent_citation_bindings.py -q
cd frontend
npm.cmd test -- --run frontend/src/utils/citations.test.ts
```

- [ ] **Step 4: Implement backend citation binding service**

Create `backend/app/services/citation_binding_service.py` with:

- `parse_answer_citations(answer: str) -> list[dict]`
  - Match `[[... p.N]]`.
  - Preserve exact marker text.
- `flatten_tool_evidence(tool_results: list[dict]) -> list[dict]`
  - Extract `doc_id`, `doc_name`, `display_label`, and `source_anchor` from nested tool results.
- `bind_answer_citations(answer: str, tool_results: list[dict]) -> list[dict]`
  - Prefer exact marker/doc-name/page matches.
  - Fall back to display label and source anchor page.
  - Return compact frontend-safe objects:

```python
{
    "marker": "[[sales.pdf p.3]]",
    "doc_id": "doc-sales",
    "document_name": "sales.pdf",
    "source_anchor": {"format": "pdf", "unit_type": "page", "start_page": 3, "end_page": 3},
    "display_label": "sales.pdf p.3",
}
```

- [ ] **Step 5: Add citation bindings to done event**

In `backend/app/services/agent_service.py`, before yielding `done`, call:

```python
from app.services.citation_binding_service import bind_answer_citations

citation_bindings = bind_answer_citations(assistant_content, tool_results_for_answer)
```

Include in the `done` data:

```python
"citation_bindings": citation_bindings,
```

Do not include raw page text, raw web content, or base64 in citation bindings.

- [ ] **Step 6: Add frontend stream types and store metadata**

In `frontend/src/types/stream.ts`, add `citation_bindings` to `DoneData`.

In `frontend/src/stores/chat.ts`:

- Add `citationBindings?: CitationBinding[]` to `Message`.
- On `done`, store `doneData.citation_bindings || []`.
- Keep `evidenceItems` as fallback.

- [ ] **Step 7: Implement frontend citation utilities**

Create `frontend/src/utils/citations.ts`:

- Parse markers.
- Bind to backend `citationBindings`.
- Fall back to `message.evidenceItems`.
- Expose display fields:

```ts
export interface BoundCitation {
  marker: string
  documentName: string
  docId?: string
  page?: number
  sourceAnchor?: SourceAnchor | null
  displayLabel?: string
}
```

- [ ] **Step 8: Render citations as clickable inline controls**

In `frontend/src/views/ChatView.vue`:

- Replace raw `v-html="renderMarkdown(message.content)"` with an approach that can attach click handlers.
- Minimum acceptable implementation:
  - Keep `marked.parse`.
  - Replace citation marker text with `<button class="citation-chip" data-citation-index="...">...</button>`.
  - Use event delegation on the assistant content container to call `openCitationPreview(message, index)`.
- Preferred implementation:
  - Create a small `AssistantMarkdown.vue` component that receives `content` and bound citations, renders sanitized markdown, and emits `citation-click`.

Avoid rendering arbitrary untrusted HTML if changing the markdown pipeline is feasible in this task.

- [ ] **Step 9: Implement reference drawer**

Create `frontend/src/components/chat/CitationPreviewDrawer.vue`:

- Props:
  - `open: boolean`
  - `docId: string`
  - `docName: string`
  - `fileType: string`
  - `sourceAnchor?: SourceAnchor | null`
  - `initialPage?: number`
- For PDF:
  - Use `PdfReferenceViewer`.
  - Pass `initialPage`.
- For non-PDF:
  - Use `UniversalPreview`.
  - Pass `initialAnchor`.
- Layout:
  - Right-side drawer over chat page.
  - No separate right information panel.
  - Header shows document name and citation label.

In `ChatView.vue`, open this drawer when a bound citation is clicked. Resolve missing file type/name by looking in loaded documents first; if not available, use `documentApi.get(docId)`.

- [ ] **Step 10: Expose PDF jump support**

In `frontend/src/components/PdfReferenceViewer.vue`, expose:

```ts
defineExpose({ scrollToPage })
```

Ensure `initialPage` watcher works after PDF loads.

- [ ] **Step 11: Run focused tests and build**

```powershell
py -m pytest backend/tests/test_agent_citation_bindings.py backend/tests/test_agent_service_sanitize.py -q
cd frontend
npm.cmd test -- --run frontend/src/utils/citations.test.ts frontend/src/stores/chat.test.ts
npm.cmd run build
```

- [ ] **Step 12: Commit**

```powershell
git add backend/app/services/citation_binding_service.py backend/app/services/agent_service.py backend/tests/test_agent_citation_bindings.py frontend/src/types/stream.ts frontend/src/stores/chat.ts frontend/src/utils/citations.ts frontend/src/utils/citations.test.ts frontend/src/components/chat/CitationPreviewDrawer.vue frontend/src/views/ChatView.vue frontend/src/components/PdfReferenceViewer.vue frontend/src/components/preview/UniversalPreview.vue
git commit -m "feat(chat): preview document citations inline"
```

---

### Task 6: High-DPI Document Preview Rendering

**Files:**
- Create: `frontend/src/utils/pdfRenderScale.ts`
- Test: `frontend/src/utils/pdfRenderScale.test.ts`
- Modify: `frontend/src/components/PdfReferenceViewer.vue`
- Modify: `frontend/src/components/PdfViewer.vue`
- Optional backend check: `backend/app/core/llm.py`

- [ ] **Step 1: Write render-scale tests**

Create `frontend/src/utils/pdfRenderScale.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { buildPdfCanvasScale } from './pdfRenderScale'

describe('pdf render scale', () => {
  it('keeps css dimensions while increasing backing pixels for high DPI', () => {
    const result = buildPdfCanvasScale({
      viewportWidth: 600,
      viewportHeight: 800,
      devicePixelRatio: 2,
    })
    expect(result.canvasWidth).toBe(1200)
    expect(result.canvasHeight).toBe(1600)
    expect(result.cssWidth).toBe(600)
    expect(result.cssHeight).toBe(800)
  })
})
```

- [ ] **Step 2: Run test and verify failure**

```powershell
cd frontend
npm.cmd test -- --run frontend/src/utils/pdfRenderScale.test.ts
```

- [ ] **Step 3: Implement helper**

Create `frontend/src/utils/pdfRenderScale.ts`:

```ts
export function buildPdfCanvasScale(input: {
  viewportWidth: number
  viewportHeight: number
  devicePixelRatio?: number
}) {
  const ratio = Math.max(1, Math.min(input.devicePixelRatio || 1, 3))
  return {
    ratio,
    canvasWidth: Math.floor(input.viewportWidth * ratio),
    canvasHeight: Math.floor(input.viewportHeight * ratio),
    cssWidth: input.viewportWidth,
    cssHeight: input.viewportHeight,
  }
}
```

- [ ] **Step 4: Apply high-DPI rendering to PDF components**

In `frontend/src/components/PdfReferenceViewer.vue` and `frontend/src/components/PdfViewer.vue`:

- Keep `viewport = page.getViewport({ scale: finalScale })`.
- Set canvas backing dimensions using helper.
- Set CSS dimensions to viewport dimensions.
- Render using a transform:

```ts
const scale = buildPdfCanvasScale({
  viewportWidth: viewport.width,
  viewportHeight: viewport.height,
  devicePixelRatio: window.devicePixelRatio,
})

canvas.width = scale.canvasWidth
canvas.height = scale.canvasHeight
canvas.style.width = `${scale.cssWidth}px`
canvas.style.height = `${scale.cssHeight}px`

await page.render({
  canvasContext: ctx,
  viewport,
  transform: scale.ratio === 1 ? undefined : [scale.ratio, 0, 0, scale.ratio, 0, 0],
  canvas,
} as any).promise
```

- [ ] **Step 5: Do not change model image DPI unless needed**

`backend/app/core/llm.py` uses 150 DPI for model page images. This task is about user-facing preview clarity. Do not raise backend DPI unless visual-agent accuracy tests show a problem, because it increases token and bandwidth cost.

- [ ] **Step 6: Run tests and build**

```powershell
cd frontend
npm.cmd test -- --run frontend/src/utils/pdfRenderScale.test.ts
npm.cmd run build
```

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/utils/pdfRenderScale.ts frontend/src/utils/pdfRenderScale.test.ts frontend/src/components/PdfReferenceViewer.vue frontend/src/components/PdfViewer.vue
git commit -m "fix(preview): render pdf pages at high dpi"
```

---

### Task 7: Keyword-Based In-Document Locator And Smarter Agent Flow

**Files:**
- Create: `backend/app/services/document_keyword_locator.py`
- Modify: `backend/app/services/retrieval_planner.py`
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/prompts/__init__.py`
- Modify: `backend/app/services/tool_executor.py`
- Modify: `frontend/src/ui/pagechatContracts.ts`
- Test: `backend/tests/test_document_keyword_locator.py`
- Test: `backend/tests/test_retrieval_planner.py`
- Test: `backend/tests/test_agent_retrieval_planner_integration.py`
- Test: `backend/tests/test_tools_prompt_catalog.py`
- Test: `backend/tests/test_agent_navigation_tools_contract.py`
- Test: `frontend/src/ui/pagechatContracts.test.ts`

- [ ] **Step 1: Write keyword locator unit tests**

Create `backend/tests/test_document_keyword_locator.py`.

Required cases:

```python
from app.services.document_keyword_locator import locate_keywords_in_index


def test_keyword_locator_prefers_exact_phrase_over_loose_terms():
    index = {
        "pages": [
            {"page": 1, "text": "华东收入增长来自渠道调整"},
            {"page": 2, "text": "收入稳定增长，但未提华东"},
        ],
        "structure": [],
    }
    result = locate_keywords_in_index(
        index_data=index,
        query="在哪一页提到了华东收入增长？",
        doc_id="doc-a",
        doc_name="sales.pdf",
    )
    assert result["matches"][0]["page"] == 1
    assert result["matches"][0]["matched_terms"]
    assert result["matches"][0]["match_type"] in {"exact_phrase", "keyword"}
    assert "华东收入增长" in result["matches"][0]["snippet"]
```

Add an OCR/visual page test:

```python
def test_keyword_locator_uses_ocr_text_for_matching_but_omits_visual_snippet():
    index = {
        "pages": [
            {
                "page": 3,
                "text": "OCR text: 华东收入增长 20%",
                "images": [{"image_path": "page://doc-a/3", "page": 3}],
                "ocr_used": True,
            }
        ],
        "page_text_map_ocr_pages": [3],
        "structure": [],
    }
    result = locate_keywords_in_index(
        index_data=index,
        query="华东收入增长",
        doc_id="doc-a",
        doc_name="scan.pdf",
    )
    match = result["matches"][0]
    assert match["page"] == 3
    assert match["match_type"] == "ocr_keyword"
    assert match["visual_evidence_required"] is True
    assert match["text_omitted_reason"] == "visual_evidence_required"
    assert "snippet" not in match
    assert match["image_refs"][0]["image_path"] == "page://doc-a/3"
    assert match["next_tool"] == "get_page_image"
```

Add a no-match test:

```python
def test_keyword_locator_returns_empty_matches_without_semantic_fallback():
    result = locate_keywords_in_index(
        index_data={"pages": [{"page": 1, "text": "完全无关"}], "structure": []},
        query="华东收入增长",
        doc_id="doc-a",
        doc_name="sales.pdf",
    )
    assert result["matches"] == []
    assert result["search_method"] == "keyword_exact"
```

- [ ] **Step 2: Write tool executor contract tests**

Update `backend/tests/test_agent_navigation_tools_contract.py`.

Replace the current `search_service.search` monkeypatch test with a keyword locator contract:

```python
def test_search_within_document_uses_keyword_locator_not_bm25(monkeypatch):
    async def run() -> None:
        executor = _executor({
            "pages": [{"page": 2, "text": "alpha appears here"}],
            "structure": [],
        })

        async def fail_search(**_kwargs):
            raise AssertionError("search_within_document must not call search_service.search")

        monkeypatch.setattr("app.services.search_service.search_service.search", fail_search)
        result = await executor.execute(
            "search_within_document", {"doc_id": "doc-a", "query": "alpha"}
        )
        assert result["success"] is True
        assert result["search_method"] == "keyword_exact"
        assert result["matches"][0]["page"] == 2

    asyncio.run(run())
```

Add a visual/OCR contract:

```python
def test_search_within_document_visual_match_omits_ocr_text() -> None:
    async def run() -> None:
        executor = _executor({
            "pages": [{
                "page": 4,
                "text": "OCR text with alpha",
                "images": [{"image_path": "page://doc-a/4", "page": 4}],
                "ocr_used": True,
            }],
            "page_text_map_ocr_pages": [4],
            "structure": [],
        })
        result = await executor.execute(
            "search_within_document", {"doc_id": "doc-a", "query": "alpha"}
        )
        match = result["matches"][0]
        assert match["visual_evidence_required"] is True
        assert "OCR text" not in str(result)
        assert match["next_tool"] == "get_page_image"

    asyncio.run(run())
```

- [ ] **Step 3: Write planner tests for locating intent**

In `backend/tests/test_retrieval_planner.py`, add:

```python
def test_selected_document_locating_query_uses_search_within_document_first():
    plan = RetrievalPlanner().plan(
        "在哪一页提到了华东收入增长？",
        document_ids=["doc-a"],
        strict_scope=True,
    )
    assert plan.steps[0].tool_name == "search_within_document"
    assert plan.steps[0].arguments["doc_id"] == "doc-a"
    assert plan.fallback_to_agent is True
```

Add:

```python
def test_selected_document_summary_still_inspects_structure_first():
    plan = RetrievalPlanner().plan(
        "总结这份文档的主要内容",
        document_ids=["doc-a"],
        strict_scope=True,
    )
    assert plan.steps[0].tool_name == "get_document_structure"
```

- [ ] **Step 4: Write planner integration test**

In `backend/tests/test_agent_retrieval_planner_integration.py`, add a fake executor case proving `_execute_initial_retrieval_plan()` calls `search_within_document` before model function-calling for selected-document locating questions.

- [ ] **Step 5: Write prompt catalog test**

In `backend/tests/test_tools_prompt_catalog.py`, assert the system prompt contains these rules:

- selected document + locating/keyword question -> `search_within_document`
- `search_within_document` is deterministic keyword/phrase matching, not BM25/rerank or semantic retrieval
- use search matches to choose pages, then fetch source content or page images before answering
- OCR/visual search matches must be verified through `get_page_image` or `get_document_image`; do not answer from OCR text returned by the locator
- do not repeat a structure/tool call if initial evidence already answered the routing need

- [ ] **Step 6: Write frontend tool-trace label test**

In `frontend/src/ui/pagechatContracts.test.ts`, add cases for:

```ts
expect(toolPresentationFor('search_within_document', { query: '收入' })).toMatchObject({
  title: expect.stringContaining('Search'),
})
```

Use the existing local helper names in `pagechatContracts.ts`.

- [ ] **Step 7: Run tests and verify failures**

```powershell
py -m pytest backend/tests/test_document_keyword_locator.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_retrieval_planner.py backend/tests/test_agent_retrieval_planner_integration.py backend/tests/test_tools_prompt_catalog.py -q
cd frontend
npm.cmd test -- --run frontend/src/ui/pagechatContracts.test.ts
```

- [ ] **Step 8: Implement deterministic document keyword locator**

Create `backend/app/services/document_keyword_locator.py`.

Responsibilities:

- Accept `index_data`, `query`, `doc_id`, `doc_name`, and `limit`.
- Extract locating terms from natural-language queries.
- Scan only the specified document's loaded index data.
- Use exact phrase and keyword matching only.
- Do not call `search_service`, BM25, rerank, embeddings, or query expansion.
- Return compact matches.

Suggested public function:

```python
def locate_keywords_in_index(
    *,
    index_data: dict,
    query: str,
    doc_id: str,
    doc_name: str,
    limit: int = 10,
) -> dict:
    ...
```

Suggested return shape:

```python
{
    "success": True,
    "doc_id": doc_id,
    "doc_name": doc_name,
    "query": query,
    "search_method": "keyword_exact",
    "matches": [
        {
            "page": 3,
            "match_type": "keyword",
            "matched_terms": ["华东", "收入", "增长"],
            "snippet": "...华东区域收入增长...",
            "display_label": "sales.pdf p.3",
            "source_anchor": {"format": "pdf", "unit_type": "page", "start_page": 3, "end_page": 3},
            "next_tool": "get_page_content",
        }
    ],
    "next_steps": {"summary": "...", "options": [...]},
}
```

For OCR/visual pages:

```python
{
    "page": 3,
    "match_type": "ocr_keyword",
    "matched_terms": ["华东", "收入", "增长"],
    "visual_evidence_required": True,
    "text_omitted_reason": "visual_evidence_required",
    "display_label": "scan.pdf p.3",
    "source_anchor": {"format": "pdf", "unit_type": "page", "start_page": 3, "end_page": 3},
    "image_refs": [{"image_path": "page://doc-a/3", "page": 3}],
    "next_tool": "get_page_image",
}
```

Do not include `snippet`, `text`, `text_content`, or OCR raw text for OCR/visual matches.

Term extraction guidance:

- Strip intent words such as `在哪`, `哪一页`, `提到`, `出现`, `查找`, `搜索`, `定位`, `包含`, `where`, `which page`, `find`, `locate`, `mentioned`, `contains`.
- Preserve numbers, percentages, dates, English acronyms, and Chinese terms.
- Produce both phrase candidates and token candidates.
- Ranking should be deterministic:
  1. exact phrase match
  2. all terms matched
  3. more matched terms
  4. title/heading match
  5. occurrence count
  6. lower page number

- [ ] **Step 9: Route ToolExecutor through keyword locator**

In `backend/app/services/tool_executor.py`, replace the `search_service.search()` call inside `_search_within_document()` with:

```python
from app.services.document_keyword_locator import locate_keywords_in_index

structure = await self.pageindex_service.load_index(doc.id)
if not structure:
    return {"success": False, "error": f"文档 {doc.id} 的索引不存在"}

return locate_keywords_in_index(
    index_data=structure,
    query=query,
    doc_id=doc.id,
    doc_name=doc.original_name,
)
```

Preserve document permission checks and `_resolve_document()`.

- [ ] **Step 10: Add intent routing to RetrievalPlanner**

In `backend/app/services/retrieval_planner.py`:

- Add route or intent enum if useful:

```python
class RetrievalIntent(str, Enum):
    LOCATE = "locate"
    SUMMARY = "summary"
    COMPARE = "compare"
    TABLE_AGGREGATION = "table_aggregation"
    GENERAL_QA = "general_qa"
```

- Implement `_is_locating_query(question)` with conservative Chinese and English triggers:
  - Chinese: `在哪`, `哪一页`, `提到`, `出现`, `查找`, `搜索`, `定位`, `包含`
  - English: `where`, `which page`, `find`, `locate`, `mentioned`, `contains`
- For a single selected doc and locating query, first step:

```python
RetrievalStep(
    tool_name="search_within_document",
    arguments={"doc_id": selected_docs[0], "query": question},
    reason="Locate the most relevant pages or sections within the selected document before reading source pages.",
)
```

- Keep summary and broad QA on `get_document_structure`.

- [ ] **Step 11: Reduce duplicate tool behavior**

In `backend/app/services/agent_service.py`:

- When initial planner evidence exists, add a compact system/developer message before the model call:

```text
Initial retrieval evidence is already available. Use it to decide the next source page/tool. Do not repeat the same tool call with identical arguments unless evidence is empty or low confidence.
```

- Preserve tool caching, but make the prompt behavior visible to the model.
- If the first planner step was `search_within_document` and returns text-page matches, the next expected tool should be `get_page_content` for those pages, not another browse.
- If the first planner step returns OCR/visual matches, the next expected tool should be `get_page_image` or `get_document_image`, not an answer from OCR text.

- [ ] **Step 12: Add citation repair pass**

In `backend/app/services/agent_service.py`, where it currently logs `CITATION_MISS`, add a bounded repair pass:

- Only run if:
  - `tool_results_for_answer` is non-empty.
  - `assistant_content` is non-empty.
  - No `[[... p.N]]` citation exists.
- Use a short non-streaming or streaming model call with no tools:

```text
Add document citations to the answer using only the provided evidence labels. Do not add new claims. If evidence is insufficient, append a brief sentence saying the available documents do not support a precise citation.
```

- Limit evidence passed into repair to compact labels/snippets/source anchors.
- Add a test with monkeypatched model response.

If this creates too much implementation risk, leave repair behind a helper function and a test, then enable it after focused verification.

- [ ] **Step 13: Improve tool result client summaries**

In `backend/app/services/tool_executor.py`:

- Ensure `search_within_document` returns:
  - `matches`
  - `display_label`
  - `source_anchor`
  - `matched_terms`
  - `match_type`
  - `next_tool`
  - `visual_evidence_required` for visual/OCR matches
  - `next_steps`
  - no full document text
- Ensure `search_method` is `keyword_exact`, not `bm25` or `bm25_rerank`.
- Ensure visual page results clearly say when image inspection is required.

In `frontend/src/ui/pagechatContracts.ts`:

- Show each tool trace with human-readable action:
  - `Searching within document`
  - `Reading document structure`
  - `Reading source pages`
  - `Inspecting image`
  - `Searching the web`
- Remove wording like `ran`.

- [ ] **Step 14: Run focused backend/frontend tests**

```powershell
py -m pytest backend/tests/test_document_keyword_locator.py backend/tests/test_retrieval_planner.py backend/tests/test_agent_retrieval_planner_integration.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_agent_service_sanitize.py -q
cd frontend
npm.cmd test -- --run frontend/src/ui/pagechatContracts.test.ts
```

- [ ] **Step 15: Commit**

```powershell
git add backend/app/services/document_keyword_locator.py backend/app/services/retrieval_planner.py backend/app/services/agent_service.py backend/app/prompts/__init__.py backend/app/services/tool_executor.py backend/tests/test_document_keyword_locator.py backend/tests/test_retrieval_planner.py backend/tests/test_agent_retrieval_planner_integration.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_agent_service_sanitize.py frontend/src/ui/pagechatContracts.ts frontend/src/ui/pagechatContracts.test.ts
git commit -m "feat(agent): add keyword document locator"
```

---

### Task 8: Final Verification And Product QA

**Files:**
- Modify if needed: `docs/pagechat_integration_development_guide.md`
- Optional create: `docs/superpowers/qa/2026-06-25-product-behavior-closure-qa.md`

- [ ] **Step 1: Run backend focused suites**

```powershell
py -m pytest backend/tests/test_document_list_scope.py backend/tests/test_folder_search_scope.py backend/tests/test_agent_navigation_tools_contract.py backend/tests/test_tool_executor_scope.py backend/tests/test_retrieval_planner.py backend/tests/test_agent_retrieval_planner_integration.py backend/tests/test_agent_citation_bindings.py backend/tests/test_agent_service_sanitize.py backend/tests/test_tools_prompt_catalog.py backend/tests/test_chat_stream_cancellation.py -q
```

Expected: all pass.

- [ ] **Step 2: Run frontend focused suites**

```powershell
cd frontend
npm.cmd test -- --run frontend/src/stores/chat.test.ts frontend/src/utils/documentWorkbench.test.ts frontend/src/ui/pagechatContracts.test.ts frontend/src/utils/citations.test.ts frontend/src/utils/chatScroll.test.ts frontend/src/utils/pdfRenderScale.test.ts frontend/src/components/chat/ThinkingBlock.test.ts
```

Expected: all pass.

- [ ] **Step 3: Run full frontend build**

```powershell
cd frontend
npm.cmd run build
```

Expected: Vite build passes.

- [ ] **Step 4: Manual browser QA**

Start the latest backend and frontend:

```powershell
C:\Users\TT_WT\Desktop\start-backend.bat
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration\frontend
npm.cmd run dev
```

Use account:

```text
admin@pagechat.ai / Admin123!
```

Manual checks:

- Documents root shows only current root content.
- Empty library has no sample sales folder/file.
- Upload or use a real document; preview is sharp.
- Open a document and use Chat; navigate to Documents and back; chat content remains.
- Select another conversation; it loads full content and scrolls to latest.
- Ask a question that streams; scroll upward while generating; viewport does not fight the user.
- Stop generation; UI stops and no new chunks continue.
- Ask a document question that produces citations; click citation; right drawer opens at the cited page/source anchor.
- Ask a selected-document locating question; tool trace shows `search_within_document` before source reading, and the tool result reports `search_method=keyword_exact`.
- Ask a visual-page question; page content avoids OCR text and routes to image inspection.

- [ ] **Step 5: Update QA notes**

If QA notes are useful, create:

```text
docs/superpowers/qa/2026-06-25-product-behavior-closure-qa.md
```

Record:

- Commands run.
- Browser URL.
- Manual checks passed/failed.
- Known follow-ups.

- [ ] **Step 6: Final commit**

If QA docs were added:

```powershell
git add docs/superpowers/qa/2026-06-25-product-behavior-closure-qa.md
git commit -m "docs(qa): record product behavior closure verification"
```

- [ ] **Step 7: Push**

```powershell
git push -u origin codex/pagechat-product-behavior-closure
```

## Rollback Strategy

- Task 1 can be reverted independently if document listing behavior regresses.
- Task 2 is the highest-risk state change. Keep backend hydration isolated in one commit so it can be reverted without losing UI work.
- Task 3 abort/scroll can be reverted without affecting persisted conversations.
- Task 5 citation drawer depends on Task 2 message persistence and existing preview components, but can be disabled by hiding citation click handlers while keeping backend bindings.
- Task 7 agent improvements should remain conservative. If citation repair or planner intent routing causes regressions, disable that subfeature behind a helper guard and keep prompt/tool trace improvements.

## Notes For Implementers

- Do not reintroduce demo data into production views.
- Do not make root browsing recursive again to compensate for search. Search recursion should be explicit.
- Do not implement `search_within_document` with BM25, rerank, embeddings, query expansion, or broad document search. It is a deterministic keyword/phrase locator.
- Do not store raw base64 or full page images in localStorage, SSE history, or DB message JSON.
- Do not expose OCR text for visual-only pages in agent tools, including `search_within_document`; OCR may be used only to decide that a page/image should be inspected.
- Do not add a separate right info panel to chat citation preview; reuse the document preview surface.
- Prefer tests around pure helpers for UI logic that is hard to verify in jsdom.
- Keep commits small and aligned to the task list.
