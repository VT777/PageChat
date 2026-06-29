# PageChat 显式 Agent Loop Runtime 设计

Document type: architecture explanation / implementation reference

Audience: PageChat 后端、前端和后续接手实现的 agent 开发者。

Goal: 恢复并规范 PageChat 的核心 agent 体验：agent 先产生可见计划，再迭代使用工具、观察结果、继续决策，最后基于证据回答。本文取代“后端先执行 deterministic retrieval，再把 evidence 交给模型”的运行时编排方向。

Status: design draft for implementation.

## 背景

重构前的 PageChat 已经具备一个 function-calling agent loop 雏形：

1. 调用模型，并传入工具列表。
2. 模型流式输出 `reasoning_content` 和工具调用。
3. 后端执行工具。
4. 工具结果追加回上下文。
5. 继续下一轮模型调用。
6. 没有工具调用时输出最终答案。

这个旧实现的问题是 raw provider thinking 过长、语言混杂、不可控，也有 deterministic initial retrieval 混入第一步。但它的产品体感更接近用户期望：先 thought，再调用工具，再观察，再继续。

当前重构后的问题是：

- 运行时把 raw thinking 移除了，但没有补上 PageChat 自己的可见计划/观察事件。
- 后端先执行 `_execute_initial_retrieval_plan()`，导致第一步经常不是 agent 自己决策。
- 文件夹目录树搜没有成为默认核心路径。
- `PageChatAgentGraph` 是自研顺序节点执行器，没有接入主聊天 API，也不是完整 agent loop。
- 事件协议、引用、持久化等底座有价值，但没有改善最核心的 agent 行为。

因此本文设计的目标不是回退旧版本，而是保留现有底座，重新定义 runtime 编排。

## 核心决策

### 1. 使用统一 agent loop，不再保留独立 deterministic initial retrieval

目标流程：

```text
plan_next_action
  -> execute_tool
  -> observe
  -> plan_next_action
  -> execute_tool
  -> observe
  -> ...
  -> answer
```

不再使用：

```text
backend initial retrieval
  -> model loop
  -> answer
```

原因：

- 两套决策脑袋会让流程变硬。
- agent 的第一步不透明，用户看不到“为什么这么查”。
- 树搜会被 `browse_documents(query=...)` 之类的捷径绕开。
- 产品体验不像官方 PageIndex/ChatGPT 工具流。

### 2. policy 约束 agent，而不是单独前置流程

完整 agent loop 不等于完全放任模型。PageChat 需要 policy guardrails：

- 什么场景允许工具。
- 第一类文档问题是否必须从目录树开始。
- 什么时候不能直接回答。
- 哪些工具必须在已有 scope 后才能调用。
- 什么时候需要视觉证据。

policy 是 loop 内部的约束，不是 loop 之前先执行一遍工具。

### 3. 不展示 raw chain-of-thought

PageChat 不展示或保存 provider 原始 `reasoning_content`。

前端显示的是 PageChat 可控的 visible trace：

- plan: “我先查看文件夹结构，定位可能相关的目录。”
- observation: “发现 1 个候选文件夹，继续浏览其中的文档。”
- decision: “找到 4 篇候选文档，先读取最相关文档的结构。”
- evidence note: “命中第 4.1 节，继续读取对应页面。”

这些是产品化的运行轨迹，不是模型私有长思考。

### 4. 暂不引入官方 LangGraph 作为必要依赖

当前不需要立刻把 runtime 迁到 LangGraph。

理由：

- PageChat 现在需要的是单 agent loop，不是复杂多 agent 图。
- 现有 ToolExecutor、事件协议、run 持久化、模型网关可以复用。
- 官方 LangGraph 适合后续的 durable execution、human-in-the-loop、多分支、多 agent 和长期任务。
- 先实现 PageChat-owned runtime wrapper，可以未来再替换底层执行器。

## 目标体验

用户提问：

```text
重庆师范大学有什么 AI 应用创新
```

如果用户没有显式选中文档，但问题明显在问资料库内容，运行轨迹应类似：

```text
Thought for 2 seconds
  我先查看资料库目录，定位可能包含重庆师范大学案例的文件夹。

Viewed folder structure · 3 folders

  发现“AI应用案例/重庆”目录可能相关，继续浏览其中的文档。

Browsed documents · 4 documents

  找到一份案例集，先读取文档结构确认具体章节。

Read document structure · 2025年度重庆市人工智能应用场景典型案例集.pdf

  结构中第 4.1 节提到重庆师范大学，继续读取对应页面。

Read pages 43-44 · 2025年度重庆市人工智能应用场景典型案例集.pdf

以下是重庆师范大学的 AI 应用创新内容...
```

这条轨迹必须由后端事件驱动，刷新或切换页面后可从 `agent_run_events` 复原。

## 术语

| Term | Meaning |
| --- | --- |
| visible thought | 给用户看的简短计划、决策或观察，不是 raw chain-of-thought。 |
| policy | PageChat 对工具使用、证据门槛、scope 安全的约束。 |
| planner | 选择下一步动作的模型适配层或确定性控制器。 |
| action | 下一步动作：调用工具、回答、澄清、失败。 |
| observation | 工具结果的简短归纳，供用户和下一轮 planner 使用。 |
| evidence | 可支撑最终回答的工具结果，通常来自页面、图片或 web 内容。 |
| tree search | 先查看文件夹目录树，再推理候选目录/文档，然后进入文档结构和页面证据。 |

## 目标架构

```mermaid
flowchart TD
    Client[Frontend Chat UI] --> ChatAPI[/api/chat/stream]
    ChatAPI --> ChatService[ChatService]
    ChatService --> RunRepo[ChatRunRepository]
    ChatService --> Runtime[AgentLoopRuntime]

    Runtime --> Policy[AgentPolicy]
    Runtime --> Planner[PlannerAdapter]
    Runtime --> ToolRunner[ToolRunner]
    Runtime --> Observer[ObservationBuilder]
    Runtime --> CitationBinder[CitationBinder]

    Planner --> ModelGateway[Model Gateway]
    ToolRunner --> ToolExecutor[ToolExecutor]
    ToolExecutor --> FolderService[FolderService]
    ToolExecutor --> DocumentService[DocumentService]
    ToolExecutor --> PageIndex[PageIndexService]
    ToolExecutor --> WebSearch[Web Search Provider]

    Runtime -->|PageChat events| ChatService
    ChatService -->|persist events| RunRepo
    ChatService -->|SSE| Client
```

### ChatService

Responsibilities:

- Create user message and assistant placeholder.
- Create one `agent_run`.
- Assign `run_id`, `conversation_id`, `message_id`, `seq`, `ts`.
- Persist every event into `agent_run_events`.
- Persist final assistant content and structured citations.
- Translate runtime events to SSE.
- Handle cancellation, failure, and client disconnects.

ChatService must not decide retrieval steps.

### AgentLoopRuntime

Responsibilities:

- Own the loop state.
- Ask policy for constraints.
- Ask planner for next action.
- Validate action against policy.
- Execute tools through ToolRunner.
- Build observations.
- Enforce max steps and evidence gates.
- Emit PageChat runtime events.

Runtime must not depend on frontend UI details.

### AgentPolicy

Responsibilities:

- Decide request mode:
  - `simple_chat`
  - `document_library`
  - `selected_document`
  - `selected_folder`
  - `multi_document`
  - `web_search`
  - `image_attachment`
- Define allowed tools.
- Define required first action, if any.
- Validate tool arguments.
- Prevent unsafe or useless loops.
- Enforce evidence sufficiency before final answer.

Policy is deterministic and heavily tested.

### PlannerAdapter

Responsibilities:

- Given state + policy constraints + compact evidence, choose the next action.
- Produce a concise visible plan message.
- Never expose raw provider reasoning.
- Use one provider protocol per run.

Planner may be implemented in two ways:

1. Native tool-calling planner:
   - Call Chat Completions with tools.
   - Request concise assistant content before tool call when provider supports it.
   - Parse native `tool_calls`.

2. Structured decision planner:
   - Ask model for JSON action:

```json
{
  "thought": "先查看资料库目录，定位可能相关的文件夹。",
  "action": {
    "type": "call_tool",
    "tool_name": "view_folder_structure",
    "arguments": {}
  }
}
```

The runtime can support both behind the same interface. For initial implementation, prefer the simpler and more testable adapter.

### ToolRunner

Responsibilities:

- Execute one validated tool call.
- Use existing `ToolExecutor`.
- Sanitize large payloads before event emission.
- Preserve full internal evidence only where safe and necessary.
- Record elapsed time.

ToolRunner does not choose tools.

### ObservationBuilder

Responsibilities:

- Convert tool result into a concise visible observation.
- Extract candidate folders/documents/pages.
- Extract citation candidates.
- Mark whether evidence is sufficient for answering.

Example:

```json
{
  "message": "找到 4 篇候选文档，其中《2025年度重庆市人工智能应用场景典型案例集》最相关。",
  "candidate_document_ids": ["doc-a"],
  "evidence_sufficient": false
}
```

## State Model

```python
class AgentLoopState:
    run_id: str
    conversation_id: str
    message_id: str
    user_id: str
    question: str
    history: list[dict]
    scope: dict
    policy: dict
    step_index: int
    max_steps: int
    allowed_tools: list[str]
    required_next_action: dict | None
    tool_results: list[dict]
    observations: list[dict]
    evidence_pack: list[dict]
    citations: list[dict]
    answer: str
    terminal_status: str | None
```

State must be serializable enough for debugging. It does not need to persist full raw model messages unless needed for resume support.

## Action Schema

Planner returns exactly one action per loop iteration.

```json
{
  "thought": "我先查看文件夹结构，定位可能相关目录。",
  "action": {
    "type": "call_tool",
    "tool_name": "view_folder_structure",
    "arguments": {}
  }
}
```

Supported action types:

| Action | Meaning |
| --- | --- |
| `call_tool` | Execute one tool. |
| `answer` | Stream final answer. |
| `ask_clarification` | Ask the user for missing scope or ambiguity. |
| `fail` | Stop with a controlled error. |

Policy may override or reject an action.

Example rejection:

```json
{
  "reason": "Document facts require page or image evidence. browse_documents metadata alone is insufficient.",
  "required_action": {
    "type": "call_tool",
    "tool_name": "get_document_structure"
  }
}
```

## Event Protocol

Reuse the current PageChat event protocol. Do not reintroduce legacy `thinking`.

### `progress`

Use `progress` for visible thought, decision, and observation.

Recommended payload:

```json
{
  "kind": "plan",
  "message": "我先查看资料库目录，定位可能相关的文件夹。",
  "step": 1
}
```

Kinds:

| kind | Purpose |
| --- | --- |
| `plan` | Planner's visible next-step intent. |
| `observation` | Concise tool-result observation. |
| `decision` | Short reason for choosing next tool or final answer. |
| `guardrail` | Policy correction, retry, or scope note. |
| `status` | Neutral lifecycle status. |

### Tool Events

`tool_started` and `tool_completed` remain one row per tool call.

Tool result payload must be compact:

- No raw base64.
- No full OCR text for visual pages.
- No full document text.
- No unbounded raw JSON.

### Answer Events

`answer_delta` is only final answer text. It must not include planning or observations.

### Citation Events

`citation_added` is emitted when structured citation candidates are bound to the answer or evidence. Document preview uses citation anchors.

## Tree Search Policy

Tree search is a core PageChat behavior.

### No explicit document, document/library question

If the user asks about uploaded content, files, folders, library contents, or a domain likely in the document library, the first action must be:

```text
view_folder_structure
```

Exceptions:

- Exact filename match for a completed document may resolve directly to that document and start with `get_document_structure`.
- User explicitly asks “有哪些文档/文件夹” may use `view_folder_structure` or `browse_documents` root depending on the wording.
- Web-only question with Web Search selected should use web search, not document tree search.

### Folder inference

After `view_folder_structure`, the planner should choose:

- `browse_documents(folder_id=..., recursive=false)` for a likely folder.
- `browse_documents(folder_id=..., recursive=true)` when the folder has relevant subfolders or the target may be nested.
- `browse_documents(folder_id="root")` for top-level browsing.
- `ask_clarification` if multiple folders are equally plausible and tool exploration would be too broad.

### Candidate document handling

`browse_documents` returns metadata only. It is not enough for final document factual claims.

After candidate documents are found:

1. Use `get_document_structure` for likely documents.
2. Use structure summaries and page ranges to choose pages.
3. Use `get_page_content` or `get_page_image`.
4. Answer only from fetched page/image evidence.

### Selected document

If a single document is explicitly selected:

- Summary / QA: first action is `get_document_structure`.
- Keyword / locating question: first action may be `search_within_document`.
- Visual page result: must use `get_page_image` or `get_document_image` before relying on image content.

### Multiple selected documents

For compare/synthesis:

1. Browse or list selected documents.
2. Inspect structure for each likely document.
3. Fetch source pages from each.
4. Answer with independent citations.

## Filename And Folder Name Resolution

Before entering the loop, ChatService or AgentPolicy may build a user-scoped name index:

- document `name`
- `original_name`
- stem without extension
- folder names and paths

This does not execute retrieval. It only gives policy and planner safe candidate IDs.

Rules:

- Exact document filename match may set `scope.matched_document_ids`.
- Exact folder name match may set `scope.matched_folder_ids`.
- Ambiguous matches remain candidates; planner must disambiguate through tools or ask.
- Never expose documents outside the current user.

This fixes prompts like:

```text
中国AI+营销趋势洞察2026.pdf 主要讲什么
```

Expected route:

```text
progress(plan: 识别到该文件，先读取文档结构)
tool_started(get_document_structure)
tool_completed
progress(observation)
tool_started(get_page_content)
...
answer_delta
```

## Evidence Gate

The runtime must block final document answers unless evidence is sufficient.

Sufficient evidence examples:

- `get_page_content` returned text for relevant pages.
- `get_page_image` or `get_document_image` returned visual evidence and the model used vision.
- Web search returned usable snippet/content preview for external facts.
- Table aggregation returned structured result rows with citations.

Insufficient evidence examples:

- Only `view_folder_structure`.
- Only `browse_documents` metadata.
- Only document title or filename.
- Only OCR locator text for a visual page without image verification.

If planner attempts `answer` too early, policy must force another tool call or ask clarification.

## Provider Compatibility

The runtime supports OpenAI-compatible Chat Completions first.

Provider differences:

- Some providers support native tool calls well.
- Some providers stream `reasoning_content`; PageChat ignores raw reasoning.
- Some providers may not emit assistant content before tool calls.
- Some providers may need JSON action mode instead of native tool calling for planner decisions.

Provider adapter must expose capabilities:

```python
supports_streaming: bool
supports_tool_calling: bool
supports_vision: bool
supports_structured_output: bool
```

One run uses one protocol. No Responses API to Chat Completions fallback inside the same answer.

## Frontend Rendering Design

`RunTimeline` should render a single ordered trace using `seq`.

Rules:

- Always show a top-level `Thought for ...` row when the run has progress or tools.
- Tool rows are one per line.
- Progress rows and tool rows are interleaved by event `seq`.
- Completed traces collapse by default but remain expandable.
- During generation, the active trace is expanded enough to show current action.
- `answer_delta` renders below the trace as final answer, not mixed into thought.
- Raw `thinking_content` is only for legacy messages.

Example visual hierarchy:

```text
Thought for 3 seconds  v
  我先查看资料库目录，定位可能相关的文件夹。
  Viewed folder structure · 3 folders
  发现“AI应用案例”目录可能相关，继续浏览。
  Browsed documents · 4 documents
  读取《案例集》的文档结构。
  Read document structure · 案例集.pdf

最终回答正文...
```

## Migration From Current Runtime

### Keep

- `ToolExecutor` and current tool contracts.
- `ChatRunRepository`.
- `agent_runs`, `agent_run_events`, `message_citations`.
- PageChat event protocol.
- Citation binding utilities.
- Frontend buffered answer rendering.

### Replace

- `_execute_initial_retrieval_plan`.
- Current ad hoc loop in `AgentService.run_agent_stream`.
- Current `RunTimeline` rule that hides thought when tools exist.
- Any reliance on raw `reasoning_content` for new runs.

### Defer

- Full official LangGraph integration.
- Cross-run resume from serialized planner state.
- Multi-agent collaboration.
- Long-running background agent tasks.

## Implementation Phases

### Phase A: Runtime Contract Tests

Add tests before code changes:

- General chat does not call tools.
- Library question starts with `view_folder_structure`.
- Exact filename question starts with `get_document_structure`.
- Selected document summary starts with `get_document_structure`.
- Selected document locating question may start with `search_within_document`.
- Final answer is blocked if only `browse_documents` evidence exists.
- Visual page evidence requires image tool verification.
- No new run emits legacy `thinking/content/tool_call/tool_result/done`.

### Phase B: AgentLoopRuntime Skeleton

Create:

- `backend/app/agent/loop_runtime.py`
- `backend/app/agent/policy.py`
- `backend/app/agent/planner.py`
- `backend/app/agent/observations.py`

Use fake planner/tool executor tests first.

### Phase C: Integrate With ChatService

Update `ChatService.stream_chat` to call `AgentLoopRuntime.stream(state)`.

Keep event metadata and persistence in ChatService.

### Phase D: Frontend Timeline Repair

Update:

- `frontend/src/components/chat/RunTimeline.vue`
- `frontend/src/components/chat/ToolTimelineItem.vue`
- `frontend/src/stores/chat.ts`

Render `progress.kind` and interleave progress/tool events by `seq`.

### Phase E: Product Golden Scenarios

Run real/manual scenarios:

1. `重庆师范大学有什么 AI 应用创新`
   - Expected: `view_folder_structure -> browse_documents -> get_document_structure -> get_page_content -> answer`.

2. `中国AI+营销趋势洞察2026.pdf 主要讲什么`
   - Expected: filename resolution -> document structure -> source pages -> answer.

3. Selected Chongqing document: `第 4.1 节讲了什么`
   - Expected: selected document scope -> structure/search -> page content -> answer.

4. `北京天气怎么样`
   - Expected: no document tools. Use Web Search only when enabled/requested.

5. `你好`
   - Expected: no tools, direct answer.

## Acceptance Criteria

- A document-library question without selected docs starts from folder tree unless exact filename match applies.
- Agent decisions are visible as concise PageChat progress events.
- Tool calls are one row each and expandable.
- Final answer never appears before necessary evidence.
- No raw provider thinking is streamed or persisted for new runs.
- `browse_documents` metadata alone cannot ground final factual answers.
- Citation preview still works from structured citations.
- Message history remains backend-backed and stable.
- The main chat API runs one unified loop, not deterministic retrieval plus model loop.
- LangGraph is not required for this milestone.

## Known Risks

### Risk: planner may skip required tree search

Mitigation: policy validates every action and can force `view_folder_structure`.

### Risk: visible thought becomes fake or repetitive

Mitigation: generate visible messages from planner action and observation, not from generic templates only. Keep them short and tied to actual events.

### Risk: extra model calls slow responses

Mitigation: start with native tool-calling where possible. Use structured planner only when provider support requires it. Keep max steps low and cache repeated structure/page reads.

### Risk: policy over-constrains agent

Mitigation: tests should cover both strict document scenarios and ordinary chat. Policy should constrain first action and evidence gates, not micromanage every step.

### Risk: current staged infrastructure makes diff large

Mitigation: implement the loop in a focused set of files and avoid unrelated frontend/design changes during this correction.

## Design Summary

PageChat should recover the old agent-loop product feel while avoiding raw provider thinking.

The new runtime should be:

- agentic in flow;
- deterministic in safety constraints;
- tree-first for document-library questions;
- evidence-gated before answers;
- provider-compatible through adapters;
- observable through persisted PageChat events;
- simple enough to implement without immediate LangGraph migration.

The most important correction is architectural: tree search is not a helper feature. It is the default entry path for document-library reasoning when the user has not selected a specific document.
