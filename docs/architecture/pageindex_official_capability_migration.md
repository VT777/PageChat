# PageIndex 官方能力迁移与最终 TOC 架构建议

> 日期：2026-06-22  
> 状态：设计说明  
> 范围：分析 `D:\projects\PageIndex` 官方实现中值得迁移的能力，说明我们当前差距，并给出适合 `page_chat` 的最终 TOC 架构。

## 1. 背景与结论

我们用官方 `D:\projects\PageIndex\examples\documents` 样例对比后，结论很清楚：

- 官方 PageIndex 在“无显式目录但正文有标题结构”“弱目录/目录页需要解释”“长章节递归展开”上明显更稳。
- 我们当前在强 `embedded_toc` 场景下表现接近官方，甚至能利用 bookmarks/links 得到更细粒度目录。
- 我们的问题不主要是某个 prompt 或某个规则，而是 TOC 构建缺少官方那种“构建 -> 映射 -> 验证 -> 修复 -> 降级”的闭环。

因此，不建议直接复制官方 `page_index.py` 的大文件结构；应该把官方算法能力拆成独立阶段，移植到我们已经建立的 `PageTextMap -> TocDraft -> MappedToc -> QualityGate` 架构里。

最终建议：

```text
S0 Analyze
S1 Build PageTextMap
S2 Collect Evidence
S3 Plan Attempt Chain
S4 Build TocDraft
S5 Map + Verify + Repair
S6 Refine Large Nodes
S7 Quality Gate
S8 Save Base Index
S9 Enrich
```

核心变化是：状态机不只是选择一条路径，而是为每条路径定义完整候选生命周期。任何候选只有通过统一映射、校验、必要修复和质量门，才允许被接受；如果失败，必须显式降级，并保留当前最好候选作为兜底。

## 2. 官方实现中值得迁移的能力

官方入口集中在 `D:\projects\PageIndex\pageindex\page_index.py`，辅助函数在 `D:\projects\PageIndex\pageindex\utils.py`。

### 2.1 目录页检测与早停

官方 `find_toc_pages()` 从前若干页开始逐页判断是否是 TOC 页：

- 没发现 TOC 且超过 `toc_check_page_num` 后停止。
- 一旦连续发现 TOC 页，直到遇到第一个非 TOC 页后早停。
- 这避免了全文件反复检测 TOC 页。

对应位置：

- `page_index.py:341` `find_toc_pages`
- `page_index.py:696` `check_toc`

我们应保留“前部扫描 + 连续 TOC 早停”的思想，但不照搬它的 LLM-only 检测。我们的设计更适合：

- 先用 `PageTextMap` 上的高置信规则检测标准目录页。
- 规则不确定时再用轻量 LLM 单页分类。
- 检测只输出 TOC 页、目录类型、页码是否存在，不直接抽完整目录。

### 2.2 三类主路径和显式降级

官方 `meta_processor()` 的核心价值是路径降级：

1. `process_toc_with_page_numbers`
2. 如果页码映射/验证失败，退到 `process_toc_no_page_numbers`
3. 如果仍失败，退到 `process_no_toc`

对应位置：

- `page_index.py:622` `process_toc_with_page_numbers`
- `page_index.py:597` `process_toc_no_page_numbers`
- `page_index.py:576` `process_no_toc`
- `page_index.py:959` `meta_processor`

我们的现有状态机已经有 `embedded_toc`、`visible_toc_with_pages`、`visible_toc_no_pages`、`content_outline`，但缺少同一候选生命周期内的校验失败降级。应改成：

```text
embedded_toc
  -> fail: visible_toc_with_pages / visible_toc_no_pages
  -> fail: content_outline

visible_toc_with_pages
  -> fail mapping: visible_toc_no_pages
  -> fail skeleton/content: content_outline

visible_toc_no_pages
  -> fail anchoring: content_outline

content_outline
  -> fail: mark failed, do not invent generic full-document node
```

### 2.3 带物理页标签的全文建树

官方 `process_no_toc()` 会把分页文本包装成：

```text
<physical_index_1>
page text
<physical_index_1>
```

然后让 LLM 从这些带页标签的文本中抽取层级结构和起始页。

对应位置：

- `page_index.py:576` `process_no_toc`
- `page_index.py:522` `generate_toc_init`
- `page_index.py:486` `generate_toc_continue`

这正是官方在 `earthmover.pdf`、`q1-fy25-earnings.pdf` 等没有标准 TOC 的样例上表现更好的原因。我们现在的 `content_outline` 还不够像官方：有时过度依赖规则或局部标题候选，导致漏前言、漏第 1 章、或坍缩。

建议迁移为：

- `content_outline` 使用 `PageTextMap` 的分页文本。
- 每页保留物理页标签。
- 长文按 token 分组，带 1 页 overlap。
- 首组用 `generate_outline_init`，后续组用 `generate_outline_continue`。
- 生成结果必须进入 S5 验证，不允许直接接受。

### 2.4 目录有页码时的 offset 推断

官方 `process_toc_with_page_numbers()` 的思路是：

1. 先把 TOC 文本转成结构化列表，保留原始 TOC 页码。
2. 取 TOC 后面的若干正文页，让 LLM 找部分目录项实际起始物理页。
3. 通过 `physical_index - printed_page` 的众数计算 offset。
4. 把 offset 应用到所有目录项。
5. 对缺失页码项再补定位。

对应位置：

- `page_index.py:622` `process_toc_with_page_numbers`
- `page_index.py:261` `toc_index_extractor`
- `page_index.py:312` `calculate_page_offset`
- `page_index.py:323` `add_page_offset_to_toc_json`

我们的 S5 已经开始统一映射，但需要进一步吸收官方思想：

- 先判断 TOC 页码是否已经是物理页，不能盲目套 offset。
- 如果不是物理页，才计算稳定 offset。
- offset 必须由多个标题锚点支持，不能只靠单个样本。
- 图目录、表目录不能参与主目录 offset，也不能抢占正文章节范围。

### 2.5 标题抽样校验与局部修复

官方 `verify_toc()` 会抽样或全量检查目录项标题是否真的出现在目标物理页。校验中等通过时，`fix_incorrect_toc_with_retries()` 会对错误项按前后正确锚点限定搜索范围，再用 LLM 局部修复。

对应位置：

- `page_index.py:13` `check_title_appearance`
- `page_index.py:900` `verify_toc`
- `page_index.py:740` `single_toc_item_index_fixer`
- `page_index.py:760` `fix_incorrect_toc`
- `page_index.py:878` `fix_incorrect_toc_with_retries`

这是我们最需要补的能力之一。当前问题中，重庆、OpenAI、年报样例反复出现“页码看似有了但没校验住”。最终架构里，S5 必须内置：

- 标题命中校验。
- 目标页或邻近页校验。
- 大量目录项指向 TOC 页时直接判失败。
- 页码非单调或过度坍缩时判失败。
- 对少量错误项做局部修复。
- 修复仍失败时降级，不把坏结果交给后处理粉饰。

### 2.6 end_index 派生与重叠边界

官方 `post_processing()` 根据下一节点是否从页首开始决定当前节点结束页：

- 如果下一节点在下一页页首开始，当前 `end_index = next.start_index - 1`
- 如果下一节点不是页首开始，当前 `end_index = next.start_index`

对应位置：

- `utils.py:433` `post_processing`
- `page_index.py:48` `check_title_appearance_in_start`
- `page_index.py:74` `check_title_appearance_in_start_concurrent`

这比简单 `next.start - 1` 更准确，因为很多 PDF 的同一物理页上会同时有上一个章节尾部和下一个章节开头。

我们的最终规则应是：

```text
if next section starts at beginning of its physical page:
    current.end_index = next.start_index - 1
else:
    current.end_index = next.start_index
```

但必须注意：

- `end_index` 只由系统派生，不由 LLM 生成。
- 允许相邻节点范围重叠一页。
- 质量门不能把这种合法重叠判成失败。
- 图目录/表目录是点状导航，不参与正文范围派生。

### 2.7 大节点递归展开

官方 `process_large_node_recursively()` 会对跨度过大且 token 过多的叶子节点再次运行 `process_no_toc()`，生成子树。

对应位置：

- `page_index.py:1000` `process_large_node_recursively`
- 默认配置：`max_page_num_each_node=10`，`max_token_num_each_node=20000`

这是官方在年报、财报、法规文件中能得到更细结构的关键。我们现在有 `child_expansion_policy`，但它更像质量检查/后处理，不够像核心建树能力。最终应把它提升为 S6 `Refine Large Nodes`：

- 只对正文主目录节点展开。
- 跳过前言、目录页、图目录、表目录、参考文献、索引等。
- 对超长叶子，用该节点页范围内的 `PageTextMap` 重新跑 content outline。
- 子树仍必须走 S5 映射和 S7 质量门。

## 3. 不应直接照搬的官方部分

官方实现能跑出好结果，但工程结构不适合直接迁移：

- 逻辑集中在一个大文件，状态、候选、映射、校验、修复、摘要互相耦合。
- 标准开源版依赖普通 PDF 文本解析，不包含我们需要的 OCR/混合型处理。
- TOC 页检测用 LLM 单页判断，成本和稳定性不一定适合我们的批量场景。
- 目录抽取、页码映射、结构生成都要求 LLM JSON，容易受输出格式影响。
- 质量判断比较隐式，失败原因不如我们的质量报告可观测。
- 官方提示词里排除了 figure list/table list 作为 TOC，但我们的产品需要把图目录、表目录作为独立顶级目录展示。

所以迁移方式应该是“移植算法闭环”，不是“移植代码组织”。

## 4. 我们当前差距

### 4.1 路由只选路径，没有管理候选生命周期

当前 `TocStateMachine` 可以选出 `embedded_toc`、`visible_toc_with_pages`、`visible_toc_no_pages`、`content_outline`，但缺少：

- 每条路径的验收标准。
- 失败后下一条路径是什么。
- 当前最好候选如何保留。
- 局部修复是否成功。
- 降级后如何避免更差结果覆盖更好结果。

在 `2023-annual-report.pdf` 中，fast `code_toc` 已经高置信接受，但因为长叶子问题触发 balanced retry，后续走到更差的 visible TOC 结果，最终失败。这说明“候选保留”和“降级边界”必须进入架构。

### 4.2 content_outline 不够接近官方

官方在无目录文档上直接以分页物理标签为证据，让 LLM 抽整篇结构；我们现有路径有时混入规则标题候选、segment fallback 或局部抽取，导致：

- `earthmover.pdf` 坍缩成泛节点。
- `four-lectures.pdf` 漏掉 Preface 和第 1 讲。
- `q1-fy25-earnings.pdf` 成功但粒度不如官方。

最终 `content_outline` 应作为完整主路径，而不是 fallback 兜底节点生成器。

### 4.3 S5 映射还没有成为所有路径的唯一事实来源

我们已有 `toc_mapping.py`，方向正确，但从测试现象看，仍存在不同路径提前写入或保留旧页码语义的问题：

- 有些目录项直接指向目录页。
- 有些本来是物理页的 TOC 被错误 offset。
- 图目录/表目录页码被映射到同一页。
- 质检未能拦住明显错误映射。

最终架构必须规定：S4 只能输出 `raw_page_label`，最终 `physical_index/start_index/end_index` 只能由 S5 写入。

### 4.4 质量门之间语义不统一

目前存在 LLM 质检认为可用，但硬校验最后报错的情况。也存在“平铺目录”被误判低质的风险。

最终应分清：

- 事实硬失败：坍缩、页码越界、标题锚点过低、目录页泄漏、前中后明显缺失。
- 质量警告：树不够深、长节点未展开、摘要为空。
- LLM 质检：只能基于事实报告做辅助判断，不能独立覆盖事实校验。

### 4.5 大节点递归展开不是核心阶段

我们的 `child_expansion_policy` 能识别长叶子，但展开能力和验收还没和主流程严密结合。官方能力说明：长节点递归展开应该是树生成的一部分，而不是最后“看起来不够细”时的补丁。

## 5. 推荐最终架构

### 5.1 总体流程

```text
S0 Analyze
  - 便宜分析：页数、文本覆盖率、文本质量、图片/乱码页、code_toc 信号

S1 Build PageTextMap
  - text：直接按页取 PDF 文本
  - ocr：全文 OCR
  - hybrid：坏页/图片页 OCR 后拼回
  - 输出后续唯一文本事实来源

S2 Collect Evidence
  - code_toc: bookmarks + links + outline + verified low-cost signals
  - toc_page_detection: rule first, LLM fallback
  - content profile: 是否短文、是否论文、是否财报/法规长文

S3 Plan Attempt Chain
  - 不是只选一个 path，而是生成有序尝试链

S4 Build TocDraft
  - 只抽结构和 raw_page_label
  - 不写最终 physical_index/end_index

S5 Map + Verify + Repair
  - 唯一物理页映射阶段
  - 标题锚点校验
  - offset 推断
  - 局部错误修复
  - 失败则回到 S3 下一个 attempt

S6 Refine Large Nodes
  - 对长叶子递归 content outline
  - 子树重新进入 S5

S7 Quality Gate
  - 统一事实质量门
  - LLM QC 只作为辅助

S8 Save Base Index
  - 保存可检索的基础 TOC 和节点文本

S9 Enrich
  - 摘要、文档描述等，不影响 TOC 路由
```

### 5.2 Attempt Chain

状态机应输出 `attempt_chain`：

```json
[
  {"path": "embedded_toc", "reason": "reliable_code_toc"},
  {"path": "visible_toc_with_pages", "reason": "toc_pages_with_page_numbers"},
  {"path": "visible_toc_no_pages", "reason": "page_mapping_failed"},
  {"path": "content_outline", "reason": "fallback_full_text_outline"}
]
```

常见链路：

| 文档情况 | 尝试链 |
|---|---|
| 高质量 code_toc | `embedded_toc -> visible_toc -> content_outline` |
| 有标准目录且有页码 | `visible_toc_with_pages -> visible_toc_no_pages -> content_outline` |
| 有目录但无页码 | `visible_toc_no_pages -> content_outline` |
| 无目录 | `content_outline` |
| 图片/乱码型 | S1 先生成 PageTextMap，再按同样链路走 |

### 5.3 Candidate Lifecycle

每个 attempt 都走同一生命周期：

```text
build_draft
  -> map_to_physical
  -> verify_mapping
  -> repair_if_partial
  -> derive_ranges
  -> refine_large_nodes
  -> quality_gate
  -> accept or fallback
```

其中 `best_candidate` 必须保留：

- 如果当前候选通过硬校验但有警告，记录为 `best_candidate`。
- 如果 fallback 结果更差，回到 `best_candidate`，不要让坏结果覆盖好结果。
- 如果所有候选失败，但存在可导航的非完美候选，可按产品策略选择“失败并保留诊断”或“降级可用但标记 needs_review”。当前调试期建议硬失败。

### 5.4 路径 A：embedded_toc

输入：

- bookmarks/outline
- TOC link annotations
- 已验证 code_toc

处理：

- bookmarks 负责层级。
- links 负责物理目标页和图表目录补充。
- 多源合并时保留来源证据。
- 不允许 regex 弱信号早返回。

验收：

- 页码范围有效。
- 抽样标题命中。
- 不是大面积指向同一页。
- 不是大面积指向目录页。
- 图目录/表目录独立保留。

失败：

- 如果有 visible TOC 页，进入 visible TOC。
- 否则进入 content outline。

### 5.5 路径 B：visible_toc_with_pages

输入：

- `toc_pages`
- `PageTextMap`

处理：

- 高置信标准目录页：规则抽取。
- 规则不确定或校验失败：LLM 抽取 TOC skeleton。
- 输出 `TocDraft`，包括 `title`、`level/structure`、`section_kind`、`raw_page_label`。

映射：

1. 先检查 `raw_page_label` 是否已经是物理页。
2. 否则计算稳定 offset。
3. offset 不稳定时，用标题搜索/局部 LLM finder。
4. 少量错误项局部修复。
5. 大量错误则降级为 `visible_toc_no_pages`，只信标题结构，不信页码。

### 5.6 路径 C：visible_toc_no_pages

输入：

- TOC skeleton
- 全文 `PageTextMap`

处理：

- LLM 或规则只负责提取目录标题结构。
- 页码完全由 S5 标题定位决定。
- 先定位顶级节点。
- 对长顶级节点在章节范围内递归建子树。

失败条件：

- 顶级标题锚点过少。
- 多个标题都只能命中 TOC 页。
- 结构与正文完全无法对应。

失败后进入 `content_outline`。

### 5.7 路径 D：content_outline

输入：

- 全文 `PageTextMap`

处理：

- 使用官方式分页物理标签。
- 按 token 分组。
- LLM 直接抽取真实正文结构。
- 对短论文、财报、法规、报告都适用。
- 不再生成 `Document Content` 这种泛节点作为成功结果。

验收：

- 不坍缩。
- 覆盖前中后。
- 标题能在对应页附近命中。
- 长文至少有合理的一级结构；长节点按 S6 递归展开。

## 6. 统一 S5 映射设计

S5 是全流程唯一能写最终物理页的地方。

输入：

```json
{
  "items": [
    {
      "title": "1. Introduction",
      "level": 1,
      "raw_page_label": "6",
      "section_kind": "main_toc",
      "source_page": 3
    }
  ]
}
```

输出：

```json
{
  "items": [
    {
      "title": "1. Introduction",
      "start_index": 6,
      "end_index": 11,
      "physical_index": 6,
      "mapping_confidence": 0.92,
      "mapping_evidence": {
        "strategy": "printed_page_identity",
        "title_anchor": "strong",
        "checked_pages": [6]
      }
    }
  ],
  "mapping_report": {
    "status": "ok",
    "title_match_rate": 0.86,
    "strong_anchor_count": 18,
    "offset": 0,
    "repaired_count": 2,
    "failed_count": 0
  }
}
```

映射策略顺序：

1. `physical_identity`：TOC 页码本来就是物理页。
2. `printed_page_offset`：稳定 offset。
3. `title_search`：标题搜索定位。
4. `local_llm_finder`：只对错误/缺失项，在前后正确锚点之间局部查找。
5. `unmapped_fail`：仍失败则降级或报错。

`end_index` 派生：

- 对正文目录按兄弟节点顺序派生。
- 允许相邻节点重叠一页。
- 使用“下一节点是否从页首开始”决定是否 `next.start - 1`。
- 对子节点也使用同样逻辑。
- 对辅助目录项保持点状页码，不参与正文范围覆盖。

## 7. 统一质量门

质量门分三层。

### 7.1 事实硬失败

必须失败：

- TOC 坍缩成一个泛节点。
- 大量节点页码越界。
- 大量节点指向 TOC 页。
- 标题锚点命中率低于阈值，且修复失败。
- 主体目录前部、中部或尾部明显丢失。
- 页码严重非单调。
- 图目录/表目录污染主目录范围。
- `content_outline` 对长文只生成 1 个节点。

### 7.2 质量警告

只警告，不直接失败：

- 平铺目录，但原文目录本身就是平铺。
- 某些长叶子未展开，但文档形态允许。
- 摘要为空。
- 少量标题命中弱。

### 7.3 LLM QC

LLM QC 只看：

- TOC tree preview
- mapping report
- child expansion report
- route decision

它不能重新发明事实，也不能单独推翻事实硬校验。它的作用是发现“事实规则没覆盖但人类明显能看出的问题”，并给出建议。

## 8. 与现有模块的落点

| 目标能力 | 建议落点 |
|---|---|
| 状态机输出 attempt chain | `backend/pageindex/pipeline/toc_state_machine.py` |
| 候选生命周期执行器 | 新建 `backend/pageindex/pipeline/toc_attempt_runner.py` |
| TOC 草稿规范 | `backend/pageindex/toc_contracts.py` |
| 统一物理页映射 | `backend/pageindex/toc_mapping.py` |
| 标题校验/局部修复 | 新建或扩展 `backend/pageindex/toc_mapping_verifier.py` |
| content outline 官方式实现 | 新建或重构 `backend/pageindex/content_outline_extractor.py` |
| 大节点递归展开 | 扩展 `backend/pageindex/child_expansion_policy.py`，新增执行器 |
| 统一质量门 | `backend/pageindex/balanced_quality_gate.py` 与 `index_quality.py` |
| 端到端样例集 | `eval0618/pageindex_official_compare` 与 AI Knowledge 13 份文档 |

## 9. 迁移阶段建议

### Phase 1：建立官方样例回归基线

目标：

- 把官方 8 份有结果样例和 `attention-residuals.pdf` 纳入诊断集。
- 固化每份文件的期望：成功、主结构、页码、节点数范围、不能坍缩。

必须覆盖：

- `earthmover.pdf` 不能坍缩，需抽出论文结构。
- `four-lectures.pdf` 必须包含 Preface 和 `ML at a Glance`。
- `Regulation Best Interest_Interpretive release.pdf` 不能因映射门失败。
- `2023-annual-report*.pdf` 不能让高质量 code_toc 被更差 fallback 覆盖。

### Phase 2：引入 Candidate Lifecycle 和 best_candidate

目标：

- 每条路径都用同一执行器。
- 通过硬校验的候选进入 `best_candidate`。
- fallback 不能覆盖更好的候选。

### Phase 3：补齐 S5 验证与局部修复

目标：

- 实现官方式标题抽样校验。
- 实现错误项局部修复。
- 修复失败时降级，而不是继续后处理。

### Phase 4：重写 content_outline 为官方式分页标签建树

目标：

- 无目录文档直接基于分页文本抽结构。
- 不再使用泛节点成功。
- 能覆盖 `earthmover`、`q1-fy25`、短论文和长报告。

### Phase 5：大节点递归展开成为核心阶段

目标：

- 对长叶子做范围内二次建树。
- 子树同样走 S5/S7。
- 年报、法规、行业报告得到足够可导航的层级。

### Phase 6：统一质量门语义

目标：

- 硬失败、警告、LLM QC 分层。
- 平铺目录不因“没层级”失败。
- 长节点是否失败由事实规则和文档形态决定。

### Phase 7：全量端到端验收

测试集：

- 官方 PageIndex examples。
- AI Knowledge 13 份文档。
- 重庆扫描型文档。

验收标准：

- 所有文件必须走预期路径或有明确 fallback 记录。
- 失败必须有可解释硬失败原因。
- 成功结果不能有目录页泄漏、明显错页、泛节点坍缩。
- 强 embedded TOC 文件不能因为 fallback 变差。
- 无目录正文结构文件不能低于官方样例的可导航性。

## 10. 最终架构判断

现有设计方向没有错：统一 PageTextMap、显式状态机、TocDraft/MappedToc 分层，都是正确基础。

真正缺的是官方 PageIndex 已经证明有效的三件事：

1. 每个候选必须经历验证、修复、降级闭环。
2. 无目录时必须把 content outline 当作主能力，而不是兜底拼节点。
3. 长节点递归展开必须成为树构建阶段的一部分。

把这三件事接进我们的架构后，我们会比官方开源版更适合当前项目：

- 官方强在算法闭环。
- 我们强在 OCR/混合文档预处理、多目录类型、可观测质量门、前端导航需求。
- 最优方案是保留我们的工程分层，移植官方的闭环能力。

