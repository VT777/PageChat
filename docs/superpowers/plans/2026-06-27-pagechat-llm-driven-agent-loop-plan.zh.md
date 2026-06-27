# PageChat LLM-Driven Agent Loop 优化计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PageChat 的 Agent Runtime 调整为真实的 LLM-driven agent loop：模型每轮自主判断下一步调用工具还是回答，后端只负责执行、边界、安全、证据和引用约束。

**Architecture:** 保留当前单线程 AgentLoopRuntime 思路，但弱化后端阶段规划；用模型上下文、工具定义、observation 和 prompt 原则引导模型。UI 将 processing/thinking 与工具调用作为一个可展开过程区域，最终回答完成后默认折叠过程。

**Tech Stack:** FastAPI / Python backend, Vue frontend, SQLite, OpenAI-compatible Chat Completions tool calling when available, JSON action fallback for providers without native tool calls, provider capability flags, existing SSE event protocol.

---

## 1. 核心判断

PageChat 后续不应该继续向“后端分层 planner -> policy -> 固定工具顺序 -> answer”发展。正确目标是：

```text
User message + history + selected scope + compact observations + tool definitions
  -> Model decides:
       - emit short processing text
       - call one or more tools
       - ask clarification
       - or produce final answer
  -> Runtime validates boundary
  -> Runtime executes tools
  -> Observations return to model context
  -> Loop continues until model answers or reaches limits
```

后端 scaffold 的职责是控制边界，不控制路线。

允许后端控制：

- 可用工具集。
- 用户选中的文件、文件夹、Web Search、图片附件等权限范围。
- 工具参数 schema、doc_id 映射、文件夹 scope 修复。
- 文档越权、Web Search 未开启、引用绑定失败、最大轮数等 guardrails。
- 工具结果压缩、证据缓存、SSE 事件协议。

不允许后端控制：

- 文档问题是否必须先 browse。
- 单文档问题是否必须先 structure。
- 搜索后是否必须读页面。
- 读页面后是否必须看图片。
- 什么时候证据“足够深入”。
- 最终回答前必须经历哪些阶段。

这些应由模型根据上下文自主判断。

---

## 2. UI 目标

不强求前端逐条展示“一句 thought + 一个工具动作”。更自然的 UI 是：

- 模型执行期间显示一个 `Thinking` / `Processing` 区域。
- 区域内包含模型短 processing 文本和工具调用链。
- 工具调用可以逐条展开查看参数和结果。
- 最终回答开始后，processing 区域可以继续展示实时状态。
- 最终回答完成后，processing 区域默认折叠为：

```text
Thought for 8 seconds
Used 4 tools
```

展开后看到：

```text
我会先定位两份文档的关键章节，再补读相关页面。
Read pages 6-13,17-35 from "2026年快消行业AI营销增长白皮书.pdf"
Read pages 4-8,11,14-19 from "2025年度重庆市人工智能应用场景典型案例集.pdf"
View page 18 image from "中国AI+营销趋势洞察2026.pdf"
```

UI 原则：

- 可以展示 thought，但必须短、自然、用户可读。
- 不展示后端 policy、guardrail、JSON schema、Python 异常等内部机制。
- 不要求每个工具调用前都有一条 thought。
- 不要求 thought 和工具动作一一对应。
- 工具标题必须清楚表达“做了什么”，而不是只显示工具函数名。
- processing 流式是渐进增强：支持时流式显示模型输出的 processing；不支持时显示稳定的 runtime 状态。
- 不伪造模型 thinking。没有模型文本流时，只显示 `Thinking...`、`Reading pages...` 等 PageChat 自己的状态。

---

## 3. Agent Loop 目标形态

### 3.1 ModelTurn

引入统一概念：`ModelTurn`。

每轮模型可以返回：

```json
{
  "processing": "我会补读两份文档中尚未覆盖的关键章节。",
  "tool_calls": [
    {
      "name": "get_page_content",
      "arguments": {
        "doc_id": "doc_a",
        "pages": "6-13,17-35,38-41"
      }
    }
  ],
  "final_answer": null,
  "clarification": null
}
```

或者：

```json
{
  "processing": "",
  "tool_calls": [],
  "final_answer": "......",
  "clarification": null
}
```

当前 `PlannerAction` 可以作为第一阶段兼容层，但语义上应从“后端 planner action”调整为“模型本轮决策”。

### 3.2 Native Tool Calling First

优先支持 OpenAI-compatible Chat Completions 的 native tool calls：

- 模型直接看到工具 schema。
- 模型直接返回 `tool_calls` 或 answer。
- Runtime 执行工具并追加 tool observations。

对不支持 tool calling 的模型，保留 JSON fallback：

- 模型按 JSON schema 返回 `processing/tool_calls/final_answer`。
- fallback 是兼容路径，不应成为主要架构定义。

### 3.3 Multiple Tool Calls

模型应能一轮返回多个工具调用，尤其是：

- 多文档比较时，同时读取两份文档结构。
- 已知关键页时，同时读取多个文档的页段。
- Web Search 和文档读取可以根据模型判断组合。

Runtime 可并发执行互不依赖的工具调用，但仍要逐个校验 scope 和参数。

### 3.4 Streaming Semantics

processing 可以流式，但不能作为所有模型/供应商的强保证。PageChat 需要把“模型流式能力”和“runtime 状态流式”分开。

稳定事件：

```text
processing_delta       # provider 支持文本流时，由模型生成；否则可为空
tool_call_delta        # provider 支持 tool call 参数流时，由模型生成；否则可为空
tool_started           # PageChat runtime 稳定发出
tool_completed         # PageChat runtime 稳定发出
tool_failed            # PageChat runtime 稳定发出
answer_delta           # 最终回答流式输出
```

设计规则：

- 支持 native streaming text + tool calls 的 provider：流式显示模型 processing、工具参数增量、工具执行状态和最终回答。
- 只支持 tool call streaming 的 provider：显示 runtime `Thinking...`，工具调用出现后显示工具动作。
- 不支持 native streaming tool calls 的 provider：使用 JSON fallback；可 best-effort 解析 processing，但不把它作为强依赖。
- 不依赖隐藏 chain-of-thought。可见 processing 是用户可读进度说明，不是模型内部完整推理。
- 如果 provider 强制 tool_choice 后不会输出前置自然语言，则不要为了 processing 强制 tool_choice；优先让模型 `auto` 决策。

---

## 4. Prompt 设计原则

当前 prompt 不应继续写成流程表：

```text
Single document QA -> get_document_structure -> get_page_content -> answer
Multi document comparison -> browse_documents -> structure -> fetch pages -> compare
```

应改为原则和工具选择提示：

```text
You decide whether to answer, ask for clarification, or call tools.
Use tools only when they add information needed for this turn.
Do not repeat a tool call with the same arguments unless the observation says the result was incomplete.
If selected scope already answers an inventory/count question, answer directly.
For document claims, cite evidence from document pages, images, tables, or web sources.
If a page observation says visual_evidence_required, inspect the image before making visual/layout claims.
```

Prompt 需要覆盖：

- 模型自主决定下一步。
- 不复述用户问题。
- processing 文本简短。
- 工具调用应围绕信息缺口。
- `next_steps` 是建议，不是强制路线。
- 回答语言跟随用户最新问题。
- 引用贴近 claim，不集中堆到底部。

---

## 5. Policy / Guardrail 设计原则

Policy 不应该替模型规划路径。它只做硬边界。

允许 policy 做：

- 工具是否存在。
- Web Search 是否开启。
- 文档和文件夹是否在用户 scope 内。
- doc_name/doc_id 是否可映射。
- 工具参数是否合法。
- 重复工具调用是否明显无意义。
- 最终回答是否有可引用证据。
- 视觉页是否缺少图像证据。
- 最大轮数后是否需要降级回答或询问用户。

Policy 不应输出：

```text
Read document structure, search within a selected document, or fetch page/image evidence before answering.
```

应改成更中性的 model observation：

```text
The final answer needs source evidence. Decide what information is missing and choose an available tool or ask a clarification.
```

如果是视觉页：

```text
The available page evidence is marked visual_evidence_required. Use an image-capable tool before making visual or layout-dependent claims.
```

这些 observation 给模型，不作为用户可见 thought。

---

## 6. 工具契约原则

工具不是普通后端 API，而是给 agent 用的行动接口。每个工具都需要：

- 简短明确的 description。
- 清楚的参数说明和示例。
- 高信号返回值。
- 低 token 成本。
- 可修复错误。
- 真实来源绑定。
- `next_steps` 短字符串，仅作为建议。

统一轻量返回字段：

```json
{
  "success": true,
  "result_count": 19,
  "result_label": "19 pages",
  "next_steps": "Use page images if visual details are required."
}
```

文档页面工具额外返回：

```json
{
  "doc_id": "...",
  "doc_name": "...",
  "requested_pages": [6, 7, 8],
  "returned_pages": [6, 7, 8],
  "total_pages": 62
}
```

关键工具要求：

- `browse_documents`：只返回当前 scope 下的文件/文件夹，不递归污染当前目录。
- `get_document_structure`：返回完整深层结构，但要压缩描述，避免塞无效全文。
- `search_within_document`：关键词/短语匹配，不做 BM25+rerank；可基于 OCR 文本定位图片页。
- `get_page_content`：支持 `1-3,8,10-12` 多段页码；普通文本页返回文本，OCR 页标注 `source_mode=ocr_text`，视觉页标注 `visual_evidence_required=true`。
- `get_page_image` / `get_document_image`：用于视觉、图表、扫描件、版面问题。
- `web_search`：仅在用户开启、明确要求或问题需要外部实时信息时可用；网页引用点击打开 URL，不走文档预览。

---

## 7. 实施计划

### Phase 1: 架构审计与生产路径确认

**Files:**
- Read: `backend/app/agent/loop_runtime.py`
- Read: `backend/app/agent/planner.py`
- Read: `backend/app/agent/policy.py`
- Read: `backend/app/prompts/__init__.py`
- Read: `backend/app/services/agent_service.py`

- [ ] 确认生产环境实际使用的是 LLM planner，不是 fallback deterministic planner。
- [ ] 确认 answer_generator 是否导致“planner 决策”和“最终回答”上下文割裂。
- [ ] 记录当前 SSE 事件类型：processing/thought/tool_started/tool_completed/answer_delta/citation。
- [ ] 确认哪些 policy rejection 会被模型看到，哪些会被用户看到。
- [ ] 输出一份简短审计记录，作为后续修改依据。

### Phase 2: 改造 Prompt，从流程表改为模型自主原则

**Files:**
- Modify: `backend/app/prompts/__init__.py`
- Modify: `backend/app/agent/planner.py`
- Test: `backend/tests/test_agent_structured_llm_planner.py`

- [ ] 移除或弱化 `Decision Framework A/B/C/D` 的硬流程。
- [ ] 移除“when selected document, always structure before content”这类强制路径。
- [ ] 增加“模型自主决定 answer/tool/clarification”的原则。
- [ ] 增加短 processing 文本约束。
- [ ] 增加不要重复工具、不要复述用户问题、不要暴露 policy 的规则。
- [ ] 增加工具选择示例，但写成示例，不写成必须路径。

### Phase 3: Policy 改成边界守卫

**Files:**
- Modify: `backend/app/agent/policy.py`
- Modify: `backend/app/agent/loop_runtime.py`
- Test: `backend/tests/test_agent_policy.py`
- Test: `backend/tests/test_agent_loop_runtime.py`

- [ ] 将 policy rejection 文案改成中性 observation。
- [ ] 不再提示固定工具顺序。
- [ ] 保留 Web Search、scope、doc_id、重复调用、证据和视觉页 guardrails。
- [ ] 对概览类问题允许结构或目录作为足够证据。
- [ ] 对具体事实、页码、视觉细节、数字结论保留证据要求。
- [ ] 确认 policy observation 不作为用户可见 thought。

### Phase 4: 支持一轮多个工具调用

**Files:**
- Modify: `backend/app/agent/loop_runtime.py`
- Modify: `backend/app/agent/planner.py`
- Modify: `backend/app/agent/models.py` or equivalent state/action definitions if present.
- Test: `backend/tests/test_agent_loop_runtime.py`
- Test: `backend/tests/test_agent_run_event_protocol.py`

- [ ] 扩展模型动作结构，从 single action 支持 `tool_calls[]`。
- [ ] Runtime 对每个 tool call 独立执行 policy validation。
- [ ] 可并发执行互不依赖的工具调用。
- [ ] 工具结果按原顺序回写 observation。
- [ ] 如果部分工具失败，模型下一轮看到失败 observation，自主修正。
- [ ] 保留 single action 兼容路径，降低改动风险。

### Phase 5: Native Tool Calling Adapter

**Files:**
- Modify: `backend/app/agent/planner.py`
- Modify: model provider integration files under `backend/app/services/`.
- Test: provider/model settings tests if affected.

- [ ] 为支持 tool calling 的 provider 使用原生 tool calls。
- [ ] 对不支持 tool calling 的 provider 保留 JSON fallback。
- [ ] 明确记录 provider capability：`tool_calling`、`streaming_text`、`streaming_tool_calls`、`text_before_tool_call`、`visible_thinking`、`vision`、`embedding`、`ocr`。
- [ ] 如果用户选择的问答模型不支持 tool calling，UI 或后端要给出明确提示，或降级到 JSON fallback。
- [ ] 不假设 OpenAI-compatible provider 都完整支持 streaming tool calls；需要按 provider capability 启用。
- [ ] 如果 provider 不支持 tool 前自然语言流，前端显示 runtime 状态，不伪造模型 processing。

### Phase 6: 工具契约修正

**Files:**
- Modify: `backend/app/agent/nodes.py`
- Modify: tool schemas wherever defined.
- Test: relevant backend tool tests.

- [ ] `get_page_content` 支持自然多段页码字符串。
- [ ] 统一 `success/result_count/result_label/next_steps`。
- [ ] 修正 `get_document_structure`、`get_page_image`、`get_document_image` 显示 `0 results` 的问题。
- [ ] 明确 OCR/text/visual evidence source mode。
- [ ] `search_within_document` 改为关键词/短语匹配语义，不误导模型以为是语义检索。
- [ ] 工具错误返回可修复建议，不暴露 Python 异常。

### Phase 7: UI Processing / Thinking 区域

**Files:**
- Modify: `frontend/src/components/chat/RunTimeline.vue`
- Modify: `frontend/src/components/chat/ToolTimelineItem.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Test: `frontend/src/components/chat/RunTimeline.contract.test.ts`
- Test: `frontend/src/components/chat/ToolTimelineItem.contract.test.ts`

- [ ] 将 thought/tool calls 统一放入 processing 区域。
- [ ] 回答完成后默认折叠 processing。
- [ ] 展开后显示短 processing 文本和清晰工具动作。
- [ ] 不显示 policy/internal/backend mechanics。
- [ ] 工具标题优先使用 action label。
- [ ] 参数和结果放进展开详情。
- [ ] 网页引用点击直接打开 URL。
- [ ] 支持 `processing_delta`，但没有模型文本流时展示 `Thinking...` 或工具状态。
- [ ] 支持 `tool_call_delta` 的增量展示；不支持时在 `tool_started` 后一次性展示工具动作。

### Phase 8: 回答与引用

**Files:**
- Modify: `backend/app/agent/citations.py`
- Modify: `backend/app/prompts/__init__.py`
- Modify: frontend citation preview components if needed.
- Test: `backend/tests/test_agent_citation_bindings.py`
- Test: frontend citation preview tests if present.

- [ ] 文档引用绑定到真实文档和页码。
- [ ] 网页引用绑定到 URL/title，不进入文档预览。
- [ ] 同一来源重复出现应复用一致 citation identity。
- [ ] 引用贴近 supported claim，不集中堆在回答末尾。
- [ ] 没有证据来源的问题不应强行插引用。

### Phase 9: 回归测试与验收

**Files:**
- Test: backend agent tests.
- Test: frontend timeline tests.
- Manual: browser at `http://localhost:5173`.

- [ ] `你好`：不调用工具，快速回答。
- [ ] `当前有哪些文档`：模型可选择 browse 或根据 selected scope summary 直接回答。
- [ ] 指定文件夹后问某主题：模型不应机械不信任 scope，但可以在信息不足时主动 browse。
- [ ] 两文档深度比较：模型可以一轮发出多个读取动作。
- [ ] 图片页问题：模型根据 visual evidence 调用图像工具。
- [ ] Web Search 问题：用户开启后才调用 web_search。
- [ ] 引用点击：文档打开右侧预览，网页打开 URL。
- [ ] 最终 processing 折叠，展开后轨迹清楚、无后端废话。
- [ ] provider 支持 processing 流时，前端能边生成边显示。
- [ ] provider 不支持 processing 流时，前端仍能稳定显示工具执行状态。

---

## 8. 风险与取舍

- Native tool calling 会受到不同 provider 能力差异影响，因此必须保留 JSON fallback。
- Processing streaming 会受到 provider 限制，因此必须做 capability detection，不能把 tool 前自然语言流作为硬依赖。
- 多工具调用会增加事件协议复杂度，但能显著减少机械多轮循环。
- Policy 弱化后，模型可能更自由，但也需要更好的工具描述和测试集来约束质量。
- UI 折叠 processing 后，调试信息不应丢失；开发模式可以保留更详细的展开内容。
- 不应为了追求“像官方”而隐藏真实失败。失败可以展示，但要以用户可理解方式展示。

## 9. 推荐执行顺序

1. Phase 1：先确认当前真实生产路径，避免继续在错误层修补。
2. Phase 2 + Phase 3：先把 prompt 和 policy 从 workflow 拉回 agent。
3. Phase 6：修工具契约，让模型拿到更好 observation。
4. Phase 7：调整 UI processing 展示。
5. Phase 4 + Phase 5：再做多工具调用和 native tool calling。
6. Phase 8 + Phase 9：收口引用和回归测试。

这个顺序可以先改善智能感和观感，再逐步靠近真正的 tool-calling agent runtime。
