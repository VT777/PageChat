# PageChat LLM Planner Agent Loop 设计

Document type: design spec

Status: draft approved for implementation planning

Date: 2026-06-26

## 背景

当前 `AgentLoopRuntime` 已经把主路径从 hidden initial retrieval 改成了显式 loop：

```text
Planner -> ToolRunner -> Observation -> Planner -> Answer
```

但是当前 `PolicyGuidedPlanner` 仍然是规则/模板 planner。它可以保证流程稳定，却带来三个产品问题：

1. agent 行为像固定脚本，而不是自主决策。
2. visible thought 是代码模板，不是 AI 根据上下文真实输出。
3. 工具使用路线被后端写死，无法体现模型根据目录、文档结构和观察结果迭代探索的能力。

本设计的目标是保留显式 runtime、事件协议、持久化和安全边界，同时把“下一步做什么”交给模型输出。

## 核心原则

### 1. AI 决策，后端校验

模型负责生成：

- 下一步 visible thought；
- 下一步 action 类型；
- 工具名；
- 工具参数；
- 何时回答、何时澄清、何时继续探索。

后端负责：

- 校验工具是否存在；
- 校验参数是否合规；
- 注入或限制用户 scope；
- 阻止越权访问；
- 阻止证据不足的最终回答；
- 阻止无意义循环。

后端不应该规定完整固定流程。

### 2. 展示真实 visible thought，但不展示 raw chain-of-thought

PageChat 不展示 provider 原始 `reasoning_content`。

模型需要显式输出一个短的、面向用户的 `thought` 字段，例如：

```json
{
  "thought": "我先查看资料库目录，判断重庆高校案例可能在哪个文件夹中。",
  "action": {
    "type": "call_tool",
    "tool_name": "view_folder_structure",
    "arguments": {}
  }
}
```

这个 `thought` 是模型真实生成的决策说明，但不是完整私密推理链。

### 3. 工具引导，不是流程写死

模型应看到完整工具目录、工具使用约束、当前 scope、历史 observation 和 evidence pack。

后端不再把“资料库问题一定先 A 再 B 再 C”的流程写进 planner。树搜、文档结构读取、页面读取、关键词定位、web search 都是模型可选择的工具。

## 目标体验

用户问：

```text
重庆师范大学有什么 AI 应用创新？
```

理想运行轨迹不是固定模板，而是模型按观察结果推进：

```text
Thought
  我需要先判断资料库里是否有重庆高校或 AI 应用案例相关目录。

Viewed folder structure

Thought
  目录中出现“重庆/AI应用案例”线索，我继续浏览该目录下的文件。

Browsed documents

Thought
  发现一份重庆人工智能应用场景案例集，先查看结构定位重庆师范大学相关章节。

Read document structure

Thought
  结构里有重庆师范大学相关章节，需要读取对应页面作为证据。

Read pages

Answer
  ...
```

其中每个 Thought 由模型真实输出；每个 Tool 和 Observation 由后端根据实际执行结果产生。

## 架构

```text
ChatService
  -> AgentService
    -> AgentLoopRuntime
      -> AgentPolicy
      -> LLMPlannerAdapter
      -> ToolRunner
      -> ObservationBuilder
      -> AnswerGenerator
```

### AgentLoopRuntime

保留现有职责：

- 维护 loop state；
- 调用 planner；
- 执行工具；
- 记录 observation；
- 发出 PageChat runtime events；
- 控制 max steps；
- 在失败时返回可解释错误。

Runtime 不生成具体 thought 文案。

### LLMPlannerAdapter

替代当前 `PolicyGuidedPlanner`。

输入：

- 用户问题；
- 最近对话历史；
- 当前 scope；
- 可用工具目录；
- 工具 JSON schema；
- 已执行工具和 observation；
- compact evidence pack；
- policy constraints；
- 当前 step 和 max steps。

输出：

```json
{
  "thought": "string",
  "action": {
    "type": "call_tool | answer | ask_clarification | fail",
    "tool_name": "string | null",
    "arguments": {},
    "content": "string | null"
  }
}
```

要求：

- `thought` 必须简短；
- `thought` 必须匹配用户语言；
- `thought` 不得包含完整答案草稿；
- 一轮只输出一个 action；
- `answer` action 的 content 是最终回答；
- `call_tool` action 必须使用可用工具中的一个。

### AgentPolicy

Policy 不再规定固定路线，只提供边界：

- 工具白名单；
- user scope；
- selected document/folder scope；
- web search 是否允许；
- image attachment 是否允许；
- 文档事实回答是否已有足够证据；
- visual evidence 是否必须通过 image 工具验证；
- 最大工具调用次数；
- 同一工具同一参数重复调用限制。

Policy 可以拒绝 planner action，并返回 guardrail observation：

```json
{
  "kind": "guardrail",
  "message": "当前只有文档列表元信息，还不能回答文档事实，需要读取文档结构或页面内容。",
  "allowed_next_actions": [...]
}
```

然后 runtime 把 guardrail 加回 state，让模型重新规划。

### ToolRunner

继续复用现有 `ToolExecutor`。

要求：

- 工具结果进入 state 时可以保留内部 evidence；
- 发给前端的 `tool_completed.result` 必须 compact；
- 不泄漏 base64；
- 不把视觉页 OCR 全文直接暴露给模型作为最终依据；
- web search 工具只在策略允许时可用。

### ObservationBuilder

Observation 由后端基于工具结果生成事实摘要，不代替 planner thought。

示例：

```json
{
  "kind": "observation",
  "message": "找到 4 篇候选文档，其中 2 篇标题包含“重庆”和“人工智能应用”。",
  "candidate_document_ids": ["doc-a", "doc-b"],
  "candidate_pages": [],
  "evidence_sufficient": false
}
```

## Planner 协议选择

### 推荐方案：Structured JSON Planner

每一步调用模型，让模型返回严格 JSON action。

优点：

- provider 兼容性更好；
- thought 和 action 都是模型真实输出；
- 后端容易校验；
- 不依赖 provider 是否支持 native tool calling 的中间文本。

缺点：

- 每一步多一次模型调用；
- 需要处理 JSON 解析失败和 retry。

### 备选方案：Native Tool Calling Planner

直接把工具 schema 交给模型，让模型使用原生 tool calls。

优点：

- 与 OpenAI/DashScope tool calling 更接近；
- 可能减少一层解析。

缺点：

- 很多 OpenAI-compatible provider 对 tool call streaming、assistant text before tool call 支持不一致；
- visible thought 不稳定；
- 更难保证一轮只有一个 action。

### 不推荐：规则 Planner 加模板 Thought

这就是当前实现的形态。它稳定但不智能，用户已经能明显感知到模板化。

## Prompt 设计

Planner system prompt 应强调：

- 你是 PageChat 的 planner；
- 你只决定下一步，不写完整答案，除非 action 是 `answer`；
- 你可以自由选择工具；
- 你需要根据 observations 迭代；
- 你必须遵守 policy constraints；
- 你必须让 thought 简短、真实、面向用户；
- 你不能输出 raw chain-of-thought；
- 输出必须是 JSON。

简化示例：

```text
You are PageChat's planning controller.
Choose the next single action based on the user's question, available tools,
observations, evidence, and policy constraints.

Return JSON only.
The thought is a short user-visible decision note, not hidden chain-of-thought.
Do not draft the final answer unless action.type is answer.
```

## 错误处理

### JSON 解析失败

Runtime 发出 `progress(kind=guardrail)`：

```text
Planner output was invalid. Retrying with stricter JSON format.
```

最多 retry 1 次；仍失败则返回 `run_failed`。

### 工具不存在

Policy 拒绝该 action，把可用工具列表压缩后交给 planner 重新规划。

### 参数不合法

Policy 尝试做安全补全，例如 selected document scope 下缺少 `doc_id` 时可注入 doc_id。

无法补全时，返回 guardrail 让 planner 重试。

### 证据不足但 planner 想回答

Policy 拒绝 answer action，说明当前缺少哪类证据。

### 重复循环

Runtime 记录 tool signature：

```text
tool_name + normalized arguments
```

重复调用同一签名时，除非上一轮 observation 明确建议 retry，否则拒绝并要求 planner 换策略或回答无法确认。

## 测试策略

### 单元测试

- `LLMPlannerAdapter` 能解析合法 JSON。
- 非法 JSON 会 retry。
- thought 进入 progress event。
- `answer` action 进入 answer_delta。
- `call_tool` action 进入 ToolRunner。
- policy 能拒绝不存在工具。
- policy 能拒绝证据不足回答。
- policy 能阻止重复工具调用。

### 集成测试

- 文档库问题不再固定模板，但第一步由模型 action 决定并可被 policy 校验。
- exact filename 问题给 planner matched candidates，而不是后端直接决定整条路线。
- selected document 问题可以由模型选择 `get_document_structure` 或 `search_within_document`。
- web search 关闭时，模型不能调用 `web_search`。
- web search 开启或用户要求时，模型可以调用 `web_search`。
- 视觉页必须经过 image 工具。
- 新 run 不产生 legacy events：`thinking/content/tool_call/tool_result/done`。

### 产品场景测试

1. `重庆师范大学有什么 AI 应用创新？`
   - 期望：AI 自己说明为什么看目录、为什么选某文档、为什么读某页。

2. `中国AI+营销趋势洞察2026.pdf 主要讲什么？`
   - 期望：后端提供 filename candidates，AI 自己决定读结构和页面。

3. `这份文档第 4.1 节讲了什么？`
   - 期望：AI 根据 selected document scope 决定结构或关键词定位。

4. `北京天气怎么样？`
   - 期望：没有文档工具；Web Search 开启时可以用 web search。

5. `你好`
   - 期望：直接回答，不调用工具。

## 迁移步骤

### Phase 1: 保留当前 Runtime，替换 Planner 接口

- 新增 `backend/app/agent/planner.py`
- 定义 `PlannerAdapter` interface
- 当前 `PolicyGuidedPlanner` 标记为 fallback/test planner
- 新增 `StructuredLLMPlanner`

### Phase 2: 引入 AgentPolicy

- 新增 `backend/app/agent/policy.py`
- 从当前 `PolicyGuidedPlanner` 中抽出 guardrails
- policy 只校验，不规定完整流程

### Phase 3: Runtime 接入 retry/guardrail

- planner action -> policy validate
- invalid -> progress guardrail -> planner retry
- valid call_tool -> execute
- valid answer -> evidence gate -> final answer

### Phase 4: Prompt 和工具目录优化

- 给 planner 单独 prompt
- 工具说明面向“何时使用”，不写死“必须第几步”
- observation/evidence pack 控制长度

### Phase 5: 前端体验微调

- Thought 展示模型 thought
- Guardrail 作为轻量系统提示折叠在 thought 内
- Tool rows 保持一行一个

## Acceptance Criteria

- visible thought 是模型根据当前 state 生成，不是固定模板。
- agent 可以在工具之间自主选择路线。
- 后端只做安全、权限、证据、循环控制。
- 文档库问题可以通过树搜，但不是硬编码流程。
- selected document、folder、multi-doc、web search 都由统一 planner 决策。
- 不展示 raw chain-of-thought。
- 不恢复旧 hidden initial retrieval。
- 所有 run events 仍符合 PageChat event protocol。

## 非目标

- 不在本阶段引入 LangGraph。
- 不做多 agent。
- 不做跨 run durable resume。
- 不展示 provider raw reasoning。
- 不把 policy 变成完整 deterministic planner。

## 结论

PageChat 下一步应该从“规则型显式 loop”升级为“LLM planner 驱动的显式 loop”。

正确边界是：

```text
AI 自主规划下一步
后端校验安全和证据
工具提供真实观察
AI 基于观察继续规划
最终答案由证据支撑
```

这样才能同时获得：

- 官方产品式的交互感；
- agent 自主探索能力；
- 可控的权限和证据边界；
- 可测试、可持久化、可回放的运行轨迹。
