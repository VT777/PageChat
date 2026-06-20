# TOC 质量恢复实施计划

> **给后续 agentic worker：** 执行本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项推进。本文使用 checkbox (`- [ ]`) 跟踪进度。

**目标：** 恢复 13 份 AI Knowledge PDF 的 TOC 构建质量，让路由确定、页码映射可验证、质量门能拒绝明显错误的 TOC。

**架构：** 保持统一状态机：先把文档预处理成 `PageTextMap`，再确定性选择一条 TOC 构建路径：`embedded_toc`、`visible_toc_with_pages`、`visible_toc_no_pages` 或 `content_outline`。规则抽取只作为高精度低成本子路径，规则校验失败必须回退到 LLM 抽取。物理页码映射是独立后处理步骤，最终 TOC 只输出物理页码。

**技术栈：** Python、PyMuPDF、现有 `pageindex` 模块、pytest、真实 PDF 样本目录 `D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`。

---

## 参考输入

- 架构文档：`D:\projects\page_chat\docs\architecture\toc_generation_unified_architecture.md`
- 测试基线：`D:\projects\page_chat\docs\architecture\ai_knowledge_toc_test_baseline.md`
- 预期 TOC 参考：`D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`
- 真实 PDF：`D:\chrome_download\rag-skill-main\rag-skill-main\knowledge\AI Knowledge`
- 当前 E2E 报告：`D:\projects\page_chat\eval0618\phase9-e2e-final-v2`

## 涉及文件

- 修改：`D:\projects\page_chat\backend\pageindex\visible_toc_rule_extractor.py`
  - 规则抽取接受条件、fallback 元数据、无页码目录分隔页映射语义。
- 修改：`D:\projects\page_chat\backend\pageindex\judge\content_page_mapper.py`
  - printed page 映射保护、强标题锚点规则、弱 `outline_marker` 处理。
- 修改：`D:\projects\page_chat\backend\pageindex\code_toc_quality.py`
  - bookmarks、links、section 维度的 code TOC 可靠性评分。
- 修改：`D:\projects\page_chat\backend\app\services\pageindex_service.py`
  - 状态机 fallback、章节内扩展、LLM 质检硬失败、诊断信息。
- 修改：`D:\projects\page_chat\backend\pageindex\balanced_quality_gate.py`
  - 路径感知质量门、长章节 flat tree 处理。
- 修改或新增：`D:\projects\page_chat\backend\tests`
  - 页码映射、规则 fallback、code TOC 质量、质量门单元测试。
- 修改或新增：`D:\projects\page_chat\scripts`
  - 基于预期 TOC 参考文件做 E2E 断言。

## Task 0：锁定 TOC 参考基线

- [ ] **Step 0.1：审查参考文件**

打开 `D:\projects\page_chat\docs\architecture\ai_knowledge_expected_toc_reference.md`。

预期：T01-T13 每份文档都有路径、关键证据、预期顶级范围；要么有可锁定的源目录条目，要么明确标注章节内扩展要求。

- [ ] **Step 0.2：把可锁定参考项转成测试 fixture**

创建：`D:\projects\page_chat\backend\tests\fixtures\toc\ai_knowledge_expected_toc_reference.json`。

fixture 至少包含：

```json
{
  "T09": {
    "required_route": "text -> visible_toc_with_pages",
    "required_sections": ["main_toc", "figure_toc", "table_toc"],
    "must_have_nodes": [
      {
        "title": "1.3、估值：持续新高，最新估值7500 亿美元",
        "start_index": 7,
        "end_index": 8
      }
    ]
  }
}
```

- [ ] **Step 0.3：新增 fixture 校验测试**

创建：`D:\projects\page_chat\backend\tests\test_ai_knowledge_expected_toc_reference.py`。

运行：

```powershell
py -X utf8 -m pytest backend/tests/test_ai_knowledge_expected_toc_reference.py -q
```

预期：PASS。

- [ ] **Step 0.4：提交**

```powershell
git add docs/architecture/ai_knowledge_expected_toc_reference.md backend/tests/fixtures/toc/ai_knowledge_expected_toc_reference.json backend/tests/test_ai_knowledge_expected_toc_reference.py
git commit -m "test: lock ai knowledge toc reference"
```

## Task 1：让规则抽取只接受高置信结果

- [ ] **Step 1.1：先写规则 fallback 的失败测试**

测试点：

- T03：当大量 logical page 超出物理页范围、或标题锚点集中塌缩到同一页时，规则抽取不能被接受。
- T08/T11：规则抽取要么保留中文括号子项 `（一）/（二）`，要么拒绝规则结果并回退 LLM。
- T13：code TOC 中的表格噪声不能被当作高质量 embedded TOC。

运行：

```powershell
py -X utf8 -m pytest backend/tests/test_visible_toc_rule_extractor.py backend/tests/test_code_toc_quality.py -q
```

实现前预期：FAIL。

- [ ] **Step 1.2：实现规则接受契约**

在 `visible_toc_rule_extractor.py` 中：

- 保持规则解析严格，不扩展成复杂长尾规则。
- 层级不完整时标记为低置信。
- 主目录、图目录、表目录拆分必须完整。
- 页码语义不明确时，可以保留抽到的标题，但要标记映射未解决；不能设置 `prevalidated=True`。
- 对 `visible_toc_with_pages`，如果原目录明显有多级结构但 parser 只抽出一级，不能设置 `allow_child_expansion=False` 后直接冻结。

- [ ] **Step 1.3：确保 LLM fallback 真能走到**

在 `pageindex_service.py` 中：

- 规则返回 `None`、低置信或校验失败时，对已确认的 TOC 页调用 LLM 目录抽取。
- `PageTextMap` 生成后，不能再切回旧的 layout/VLM 目录构建分支。

- [ ] **Step 1.4：真实文件验证**

逐个运行 T03、T08、T11、T13 的诊断。

预期：

- T03：不能接受 10-37 全部塌缩到第 40 页的结果。
- T08/T11：源目录可见的 `（一）/（二）` 子项存在；如果规则做不到，就必须走 LLM fallback。
- T13：bookmarks/table cell 噪声不能作为 clean embedded TOC 通过。

- [ ] **Step 1.5：提交**

```powershell
git add backend/pageindex/visible_toc_rule_extractor.py backend/app/services/pageindex_service.py backend/tests
git commit -m "fix: require validated visible toc rule results"
```

## Task 2：保护物理页码映射

- [ ] **Step 2.1：先写映射失败测试**

测试点：

- T09：目录已经给出 `1.3` 在物理页 7，且物理页 7 包含该标题时，不能被改到第 4 页。
- T03：弱 `outline_marker` 不能计为强标题锚点。
- T05：重复目录/分隔页必须作为下一章节起始页，不能变成 `divider + 1`。

- [ ] **Step 2.2：实现强锚点规则**

在 `content_page_mapper.py` 中：

- 不允许 `outline_marker` 覆盖 `printed_page_offset`。
- 只有直接标题命中足够强，且能改善整体一致性时，才允许覆盖 printed mapping。
- title match rate 只统计直接标题或可靠 fuzzy title 命中。
- 通用数字 marker、编号 marker 都是弱证据。

- [ ] **Step 2.3：修正无页码目录的分隔页语义**

在 `visible_toc_rule_extractor.py` 中：

- 对重复章节分隔页，下一章节从该分隔页开始。
- 不要把分隔页从它引入的章节范围中排除。
- 只有边界页内容支持时，才允许相邻章节一页重合。

- [ ] **Step 2.4：真实文件验证**

预期：

- T05 范围：`3-8`、`9-15`、`16-17`、`18-21`。
- T09 `1.3` 范围：`7-8` 或基于边界证据的 `7-9`，但绝不能是 4。
- T03 不再出现大量节点塌缩到第 40 页。

- [ ] **Step 2.5：提交**

```powershell
git add backend/pageindex/judge/content_page_mapper.py backend/pageindex/visible_toc_rule_extractor.py backend/tests
git commit -m "fix: protect printed page mapping anchors"
```

## Task 3：实现章节内 LLM 建树

- [ ] **Step 3.1：先写浅层无页码 TOC 的失败测试**

测试点：

- T04/T07/T12 不能只生成一级目录后结束。
- flat 顶级目录只有在源文档本身确实不需要章节内结构时才可接受。

- [ ] **Step 3.2：替换确定性 page-title 子节点扩展**

在 `pageindex_service.py` 中：

- 对 `visible_toc_no_pages`，顶级 anchor 映射完成后，按每个章节范围调用 LLM。
- 输入保持简单：物理页码 + `PageTextMap` 每页前 200 字。
- LLM 只输出子节点标题和物理起始页。
- 子节点范围仍由后处理按统一边界规则修正。

- [ ] **Step 3.3：确定性抽取只能作为证据**

`page_outline_extractor.py` 可以提供候选标题，但不能作为长章节最终子树的唯一来源。

- [ ] **Step 3.4：真实文件验证**

预期：

- T04：顶级范围为 `3-12`、`13-34`、`35-48`、`49-60`、`61-68`，且有章节内子节点。
- T07：Part01-Part05 映射保持正确，并生成可用子节点。
- T12：序言 + 第一章到第八章映射保持正确，并生成章节内子节点。

- [ ] **Step 3.5：提交**

```powershell
git add backend/app/services/pageindex_service.py backend/pageindex/page_outline_extractor.py backend/tests
git commit -m "feat: expand shallow toc chapters with llm snippets"
```

## Task 4：增强 code TOC 质量判断

- [ ] **Step 4.1：先写 T13 噪声 bookmarks 的失败测试**

必须拒绝：

- 纯数字标题。
- 日期型标题。
- 表格里的发布主体/机构名称。
- 附录表格中的长正文句子。
- 主目录被表格行污染。

- [ ] **Step 4.2：评估所有 section，而不是只看 main TOC**

在 `code_toc_quality.py` 中：

- 分别评分 `main_toc`、`figure_toc`、`table_toc`。
- bookmarks 和 links 只有在 section 证据一致时才合并。
- 如果 visible TOC/link 证据比 bookmarks 更干净，应拒绝污染 bookmarks。

- [ ] **Step 4.3：真实文件验证**

预期：

- T06 仍通过 link-based embedded TOC。
- T13 要么生成干净的 embedded 主目录/表目录/图目录，要么回退到 visible TOC 抽取。
- T11 如果 embedded bookmarks 缺少图目录，应被拒绝并进入可见目录路径。

- [ ] **Step 4.4：提交**

```powershell
git add backend/pageindex/code_toc_quality.py backend/pageindex/code_toc_collector.py backend/tests
git commit -m "fix: reject noisy embedded toc sections"
```

## Task 5：让质量门按路径强校验

- [ ] **Step 5.1：先写 hard fail 测试**

必须 hard fail：

- 大量节点塌缩到同一个非目录页。
- 直接标题命中率低于该路径阈值。
- 源目录可见子项缺失。
- 长章节没有完成子节点扩展。
- 当前调优阶段 LLM QC 返回 fail。

- [ ] **Step 5.2：实现路径感知质量检查**

在 `balanced_quality_gate.py` 和 `index_quality.py` 中：

- `visible_toc_with_pages`：要求强标题锚点，禁止弱 marker 主导映射。
- `visible_toc_no_pages`：要求顶级 anchor 可验证，长跨度章节必须完成子节点扩展。
- `embedded_toc`：要求标题语义干净、section 完整。
- `content_outline`：校验物理页范围和标题/正文一致性。

- [ ] **Step 5.3：当前调优阶段重新启用 LLM QC 硬失败**

在 `pageindex_service.py` 中：

- 如果 LLM QC 返回 `needs_repair=True` 且包含 hard reasons，则当前调优模式下失败。
- 保留配置开关，方便后续切回 advisory 模式。

- [ ] **Step 5.4：提交**

```powershell
git add backend/pageindex/balanced_quality_gate.py backend/pageindex/index_quality.py backend/app/services/pageindex_service.py backend/tests
git commit -m "fix: fail unusable toc quality results"
```

## Task 6：端到端验证

- [ ] **Step 6.1：逐个运行 13 份真实文档**

按顺序运行 E2E 脚本，并记录每份文件耗时。

预期：

- 没有文件意外失败。
- 如果失败，必须给出明确 hard-fail reason，并能对应到参考文件。
- 输出路径和 TOC 树与预期参考一致。

- [ ] **Step 6.2：生成观测产物**

生成：

- JSON report：`D:\projects\page_chat\eval0618`
- HTML tree review：`D:\projects\page_chat\eval0618`
- 与 `ai_knowledge_expected_toc_reference.md` 对比的 diff report

- [ ] **Step 6.3：人工复核 checkpoint**

暂停并汇报：

- 每份文件实际路径。
- 处理耗时。
- 质量状态。
- 与参考文件不一致的地方。
- JSON/HTML 产物链接。

- [ ] **Step 6.4：提交**

```powershell
git add backend docs scripts
git commit -m "test: verify ai knowledge toc e2e quality"
```

除非用户明确要求把运行报告版本化，否则不要提交 `eval0618` 生成产物。

## 验收标准

- T03 不再接受大量节点塌缩到第 40 页的规则映射结果。
- T04/T07/T12 在需要章节内结构时不能只输出一级目录。
- T05 重复目录/分隔页映射为章节起始页。
- T08/T11 保留源目录可见的 `（一）/（二）` 子项。
- T09 printed physical page 不会被弱 `outline_marker` 覆盖。
- T13 附录表格行、日期、机构名、正文片段不会变成 TOC 标题。
- 当前调优阶段 LLM QC fail 能阻止最终索引生成。
- 13 份真实文件 E2E 报告包含路径、耗时、TOC 树、质量状态和参考 diff。
