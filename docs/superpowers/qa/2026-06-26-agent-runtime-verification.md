# PageChat Agent Runtime Verification

Document type: how-to / QA record

Audience: PageChat developers validating the agent runtime, citations, preview, and history work before moving to cleanup.

Goal: verify the new PageChat event protocol against the parsed Chongqing document scenarios without depending on raw provider thinking or legacy stream events.

## Scope

This Phase 9 verification covers:

- Backend PageChat SSE event protocol.
- Document-scoped agent tool use.
- Web/general question retrieval policy.
- Structured citations and preview anchors.
- Frontend inline tool timeline and integrated citation preview.

This document does not validate model answer quality exhaustively. It checks product behavior and protocol correctness; answer wording still needs human review.

## Target Document

Use the parsed document:

`2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf`

The document appears in the AI Knowledge baseline fixtures as the Chongqing scanned/OCR case. It is expected to use OCR-derived text for matching while returning image/page anchors for visual reasoning and preview.

## Automated Coverage

Backend scenario verifier tests:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat\backend
C:\Users\TT_WT\AppData\Local\Python\bin\python.exe -m pytest tests/test_pagechat_real_document_scenarios.py -v
```

Latest result:

`8 passed`

Frontend browser runtime test:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat\frontend
npm.cmd exec playwright test tests/chat-agent-runtime.spec.ts
```

Latest result:

`1 passed`

Generated screenshot:

`docs/superpowers/qa/agent-runtime/chat-agent-runtime-preview.png`

## Manual Real-Backend Run

Start the latest backend and frontend for this worktree, log in, and find the parsed Chongqing document id from the Documents page or API.

Run the verifier:

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat\backend
C:\Users\TT_WT\AppData\Local\Python\bin\python.exe scripts/verify_pagechat_agent_runtime.py `
  --base-url http://127.0.0.1:8000 `
  --token <bearer-token> `
  --document-id <chongqing-document-id> `
  --web-search-enabled `
  --output ..\docs\superpowers\qa\agent-runtime\manual-run.md
```

For a dry-run checklist without calling the backend:

```powershell
C:\Users\TT_WT\AppData\Local\Python\bin\python.exe scripts/verify_pagechat_agent_runtime.py --dry-run
```

### Manual Streaming Smoothness Check

Use the real backend, a real configured model, and the parsed Chongqing document. Ask a document-scoped question and watch the assistant answer before the run reaches `run_completed`.

Expected behavior:

- Answer text appears incrementally as `answer_delta` events arrive, not as one final dump after all tools finish.
- Tiny provider chunks are visually buffered into smooth readable updates.
- Tool/progress timeline rows appear before or between answer text when their events arrive.
- No raw provider thinking or chain-of-thought is shown.
- The final rendered answer is identical to the accumulated stream content after `run_completed`.

The Playwright mock validates deterministic final event handling, inline tools, citations, preview layout, PDF zoom, and route-preserved history. This manual real-backend check validates provider chunk cadence and perceived output smoothness.

## Scenarios

| Scenario | Question | Expected behavior |
| --- | --- | --- |
| `cq-ai-innovation` | 重庆师范大学有什么 AI 应用的创新？ | Uses document tools only when the Chongqing document is selected or scoped; emits structured citations. |
| `cq-compare-themes` | 对比文档中 AI 应用、数据治理、教学改革三类内容。 | Shows multiple evidence/tool steps and citations across relevant pages. |
| `cq-chapter-3-requirements` | 只看第 3 章，提炼可落地的功能需求。 | Uses scoped document/page evidence and does not expand to unrelated library content. |
| `beijing-weather` | 北京天气怎么样？ | Does not call document tools; uses web search only when enabled/requested. |

## Pass Criteria

- No streamed event uses legacy `thinking`, `content`, `tool_call`, `tool_result`, or `done`.
- Every new event includes `run_id`, `conversation_id`, `message_id`, `seq`, and `ts`.
- Document scenarios emit at least one document `tool_started` event and at least one `citation_added` event.
- The weather scenario emits no document tool events.
- Successful runs end with `run_completed`.
- Frontend renders tool calls inline in the assistant message.
- Citation click opens the integrated right preview pane and narrows the chat column instead of overlaying the page.
- PDF preview receives the cited page anchor.
- PDF zoom to 180% visibly increases the rendered page/canvas size.
- Switching Documents -> Chat preserves the same message order and content.
- Real-backend answer streaming feels incremental and smooth, without raw thinking leakage.

## Current Notes

- The automated backend verifier tests the scenario catalog and event validator with canned PageChat events. It intentionally does not call a real model.
- The Playwright test uses a mocked PageChat stream so UI behavior remains deterministic.
- A manual real-backend run is still required to validate actual model/tool behavior on the parsed Chongqing document.
