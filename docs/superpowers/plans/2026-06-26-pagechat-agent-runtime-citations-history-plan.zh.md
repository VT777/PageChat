# PageChat Agent Runtime, Citations, Preview, and History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stable PageChat agent runtime and event protocol that fixes tool/thinking behavior, citation preview integration, PDF zoom, and conversation history ordering/loss.

**Architecture:** Introduce a PageChat-owned Agent Run state machine, preferably implemented with LangGraph, while keeping PageChat's existing document tools and retrieval rules. The backend becomes the single source of truth for conversations, messages, run events, citations, and generation status; the frontend consumes normalized PageChat events instead of provider-specific thinking/tool payloads.

**Tech Stack:** FastAPI, SQLite/aiosqlite, OpenAI-compatible Chat Completions, optional LangGraph runtime, Vue 3, Pinia, pdfjs-dist, Vitest, pytest, Playwright.

---

## Current Problems And Root Causes

### User-visible issues

1. **Citation preview and Q&A feel disconnected.**
   The current right preview panel overlays or visually detaches from the chat surface. Citation links are generated from markdown regex and `window.handleCitationClick`, so the UI does not have a first-class citation model.

2. **PDF preview zoom changes the number but not the rendered page.**
   `frontend/src/components/PdfReferenceViewer.vue` clears page state and the canvas map, but it does not reliably clear already inserted canvases from the DOM. `renderPage()` then sees an existing canvas and does not replace it.

3. **Conversation history can reorder, lose assistant answers, or lose whole records after navigation.**
   The frontend stores full session messages in localStorage while the backend also stores conversations/messages. `frontend/src/stores/chat.ts` can fall back to reconstructing a session from `firstMessage`, causing partial conversations. Backend ordering relies on timestamp/id without a run sequence. Streaming assistant messages are periodically updated but not represented as durable run events.

4. **Thinking and tool calls do not look like the official PageIndex-style flow.**
   The current SSE protocol exposes raw `thinking` and provider/tool events. This leaks provider behavior, can be long/mixed-language, and is hard for the UI to render as a concise progress timeline.

5. **A single answer may cross provider protocols.**
   Responses API plus Chat Completions fallback makes state, citations, and final answer persistence fragile. One assistant answer should use exactly one runtime path.

## Design Principles

- Backend is the source of truth for conversation history. Frontend localStorage may keep drafts/UI preferences only.
- No raw chain-of-thought is persisted or shown. UI displays concise PageChat progress/tool timeline.
- One assistant answer equals one `agent_run` with stable sequence numbers and a terminal state.
- One run uses one provider protocol. No Responses-to-Chat-Completions fallback inside the same answer.
- Citations are structured data, not only markdown text. Inline rendering is a UI concern; preview navigation uses citation anchors.
- LangGraph may manage the agent state machine, but PageChat owns event names, citation schema, tool contracts, and provider capabilities.

## Relevant Existing Files

### Backend

- `backend/requirements.txt` - add LangGraph only after runtime wrapper tests exist.
- `backend/app/services/agent_service.py` - current hand-written agent/tool loop; target for extraction/replacement.
- `backend/app/services/chat_service.py` - current SSE orchestrator and message persistence.
- `backend/app/api/chat.py` - chat stream, conversation list, message load endpoints.
- `backend/app/models/database.py` - base SQLite schema.
- `backend/app/models/migrations.py` - add durable run/event/citation fields.
- `backend/app/services/tool_executor.py` - existing PageChat document tools, keep and adapt.
- `backend/app/core/llm.py` - provider call abstraction and thinking disablement.
- `backend/app/services/model_gateway.py` - provider/model route integration.

### Frontend

- `frontend/src/types/stream.ts` - replace old SSE event union.
- `frontend/src/stores/chat.ts` - remove full-message localStorage source of truth; add backend hydration.
- `frontend/src/views/ChatView.vue` - chat layout, citation rendering, preview panel integration.
- `frontend/src/components/PdfReferenceViewer.vue` - fix zoom/render invalidation.
- `frontend/src/components/PdfViewer.vue` - keep behavior aligned with reference viewer.
- `frontend/src/components/preview/UniversalPreview.vue` - reuse for right-side citation preview.
- `frontend/src/utils/documentWorkbench.ts` - source anchor conversion and preview support.
- `frontend/src/utils/evidence.ts` - citation/evidence label formatting.

## Target Backend Event Protocol

All streamed events should include:

```json
{
  "run_id": "run_...",
  "conversation_id": "conv_...",
  "message_id": "msg_...",
  "seq": 12,
  "ts": "2026-06-26T10:00:00Z"
}
```

Event names:

- `run_started`
- `message_created`
- `progress`
- `tool_started`
- `tool_delta` optional
- `tool_completed`
- `answer_delta`
- `citation_added`
- `preview_ready`
- `run_completed`
- `run_failed`
- `run_cancelled`

Legacy events (`thinking`, `content`, `tool_call`, `tool_result`, `done`) should be supported through a temporary compatibility adapter only during migration. The new frontend should consume only the new protocol.

## Target Data Model

Add durable run and event tables:

```sql
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_id TEXT,
    model TEXT,
    protocol TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE agent_run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, seq),
    FOREIGN KEY (run_id) REFERENCES agent_runs(id)
);

CREATE TABLE message_citations (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    citation_key TEXT NOT NULL,
    document_id TEXT,
    document_name TEXT NOT NULL,
    source_anchor_json TEXT NOT NULL,
    display_label TEXT NOT NULL,
    preview_kind TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);
```

Add stable ordering fields to `messages`:

```sql
ALTER TABLE messages ADD COLUMN sequence INTEGER;
ALTER TABLE messages ADD COLUMN run_id TEXT;
```

Backfill `sequence` per conversation based on `created_at, id`.

## Phase 0: Baseline Reproduction And Safety Net

### Task 0.1: Capture current history-loss failure

**Files:**
- Create: `backend/tests/test_chat_history_persistence.py`
- Create: `frontend/src/stores/chat.history.test.ts`

- [ ] Write a backend test that creates a conversation with user/assistant messages and asserts `/api/chat/conversations/{id}/messages` returns stable order by `sequence`.
- [ ] Write a frontend store test that loads a conversation from backend payload and never reconstructs it from `firstMessage` when backend messages are available.
- [ ] Run: `cd backend; pytest tests/test_chat_history_persistence.py -v`
- [ ] Run: `cd frontend; npm test -- src/stores/chat.history.test.ts`
- [ ] Expected before implementation: tests fail because `sequence` does not exist and frontend still relies on localStorage sessions.

### Task 0.2: Capture current PDF zoom failure

**Files:**
- Create: `frontend/src/components/PdfReferenceViewer.zoom.test.ts`

- [ ] Mock pdfjs page rendering and canvas insertion.
- [ ] Mount `PdfReferenceViewer` in embedded mode.
- [ ] Trigger zoom from 100% to 180%.
- [ ] Assert old canvas nodes are removed or replaced and render is called with a larger viewport.
- [ ] Run: `cd frontend; npm test -- src/components/PdfReferenceViewer.zoom.test.ts`
- [ ] Expected before implementation: test fails because the DOM canvas can remain unchanged.

### Task 0.3: Capture new event protocol expectations

**Files:**
- Create: `backend/tests/test_agent_run_event_protocol.py`
- Create: `frontend/src/types/stream.test.ts`

- [ ] Backend test: a fake agent run emits monotonically increasing `seq`, includes `run_id`, `conversation_id`, and `message_id`, and never emits raw `thinking`.
- [ ] Frontend test: event parser accepts `answer_delta`, `tool_started`, `tool_completed`, `citation_added`, `run_completed`.
- [ ] Run focused tests and keep them failing until Phase 1/2 implements the protocol.

## Phase 1: Durable Conversation And Run Storage

### Task 1.1: Add database migrations

**Files:**
- Modify: `backend/app/models/migrations.py`
- Modify: `backend/app/models/database.py`
- Test: `backend/tests/test_database_migrations.py`

- [ ] Add migration `20260626_005_add_agent_runs_events_citations`.
- [ ] Create `agent_runs`, `agent_run_events`, `message_citations`.
- [ ] Add nullable `sequence` and `run_id` to `messages` if missing.
- [ ] Add indexes:
  - `idx_messages_conversation_sequence`
  - `idx_agent_runs_conversation_started`
  - `idx_agent_run_events_run_seq`
  - `idx_message_citations_message`
- [ ] Backfill `messages.sequence` per conversation.
- [ ] Update migration tests to assert idempotence.
- [ ] Run: `cd backend; pytest tests/test_database_migrations.py -v`

### Task 1.2: Create repository layer for runs and messages

**Files:**
- Create: `backend/app/services/chat_run_repository.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_run_repository.py`

- [ ] Implement `create_user_message(conversation_id, content)`.
- [ ] Implement `create_assistant_placeholder(conversation_id, run_id)`.
- [ ] Implement `create_run(...)`.
- [ ] Implement `append_run_event(run_id, event_type, payload) -> seq`.
- [ ] Implement `complete_run(run_id, final_content, citations)`.
- [ ] Implement `fail_run(run_id, error)`.
- [ ] Implement `list_messages(conversation_id)` ordered by `sequence, created_at, id`.
- [ ] Tests must prove concurrent inserts do not duplicate `sequence`.

### Task 1.3: Update chat API history endpoint

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat_history_persistence.py`

- [ ] Return messages with:
  - `id`
  - `role`
  - `content`
  - `status`
  - `sequence`
  - `run_id`
  - `agent_steps`
  - `citations`
  - `created_at`
  - `updated_at`
- [ ] Return conversations ordered by `updated_at DESC`, not only `created_at DESC`.
- [ ] Update conversation `updated_at` when a user message is created and when a run completes.
- [ ] Run chat API tests.

## Phase 2: PageChat Event Protocol

### Task 2.1: Define backend event models

**Files:**
- Create: `backend/app/agent/events.py`
- Test: `backend/tests/test_agent_run_event_protocol.py`

- [ ] Define dataclasses or Pydantic models for:
  - `RunStarted`
  - `ProgressEvent`
  - `ToolStarted`
  - `ToolCompleted`
  - `AnswerDelta`
  - `CitationAdded`
  - `PreviewReady`
  - `RunCompleted`
  - `RunFailed`
- [ ] Add `to_sse()` helper.
- [ ] Add validation that every event has `run_id`, `conversation_id`, `message_id`, `seq`, and `ts`.
- [ ] Add a compatibility helper only if old frontend still needs it during transition.

### Task 2.2: Replace raw thinking with concise progress

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/core/llm.py`
- Test: `backend/tests/test_agent_service_sanitize.py`
- Test: `backend/tests/test_agent_run_event_protocol.py`

- [ ] Stop streaming provider `reasoning_content`, `reasoning_text`, or `reasoning_summary_text` to clients.
- [ ] Stop saving raw thinking to `messages.thinking_content` for new runs.
- [ ] Emit deterministic `progress` text from runtime state, for example:
  - `正在确定是否需要检索文档`
  - `正在读取文档结构`
  - `正在定位相关页面`
  - `正在整理引用`
- [ ] Keep `thinking_content` column for legacy messages only.
- [ ] Test that raw provider reasoning never appears in SSE or DB for new runs.

### Task 2.3: Update frontend stream types and parser

**Files:**
- Modify: `frontend/src/types/stream.ts`
- Modify: `frontend/src/stores/chat.ts`
- Test: `frontend/src/types/stream.test.ts`
- Test: `frontend/src/stores/chat.history.test.ts`

- [ ] Add new event names and payload types.
- [ ] Map `progress` events to a compact timeline item.
- [ ] Map `tool_started/tool_completed` to one inline tool row per tool.
- [ ] Map `answer_delta` to assistant content.
- [ ] Map `citation_added` to structured citations on the assistant message.
- [ ] Map `run_completed` to `isLoading=false` and durable backend message id.
- [ ] Ignore old `thinking` for new protocol.

## Phase 3: LangGraph Agent Runtime

### Task 3.1: Add LangGraph dependency behind a wrapper

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/agent/runtime.py`
- Create: `backend/app/agent/state.py`
- Test: `backend/tests/test_agent_runtime_graph.py`

- [ ] Add `langgraph` to backend requirements.
- [ ] Create `AgentRunState` with:
  - `question`
  - `conversation_id`
  - `run_id`
  - `message_id`
  - `scope`
  - `history`
  - `tool_results`
  - `citations`
  - `answer`
  - `provider_capabilities`
- [ ] Create `PageChatAgentRuntime.stream(state)` wrapper so the rest of the app does not depend directly on LangGraph APIs.
- [ ] Test with a fake graph that emits PageChat events.

### Task 3.2: Implement explicit graph nodes

**Files:**
- Create: `backend/app/agent/graph.py`
- Create: `backend/app/agent/nodes.py`
- Modify: `backend/app/services/agent_service.py`
- Test: `backend/tests/test_agent_runtime_graph.py`

- [ ] Node `prepare_scope`: resolve selected documents/folder/user library.
- [ ] Node `decide_retrieval`: decide no-tool vs document tools vs web search.
- [ ] Node `execute_tools`: call existing `ToolExecutor`.
- [ ] Node `build_evidence_pack`: normalize tool results into concise evidence.
- [ ] Node `generate_answer`: call one provider protocol.
- [ ] Node `bind_citations`: convert evidence to structured citations.
- [ ] Node `finalize`: persist final answer and citations.
- [ ] Each node emits PageChat events through the runtime wrapper.

### Task 3.3: Enforce one provider protocol per run

**Files:**
- Create: `backend/app/agent/provider_adapter.py`
- Modify: `backend/app/core/llm.py`
- Modify: `backend/app/services/model_gateway.py`
- Test: `backend/tests/test_provider_protocol_selection.py`

- [ ] Define provider capability flags:
  - `supports_streaming`
  - `supports_tool_calling`
  - `supports_vision`
  - `supports_structured_output`
  - `supports_responses_api`
- [ ] For OpenAI-compatible/DashScope, use Chat Completions/function calling or PageChat deterministic tool execution.
- [ ] Do not use Responses API for DashScope until it has a dedicated single-protocol adapter with passing tests.
- [ ] Fail fast with a product-friendly error when the selected model lacks required capabilities.
- [ ] Test that one run records exactly one `protocol` in `agent_runs.protocol`.
- [ ] Test there is no Responses-to-Chat fallback path inside one run.

### Task 3.4: Retrieval policy and automatic tool-call control

**Files:**
- Modify: `backend/app/agent/nodes.py`
- Modify: `backend/app/services/tool_executor.py`
- Test: `backend/tests/test_agent_retrieval_policy.py`

- [ ] Do not automatically retrieve documents for every question.
- [ ] Use tools when:
  - user selected documents/folders
  - user asks about uploaded content
  - answer requires document evidence
  - user explicitly asks to search web and Web Search is enabled
- [ ] Do not use document tools for ordinary general chat.
- [ ] Add tests for:
  - "你好" -> no tools
  - "北京天气" with Web Search enabled -> web search, no document search
  - "重庆师范大学有什么 AI 应用创新" with selected document -> document tools
  - "总结这篇文档" with selected file -> document tools

## Phase 4: Citation Data Model And Preview Integration

### Task 4.1: Normalize citations at backend

**Files:**
- Create: `backend/app/agent/citations.py`
- Modify: `backend/app/services/tool_executor.py`
- Test: `backend/tests/test_citation_binding.py`

- [ ] Define citation schema:

```json
{
  "citation_key": "c1",
  "document_id": "doc_...",
  "document_name": "重庆.pdf",
  "display_label": "重庆 p.12",
  "source_anchor": {
    "format": "pdf",
    "start_page": 12,
    "end_page": 12
  },
  "preview_kind": "pdf"
}
```

- [ ] Convert document tool results into citation candidates.
- [ ] Convert web search results into citation candidates with `preview_kind: "web"`.
- [ ] Persist final citations in `message_citations`.
- [ ] Return citations with history endpoint.

### Task 4.2: Stop regex-only citation behavior

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/components/chat/CitationLink.vue`
- Create: `frontend/src/components/chat/CitationRenderer.vue`
- Modify: `frontend/src/utils/evidence.ts`
- Test: `frontend/src/utils/evidence.test.ts`

- [ ] Continue to render legacy `[[doc p.1]]` only as fallback.
- [ ] For new messages, render structured `message.citations` inline.
- [ ] Avoid `window.handleCitationClick` for new citations.
- [ ] Clicking a citation emits a typed citation object to the preview controller.
- [ ] Citation design should be compact, readable, and embedded in the answer, not a large chip row at the bottom.

### Task 4.3: Make right preview part of chat layout

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/style.css` if global tokens are needed.
- Test: Playwright visual test in `frontend/tests/chat-preview-layout.spec.ts`

- [ ] Replace overlay-style right preview with a split workspace:
  - left sidebar remains stable
  - chat column narrows gracefully
  - right preview occupies fixed/responsive width
  - no opaque modal backdrop over chat
- [ ] Preview open/close should not reset chat scroll or message state.
- [ ] On desktop, preview appears as an integrated right pane.
- [ ] On narrow viewports, preview can fall back to drawer.
- [ ] Playwright assertions:
  - chat column width shrinks when preview opens
  - preview pane is adjacent to chat, not overlaying it
  - citation click opens target page/anchor

## Phase 5: PDF Preview Zoom Fix And Viewer Consistency

### Task 5.1: Fix PdfReferenceViewer zoom invalidation

**Files:**
- Modify: `frontend/src/components/PdfReferenceViewer.vue`
- Test: `frontend/src/components/PdfReferenceViewer.zoom.test.ts`

- [ ] Update `clearAllPages()` to remove existing canvas DOM nodes from every `[data-page]` container.
- [ ] Track a `renderGeneration` number so stale render promises cannot reinsert old canvases after zoom changes.
- [ ] After zoom, keep current page anchored near the same scroll position.
- [ ] Ensure `canvas.style.width` and `canvas.style.height` match viewport dimensions.
- [ ] Test zoom 100 -> 180 -> 80 replaces canvases and changes dimensions.

### Task 5.2: Align PdfViewer and PdfReferenceViewer

**Files:**
- Modify: `frontend/src/components/PdfViewer.vue`
- Modify: `frontend/src/components/PdfReferenceViewer.vue`
- Create: `frontend/src/composables/usePdfRenderQueue.ts` if duplication becomes risky.

- [ ] If both viewers duplicate render invalidation logic, extract a small composable.
- [ ] Keep extraction limited to render queue/cache invalidation; do not redesign viewer UI.
- [ ] Run: `cd frontend; npm run build`

## Phase 6: Frontend Conversation State Cleanup

### Task 6.1: Backend-backed chat store

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/api/index.ts`
- Test: `frontend/src/stores/chat.history.test.ts`

- [ ] Add API calls:
  - `listConversations()`
  - `getConversationMessages(conversationId)`
  - `deleteConversation(conversationId)`
  - `exportConversation(conversationId)`
- [ ] Remove full-message localStorage as a source of truth.
- [ ] Keep localStorage only for:
  - current draft input per conversation
  - last selected conversation id
  - UI preferences like sidebar open state
- [ ] `loadConversation(id)` must fetch backend messages and hydrate exactly those messages.
- [ ] If fetch fails, show error state; do not reconstruct from `firstMessage`.

### Task 6.2: Streaming reconciliation

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Test: `frontend/src/stores/chat.history.test.ts`

- [ ] When sending:
  - create optimistic user message
  - create optimistic assistant placeholder
  - replace optimistic ids when backend emits `message_created/run_started`
- [ ] On `run_completed`, fetch or reconcile final assistant message by `message_id`.
- [ ] On navigation away and back, call backend history endpoint.
- [ ] No duplicate messages after reconnect.
- [ ] No missing assistant message after stream interruption.

### Task 6.3: Conversation navigation behavior

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/stores/chat.ts`
- Test: Playwright `frontend/tests/chat-history.spec.ts`

- [ ] Clicking a conversation loads messages and scrolls to the latest message.
- [ ] During generation, the chat follows latest output only while user is pinned to bottom.
- [ ] If user scrolls up, do not force-scroll.
- [ ] When generation completes, scroll to the start of the latest assistant answer, unless user has explicitly scrolled away during generation.
- [ ] Switching to Documents and back preserves current conversation through backend hydration.

## Phase 7: Tool Timeline And Official-like Interaction

### Task 7.1: Replace thinking block with progress/tool timeline

**Files:**
- Modify: `frontend/src/views/ChatView.vue`
- Create: `frontend/src/components/chat/RunTimeline.vue`
- Create: `frontend/src/components/chat/ToolTimelineItem.vue`
- Test: `frontend/src/components/chat/RunTimeline.test.ts`

- [ ] Show progress rows in order of backend `seq`.
- [ ] Tool rows are one per line, expandable.
- [ ] Arrow/chevron stays next to tool name.
- [ ] Display useful details:
  - tool name
  - target document/folder/page
  - result count
  - elapsed time
  - status
- [ ] No raw provider thinking is shown.
- [ ] Completed progress collapses into concise "Thought for a moment" only if there was no tool timeline; otherwise show the tool timeline summary.

### Task 7.2: Make model output smoother

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Create: `frontend/src/composables/useBufferedStreamText.ts`
- Test: `frontend/src/composables/useBufferedStreamText.test.ts`

- [ ] Buffer tiny token chunks for 16-40ms animation frames.
- [ ] Flush immediately on punctuation/newline/tool event/run completion.
- [ ] Do not delay persistence; only smooth UI rendering.
- [ ] Test that final content is identical to raw deltas.

## Phase 8: Backend Chat Stream API Update

### Task 8.1: Stream new protocol from `/api/chat/stream`

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Test: `backend/tests/test_chat_stream_api.py`

- [ ] `chat_stream` should create a durable run before returning events.
- [ ] If client disconnects:
  - mark run as `cancelled` if runtime stops
  - keep already persisted events
  - do not delete partial assistant message
- [ ] Errors should emit `run_failed` and persist `status=failed`.
- [ ] Do not emit fake final answer text when provider fails to generate one.
- [ ] If no final answer is available, return a structured error that frontend can display.

### Task 8.2: Add run event replay endpoint

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat_stream_api.py`

- [ ] Add `GET /api/chat/runs/{run_id}/events?after_seq=N`.
- [ ] Return persisted run events ordered by `seq`.
- [ ] Use this for future stream resume and debugging.

## Phase 9: Product Verification With Real Documents

### Task 9.1: Regression scenarios using parsed 重庆 document

**Files:**
- Create: `backend/tests/test_pagechat_real_document_scenarios.py` or a documented manual test script under `backend/scripts/`.
- Create: `docs/superpowers/qa/2026-06-26-agent-runtime-verification.md`

- [ ] Scenario 1: "重庆师范大学有什么 AI 应用的创新？"
  - expected: document tools only when the 重庆 document is selected or scope implies it
  - expected: final answer with inline citations
  - expected: citation preview opens exact page
- [ ] Scenario 2: "对比文档中 AI 应用、数据治理、教学改革三类内容"
  - expected: multiple tool calls shown in timeline
  - expected: citations across multiple pages
- [ ] Scenario 3: "只看第 3 章，提炼可落地的功能需求"
  - expected: search/structure/page tools use scoped pages
  - expected: no unrelated library-wide expansion unless explicitly allowed
- [ ] Scenario 4: "北京天气怎么样？"
  - expected: no document retrieval
  - expected: web search only if Web Search is enabled/auto mode allows it

### Task 9.2: End-to-end browser QA

**Files:**
- Create: `frontend/tests/chat-agent-runtime.spec.ts`
- Create screenshots under `docs/superpowers/qa/agent-runtime/`

- [ ] Start backend with latest branch.
- [ ] Start frontend with latest branch.
- [ ] Login as admin.
- [ ] Send document-scoped question.
- [ ] Assert:
  - tool timeline appears inline
  - answer streams smoothly
  - citations are inline
  - right preview integrates with chat layout
  - PDF zoom to 180% visibly changes canvas width/height
  - switching Documents -> Chat preserves message order/content

## Phase 10: Cleanup And Migration Removal

### Task 10.1: Remove old event path after migration

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/types/stream.ts`

- [ ] Remove old `thinking/content/tool_call/tool_result/done` dependencies after frontend consumes new protocol.
- [ ] Keep a small legacy message display path for old DB records only.
- [ ] Remove raw thinking display for new messages.
- [ ] Remove localStorage session message migration after one release if acceptable.

### Task 10.2: Documentation

**Files:**
- Create: `docs/architecture/pagechat_agent_runtime_event_protocol.md`
- Modify: `docs/pagechat_integration_development_guide.md`

- [ ] Document event protocol and example SSE frames.
- [ ] Document provider capability model.
- [ ] Document citation schema.
- [ ] Document how to debug a run through `agent_run_events`.
- [ ] Document manual QA steps.

## Implementation Order

Recommended order:

1. Phase 0 tests.
2. Phase 1 durable storage.
3. Phase 2 event protocol.
4. Phase 6 frontend history cleanup.
5. Phase 5 PDF zoom fix.
6. Phase 4 citation model and preview layout.
7. Phase 3 LangGraph runtime.
8. Phase 7 timeline/output smoothing.
9. Phase 8 stream API hardening.
10. Phase 9 real document verification.
11. Phase 10 cleanup/docs.

Reasoning: fix data loss first, then UI correctness, then runtime sophistication. LangGraph integration should not happen before the storage/event contract exists.

## Acceptance Criteria

- No new run persists raw provider thinking or chain-of-thought.
- No assistant answer uses mixed provider protocols.
- Conversation history is loaded from backend and remains stable after:
  - switching pages
  - refreshing browser
  - selecting another conversation
  - returning to the latest conversation
  - stream interruption
- PDF zoom visibly changes page render at 180%.
- Citation click opens an integrated right preview pane and jumps to the correct page/anchor.
- Inline citations are embedded in the answer, not only collected at the bottom.
- General questions do not automatically trigger document retrieval.
- Document-scoped questions use tools and show a concise, ordered timeline.
- Focused backend tests pass.
- Focused frontend tests pass.
- Browser QA passes on the 重庆 document scenarios.

## Risks And Mitigations

- **Risk: LangGraph dependency adds complexity.**
  Mitigation: hide it behind `PageChatAgentRuntime`; keep PageChat events and tools independent of LangGraph APIs.

- **Risk: DB migration damages existing chats.**
  Mitigation: nullable columns, idempotent migrations, backfill tests, and DB backup before production use.

- **Risk: Frontend/backend protocol migration creates temporary incompatibility.**
  Mitigation: add a short-lived compatibility adapter while migrating, then remove old events in Phase 10.

- **Risk: Provider tool-calling compatibility differs by vendor.**
  Mitigation: capability flags, fail-fast validation, and deterministic PageChat tool execution where possible.

- **Risk: Citation generation from model text is unreliable.**
  Mitigation: bind citations from backend evidence objects, not only model-emitted markdown.

## Commands

Backend focused tests:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat\backend
pytest tests/test_database_migrations.py tests/test_chat_history_persistence.py tests/test_agent_run_event_protocol.py -v
```

Frontend focused tests:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat\frontend
npm test -- src/stores/chat.history.test.ts src/components/PdfReferenceViewer.zoom.test.ts src/types/stream.test.ts
```

Full frontend build:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat\frontend
npm run build
```

Manual verification should use the latest backend and frontend startup scripts after confirming they point at this worktree.

