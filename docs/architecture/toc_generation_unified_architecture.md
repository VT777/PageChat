# TOC 生成统一架构设计

> 日期：2026-06-18  
> 状态：设计稿  
> 目标：用简单、确定、可校验的状态机替代当前多路径竞赛式 TOC 生成流程。

## 1. 背景

当前 TOC 构建已经接入文本解析、OCR、目录页检测、LLM 抽取、标题搜索、页码 offset、质量门等能力，但整体路径过于分散：

- 同一份文档可能同时跑多个 TOC 候选，再由评分器选择，成本和耗时不可控。
- 文本型、图片型、混合型文档的处理逻辑交织在 TOC 构建过程中，导致路径质量不一致。
- 主目录、图目录、表目录没有稳定拆分，容易互相抢占页码映射。
- 规则解析、LLM 抽取、OCR、正文建树的职责边界不清晰。
- 质量门有时偏审美，例如误把“平铺目录”判为低质量，而不是判断目录是否真实反映原文。

新的架构目标是：

```text
先把 PDF 统一预处理成按页可靠文本，
再按 TOC 信号选择唯一确定路径，
最后统一做物理页码映射和质量校验。
```

## 2. 设计原则

### 2.1 简单优先

主流程只保留必要状态，不再引入多候选竞赛。每个阶段只做一件事：

- 预处理阶段只负责得到可靠的按页文本。
- TOC 检测阶段只负责判断有没有目录页。
- TOC 构建阶段只负责抽取目录结构。
- 映射阶段只负责把目录项定位到物理页。
- 质量门只判断 TOC 是否可用。

### 2.2 确定性路径

每份文档一次只走一条主路径。允许 fallback，但 fallback 必须是显式的：当前路径失败，记录原因，然后进入下一条路径。禁止同时跑多条完整路径再比较。

### 2.3 规则优先，但只做高置信任务

规则适合做三件事：

1. 检测标准目录页。
2. 抽取标准目录格式。
3. 做硬校验。

规则不负责理解复杂目录，也不靠不断增加特殊规则来覆盖长尾情况。规则失败或校验不过，直接交给 LLM。

### 2.4 LLM 做理解，不做页码推理

LLM 负责从目录页文本中抽取结构、区分主目录/图目录/表目录、在无目录文档中基于页级摘要生成目录，以及做最终质量判断。

LLM 不负责猜 printed page offset、猜物理页码、修复 OCR 缺失，也不代替后处理做复杂页码逻辑。

### 2.5 统一物理页码输出

最终 TOC 必须使用物理页码，支持直接按物理页提取节点内容。

## 3. 总体流程

```text
S0 Analyze
  -> S1 PreprocessToPageText
  -> S2 TryEmbeddedToc
  -> S3 DetectTocPages
  -> S4 BuildToc
  -> S5 MapPhysicalPages
  -> S6 QualityGate
  -> S7 SaveBaseIndex
  -> S8 Enrich
```

### 3.1 状态说明

| 状态 | 目的 | 是否允许 LLM | 输出 |
|---|---|---:|---|
| S0 Analyze | 便宜分析文档形态 | 否 | `DocumentProfile` |
| S1 PreprocessToPageText | 统一生成按页可靠文本 | 否 | `PageTextMap` |


| S2 TryEmbeddedToc | 尝试内置目录快路径 | 否 | `TocDraft` 或失败原因 |
| S3 DetectTocPages | 检测可见目录页 | 规则优先，必要时 LLM | `TocPageDetection` |
| S4 BuildToc | 按选定路径构建 TOC | 必要时允许 | `TocDraft` |
| S5 MapPhysicalPages | 统一映射到物理页 | 否 | `MappedToc` |
| S6 QualityGate | 判断 TOC 是否可用 | 可选 | 通过/失败报告 |
| S7 SaveBaseIndex | 保存基础索引 | 否 | base index |
| S8 Enrich | 摘要、描述、节点补充 | 可选 | final index |

## 4. S0 Analyze：便宜分析

Analyze 阶段只采集低成本信号，不生成 TOC，不做全文 OCR，不调用 LLM。

输出 `DocumentProfile`：

```json
{
  "page_count": 64,
  "text_coverage": 0.92,
  "image_ratio": 0.18,
  "text_quality": "reliable",
  "content_type": "text | ocr | hybrid",
  "embedded_toc_signal": true,
  "toc_page_rule_signal": true
}
```

`content_type` 只分三类：

| 类型 | 含义 |
|---|---|
| `text` | 文本层可靠，大多数页可直接用 PDF 文本 |
| `ocr` | 图片型或乱码型，需要全文 OCR |
| `hybrid` | 部分页文本可靠，部分页需要 OCR 修补 |

这个分类只影响预处理，不直接决定 TOC 构建路径。

## 5. S1 PreprocessToPageText：统一按页文本

预处理目标是生成统一输入 `PageTextMap`。后续 TOC 构建不再关心文本来自 PDF 解析还是 OCR。

```json
[
  {
    "physical_page": 1,
    "text": "...",
    "source": "pdf_text | ocr | mixed",
    "quality": "reliable | partial | low",
    "ocr_used": false
  }
]
```

### 5.1 文本层可靠

直接使用 PDF 文本层，按物理页保存。

### 5.2 图片型 / 乱码型

全文 OCR，按阅读顺序输出文本，并按物理页保存。

正文 OCR 提示词保持简单：

```text
Recognize all readable text in natural reading order.
```

### 5.3 混合型

逐页判断文本质量：

- 可靠页：保留 PDF 文本。
- 空白页、乱码页、图片页：单独 OCR。
- 最后按物理页拼回 `PageTextMap`。

混合型不能粗暴全文 OCR，也不能只信 PDF 文本层。它的目标是低成本修补坏页，同时保留原文档结构。

### 5.4 节点内容来源

后续节点内容必须从 `PageTextMap` 填充。索引构建完成后不应再次 OCR。

### 5.5 `layout_required` 的边界

`layout_required` 只表示原生 PDF 文本层不可靠，S1 必须通过 OCR 或混合修补生成可靠 `PageTextMap`。它不能作为 S4 TOC 构建阶段的路由条件。

一旦 S1 产出按页文本，后续 `embedded_toc`、`visible_toc_with_pages`、`visible_toc_no_pages`、`content_outline` 都只能消费 `PageTextMap` 和 code-extracted TOC 证据。旧的视觉/layout 目录候选不再作为 S4 并列路径存在；OCR/VLM-OCR/PP-OCR 只能是 S1 生成按页文本的内部实现。

## 6. S2 TryEmbeddedToc：内置目录快路径

优先尝试不需要 LLM 的内置目录来源：

- PDF bookmarks / outline。
- PDF links。
- 已有 `code_toc`。
- 高置信文本标题结构。

`embedded_toc` 不是单一来源，而是 code-extracted TOC 的统一结果。S2 必须先独立采集所有低成本代码信号，再决定是否接受，不能因为先发现 bookmarks 就跳过 PDF links：

- bookmarks/outline：适合作为主目录层级来源。
- TOC 页 link annotations：适合作为精确物理页来源，也可能包含 bookmarks 没有覆盖的图目录、表目录。
- regex/text heading：只能作为低置信补充，必须有额外校验，不能直接早返回。

采集结果需要保留来源明细，例如：

```json
{
  "sources": {
    "bookmarks": {"items": 172},
    "links": {"items": 112, "toc_pages": [7, 8, 9]},
    "regex": {"items": 0}
  },
  "toc_sections": [
    {"kind": "main_toc", "source": "bookmarks+links", "items": []},
    {"kind": "table_toc", "source": "links", "items": []},
    {"kind": "figure_toc", "source": "links", "items": []}
  ]
}
```

如果 bookmarks 与 links 互补，必须合并；如果两者冲突，必须用标题命中和页码校验决定是否接受，不能简单按来源优先级覆盖。

通过硬校验即可接受，否则进入目录页检测。

硬校验包括：

- 页码在物理页范围内。
- 抽样标题能在目标页或附近页命中。
- 节点数量与文档页数大致合理。
- 不是大量节点都指向同一页。
- 不是大量节点都指向目录页。
- 如果可检测到图目录、表目录，最终 `embedded_toc` 必须保留独立 `figure_toc` / `table_toc`，不能只接受主目录。
- 弱 slide-export outline 不能直接早返回。典型噪声包括 `默认节`、`幻灯片 X`、`Slide X`、`Page X` 等。只有清洗后仍能形成有意义章节/页级目录，并通过页码和标题抽样校验，才允许接受。
- fast path、provider、质量门必须复用同一套可靠性判定，不能出现同一份 `code_toc` 在一个入口通过、另一个入口拒绝的情况。

该路径失败后只记录失败原因，不再作为候选参与后续评分。

## 7. S3 DetectTocPages：目录页检测

目录页检测先走规则，规则不确定时再走轻量 LLM 分类。检测阶段只判断目录页位置和目录类型，不抽取完整目录。

### 7.1 规则检测

规则检测基于 `PageTextMap`，不额外 OCR。

默认扫描范围：

```text
scan_limit = min(30, max(10, page_count * 0.3))
```

早停规则：

- 如果检测到连续目录页，并且后续连续 1-2 页不是目录页，则停止。
- 如果当前扫描批次最后一页仍是目录页，继续补扫下一批，避免漏掉连续目录页。

高置信目录页信号：

- 页面标题包含目录类关键词，例如 `目录`、`目 录`、`CONTENTS`、`Table of Contents`。
- 页面标题包含图表目录类关键词，例如 `图目录`、`表目录`、`List of Figures`、`List of Tables`。
- 多行满足 `标题 + 页码` 或 `标题 + 点线/空格/tab + 页码`。
- 多行以章节编号开头，例如 `1`、`1.1`、`I`、`IV`、`第一章`、`Chapter 1`。
- 行尾页码密集，且短标题行比例高。

规则检测必须依赖多个独立信号组合，不能因为单个关键词就判定为目录页。规则要覆盖常见语言和标准目录形态，但只做泛化模式，不为单个文件增加特例。

规则检测的取舍原则：

- 高置信标准目录：直接进入规则抽取。
- 有目录迹象但信号不足：交给 LLM 分类。
- 信号互相矛盾：交给 LLM 分类。

排除信号：

- 大段正文。
- 参考文献、免责声明、版权页。
- 普通章节首页。
- 只有页脚页码，没有目录项密度。

规则检测输出：

```json
{
  "toc_pages": [3, 4, 5],
  "confidence": 0.92,
  "sections": [
    {"kind": "main_toc", "pages": [3, 4]},
    {"kind": "figure_toc", "pages": [5]},
    {"kind": "table_toc", "pages": [5]}
  ],
  "method": "rule"
}
```

### 7.2 LLM 分类 fallback

当规则检测低置信或互相矛盾时，使用轻量 LLM 单页分类。

要求：

- 每页一次调用。
- 输出尽量短。
- 可以并发，但只在扫描小批次内并发。
- 分类只判断是否目录页及目录类型，不抽取完整目录。
- 一页可能同时包含多种目录类型，输出必须支持多类型数组，不能只返回单个 `kind`。

输出示例：

```json
{
  "is_toc": true,
  "page": 5,
  "primary_kind": "mixed_toc",
  "sections": [
    {"kind": "main_toc", "confidence": 0.88},
    {"kind": "figure_toc", "confidence": 0.91},
    {"kind": "table_toc", "confidence": 0.86}
  ],
  "confidence": 0.9
}
```

字段约定：

- `is_toc=false` 时，`sections` 为空数组，`primary_kind="none"`。
- 一页只有一种目录时，`primary_kind` 等于该类型，例如 `main_toc`、`figure_toc`、`table_toc`。
- 一页同时有多种目录时，`primary_kind="mixed_toc"`，并在 `sections` 中列出所有目录类型。
- `sections[].kind` 只允许使用稳定枚举：`main_toc`、`figure_toc`、`table_toc`、`other_toc`。
- LLM 分类阶段不抽取目录项；S4 抽取阶段按 `sections` 拆成独立 `toc_sections`，最终前端仍显示为 `目录`、`图目录`、`表目录` 等独立顶级节点。

## 8. S4 BuildToc：四条确定路径

TOC 构建路径只保留四类。无可见目录时统一进入 `content_outline`，由 LLM 根据页级压缩文本判断应输出章节树还是页级平铺，不再保留独立的 `page_outline` 路径。

S4 的统一输入是 S1 生成的 `PageTextMap`。即使文档在 S0/S1 被判定为扫描型、乱码型或 `layout_required`，只要 `PageTextMap` 已生成，规则抽取和 LLM fallback 都必须在该文本上执行。不能因为原始文档需要 OCR，就跳过可见目录页文本抽取，或者回到旧的 layout/VLM 目录构建分支。

| 路径 | 触发条件 | 主要方法 |
|---|---|---|
| A. `embedded_toc` | 多源内置目录采集、合并后通过硬校验 | 直接规范化 |
| B. `visible_toc_with_pages` | 有目录页，且目录项有页码 | 规则优先，失败走 LLM 抽取 |
| C. `visible_toc_no_pages` | 有目录页，但目录项无页码 | LLM 抽取标题，正文定位 |
| D. `content_outline` | 无目录页 | 基于页级压缩文本生成章节树或页级平铺 |

### 8.1 标准目录规则抽取

如果目录页格式标准，优先使用规则直接抽取。

对于没有可用 `embedded_toc`、但可见目录页质量很高的文档，规则抽取是 `visible_toc_with_pages` / `visible_toc_no_pages` 的首选子路径。只要规则抽取结果通过完整性、页码语义、标题命中和图表目录拆分校验，就直接进入 S5 映射，不调用 LLM 抽取。LLM 只在规则低置信、目录跨区块不稳定、页码语义无法确定或校验失败时使用。

支持高置信格式：

```text
第一章 标题 ........ 1
1.1 标题 .......... 3
1.1.1 标题 ........ 5
图 1 标题 ........ 10
表 2 标题 ........ 12
```

规则抽取要增强鲁棒性，但保持高精度边界：

- 支持常见编号、点线、空格、tab、行尾页码、图表目录等标准模式。
- 支持中文和英文等常见目录标题与章节编号形态。
- 不处理需要语义理解、跨行合并不稳定、多栏顺序不确定的复杂目录。
- 必须区分“章节编号”和“页码”。例如 `01-04` 可能是章节号而不是页码，不能直接拿来计算 printed page offset；如果页码语义校验不通过，应切换到 `visible_toc_no_pages` 的标题定位逻辑，但目录项抽取本身仍可来自规则。
- 必须能拆分主目录、图目录、表目录；如果规则把图表目录混入主目录，视为校验失败并降级 LLM。

规则抽取失败、低置信或校验不过，立即降级到 LLM 抽取。不要继续叠加特殊规则。

规则抽取失败或映射校验失败时，必须继续调用 LLM 抽取目录页文本，而不是直接返回空目录或切换到旧 layout 分支。规则只是低成本高精度的首选子路径，不是可见目录路径的唯一实现。

当前真实样本中，这类高质量可见目录至少包括：

- `2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf`
- `AI眼镜关键技术与产业生态研究报告（2025年）.pdf`
- `OpenAI深度报告：大模型王者，引领AGI之路.pdf`
- `人工智能安全治理研究报告（2025年）.pdf`

### 8.2 LLM 目录抽取

LLM 只处理确认过的目录页文本。

提示词职责：

- 完整抽取目录项。
- 保持自然阅读顺序。
- 区分主目录、图目录、表目录。
- 有页码则保留原始页码。
- 无页码则留空。
- 不推理物理页码和 offset。

输出结构：

```json
{
  "toc_sections": [
    {"kind": "main_toc", "title": "目录", "items": []},
    {"kind": "figure_toc", "title": "图目录", "items": []},
    {"kind": "table_toc", "title": "表目录", "items": []}
  ]
}
```

### 8.3 有页码目录

路径：`visible_toc_with_pages`。

处理方式：

1. 抽取目录项和原始页码。
2. 不让 LLM 推理 offset。
3. 后处理计算 printed page offset。
4. 用标题命中验证 offset。
5. offset 稳定则批量映射。
6. 失败项回退标题搜索。

### 8.4 无页码目录

路径：`visible_toc_no_pages`。

处理方式：

1. 抽取标题和层级。
2. 不猜页码。
3. 用标题在 `PageTextMap` 中检索定位。
4. 定位成功的标题作为章节 anchor。
5. 根据 anchor 顺序生成范围。
6. 如果只定位到顶级节点，章节内部结构交给 LLM 判断：对章节范围内每页取前 200 个字符，连同物理页码传给 LLM，让它生成该章节内的子目录结构。

章节内子节点不能再用规则硬抽标题。规则只负责顶级 anchor 的检索和校验；层级结构判断交给 LLM。

### 8.5 无目录正文建树

如果没有可见目录页，统一走 `content_outline`。

`content_outline` 可以复用现有 hierarchical/batch 能力，但它们只能作为该路径内部实现，不再作为并列候选。输入应优先使用页级压缩文本，例如每页前 200 个字符和物理页码，由 LLM 判断结构。

输出规则：

- 如果文档有稳定章节结构，输出章节树。
- 如果文档是 PPT、白皮书、逐页主题型报告，输出页级平铺，或少量主题分组下挂页级节点。
- 平铺是允许的，只要它反映原文形态。
- 不能为了追求层级而用规则硬抽子标题。

## 9. S5 MapPhysicalPages：统一物理页码映射

最终 TOC 只输出物理页码。

| 来源 | 映射方式 |
|---|---|
| `embedded_toc` | 内置页码转物理页，抽样校验 |
| `visible_toc_with_pages` | printed page offset + 标题校验 |
| `visible_toc_no_pages` | 标题检索定位 |
| `content_outline` | 生成时就是物理页 |

图目录、表目录要独立映射，不参与主目录章节范围切分。

### 9.1 范围修正规则

节点范围修正必须对所有同级节点递归适用，不只处理顶级节点。

对任意同级节点 `current` 和它的下一个节点 `next`：

```text
if next.start_page == current.end_page:
    current.end_page = next.start_page
else:
    current.end_page = next.start_page - 1
```

原因是：如果两个节点共享同一个起始页，通常表示下一个章节标题出现在当前章节的最后一页；这种边界重合是合理的，不应强行减一。

范围修正后必须校验：页码在物理页范围内，`start_page <= end_page`，子节点范围不得明显超出父节点范围，相邻节点允许边界重合但不允许大范围无解释重叠，大量节点落在目录页时必须判为质量问题。

## 10. S6 QualityGate：质量门

质量门只判断 TOC 是否可用，不做审美评价。

### 10.1 硬失败条件

- TOC 为空。
- 大量节点页码越界。
- 大量节点指向目录页。
- 有页码目录的 offset 校验失败。
- 无页码目录的标题定位率过低。
- 节点内容无法从 `PageTextMap` 填充。
- 图目录/表目录混入主目录并影响主章节范围。

### 10.2 不应失败的情况

- 原文目录本来就是平铺结构。
- 章节层级较浅。
- 父子节点范围有合理重合。
- 图目录/表目录是索引型节点，没有完整正文范围。

### 10.3 LLM 质检

LLM 质检只作为最终质量判断，不参与前面的路径竞赛。

质检重点：

- 是否反映原文目录形态。
- 页码是否明显错误。
- 是否有大量目录项落在目录页。
- 图目录、表目录是否与主目录分开。
- 平铺是否符合原文，而不是强制要求树状结构。

## 11. S7/S8 保存与 enrich

保存顺序固定：

```text
TOC 通过质量门
  -> Save base index
  -> Enrich summary / description / node summaries
  -> Save final index
```

enrich 只消费 TOC 结果，不参与路由，不改变 TOC 结构。

节点内容从 `PageTextMap` 中按物理页范围填充，不重新 OCR。

## 12. 日志与可观测性

主日志保持简洁，只记录阶段、路径和关键结果。

示例：

```text
[TOC-PIPELINE] stage=preprocess content_type=hybrid pages=64 ocr_pages=7
[TOC-PIPELINE] stage=toc_detect method=rule toc_pages=7-9 sections=main,figure,table
[TOC-PIPELINE] stage=toc_build path=visible_toc_with_pages method=llm items=58
[TOC-MAPPING] strategy=printed_page_offset offset=9 anchors=12/14 title_match=86%
[TOC-QUALITY] status=pass score=0.82 warnings=2
```

OCR 细节日志不要写入主日志。主日志只保留模型和页数摘要：

```text
[TOC-OCR] task=page_text model=qwen-vl-ocr pages=44 concurrency=20
```

详细 OCR 输入、输出、耗时、错误写入单独调试日志。

## 13. 复用现有能力

这次重构不是推翻现有实现，而是重新组织职责。

| 现有能力 | 新位置 |
|---|---|
| OCR adapter | S1 PreprocessToPageText |
| code_toc/bookmarks/links | S2 TryEmbeddedToc；必须并行采集、合并、分类为主目录/图目录/表目录，不能单源短路 |
| TOC page detector | S3 DetectTocPages |
| strict parser | S4 标准目录规则抽取，仅高置信使用 |
| LLM TOC extractor | S4 LLM 目录抽取 |
| title search | S5 物理页映射 |
| printed page offset | S5 物理页映射 |
| hierarchical/batch extractor | S4 `content_outline` 内部实现 |
| flat fallback / page heading outline | 不作为独立路径；并入 `content_outline` 的页级平铺输出，且低置信时必须交给 LLM 判断 |
| quality gate | S6 QualityGate |

## 14. 迁移计划

### 14.1 第一阶段：建立统一输入

- 实现 `PageTextMap`。
- 把文本型、OCR 型、混合型统一到同一输出结构。
- 节点内容填充改为读取 `PageTextMap`。

### 14.2 第二阶段：显式状态机

- 引入状态机入口。
- 禁止多候选竞赛式执行。
- 每个状态记录明确输入、输出和失败原因。

### 14.3 第三阶段：目录页检测与标准解析

- 规则检测 TOC 页。
- 规则抽取标准目录。
- 校验失败后降级 LLM。

### 14.4 第四阶段：统一映射与质量门

- 统一 printed page offset、标题搜索和范围生成。
- 图目录、表目录独立处理。
- 质量门按路径判断，不强制树状结构。

### 14.5 第五阶段：清理旧路径

- 移除或隔离多候选竞赛入口。
- 删除不能解释来源的 fallback。
- 保留旧能力作为状态机内部实现。

## 15. 端到端验收样本

至少覆盖以下文档类型：

| 样本 | 预期路径 | 验收重点 |
|---|---|---|
| 重庆扫描 PDF | `ocr` + `visible_toc_with_pages` 或 `visible_toc_no_pages` | OCR 后标题定位、物理页正确 |
| OpenAI 深度报告 | `text/hybrid` + `visible_toc_with_pages` | 主目录、图目录、表目录分开；第四章页码正确 |
| 高质量可见目录无 code_toc 样本 | `visible_toc_with_pages` 或 `visible_toc_no_pages` | 优先规则抽取；规则通过校验则不调用 LLM；包括 2026AI 应用专题、AI 眼镜、OpenAI 深度报告、人工智能安全治理 |
| 生成式人工智能服务合规备案指南 | `text` + `embedded_toc`，质检失败时回退 `visible_toc_with_pages` | bookmarks 与 TOC links 合并，保留目录、表目录、图目录；不能因 bookmarks 存在而跳过 links；embedded 结构不干净时用可见目录重建 |
| AI Agent 智能体技术发展报告 | `text` + `embedded_toc` | 通过 PDF links 提取 3-8 页目录，规范化多级结构，避免第二章被推成 `1.x` 子项 |
| 全球人工智能技术应用洞察报告 | `text` + `embedded_toc` | 识别弱 slide-export outline，清洗后才可接受；不能让 raw 幻灯片书签绕过 fast path 质量门 |
| AI 眼镜研究报告 | `text/hybrid` + `visible_toc_with_pages` | 图表目录独立映射 |
| 快消行业 AI 营销白皮书 | `hybrid` + `visible_toc_no_pages` | 先补 OCR 识别第 4 页目录，再按 Part 目录定位和建树 |
| 第五范式报告 | `text` + `visible_toc_with_pages` 或 `embedded_toc` | 不再并行跑多条 LLM 路径 |

验收标准：

- 能成功生成 TOC。
- TOC 物理页码可直接用于内容提取。
- 主目录、图目录、表目录不互相干扰。
- OCR 内容只生成一次并复用。
- 主日志能清楚看出实际路径。
- 失败时能给出明确失败原因。

## 16. 非目标

本架构不追求：

- 让所有文档都生成深层树状结构。
- 用规则覆盖所有目录格式。
- 用 LLM 解决所有页码映射问题。
- 在同一轮中跑多个完整 TOC 路径竞赛。
- enrich 阶段反向修正 TOC 路由。
- 保留独立的 `page_outline` 路径；页级平铺由 `content_outline` 输出。

## 17. 总结

新的 TOC 架构可以概括为：

```text
PDF
  -> 按页可靠文本 PageTextMap
  -> 确定性 TOC 路径
  -> 统一物理页码映射
  -> 质量门
  -> 保存与 enrich
```

它保留现有 OCR、规则、LLM、标题搜索和质量门能力，但把它们放回清晰的层次中。

核心收益：

- 路径更少。
- 成本更可控。
- 日志更可解释。
- 不同文档类型质量更一致。
- 后续问题可以定位到明确阶段，而不是在多个候选路径之间猜。
