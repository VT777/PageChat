# Agent 架构落地与文档内部搜索工具分析

日期：2026-06-12  
范围：`D:\projects\page_chat` 当前代码、`D:\projects\page_chat - 副本\docs\superpowers\plans` 下 2026-06-10 相关计划、当前 `docs/superpowers` 阶段报告。

## 结论摘要

0610 的相关计划里确实讨论过“不要让单个自由 Agent 执行全部职责”，而是把文档问答拆成更清晰的层次：范围解析、候选文档检索、文档结构推理、证据读取、答案生成，以及必要时回退到函数调用 Agent。

当前代码已经部分实现了这个方向，并且不是只停留在文档层面。核心链路已经从单一 Agent 工具循环，演进为：

```text
ChatService
  -> AgentService
    -> RetrievalPlanner 先做确定性第一步
    -> ToolExecutor 执行受 user/scope 约束的工具
    -> SearchService / PageIndexService / FolderService 提供检索与结构证据
    -> 原有 function-calling Agent 继续作为后续推理和兜底
```

但它还没有完全达到“多 Agent / 多职责模块”的理想形态。现在更准确的描述是：已经实现了“单 Agent 外围的确定性检索规划层”和“工具职责拆分”，还没有实现独立的 planner agent、retriever agent、reader agent、critic agent 等多智能体协作。这个现状是合理的，比过早拆成多个 LLM Agent 更稳。

关于新增“文档内部搜索工具”：我建议新增，但要把它设计为确定性检索工具，而不是再加一个会自主推理的小 Agent。当前 `find_related_documents` 已能在 `document_ids + strict_scope=true` 下做近似的单文档节点搜索，但它的语义仍然是“找相关文档”，对长文档内定位、同一文档多节点召回、非 PDF source anchor 定位、以及 Agent 工具选择都不够直观。新增 `search_document_content` 或 `search_within_document` 有明确必要性。

## 0610 计划中的相关内容

### `2026-06-10-agent-retrieval-improvement-plan.md`

这个计划最直接对应你记得的讨论。它明确提出保留 `find_related_documents`，但把它从全局兜底工具改造成 scope-aware 文档与节点检索工具，并新增文件夹导航工具。

计划中的目标检索流是：

```text
folder tree
  -> document candidates
    -> PageIndex document tree
      -> page content
```

它提出的职责拆分包括：

- `RetrievalScopeResolver`：解析用户、选中文档、当前文件夹、严格范围或可扩展范围。
- `RetrievalPlanner`：在 LLM 自由调用工具前，先决定第一个确定性检索步骤。
- `ToolExecutor`：执行工具、强制 user/scope 授权、返回紧凑 typed 结果。
- 原有 Agent loop：保留为迁移期兜底，而不是立即移除。

这不是典型“多个 LLM Agent 互相对话”的方案，而是更工程化的职责分层：把容易确定的检索路由从 LLM 手里拿出来，把复杂答案组织仍交给 Agent。

### `2026-06-10-core-tree-retrieval-quality-plan.md`

这个计划强调 PageIndex 的核心优势不是关键词搜索，而是“树优先检索”：

```text
user query
  -> identify document scope
  -> inspect document tree
  -> select relevant nodes
  -> fetch original source content by anchor
  -> answer with citations
```

它还要求每个检索结果都带可解释元数据：

- `retrieval_source`
- `confidence`
- `why_selected`
- `source_anchor`
- `display_label`

这个计划的重点是把树推理、关键词 fallback、视觉摘要、表格聚合、多格式 source anchor 分清楚，避免所有能力混成一个黑箱。

### 当前仓库中的 Phase 1-4 计划和报告

当前仓库 `docs/superpowers/plans/2026-06-10-phase-4-folder-aware-agent-retrieval.md` 是 0610 agent retrieval 计划的阶段化执行版本。`docs/superpowers/2026-06-11-phase-4-improvement-report.md` 记录了实际完成项：

- chat request 支持 `folder_id`、`include_subfolders`、`strict_scope`。
- `SearchService.search()` 支持 folder/document/user scope 过滤。
- `ToolExecutor` 增加 `list_folder_tree`、`list_folder_contents`。
- `find_related_documents` 支持显式 scope 字段和 trace。
- `get_document_structure(compact=true)` 支持层级保留、无正文的 compact tree。
- 新增 `RetrievalPlanner`，在 Agent loop 前执行确定性第一步。

报告中还记录了验证基线：Phase 4 focused suite `45 passed`，当时 full backend suite `342 passed, 8 skipped`。

## 当前实际代码架构

### 入口层：`ChatService`

文件：`backend/app/services/chat_service.py`

`ChatService.stream_chat()` 负责：

- 创建或复用 conversation。
- 保存用户消息和 assistant 流式消息。
- 接收并转发 chat scope：`document_ids`、`folder_id`、`include_subfolders`、`strict_scope`。
- 获取当前用户可访问的 indexed documents。
- 把前端选中文档作为 `preferred_document_ids`，同时把当前用户全部可访问文档作为外层可访问范围传给 Agent。

这个设计的关键点是：前端选择文档不等于授权边界。真正的授权边界仍是当前用户的全部可访问文档；是否严格限制在选中文档，由 `strict_scope` 决定。

### 编排层：`AgentService`

文件：`backend/app/services/agent_service.py`

`AgentService.run_agent_stream()` 现在有两段式行为：

1. 先执行 `RetrievalPlanner` 给出的第一步检索。
2. 再进入原有 function-calling Agent loop，由 LLM 根据已有证据和工具结果继续调用工具或生成答案。

已经落地的关键机制：

- `user_id` 必填，缺失时直接拒绝。
- 会话缓存 key 纳入 user、document scope、folder scope、`strict_scope` 等信息，避免不同范围之间复用旧工具结果。
- 如果选中文档或文件夹且未显式传 `strict_scope`，默认 strict。
- `strict_scope=false` 时允许扩展到当前用户文档库，但不跨用户。
- 初始 planner evidence 作为 assistant 消息注入，而不是非法的 orphan tool message。

当前限制：

- `RetrievalPlanner` 只执行第一步，不负责完整多步计划。
- planner 没有基于上一轮工具结果动态改写计划。
- 后续工具调用仍依赖 LLM 自由选择，因此稳定性比纯确定性 pipeline 弱。

### 规划层：`RetrievalPlanner`

文件：`backend/app/services/retrieval_planner.py`

`RetrievalPlanner` 是当前“职责拆分”的核心落地点。它根据问题和 scope 输出：

- route：`selected_document`、`selected_folder`、`user_library`、`table_aggregation`、`agent_fallback`。
- steps：目前通常只包含第一步工具调用。
- scope trace：document、folder、是否包含子文件夹、是否 strict、是否扩展到用户文档库。

当前路由规则大致是：

- 单个选中文档且 strict：先 `get_document_structure(compact=true)`。
- 文件夹 strict：先 `find_related_documents(folder_id=..., strict_scope=true)`。
- 无显式 scope：先在当前用户库里 `find_related_documents`。
- 统计/表格类问题：先搜索候选表格文档，再交给后续 `aggregate_tables`。
- 空问题：`agent_fallback`。

这是“轻量 planner”，不是完整 agentic planner。它的好处是行为可测、可预测；缺点是对复杂问题的多步拆解能力还有限。

### 工具层：`ToolExecutor`

文件：`backend/app/services/tool_executor.py`

当前工具集包括：

- `get_document_structure`
- `list_folder_tree`
- `list_folder_contents`
- `get_page_content`
- `get_document_image`
- `find_related_documents`
- `list_documents`
- `aggregate_tables`

已经实现的职责边界：

- 文档结构工具只返回结构，compact 模式不返回 full text。
- 文件夹工具只返回 metadata，不返回正文。
- `find_related_documents` 做候选文档和节点 hint，不直接生成答案。
- `get_page_content` 获取原文证据。
- `aggregate_tables` 专门处理表格聚合。
- `_resolve_source_anchor_content()` 内部支持非 PDF anchor 内容解析，但没有暴露成 public agent tool。

当前限制：

- 没有公开的“在某个文档内部搜索”工具。
- `find_related_documents` 虽可通过 `document_ids` 退化为单文档搜索，但名称、返回结构和 prompt 语义仍偏“文档候选发现”。
- `get_page_content` 仍以 page 为主要接口，对 line/paragraph/row/slide anchor 的 agent 工具体验不统一。

### 检索层：`DocumentSearchService`

文件：`backend/app/services/search_service.py`

当前搜索服务已经有比较完整的节点级能力：

- 从 completed documents 的 PageIndex 结构中抽取节点文本建立 BM25 corpus。
- 可选 bge-small rerank。
- segment metadata 包含 user、folder、file type、node id、title、start/end index、source anchor 等。
- 搜索前先按 `user_id`、`allowed_doc_ids`、`document_ids`、`folder_id`、`include_subfolders` 过滤候选。
- 返回 matched segments，并带 `source_anchor`、`display_label`、`retrieval_source`、`confidence`、`why_selected`。

也就是说，新增“文档内部搜索工具”不需要新建一套索引。它可以复用 `SearchService.search(document_ids=[doc_id])`，只是在工具语义、返回结构和下一步动作上做更明确的封装。

### 前端范围集成

文件：`frontend/src/views/ChatView.vue`、`frontend/src/api/index.ts`、`frontend/src/stores/chat.ts`

当前前端已经能构造聊天 scope：

- 选中文档：发送 `document_ids + strict_scope=true`。
- 当前文件夹：发送 `folder_id + include_subfolders=false + strict_scope=true`。
- 当前文件夹及子文件夹：发送 `folder_id + include_subfolders=true + strict_scope=true`。
- 全部文档：不发送额外 scope。

`chat.ts` 也已经能从工具结果中收集 scope trace、fallback 来源和 evidence chips。这说明 Phase 4 后续的前端 evidence 集成也已有落地迹象。

## 实现对照：计划是否落地

| 计划目标 | 当前状态 | 说明 |
| --- | --- | --- |
| 不让单个 Agent 完全自由决定检索路径 | 部分完成 | `RetrievalPlanner` 已先执行确定性第一步，但后续仍回到 Agent loop。 |
| user/scope 安全边界 | 基本完成 | `ToolExecutor` 要求 `user_id`；搜索按 user、allowed docs、document/folder scope 过滤。 |
| 文件夹优先检索 | 基本完成 | 后端有 folder tools、folder scope search；前端可发送 folder scope。 |
| `find_related_documents` scope-aware | 已完成主要部分 | 支持 `folder_id`、`include_subfolders`、`document_ids`、`strict_scope` 和 trace。 |
| compact tree retrieval | 已完成主要部分 | `get_document_structure(compact=true)` 保留层级并去除正文。 |
| tree-first policy | 部分完成 | prompt 和 planner 已体现；但实际后续步骤仍依赖 LLM 是否遵守。 |
| retrieval trace | 基本完成 | 搜索结果和 matched segments 有 trace 字段；前端也开始消费。 |
| source anchor 内容读取 | 部分完成 | 内部 resolver 存在，非 PDF anchor 可解析；但没有 public tool，Agent 仍主要使用 page content。 |
| 完整多 Agent 架构 | 未实现，也暂不建议急着实现 | 当前是模块化单 Agent + deterministic planner，更适合现阶段。 |

## 架构评价

### 做得好的地方

1. 先拆确定性职责，而不是盲目拆多个 LLM Agent。

   检索问答系统最容易出问题的是权限、范围、证据定位和缓存污染。这些问题用普通代码比用多个 Agent 更可靠。当前把 scope、planner、executor、search 拆开，是正确方向。

2. Scope 语义已经比较清楚。

   `user_id` 是外层授权边界，`document_ids/folder_id` 是内层检索范围，`strict_scope=false` 只能扩展到当前用户库。这是非常重要的产品级边界。

3. PageIndex tree-first 的核心还保留着。

   选中文档时先看 compact structure，全局或文件夹问题先找候选文档再看结构。虽然实现还不完美，但没有退化成纯 chunk RAG。

4. 多格式 source anchor 的方向正确。

   代码已经承认非 PDF 不应该伪装成 page-only 模型，line、paragraph、row、slide 等 anchor 已进入 adapter、search、preview、resolver 链路。

### 主要问题

1. Planner 只做第一步，链路仍容易被 LLM 工具选择带偏。

   比如 `find_related_documents` 返回 matched segments 和 recommended next action 后，后续是否直接读取命中页、是否先看结构、是否误用 `list_documents`，仍由 LLM 决定。对高频问答来说，可以继续把第二步也确定性化。

2. 工具命名与能力边界还不够贴合。

   `find_related_documents(document_ids=[doc])` 实际能做单文档内部节点搜索，但这个用法不直观。Agent 看到工具名时会把它理解成“多文档候选发现”，不一定会用它做文档内定位。

3. Anchor-first evidence 还没有成为 Agent 主接口。

   内部 `_resolve_source_anchor_content()` 已存在，但工具列表没有 `get_content_by_anchor`。这会导致非 PDF 证据读取仍绕回 page-like 接口或依赖预览层，而不是统一通过 anchor。

4. 检索质量闭环仍偏测试和报告，运行时可观测性不足。

   已经有 trace 字段，但还缺少结构化日志或统计：每次问答用了哪个 route、是否 expanded、是否 fallback、最终答案用了哪些 anchors、是否 citation miss。

5. 代码中仍可见中文 mojibake。

   很多源码注释和 prompt 输出在当前读取环境中显示为乱码。若文件本身也是错误编码，会影响 prompt 质量；若只是终端编码问题，则风险较小。但建议单独确认 UTF-8 保存和运行时 prompt 内容。

## 是否需要新增“文档内部搜索工具”

### 我的判断：需要，但应作为检索工具而不是新 Agent

新增工具有必要，原因有五点。

第一，当前工具缺少一个语义清晰的“单文档内部定位”入口。用户选中某个长文档后，经常问的是“这份文档哪里提到 X”“找到关于 Y 的条款”“帮我定位风险披露”。此时最自然的工具不是 `find_related_documents`，而是 `search_document_content(doc_id, query)`。

第二，compact tree 适合结构浏览，不适合精确全文定位。对于标题明显的问题，tree-first 很好；但对于正文里的细节、表格字段、合同条款关键词、跨章节重复概念，先搜索文档内部节点会更快。

第三，能减少 Agent 无效工具调用。当前单文档问题常见路径是 `get_document_structure -> get_page_content`。如果结构很大、标题不直接命中，Agent 可能读错页或读太多页。文档内部搜索可以直接返回 node/page/anchor hints。

第四，多格式文档更需要 anchor-based 内部搜索。DOCX 的 paragraph、Markdown 的 line、Excel 的 row、PPTX 的 slide，都不适合用 page number 表达。内部搜索工具可以直接返回 `source_anchor`，再衔接 `get_content_by_anchor`。

第五，工具名称会影响 LLM 行为。即使底层复用同一个 `SearchService.search()`，给 Agent 暴露一个明确的 `search_document_content`，会比让它猜 `find_related_documents` 可以单文档搜索更可靠。

### 不建议做的版本

不建议新增一个“文档内部搜索 Agent”，让它自己决定读结构、读页、再总结。这样会引入更多不可控中间推理，也会和现有 `AgentService` 争夺职责。

也不建议新建一套独立索引。当前 `SearchService` 已有节点级 corpus 和 scope filter；新增索引会带来一致性、缓存、重建和权限边界的重复成本。

### 推荐工具设计

建议新增工具名：`search_document_content`。

输入：

```json
{
  "doc_id": "doc-1",
  "query": "renewal risk",
  "top_k": 5,
  "search_mode": "hybrid",
  "include_snippets": true
}
```

也可以允许批量文档，但我建议第一版只做单文档，避免和 `find_related_documents` 边界重叠。

输出：

```json
{
  "status": "success",
  "data": {
    "doc_id": "doc-1",
    "doc_name": "contract.docx",
    "query": "renewal risk",
    "matches": [
      {
        "node_id": "n-12",
        "title": "Renewal Terms",
        "snippet": "...",
        "confidence": 0.86,
        "retrieval_source": "document_internal_search",
        "source_anchor": {
          "format": "docx",
          "unit_type": "paragraph",
          "start_paragraph": 42,
          "end_paragraph": 48
        },
        "display_label": "contract.docx paragraphs 42-48",
        "recommended_next_action": "get_content_by_anchor"
      }
    ]
  },
  "next_steps": {
    "suggested_tool": "get_content_by_anchor",
    "reason": "Use the top anchors to fetch exact source content before answering."
  }
}
```

### 是否同时新增 `get_content_by_anchor`

我建议一起新增，或者至少把它列为同一小阶段的第二个任务。

原因是内部搜索真正返回的是 anchor，而不是 page。没有 public `get_content_by_anchor`，Agent 只能拿着 line/paragraph/row/slide anchor 发呆，或继续错误地转成 page 读取。

第一版可以这样做：

- PDF page anchor：内部转发到现有 `get_page_content`。
- TXT/Markdown line anchor：使用 `source_anchor_resolver.resolve_source_anchor()`。
- DOCX paragraph anchor：使用 resolver。
- CSV/TSV/XLSX row anchor：使用 resolver。
- PPTX slide anchor：使用 resolver。

工具输入：

```json
{
  "doc_id": "doc-1",
  "source_anchor": {
    "format": "markdown",
    "unit_type": "line",
    "start_line": 20,
    "end_line": 42
  }
}
```

### 与现有工具的关系

建议边界如下：

| 工具 | 主要职责 | 何时使用 |
| --- | --- | --- |
| `find_related_documents` | 跨文档/文件夹找候选文档和节点 hints | 用户未选文档、文件夹范围、多文档比较 |
| `get_document_structure` | 查看文档树结构 | 选中文档、标题/章节定位、需要理解结构 |
| `search_document_content` | 在单个文档内搜索正文/节点 | 长文档细节定位、结构标题不明显、需要快速命中 anchor |
| `get_content_by_anchor` | 根据 anchor 读取原文证据 | 内部搜索或 matched segment 已给出 anchor 后 |
| `get_page_content` | PDF page 兼容读取 | PDF 页码证据、旧工具兼容 |

### 推荐调用策略

对 Agent prompt 和 planner 的策略建议：

```text
选中单文档：
  1. 如果问题像章节/目录/总结：get_document_structure(compact=true)
  2. 如果问题像关键词/条款/字段/细节定位：search_document_content(doc_id, query)
  3. 拿到 source_anchor 后：get_content_by_anchor
  4. 基于原文回答并引用

未选文档或文件夹范围：
  1. find_related_documents 找候选文档
  2. 对 top 文档使用 get_document_structure 或 search_document_content
  3. get_content_by_anchor / get_page_content 获取证据
```

### 预期收益

- 长文档问答更快：减少先读大目录再猜页码的成本。
- Agent 工具选择更稳定：单文档定位有明确入口。
- 多格式检索更自然：line/paragraph/row/slide anchor 不必伪装成 page。
- 引用更准确：内部搜索返回的 anchor 可直接用于 evidence chips 和 source preview。
- 更容易测试：可以单独测 `doc_id + query -> expected node/anchor`。

### 风险和控制

1. 工具重叠风险。

   控制方式：明确 `find_related_documents` 是跨文档候选发现，`search_document_content` 是单文档内部定位。第一版不支持多 doc。

2. Agent 过度搜索风险。

   控制方式：prompt 规定结构类问题优先 tree；细节定位类问题才用 internal search。planner 可用简单 intent 判断。

3. 返回 snippet 泄露过多正文风险。

   控制方式：snippet 限长，完整证据必须再经 `get_content_by_anchor` 读取，且仍受 `user_id/allowed_doc_ids` 授权。

4. 非 PDF anchor resolver 覆盖不足。

   控制方式：第一版只承诺现有 resolver 已支持的 line、paragraph、row_range、slide、page；未知 anchor 返回清晰错误。

5. 搜索质量被误认为最终证据。

   控制方式：工具输出 `recommended_next_action=get_content_by_anchor`，prompt 要求“搜索命中不是最终证据，回答前必须读取原文”。

## 建议改进路线

### P0：保持当前架构，不急于多 Agent 化

当前最值得保留的是“确定性代码负责边界，LLM 负责理解和表达”。不建议立刻拆成多个 LLM Agent。下一步应继续增强 `RetrievalPlanner` 和工具契约，而不是引入 planner agent、retriever agent、reader agent 的复杂协作。

### P1：新增 `search_document_content` 与 `get_content_by_anchor`

建议作为一个小阶段实现：

1. 给 `ToolExecutor` 新增 `search_document_content`，底层复用 `search_service.search(document_ids=[doc_id])`。
2. 新增 public `get_content_by_anchor`，底层复用现有 `resolve_source_anchor`，PDF page anchor 转发到 `get_page_content`。
3. 更新 `AGENT_TOOLS` schema 和 prompt。
4. 增加测试：授权、单文档限制、anchor 输出、非 PDF anchor 读取、planner 路由。

### P1：让 planner 支持第二步建议

当前 planner 只执行第一步。可以先不做完整 DAG，但至少让 planner 根据第一步结果自动执行第二步：

- `find_related_documents` 高置信且有 anchor：自动 `get_content_by_anchor` 或 `get_page_content`。
- 单文档细节定位：自动 `search_document_content`。
- compact structure 低质量或 `needs_review`：强制读取 source content。

这样能减少 LLM 在工具选择上的随机性。

### P2：统一 evidence/citation contract

建议让所有证据工具统一返回：

- `document_id`
- `document_name`
- `source_anchor`
- `display_label`
- `content`
- `retrieval_source`
- `confidence`
- `quality_flags`

这样前端 evidence chip、source preview、fallback disclosure 都能少写兼容逻辑。

### P2：增加运行时检索 trace 日志

建议每次问答记录结构化 trace：

- planner route
- scope
- tools called
- selected documents/nodes/anchors
- fallback sources
- final citation count
- citation miss warning

这会让后续调检索质量不靠猜。

## 推荐验收标准

新增文档内部搜索工具后，建议至少满足：

1. 选中单个 PDF，搜索正文关键词，返回正确 node/page anchor。
2. 选中 Markdown/TXT，返回 line anchor，并能通过 `get_content_by_anchor` 读取原文。
3. 选中 DOCX，返回 paragraph anchor，并能读取原文。
4. 选中 XLSX/CSV，返回 row_range anchor，并能读取表格行。
5. 选中 PPTX，返回 slide anchor，并能读取 slide 文本。
6. 无权限 doc_id 被拒绝。
7. `allowed_doc_ids` 不能被工具参数绕过。
8. Agent 在“定位/查找/哪里提到”类问题中优先使用内部搜索。
9. 回答前必须读取 source content，不能只根据搜索 snippet 直接下结论。
10. 前端 evidence chip 能显示 `display_label` 并跳转预览。

## 最终建议

当前架构已经实现了 0610 讨论中的大部分“职责拆分”思想：scope、planner、executor、search、structure、evidence 都有了独立模块。它还不是完整多 Agent 系统，但这是优点而不是缺点。现阶段真正需要补的是工具语义和证据读取闭环。

我建议下一步不要重构成多 Agent，而是新增两个精确工具：

- `search_document_content`：单文档内部定位。
- `get_content_by_anchor`：统一 anchor 原文读取。

这两个工具能直接补上当前链路里最明显的空缺：Agent 已经能知道“应该在哪个文档/节点/anchor”，但还缺一个清晰、稳定、跨格式的方式，在文档内部快速定位并读取精确证据。
