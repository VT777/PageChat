# PageIndex 官方样例 TOC 验证集

> 日期：2026-06-22  
> 状态：已建立基础数据集  
> 目的：把 `D:\projects\PageIndex\examples\documents` 官方样例改造成后续 TOC 架构实施的阶段性回归验证集。

## 1. 数据集位置

验证 fixture：

```text
D:\projects\page_chat\backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json
```

源 PDF：

```text
D:\projects\PageIndex\examples\documents
```

官方结果：

```text
D:\projects\PageIndex\examples\documents\results
```

配套测试：

```text
D:\projects\page_chat\backend\tests\test_official_pageindex_validation_fixture.py
```

E2E runner 已支持通过 `--fixture` 指向该数据集：

```powershell
py -X utf8 scripts\run_ai_knowledge_toc_e2e.py `
  --fixture backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json `
  --input D:\projects\PageIndex\examples\documents `
  --output eval0618\official_pageindex_validation
```

单文件调试：

```powershell
py -X utf8 scripts\run_ai_knowledge_toc_e2e.py `
  --fixture backend\tests\fixtures\toc\official_pageindex_expected_toc_reference.json `
  --input D:\projects\PageIndex\examples\documents `
  --file earthmover.pdf `
  --output eval0618\official_pageindex_validation\earthmover
```

## 2. 设计原则

官方结果不作为逐字逐节点 gold tree，而是作为结构约束来源。原因：

- 不同实现可以有合理风格差异，例如 `PRML.pdf` 官方把多个 `Exercises` 作为 root，我们可以更紧凑。
- 我们有自己的前端目录分组、OCR、图目录/表目录、多源 code_toc 合并逻辑。
- 真正要稳定的是可导航性、关键结构、物理页映射和不能坍缩。

因此 fixture 采用约束型验收：

- 必须成功。
- 必须达到最小 root/node/depth。
- 必须包含关键 root 标题。
- 关键标题必须映射到预期物理页。
- 禁止泛节点坍缩、目录页大面积映射、优质 embedded TOC 被差 fallback 覆盖等。

## 3. 文档清单

| ID | 文件 | 官方 baseline | 主要用途 |
|---|---|---:|---|
| P01 | `2023-annual-report.pdf` | 有 | 验证高质量 code_toc 不被差 fallback 覆盖，年报结构不能丢。 |
| P02 | `2023-annual-report-truncated.pdf` | 有 | 验证截断文档的 TOC 页码映射、非单调页码防护。 |
| P03 | `attention-residuals.pdf` | 无 | canary：验证我们自己的强内置/论文结构能力不退化。 |
| P04 | `earthmover.pdf` | 有 | 验证无目录正文建树，不能坍缩为单节点。 |
| P05 | `four-lectures.pdf` | 有 | 验证 OCR/弱文本下前言和第 1 讲不能丢失。 |
| P06 | `PRML.pdf` | 有 | 验证大书籍 embedded TOC、深度和大节点结构。 |
| P07 | `q1-fy25-earnings.pdf` | 有 | 验证短财报 content outline 的层级粒度。 |
| P08 | `Regulation Best Interest_Interpretive release.pdf` | 有 | 验证质量门与内容映射不能互相矛盾导致误失败。 |
| P09 | `Regulation Best Interest_proposed rule.pdf` | 有 | 验证长法规文档 embedded TOC、深层结构和关键页码。 |

## 4. 后续阶段使用方式

每个实现阶段至少做两类验证：

1. 阶段相关样本快速验证  
   例如改 `content_outline` 时，必须跑 P04、P05、P07。

2. 阶段完成全量验证  
   跑官方 9 份样例和 AI Knowledge 13 份业务样例。

建议输出目录按阶段命名：

```text
eval0618/
  phaseN-official-pageindex/
  phaseN-ai-knowledge/
```

阶段通过标准：

- `summary.json` 中没有 `error`。
- 调试期可以允许 `failed` 暴露未完成能力，但必须与当前阶段目标一致。
- 进入下一阶段前，与本阶段相关的样本必须全部 `ok`。
- 最终阶段要求官方样例和 AI Knowledge 样例都达到预期路径和 TOC 质量。

## 5. 当前已完成

- 新增官方样例 fixture。
- 新增 fixture contract 测试。
- E2E runner 支持 `--fixture`。
- E2E report 支持 `acceptance.min_root_count`、`min_node_count`、`min_depth`、`required_root_titles`、`required_pages`、`forbidden_patterns.no_generic_single_node`。

