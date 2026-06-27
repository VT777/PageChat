# PageChat Flat LLM Tool Loop Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current planner-shaped agent runtime with a flat LLM-driven tool loop similar to Claude Code: the model emits native tool calls, PageChat executes tools and appends tool results, and the same loop continues until the model produces the final answer.

**Architecture:** Introduce a new `ModelToolLoopRuntime` behind a feature flag while keeping the current `AgentLoopRuntime` as a rollback path. The new runtime owns one flat message history of `system/user/assistant tool_calls/tool_result/assistant final answer`; backend policy only enforces boundaries and never plans the route.

**Tech Stack:** FastAPI backend, LiteLLM/OpenAI-compatible chat completions with native tool calling, existing PageChat tool executor, Vue chat timeline, pytest, Vitest.

---

## Current Branch And Safety Rules

- Worktree: `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`
- Branch: `codex/pagechat-ui-agent-runtime-integration`
- Read `codex.md` before starting execution.
- Do not develop this refactor in:
  - `C:\Users\TT_WT\.codex\worktrees\fc17\page_chat`
  - `C:\Users\TT_WT\.codex\worktrees\pagechat-frontend`
  - `D:\projects\page_chat`
- Keep the old runtime callable until the new runtime passes API and browser E2E.
- Commit after each phase.

## Problem Statement

The current production path is not yet a true flat LLM-driven loop:

```text
AgentService
  -> AgentLoopRuntime
  -> StructuredLLMPlanner
  -> PlannerAction
  -> AgentPolicy
  -> ToolRunner
  -> ObservationBuilder
  -> StructuredLLMPlanner
  -> AnswerGenerator
```

This creates several product problems:

- The model is asked to output `thought/action` JSON, so behavior feels mechanical.
- The final answer is produced by a separate answer generator instead of naturally emerging from the same tool loop.
- Tool results are transformed into `observations/evidence_pack` instead of being appended as native `tool_result` messages.
- Policy still shapes control flow by rejecting final answers for subjective evidence sufficiency.
- Old `PolicyGuidedPlanner` remains in the codebase and creates confusion.
- Frontend processing displays planner thought instead of concise model/tool progress.

The target path is:

```text
ModelToolLoopRuntime
  -> ToolCallingModelAdapter.stream_turn(messages, tools)
  -> assistant content/tool_calls
  -> RuntimeBoundaryPolicy validates tool calls
  -> ToolRunner executes tools
  -> append tool_result messages
  -> repeat
  -> assistant final answer
```

## Non-Goals

- Do not rebuild document parsing, TOC generation, OCR, or search ranking.
- Do not introduce LangGraph in this phase.
- Do not force all providers to support native tool calls. Unsupported providers may use a clearly named compatibility adapter or degrade to normal chat.
- Do not expose hidden chain-of-thought. Processing can show concise visible status and tool actions only.
- Do not pass OCR full text, base64 images, local file paths, or large raw payloads back to the model.

## File Structure

### Backend Files To Create

- `backend/app/agent/model_tool_loop.py`
  - Owns the new flat tool loop.
  - Keeps one `messages` list for the full run.
  - Streams runtime events to the existing SSE layer.

- `backend/app/agent/model_turn.py`
  - Defines provider-neutral events:
    - `ModelTextDelta`
    - `ModelToolCallDelta`
    - `ModelToolCall`
    - `ModelTurn`
  - Does not mention planner/action.

- `backend/app/agent/tool_messages.py`
  - Converts model tool calls into executable requests.
  - Converts tool results into OpenAI-compatible `role="tool"` messages.
  - Produces compact model-facing JSON.

- `backend/app/agent/runtime_boundary_policy.py`
  - Validates tool existence, scope, web-search enablement, and argument shape.
  - May repair doc/folder ids.
  - Must not decide route or evidence sufficiency.

- `backend/tests/test_model_tool_loop_runtime.py`
  - Unit tests for loop behavior with fake model turns.

- `backend/tests/test_tool_messages.py`
  - Unit tests for tool result compaction and message construction.

- `backend/tests/test_runtime_boundary_policy.py`
  - Unit tests for tool permission and scope boundaries.

### Backend Files To Modify

- `backend/app/services/agent_service.py`
  - Add feature flag switch.
  - Build `ModelToolLoopRuntime` for `AGENT_RUNTIME_MODE=flat_tool_loop`.

- `backend/app/core/llm.py`
  - Ensure streaming native tool call deltas are exposed consistently.
  - Preserve current provider behavior for old runtime.

- `backend/app/services/tool_executor.py`
  - Keep existing tool implementations.
  - Ensure each tool returns compact next-step guidance suitable for model-facing `tool_result`.

- `backend/app/agent/nodes.py`
  - Reuse or split compact result helpers.
  - Add missing display metadata for `view_folder_structure`.

- `backend/app/agent/loop_runtime.py`
  - Do not delete immediately.
  - Move `PolicyGuidedPlanner` to legacy or remove after new runtime is default and tests pass.

- `backend/app/agent/planner.py`
  - Keep as legacy compatibility only.
  - Rename later to `json_tool_calling_compat.py` if still needed.

### Frontend Files To Modify

- `frontend/src/types/stream.ts`
  - Add/confirm stream event contracts for flat loop:
    - `processing_delta`
    - `tool_call_delta`
    - `tool_started`
    - `tool_completed`
    - `answer_delta`

- `frontend/src/stores/chat.ts`
  - Merge native tool call deltas into tool timeline rows.
  - Avoid storing verbose planner thoughts as final visible reasoning.

- `frontend/src/components/chat/RunTimeline.vue`
  - Display concise processing area.
  - Default collapsed after final answer.

- `frontend/src/components/chat/ToolTimelineItem.vue`
  - Prefer `result_label`.
  - Fix display for folder structure and page labels.

### Documentation Files To Modify

- `refactor_process.md`
  - Add a new section for this flat-loop refactor.
  - Update at start and end of every phase.

- `codex.md`
  - Only update if launch commands or runtime flag expectations change.

---

## Phase 1: Define Provider-Neutral Model Turn Events

**Files:**
- Create: `backend/app/agent/model_turn.py`
- Test: `backend/tests/test_model_turn.py`

- [ ] **Step 1: Write failing tests for model event types**

```python
from app.agent.model_turn import ModelToolCall, ModelTurn


def test_model_turn_collects_text_and_tool_calls():
    turn = ModelTurn(
        content="",
        tool_calls=[
            ModelToolCall(
                id="call_1",
                name="browse_documents",
                arguments={"folder_id": "fffbf2f9", "recursive": True},
            )
        ],
    )

    assert turn.has_tool_calls is True
    assert turn.has_final_text is False
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py -q
```

Expected: FAIL because `app.agent.model_turn` does not exist.

- [ ] **Step 3: Implement minimal event dataclasses**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    arguments_delta: str = ""


@dataclass(slots=True)
class ModelTextDelta:
    delta: str


@dataclass(slots=True)
class ModelTurn:
    content: str = ""
    tool_calls: list[ModelToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def has_final_text(self) -> bool:
        return bool(self.content.strip()) and not self.tool_calls
```

- [ ] **Step 4: Run test and verify pass**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_turn.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent/model_turn.py backend/tests/test_model_turn.py
git commit -m "feat(agent): add flat loop model turn events"
```

---

## Phase 2: Build Tool Result Messages

**Files:**
- Create: `backend/app/agent/tool_messages.py`
- Modify: `backend/app/agent/nodes.py`
- Test: `backend/tests/test_tool_messages.py`

- [ ] **Step 1: Write failing tests for tool result message construction**

```python
from app.agent.model_turn import ModelToolCall
from app.agent.tool_messages import build_tool_result_message


def test_browse_documents_tool_result_is_compact_model_json():
    call = ModelToolCall(
        id="call_1",
        name="browse_documents",
        arguments={"folder_id": "fffbf2f9"},
    )
    result = {
        "success": True,
        "documents": [
            {
                "id": "doc-a",
                "name": "Report.pdf",
                "page_count": 12,
                "description": "A report",
                "file_path": "C:/secret/Report.pdf",
            }
        ],
    }

    message, ui_result = build_tool_result_message(call, result)

    assert message["role"] == "tool"
    assert message["tool_call_id"] == "call_1"
    assert message["name"] == "browse_documents"
    assert "file_path" not in message["content"]
    assert "Report.pdf" in message["content"]
    assert ui_result["result_label"] == "1 document"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_messages.py -q
```

Expected: FAIL because helper does not exist.

- [ ] **Step 3: Implement compact tool result message builder**

Implementation rules:

- Output model-facing JSON as `message["content"]`.
- Keep only compact, useful fields.
- Strip:
  - local paths
  - base64
  - raw OCR full text
  - embeddings
  - rerank scores
- Preserve:
  - document id/name/page count/description
  - page numbers
  - snippets
  - source anchors
  - web URL/title/snippet
  - `next_steps` string
- Return both:
  - tool message for model
  - UI compact result for timeline

- [ ] **Step 4: Fix folder structure display metadata**

Add display metadata for `view_folder_structure`:

```python
if tool_name == "view_folder_structure":
    count = _coerce_positive_int(result.get("total_folders"))
    if count:
        return {"result_count": count, "result_label": _plural(count, "folder")}
```

- [ ] **Step 5: Run targeted tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_messages.py backend/tests/test_agent_run_event_protocol.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/agent/tool_messages.py backend/app/agent/nodes.py backend/tests/test_tool_messages.py backend/tests/test_agent_run_event_protocol.py
git commit -m "feat(agent): build compact tool result messages"
```

---

## Phase 3: Add Runtime Boundary Policy

**Files:**
- Create: `backend/app/agent/runtime_boundary_policy.py`
- Test: `backend/tests/test_runtime_boundary_policy.py`

- [ ] **Step 1: Write failing tests for boundary-only policy**

```python
from app.agent.model_turn import ModelToolCall
from app.agent.runtime_boundary_policy import RuntimeBoundaryPolicy


def test_policy_allows_browse_documents_without_planning_route():
    policy = RuntimeBoundaryPolicy(tools=[{"function": {"name": "browse_documents"}}])
    call = ModelToolCall(id="call_1", name="browse_documents", arguments={})

    result = policy.validate_tool_call(call, scope={})

    assert result.allowed is True
    assert result.repaired_call.name == "browse_documents"


def test_policy_does_not_reject_final_answer_for_evidence_sufficiency():
    policy = RuntimeBoundaryPolicy(tools=[])

    assert not hasattr(policy, "validate_answer_evidence")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_boundary_policy.py -q
```

Expected: FAIL because policy does not exist.

- [ ] **Step 3: Implement boundary policy**

Policy responsibilities:

- Verify tool exists.
- Block `web_search` when disabled.
- Repair known document names to doc ids when internal mapping is available.
- Normalize root folder ids.
- Reject doc ids outside selected scope.
- Reject invalid JSON arguments.
- Return a tool error result instead of throwing when possible.

Policy must not:

- Choose next tool.
- Force document structure before page content.
- Force page image after visual evidence.
- Decide whether final answer has enough evidence.

- [ ] **Step 4: Run tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_runtime_boundary_policy.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent/runtime_boundary_policy.py backend/tests/test_runtime_boundary_policy.py
git commit -m "feat(agent): add boundary-only tool policy"
```

---

## Phase 4: Implement ModelToolLoopRuntime With Fake Model

**Files:**
- Create: `backend/app/agent/model_tool_loop.py`
- Test: `backend/tests/test_model_tool_loop_runtime.py`

- [ ] **Step 1: Write failing test for one tool call then final answer**

```python
import pytest

from app.agent.model_tool_loop import ModelToolLoopRuntime
from app.agent.model_turn import ModelToolCall, ModelTurn
from app.agent.state import AgentRunState


class FakeModel:
    def __init__(self):
        self.calls = 0

    async def stream_turn(self, *, messages, tools, user_id=None):
        self.calls += 1
        if self.calls == 1:
            yield ModelTurn(
                tool_calls=[
                    ModelToolCall(
                        id="call_1",
                        name="browse_documents",
                        arguments={"folder_id": "fffbf2f9", "recursive": True},
                    )
                ]
            )
        else:
            yield ModelTurn(content="当前文件夹里有 3 个文档。")


class FakeToolRunner:
    async def execute(self, tool_name, arguments):
        return {
            "success": True,
            "documents": [
                {"id": "doc-a", "name": "A.pdf"},
                {"id": "doc-b", "name": "B.pdf"},
                {"id": "doc-c", "name": "C.pdf"},
            ],
        }


@pytest.mark.asyncio
async def test_flat_loop_executes_tool_and_returns_final_answer():
    runtime = ModelToolLoopRuntime(
        model=FakeModel(),
        tool_runner=FakeToolRunner(),
        tools=[{"function": {"name": "browse_documents"}}],
    )
    state = AgentRunState(question="现在有哪些文档", scope={"user_id": "u1"})

    events = [event async for event in runtime.stream(state)]

    assert any(event.type == "tool_started" for event in events)
    assert any(event.type == "tool_completed" for event in events)
    assert "".join(
        event.payload.get("content", "") or event.payload.get("delta", "")
        for event in events
        if event.type == "answer_delta"
    ) == "当前文件夹里有 3 个文档。"
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py -q
```

Expected: FAIL because runtime does not exist.

- [ ] **Step 3: Implement runtime loop**

Runtime requirements:

- Build initial messages:
  - system prompt
  - compact conversation history
  - current user question
  - optional selected scope summary
- Call model with `tools`.
- If model returns tool calls:
  - emit `tool_started`
  - validate call with boundary policy
  - execute tool
  - build tool result message
  - append assistant tool call message
  - append tool result message
  - emit `tool_completed`
  - continue loop
- If model returns final text:
  - stream as `answer_delta`
  - finish run
- If max steps exceeded:
  - emit failure.

- [ ] **Step 4: Add test for no tool call greeting**

Input: `你好`

Fake model returns final text immediately.

Expected:

- no `tool_started`
- answer delta returned

- [ ] **Step 5: Add test for multiple tool calls in same model turn**

Fake model returns two tool calls:

- `get_document_structure`
- `search_within_document`

Expected:

- both execute in model-provided order
- both tool result messages are appended before next model turn

- [ ] **Step 6: Run tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/agent/model_tool_loop.py backend/tests/test_model_tool_loop_runtime.py
git commit -m "feat(agent): add flat model tool loop runtime"
```

---

## Phase 5: Add Native Tool Calling Model Adapter

**Files:**
- Create: `backend/app/agent/tool_calling_model_adapter.py`
- Modify: `backend/app/core/llm.py` if needed
- Test: `backend/tests/test_tool_calling_model_adapter.py`

- [ ] **Step 1: Write failing tests for native tool call parsing**

Test response shapes:

- non-streaming `message.tool_calls`
- streaming `delta.tool_calls`
- assistant final content with no tool calls

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_calling_model_adapter.py -q
```

Expected: FAIL because adapter does not exist.

- [ ] **Step 3: Implement adapter**

Adapter API:

```python
class ToolCallingModelAdapter:
    async def stream_turn(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        user_id: str | None = None,
    ):
        ...
```

It must:

- Call `chat_by_scenario(..., stream=True, tools=tools, tool_choice="auto")`.
- Yield `ModelTextDelta` for streamed text.
- Yield `ModelToolCallDelta` for streamed function call arguments.
- Yield one final `ModelTurn` with completed content/tool calls.
- Set `disable_thinking=True` by default.

- [ ] **Step 4: Decide unsupported provider behavior**

Implement one of:

Option A, strict:

- If provider cannot do native tool calls, return final text only and do not use tools.

Option B, compatibility:

- Introduce `JsonToolCallingCompatAdapter`.
- Mark it as compatibility mode.
- Do not call it planner.

Recommendation: implement Option B only if existing provider coverage requires it; otherwise start with Option A for clarity.

- [ ] **Step 5: Run tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_tool_calling_model_adapter.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/agent/tool_calling_model_adapter.py backend/tests/test_tool_calling_model_adapter.py backend/app/core/llm.py
git commit -m "feat(agent): add native tool calling model adapter"
```

---

## Phase 6: Wire New Runtime Behind Feature Flag

**Files:**
- Modify: `backend/app/services/agent_service.py`
- Modify: `backend/app/core/config.py` if needed
- Test: `backend/tests/test_agent_service_flat_loop_runtime.py`

- [ ] **Step 1: Write failing service integration test**

Test:

- when `AGENT_RUNTIME_MODE=flat_tool_loop`, service builds `ModelToolLoopRuntime`.
- when unset, service keeps existing runtime.

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_flat_loop_runtime.py -q
```

Expected: FAIL.

- [ ] **Step 3: Add runtime mode config**

Add:

```python
AGENT_RUNTIME_MODE = os.getenv("AGENT_RUNTIME_MODE", "legacy_loop").strip().lower()
```

Allowed:

- `legacy_loop`
- `flat_tool_loop`

- [ ] **Step 4: Add service runtime builder**

Add:

```python
def build_flat_tool_loop_runtime(...):
    model = ToolCallingModelAdapter(...)
    return ModelToolLoopRuntime(
        model=model,
        tool_runner=AgentLoopToolRunner(...),
        tools=tools,
        boundary_policy=RuntimeBoundaryPolicy(...),
    )
```

- [ ] **Step 5: Route `run_agent_stream` through flag**

Do not remove old runtime yet.

- [ ] **Step 6: Run service tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_agent_service_flat_loop_runtime.py backend/tests/test_agent_service_loop_runtime.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/agent_service.py backend/app/core/config.py backend/tests/test_agent_service_flat_loop_runtime.py
git commit -m "feat(agent): gate flat tool loop runtime behind flag"
```

---

## Phase 7: Replace Evidence Policy With Tool Guidance

**Files:**
- Modify: `backend/app/services/tool_executor.py`
- Modify: `backend/app/agent/runtime_boundary_policy.py`
- Modify: `backend/app/prompts/__init__.py`
- Test: `backend/tests/test_flat_loop_tool_guidance.py`

- [ ] **Step 1: Write tests for inventory question behavior**

With selected folder:

- Model should have enough tool descriptions to choose `browse_documents`.
- Runtime must not force `view_folder_structure`.

Use fake model to assert the runtime does not inject route instructions.

- [ ] **Step 2: Rewrite system prompt**

Remove JSON action language from the flat runtime prompt.

Use principles:

```text
You may call tools when needed.
Choose tools dynamically based on the user's question and the information gap.
When tool results are enough, answer in the user's language.
Cite document and web sources inline when using evidence.
Do not expose backend mechanics or policy checks.
```

- [ ] **Step 3: Rewrite key tool descriptions**

Update:

- `browse_documents`
- `view_folder_structure`
- `get_document_structure`
- `search_within_document`
- `get_page_content`
- `get_page_image`
- `web_search`

Descriptions should guide usage but not prescribe fixed chains.

- [ ] **Step 4: Add concise `next_steps` strings**

Examples:

- `browse_documents`: `Use document structure/search/page tools if the user asks about document contents.`
- `get_page_content`: `If visual_evidence_required is true, use get_page_image for that page.`
- `search_within_document`: `Read the matched pages before answering specific facts.`

- [ ] **Step 5: Run tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_loop_tool_guidance.py backend/tests/test_agent_navigation_tools_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/app/services/tool_executor.py backend/app/prompts/__init__.py backend/app/agent/runtime_boundary_policy.py backend/tests/test_flat_loop_tool_guidance.py
git commit -m "feat(agent): move route guidance into tool contracts"
```

---

## Phase 8: Adapt SSE Events And Frontend Timeline

**Files:**
- Modify: `frontend/src/types/stream.ts`
- Modify: `frontend/src/stores/chat.ts`
- Modify: `frontend/src/components/chat/RunTimeline.vue`
- Modify: `frontend/src/components/chat/ToolTimelineItem.vue`
- Test: `frontend/src/stores/chat.test.ts`
- Test: `frontend/src/components/chat/RunTimeline.contract.test.ts`
- Test: `frontend/src/components/chat/ToolTimelineItem.contract.test.ts`

- [ ] **Step 1: Write frontend failing tests**

Test:

- `tool_call_delta` creates one pending tool row.
- `tool_completed` updates the same row.
- `processing_delta` is concise.
- Completed answer collapses processing.
- `view_folder_structure` displays `1 folder`, not `0 results`.

- [ ] **Step 2: Run frontend tests and verify failure**

Run:

```powershell
npm.cmd test -- src/stores/chat.test.ts src/components/chat/RunTimeline.contract.test.ts src/components/chat/ToolTimelineItem.contract.test.ts
```

Expected: FAIL for missing or incorrect behavior.

- [ ] **Step 3: Implement store changes**

Rules:

- Tool rows are keyed by `tool_call_id` when present.
- Do not create duplicate rows for `tool_call_delta` then `tool_started`.
- `answer_delta` should stream smoothly using existing buffered text.
- Do not store rejected policy thoughts as visible messages.

- [ ] **Step 4: Implement timeline changes**

UI rules:

- Default collapsed after answer starts or completes.
- Show concise title: `Processing details`.
- Tool rows show action, target, result label, elapsed time.
- Do not display raw JSON unless expanded.

- [ ] **Step 5: Run frontend tests**

Run:

```powershell
npm.cmd test -- src/stores/chat.test.ts src/components/chat/RunTimeline.contract.test.ts src/components/chat/ToolTimelineItem.contract.test.ts
```

Expected: PASS.

- [ ] **Step 6: Run frontend build**

Run:

```powershell
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend/src/types/stream.ts frontend/src/stores/chat.ts frontend/src/components/chat/RunTimeline.vue frontend/src/components/chat/ToolTimelineItem.vue frontend/src/stores/chat.test.ts frontend/src/components/chat/RunTimeline.contract.test.ts frontend/src/components/chat/ToolTimelineItem.contract.test.ts
git commit -m "feat(chat): render flat tool loop timeline"
```

---

## Phase 9: API End-To-End Tests

**Files:**
- Create: `backend/tests/test_flat_tool_loop_e2e.py`
- Modify: test fixtures as needed

- [ ] **Step 1: Add E2E test for greeting**

Input:

```json
{"question": "你好"}
```

Expected:

- no tools
- direct Chinese answer
- no document registry injected

- [ ] **Step 2: Add E2E test for selected folder inventory**

Input:

```json
{
  "question": "现在有哪些文档",
  "folder_id": "fffbf2f9",
  "include_subfolders": true,
  "strict_scope": true
}
```

Expected:

- one `browse_documents` call is enough
- no `view_folder_structure`
- answer lists three documents

- [ ] **Step 3: Add E2E test for document content question**

Input:

```json
{
  "question": "重庆师范大学有什么 AI 应用的创新？",
  "document_ids": ["c0c48156"],
  "strict_scope": true
}
```

Expected:

- model chooses tools freely
- final answer references p.43
- no policy evidence rejection is visible

- [ ] **Step 4: Add E2E test for same-conversation follow-up**

First ask the Chongqing question, then ask:

```text
它具体怎么服务陆海新通道？
```

Expected:

- prior messages/tool results are available in flat history.
- repeated identical tool calls should be avoided when cached tool result is sufficient.

- [ ] **Step 5: Add E2E test for Web Search**

Input:

```json
{
  "question": "北京今天天气怎么样？",
  "web_search_requested": true,
  "web_search_enabled": true
}
```

Expected:

- model may call `web_search`
- final answer has web citations
- web citations are marked as web sources

- [ ] **Step 6: Run E2E tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_flat_tool_loop_e2e.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/tests/test_flat_tool_loop_e2e.py
git commit -m "test(agent): cover flat tool loop e2e scenarios"
```

---

## Phase 10: Browser E2E Validation

**Files:**
- No product code required unless bugs are found.
- Optional test script: `frontend/tests/e2e/flat-tool-loop.spec.ts`

- [ ] **Step 1: Restart backend and frontend using `codex.md`**

Expected:

- backend source is current worktree.
- frontend source is current worktree.
- `/health` returns `ok`.

- [ ] **Step 2: Validate chat inventory UI**

Browser steps:

1. Log in.
2. Select `AI_Knowledge` folder.
3. Ask `现在有哪些文档`.

Expected:

- Processing shows concise tool action.
- One `Browse documents` row is sufficient.
- No `0 results`.
- Final answer lists three documents.

- [ ] **Step 3: Validate document citation preview**

Browser steps:

1. Select Chongqing AI case document.
2. Ask `重庆师范大学有什么 AI 应用的创新？`.
3. Click inline citation.

Expected:

- Right preview opens.
- PDF jumps to p.43.
- Chat area shrinks smoothly.
- Repeated same source uses same citation number.

- [ ] **Step 4: Validate Web Search citation**

Browser steps:

1. Enable Web Search in composer.
2. Ask current weather/news question.
3. Click web citation.

Expected:

- Browser opens external URL.
- No document preview drawer for web source.

- [ ] **Step 5: Record findings**

Update `refactor_process.md` with:

- commands run
- browser cases tested
- remaining issues

- [ ] **Step 6: Commit test artifacts or notes**

```powershell
git add refactor_process.md
git commit -m "docs(agent): record flat loop browser validation"
```

---

## Phase 11: Make Flat Tool Loop Default

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `codex.md`
- Modify: `start-backend.bat` only if runtime env needs explicit default
- Test: regression suite

- [ ] **Step 1: Change default runtime mode**

Default:

```text
AGENT_RUNTIME_MODE=flat_tool_loop
```

Keep rollback:

```text
AGENT_RUNTIME_MODE=legacy_loop
```

- [ ] **Step 2: Run backend regression**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests/test_model_tool_loop_runtime.py backend/tests/test_tool_calling_model_adapter.py backend/tests/test_tool_messages.py backend/tests/test_runtime_boundary_policy.py backend/tests/test_flat_tool_loop_e2e.py backend/tests/test_agent_service_flat_loop_runtime.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend regression**

Run:

```powershell
npm.cmd test
npm.cmd run build
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add backend/app/core/config.py codex.md start-backend.bat
git commit -m "feat(agent): default to flat tool loop runtime"
```

---

## Phase 12: Remove Or Quarantine Legacy Planner Code

**Files:**
- Modify: `backend/app/agent/loop_runtime.py`
- Modify: `backend/app/agent/planner.py`
- Modify: backend tests referencing `PolicyGuidedPlanner`
- Optional create: `backend/app/agent/legacy/`

- [ ] **Step 1: Move `PolicyGuidedPlanner` out of production module**

Options:

- Delete it if tests no longer need it.
- Or move to `backend/app/agent/legacy/policy_guided_planner.py`.

Preferred: delete.

- [ ] **Step 2: Rename `StructuredLLMPlanner` if JSON compatibility remains**

If still needed:

```text
StructuredLLMPlanner -> JsonToolCallingCompatAdapter
```

It must not be used by default.

- [ ] **Step 3: Delete `PlannerAction` from flat runtime path**

Do not delete if legacy runtime still imports it.

Add tests proving flat runtime does not import:

- `StructuredLLMPlanner`
- `PolicyGuidedPlanner`
- `PlannerAction`

- [ ] **Step 4: Run full backend tests**

Run:

```powershell
D:\projects\page_chat\backend\venv\Scripts\python.exe -m pytest backend/tests -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/agent backend/tests
git commit -m "refactor(agent): quarantine legacy planner runtime"
```

---

## Acceptance Criteria

The refactor is complete only when all items below are true:

- Production path is `ModelToolLoopRuntime`.
- Default runtime does not use `StructuredLLMPlanner`.
- Default runtime does not use `PolicyGuidedPlanner`.
- Default runtime does not use `PlannerAction`.
- A single flat message history carries model text, tool calls, tool results, and final answer.
- Final answer is generated by the same loop, not a separate answer generator.
- For `现在有哪些文档` with selected folder, the model can answer after one `browse_documents` call.
- Tool timeline does not show `0 results` for folder structure or image/page tools.
- Processing is concise and not filled with planner narration.
- Web Search works and web citations open as links.
- Document citations open right-side preview at the cited page.
- Backend targeted tests pass.
- Frontend tests and build pass.
- Browser E2E passes for:
  - greeting
  - selected folder inventory
  - document content with citation
  - same conversation follow-up
  - Web Search

## Rollback Plan

If flat runtime fails in local validation:

1. Set:

```text
AGENT_RUNTIME_MODE=legacy_loop
```

2. Restart backend using `codex.md`.
3. Confirm old runtime works.
4. Keep new files but do not make them default.
5. Fix failing phase before attempting default switch again.

## Recommended Execution Style

Use subagent-driven development for isolated phases:

- Phase 1-4: backend runtime foundation.
- Phase 5-7: model adapter, policy, tool contracts.
- Phase 8: frontend timeline.
- Phase 9-10: E2E validation.
- Phase 11-12: default switch and cleanup.

Each phase must:

- Start by reading this plan and `refactor_process.md`.
- Write failing tests first.
- Implement minimal passing code.
- Run listed tests.
- Update `refactor_process.md`.
- Commit before moving to the next phase.

