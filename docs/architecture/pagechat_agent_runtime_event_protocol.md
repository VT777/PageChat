# PageChat Agent Runtime Event Protocol

Document type: reference / explanation

Audience: PageChat backend and frontend developers.

Goal: define the PageChat-owned agent run event protocol, citation schema, provider capability model, and run-debugging workflow.

## Runtime Ownership

One assistant answer is represented by one durable `agent_run`.

The backend is the source of truth for:

- conversations
- messages
- agent runs
- run events
- citations
- run status

The frontend consumes PageChat events only. It must not depend on provider-specific reasoning chunks, raw tool-call payloads, or legacy stream event names.

## Event Contract

Every event sent to the browser includes this metadata:

```json
{
  "run_id": "run_abc",
  "conversation_id": "conv_abc",
  "message_id": "msg_assistant",
  "seq": 3,
  "ts": "2026-06-26T10:00:00Z"
}
```

`seq` is monotonic within one run and is persisted in `agent_run_events`.

Supported event names:

| Event | Purpose |
| --- | --- |
| `run_started` | Durable run exists and generation has started. |
| `message_created` | Optional message id/content reconciliation event. |
| `progress` | Concise PageChat progress text. Never raw chain-of-thought. |
| `tool_started` | One tool call started. |
| `tool_delta` | Optional incremental tool detail. |
| `tool_completed` | One tool call completed with compact sanitized result. |
| `answer_delta` | Assistant answer text delta. |
| `citation_added` | Structured citation available for inline rendering and preview. |
| `preview_ready` | Optional preview artifact is ready. |
| `run_completed` | Final answer and citations are persisted. |
| `run_failed` | Run failed with a user-displayable error. |
| `run_cancelled` | Run was cancelled/interrupted. |

Legacy stream events are not part of the active protocol:

- `thinking`
- `content`
- `tool_call`
- `tool_result`
- `done`

Old database rows may still contain `thinking_content` for legacy display, but new runs must not persist or stream raw provider reasoning.

## Example SSE Frames

```text
event: run_started
data: {"run_id":"run_1","conversation_id":"conv_1","message_id":"msg_a","seq":1,"ts":"2026-06-26T10:00:00Z","status":"running"}

event: tool_started
data: {"run_id":"run_1","conversation_id":"conv_1","message_id":"msg_a","seq":2,"ts":"2026-06-26T10:00:01Z","tool_name":"search_within_document","arguments":{"doc_id":"doc_1","query":"AI innovation"}}

event: tool_completed
data: {"run_id":"run_1","conversation_id":"conv_1","message_id":"msg_a","seq":3,"ts":"2026-06-26T10:00:02Z","tool_name":"search_within_document","elapsed_ms":42,"result":{"status":"success","items":[{"display_label":"report p.3"}]}}

event: answer_delta
data: {"run_id":"run_1","conversation_id":"conv_1","message_id":"msg_a","seq":4,"ts":"2026-06-26T10:00:03Z","content":"The document describes ..."}

event: citation_added
data: {"run_id":"run_1","conversation_id":"conv_1","message_id":"msg_a","seq":5,"ts":"2026-06-26T10:00:04Z","citation":{"citation_key":"c1","document_id":"doc_1","document_name":"report.pdf","display_label":"report p.3","source_anchor":{"format":"pdf","unit_type":"page","start_page":3,"end_page":3},"preview_kind":"pdf"}}

event: run_completed
data: {"run_id":"run_1","conversation_id":"conv_1","message_id":"msg_a","seq":6,"ts":"2026-06-26T10:00:05Z","status":"completed"}
```

## Citation Schema

Structured citations are bound from backend evidence, not from regex-only markdown parsing.

```json
{
  "citation_key": "c1",
  "document_id": "doc_1",
  "document_name": "report.pdf",
  "display_label": "report p.12",
  "source_anchor": {
    "format": "pdf",
    "unit_type": "page",
    "start_page": 12,
    "end_page": 12
  },
  "preview_kind": "pdf"
}
```

Web citations use `preview_kind: "web"` and must include a safe `http` or `https` URL inside `source_anchor.url`.

The frontend renders citations inline and opens the integrated right preview pane from the structured citation object.

## Provider Capability Model

Provider/model configuration should describe capabilities explicitly:

| Capability | Meaning |
| --- | --- |
| `supports_streaming` | Provider can stream answer tokens. |
| `supports_tool_calling` | Provider can produce native tool calls. |
| `supports_vision` | Provider can reason over images. |
| `supports_structured_output` | Provider can reliably return constrained JSON. |
| `supports_responses_api` | Provider supports OpenAI Responses API semantics. |

One run uses exactly one provider protocol, recorded in `agent_runs.protocol`.

OpenAI-compatible providers and DashScope should use the Chat Completions path unless a dedicated single-protocol adapter exists. Do not fall back from one protocol to another inside the same assistant answer.

## Debugging A Run

Use the replay endpoint first:

```http
GET /api/chat/runs/{run_id}/events?after_seq=0
```

When inspecting SQLite directly:

```sql
SELECT status, provider_id, model, protocol, error
FROM agent_runs
WHERE id = :run_id;

SELECT seq, event_type, payload_json
FROM agent_run_events
WHERE run_id = :run_id
ORDER BY seq;

SELECT citation_key, document_name, display_label, source_anchor_json
FROM message_citations
WHERE message_id = :assistant_message_id
ORDER BY created_at, id;
```

Healthy runs should show:

- `run_started` first.
- Tool events only when retrieval or web search is needed.
- `answer_delta` before completion.
- `citation_added` before `run_completed` when document or web evidence is used.
- A terminal `run_completed`, `run_failed`, or `run_cancelled`.

No event payload should contain raw chain-of-thought, base64 image payloads, full OCR page text for visual pages, or unbounded raw tool JSON.

## Manual QA Checklist

Use the detailed QA record at `docs/superpowers/qa/2026-06-26-agent-runtime-verification.md` for the current Chongqing document scenarios.

Before signing off a runtime or frontend integration change:

1. Start the latest backend and frontend from the same worktree.
2. Log in with a test/admin account.
3. Select a parsed document and ask a document-scoped question.
4. Verify the assistant shows inline progress/tool timeline rows, not a raw thinking block.
5. Verify answer text streams incrementally and finishes with `run_completed`.
6. Verify inline citations appear inside the answer.
7. Click a citation and confirm the integrated right preview opens without overlaying the chat.
8. For PDF citations, zoom to 180% and confirm the rendered canvas/page visibly grows.
9. Switch Documents -> Chat and confirm message order/content are preserved.
10. Ask a general question such as weather/current facts and confirm document tools are not called unless document scope or Web Search policy requires it.
11. Inspect the run replay endpoint and confirm no legacy `thinking`, `content`, `tool_call`, `tool_result`, or `done` events appear.
