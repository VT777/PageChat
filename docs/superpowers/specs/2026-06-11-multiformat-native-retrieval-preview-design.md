# 多格式原生检索、导航图、预览与引用设计文档

日期：2026-06-11

## 1. 背景与目标

当前系统已经完成 Phase 7 的多格式 canonical adapter 迁移，并在 Phase 8.2 中让前端可以消费 TXT、Markdown、CSV/TSV、XLSX、DOCX、PPTX 的基础 preview block 和 `source_anchor`。这解决了“非 PDF 不能预览、不能定位”的底层问题，但还没有达到产品层面的“模型能快速判断文档是否值得查、查到后能稳定引用、用户点击后能回到原文位置”。

本设计文档将下一阶段目标从“为每种格式生成更多摘要和更像原生的预览”收敛为三个更基础的目标：

- 为每个文档生成清晰的“导航图”：PDF/DOCX/Markdown/PPTX 是目录或结构树，CSV/XLSX 是 workbook、sheet、table region、schema 和字段画像，TXT 是轻量分段地图。导航图的第一职责是让模型判断“问题相关信息是否可能在这个文档里”。
- 摘要不是默认必要能力。摘要、视觉理解和模型生成内容都应按需触发，并通过成本、风险和收益阈值控制。很多视觉内容先 OCR 后进入关键词匹配，可能已经足够支持召回和取证。
- 建立跨格式稳定引用标识体系。引用应由结构化 `source_anchor` 驱动，文本引用只是人类可读标签；对易变内容要加入 quote/hash 等二级 selector，减少重建索引或文档轻微变化造成的定位漂移。

本文是设计规格，不是实现计划。后续应基于本文再拆分为可执行的分阶段计划。

## 2. 当前基线

### 2.1 已有能力

- PDF 已有页级预览、目录树、页面跳转和 page anchor。
- 非 PDF canonical adapters 已能输出 `DocumentContent`、`ContentBlock`、`IndexNode` 和 `source_anchor`。
- Search、tools 和 frontend evidence chip 已能保留 `source_anchor` 和 `display_label`。
- `source_anchor_resolver.py` 已支持 line、row、paragraph、slide 等 source anchor 的内容解析。
- 前端 `UniversalPreview` 已能按格式选择 TXT、Markdown、table、DOCX、PPTX viewer。

### 2.2 主要不足

- 当前设计把“节点摘要”放得过重，容易把索引成本推高，也可能让模型依赖二手概括而不是原文结构。
- 非 PDF 的结构地图还不够像各自格式：Excel 左侧导航更像行块列表，而不是 workbook/sheet/schema；PPTX 更像文本列表，而不是 deck/slide；DOCX 与 Markdown 的 heading 结构还没有成为模型首要入口。
- PPTX 预览只是文本卡片，不是原样幻灯片。
- Markdown 预览是逐 block 渲染，不能完整体现 GFM 文档结构。
- DOCX 预览是结构化文本，不是 Word 原生版式。
- 非 PDF 的 modal 左侧 TOC 仍然偏 PDF page 模型，点击不能统一传递 `source_anchor`。
- TOC hover 摘要在视觉上不协调，应取消。
- Agent prompt 仍在教模型对非 PDF 使用 `p.x`，与当前 source anchor contract 冲突。
- 引用标识还缺少“稳定性层”：当行号、段落号、row chunk 或渲染资产变化时，没有 quote、hash、路径 selector 帮助恢复定位。

## 3. 核心设计原则

### 3.1 Navigation Map First

所有格式都应先产出一个低成本、稳定、可解释的 `navigation_map`。它不是为了替代全文检索，而是为了让模型在回答前能快速完成三件事：

1. 判断这个文档是否可能包含答案。
2. 判断应该进入哪个章节、sheet、表格区域、slide 或 line window。
3. 为后续 resolver 和引用生成提供稳定 anchor。

不同格式的导航图不必长得一样：

| 格式 | 导航图核心 | 模型判断问题 |
| --- | --- | --- |
| PDF | TOC、页范围、扫描/OCR 状态、图表页标记 | 答案可能在哪个章节或页？是否需要 OCR/视觉？ |
| Markdown | heading tree、section line range、code/table/image blocks | 答案在哪个 heading 下？是否是代码或表格问题？ |
| DOCX | heading style tree、paragraph groups、tables、images、footnotes | 答案在哪个条款/章节/表格？ |
| PPTX | deck -> slide outline、slide title、text/notes presence、visual-heavy flag | 答案可能在哪页？是文字、备注还是视觉图表？ |
| CSV/TSV | table schema、字段类型、row count、关键字段、统计画像 | 是否包含目标字段或记录？要查行还是做聚合？ |
| XLSX | workbook -> sheet -> table region -> schema/row chunks | 目标信息在哪个 sheet/table？字段是否存在？ |
| TXT | line windows、段落边界、时间戳/日志弱信号 | 只能按文本召回，命中范围在哪些行？ |

### 3.2 摘要按需，而不是默认产物

摘要有价值，但不是多格式检索的基础依赖。它有三个风险：

- 成本风险：为每个 node 预生成摘要会在大文档、Excel 多 sheet、PPT 多页场景快速膨胀。
- 事实风险：摘要会丢字段、丢限定条件、误概括图表或合同条款。
- 维护风险：摘要一旦成为检索主入口，重建策略、缓存失效和质量评估都会复杂化。

默认策略应是：

- 导航图、schema、结构 metadata、关键词、OCR 文本优先。
- 对表格先生成 deterministic profile，例如字段名、类型、空值率、distinct 样例、min/max，而不是自然语言摘要。
- 对视觉内容优先 OCR，保存 text layer 和 low-confidence 标记。只有 OCR 为空、用户问题明显涉及图表/布局/图片，或文档被标记为 visual-heavy 时，才触发视觉模型摘要。
- 对长章节或长 slide deck，可按需生成 query-scoped 摘要，而不是 ingest 阶段全量摘要。

### 3.3 索引、导航、预览分工明确

- `navigation_map` 面向路由和判断：轻量、稳定、覆盖全局结构。
- `index_nodes` 面向召回：可切分得更细，支持 embedding、BM25、keyword、schema search。
- `content_blocks` 面向预览：尽量保留原始结构和渲染需要。
- `render_assets` 面向原生预览：PDF/PPTX/DOCX 可生成页面或 slide 图片。
- `source_anchor` 面向定位和引用：跨后端、前端、Agent 的唯一权威。

不要把所有格式强行抽象成 PDF page，也不要让预览形态反过来决定检索结构。

### 3.4 引用必须由结构化 anchor 驱动

文本引用标记只是 UI 表达，不应该成为真实定位来源。工具结果、检索结果和 Agent 上下文应优先传递：

- `doc_id`
- `doc_version` 或 `content_hash`
- `source_anchor`
- `display_label`
- `selector_fallbacks`
- `retrieval_source`
- `confidence`
- `why_selected`

前端点击引用时必须优先使用结构化 anchor。文本 `[[...]]` 只作为人类可读 fallback。

### 3.5 质量报告评估结构覆盖，而不是摘要覆盖

质量报告应从“摘要是否齐全”转向“导航图和 anchor 是否可信”：

- 导航图覆盖率。
- anchor 完整率。
- anchor 可解析率。
- schema 识别置信度。
- OCR 覆盖率和低置信 OCR 比例。
- visual-heavy 内容比例。
- 表格区域识别质量。
- 超长节点比例。
- fallback selector 可用率。

摘要覆盖率可以作为可选增强指标，但不应成为核心 gate。

## 4. 通用数据模型

### 4.1 DocumentContent

`DocumentContent` 是 adapter 输出根对象，应包含：

- `format`
- `title`
- `doc_description`，可选，低成本 metadata 或用户提供标题优先；不要默认调用模型生成。
- `unit_type`
- `unit_count`
- `navigation_map`，新增，模型和 UI 的首要结构入口。
- `index_nodes`
- `content_blocks`
- `metadata`
- `render_assets`，用于原生预览资产，例如 PPT/PDF/Office 转换后的页面图片。
- `quality_report`

### 4.2 NavigationMap

`NavigationMap` 是跨格式结构地图，强调稳定、轻量和可被模型扫描。

推荐 shape：

```json
{
  "format": "xlsx",
  "doc_id": "doc_123",
  "doc_version": "sha256:...",
  "root": {
    "id": "nav:workbook",
    "label": "Workbook",
    "kind": "workbook",
    "anchor": { "format": "xlsx", "unit_type": "workbook" },
    "children": [
      {
        "id": "nav:sheet:Sales",
        "label": "Sales",
        "kind": "sheet",
        "anchor": { "format": "xlsx", "unit_type": "sheet", "sheet": "Sales" },
        "metadata": { "used_range": "A1:H2400", "table_count": 2 }
      }
    ]
  }
}
```

字段说明：

- `id`：导航节点内部稳定 ID，重建索引后应尽量保持一致。
- `label`：短标题，供模型和 UI 扫描。
- `kind`：`section`、`sheet`、`table_region`、`schema`、`row_chunk`、`slide`、`line_window` 等。
- `anchor`：跳转和引用的结构化定位。
- `metadata`：结构判断所需的低成本信息，例如字段名、行数、页数、OCR 状态、visual-heavy 标记。
- `children`：结构层级。

导航图不默认包含大段正文，也不默认包含自然语言摘要。

### 4.3 IndexNode

`IndexNode` 是召回主单元，可以从导航图派生，也可以比导航图更细。建议字段：

- `node_id`
- `nav_id`，可选，关联导航节点。
- `title`
- `text`
- `level`
- `source_anchor`
- `node_type`：`section`、`row_chunk`、`schema`、`table_region`、`slide_text`、`ocr_text` 等。
- `keywords`：deterministic extraction 优先。
- `schema`：表格列类型或字段信息。
- `stats`：表格字段画像、行数、空值率、min/max 等。
- `visual_flags`：是否依赖图片、图表、OCR。
- `confidence`：节点结构置信度。
- `summary`：可选，仅在策略触发时生成。

### 4.4 ContentBlock

`ContentBlock` 面向预览，应保留原始结构：

- TXT/Markdown：line、heading、paragraph、code、table。
- XLSX：sheet、table_region、table_row、formula、merged_cell marker。
- DOCX：heading、paragraph、table、list、image_placeholder、footnote。
- PPTX：slide、shape_text、notes、rendered_slide、ocr_text、visual_placeholder。

### 4.5 SourceAnchor

`SourceAnchor` 是跨层定位契约。下一阶段应把它作为左侧导航、证据 chip、正文引用和 viewer 跳转的唯一权威。

推荐 shape：

```json
{
  "format": "xlsx",
  "unit_type": "row_range",
  "sheet": "Sales",
  "table_id": "sales_orders_1",
  "start_row": 2,
  "end_row": 24,
  "start_col": 1,
  "end_col": 8
}
```

通用字段：

- `format`
- `unit_type`
- `section_id`
- `table_id`
- `render_asset_id`
- `bbox`，用于 PDF/PPT/图片区域定位。
- `path`，用于 heading path、sheet path、slide path 等结构路径。

## 5. 稳定引用标识设计

### 5.1 设计目标

跨格式引用要同时满足三类需求：

- 模型生成稳定：Agent 不需要猜页码、行号或 sheet 名；它应使用工具返回的 `display_label` 和 `source_anchor`。
- 系统定位稳定：重建索引、轻微文档变化、渲染资产变化后，系统仍能尽量找回原位置。
- 用户可读：回答里的引用标签要短、自然、能帮助用户理解证据来源。

### 5.2 可借鉴的标准实践

外部标准给出几条有用经验：

- RFC 5147 为 `text/plain` 定义了 line/char fragment，并允许用完整性信息增强定位鲁棒性。
- RFC 7111 为 `text/csv` 定义了 row、col、cell fragment，说明表格引用应保留二维坐标，而不是只用行号。
- W3C Media Fragments 使用 `xywh` 表达空间区域，适合 PDF/PPTX/图片的 bbox 扩展。
- W3C Web Annotation Data Model 使用多种 selector 组合，例如位置 selector、quote selector、fragment selector。这个思想很适合我们：结构 anchor 是主 selector，quote/hash/path 是 fallback selector。

### 5.3 三层引用模型

每条证据应包含三层信息：

1. Primary selector：`source_anchor`。负责精确跳转，是系统权威。
2. Robust fallback selectors：`selector_fallbacks`。负责 anchor 漂移后的恢复。
3. Human label：`display_label`。负责模型回答和 UI 展示。

推荐 shape：

```json
{
  "doc_id": "doc_123",
  "doc_version": "sha256:abc",
  "source_anchor": {
    "format": "markdown",
    "unit_type": "line_range",
    "start_line": 35,
    "end_line": 48,
    "path": ["Architecture", "Indexing"]
  },
  "selector_fallbacks": {
    "text_quote": {
      "exact": "NavigationMap is the first structure entry...",
      "prefix": "The adapter should emit",
      "suffix": "before retrieval nodes are built."
    },
    "content_hash": "sha256:node_text_hash",
    "structural_path": "Architecture > Indexing",
    "ordinal_hint": 3
  },
  "display_label": "design.md line 35-48"
}
```

### 5.4 Anchor 稳定性等级

不同 anchor 的稳定性不同，系统应显式记录 `stability_level`：

| 等级 | 示例 | 稳定性 | 恢复策略 |
| --- | --- | --- | --- |
| A | PDF page、PPTX slide、XLSX sheet + cell/range | 高 | 结构 anchor 优先，hash 校验 |
| B | Markdown line range + heading path、DOCX paragraph + heading path | 中 | line/paragraph 失败后用 heading path + text quote |
| C | TXT line window、OCR text block、自动 table region | 较低 | quote/hash/keyword fallback，必要时提示位置近似 |
| D | visual bbox、转换后 render asset 坐标 | 取决于渲染版本 | 绑定 render asset version，转换变化后重新定位 |

### 5.5 文本引用格式

Agent 应使用工具返回的 `display_label`。没有 `display_label` 时才由系统格式化：

| 格式 | 文本 fallback |
| --- | --- |
| PDF | `[[报告.pdf p.12]]` |
| TXT | `[[访谈.txt line.20-38]]` |
| Markdown | `[[README.md line.35-48]]` |
| CSV/TSV | `[[sales.csv row.8-24]]` 或 `[[sales.csv cell.B8]]` |
| XLSX | `[[sales.xlsx Sales!A2:H24]]`，真实定位依赖 `source_anchor.sheet/table_id` |
| DOCX | `[[合同.docx para.12-20]]` |
| PPTX | `[[方案.pptx slide.3]]` |
| PDF/PPTX/image region | `[[方案.pptx slide.3 region]]`，bbox 不直接暴露给模型 |

明确禁止非 PDF 统一使用 `p.x`。

### 5.6 引用解析优先级

点击引用或二次取证时按以下顺序解析：

1. `doc_id + doc_version + source_anchor` 精确解析。
2. 如果版本变化，尝试同一 `source_anchor` 并校验 `content_hash`。
3. 如果 anchor 失败，使用 `structural_path` 找相近 section/sheet/slide。
4. 在候选范围内用 `text_quote.exact` 或 OCR 文本匹配。
5. 仍失败时用 `prefix/suffix`、keywords 和 ordinal_hint 近似恢复，并在 UI 标记“位置可能近似”。

## 6. 分格式索引与导航设计

### 6.1 PDF

PDF 继续作为高结构格式处理，但导航图应强调“目录和页的覆盖关系”：

- `navigation_map`：TOC tree、page ranges、unmapped pages、OCR/scanned flags、visual-heavy pages。
- `index_nodes`：TOC section、page text、OCR text、可选 visual node。
- `source_anchor`：`page`，未来扩展 `bbox`。
- 摘要策略：不要求每个 TOC 节点有摘要。优先使用 TOC title、page text 和 OCR。只有长 section 或 visual-heavy page 需要 query-scoped summary。
- 质量指标：TOC 覆盖率、page anchor 可解析率、OCR 页比例、unmapped pages、visual-heavy pages、bbox/render asset version 一致性。

### 6.2 TXT

TXT 是轻量文本格式，不构建正式 TOC，不预生成全量摘要。目标是“轻量可检索、可定位、可引用”。

- `navigation_map`：line windows、段落边界、首行 snippet、字符数、可选时间戳/日志级别弱信号。
- `index_nodes`：paragraph chunk 或 fixed line window。
- `source_anchor`：`{ "format": "txt", "unit_type": "line_range", "start_line": 12, "end_line": 38 }`。
- 检索策略：BM25/embedding + line resolver；第一跳返回 line range、命中 snippet 和 metadata，不返回超长正文。
- 摘要策略：默认无摘要。大文件只做固定窗口和关键词召回。
- 预览设计：左侧显示轻量分段列表或命中列表，不叫 TOC；右侧按 line anchor 跳转和高亮。
- 质量指标：行数覆盖率、编码异常、空行/乱码比例、超长窗口比例、大文件轻量模式状态。

### 6.3 Markdown

Markdown 的导航图应以 heading tree 为中心，并保留 code/table/image 的结构信号。

- `navigation_map`：H1-H6 tree、section line range、code fence、GFM table、image reference、link density。
- `index_nodes`：heading section、code block、table block、image alt/OCR text。
- `source_anchor`：line range + heading path。
- 检索策略：标题/说明问题先查 heading section；代码问题查 code block；表格问题查 markdown table schema。
- 摘要策略：默认不生成 section summary。长 section 可在 query 阶段临时压缩；image-only section 先 OCR/alt text。
- 预览设计：右侧整体 GFM 渲染，左侧 heading tree 点击 line anchor，命中行范围高亮。
- 质量指标：heading 覆盖率、code fence 闭合率、table 解析成功率、section 长度分布、image-only section 数量、line anchor 可解析率。

### 6.4 CSV / TSV

CSV/TSV 的核心不是摘要，而是 schema 和二维坐标。

- `navigation_map`：table schema、row count、column list、column types、关键字段样例、row chunks、可选统计画像。
- `index_nodes`：schema node、row chunk、column profile、category/numeric profile。
- `source_anchor`：row/col/cell/range。参考 RFC 7111 思路，保留 row、col、cell 维度。
- 检索策略：字段含义查 schema；具体记录查 row chunk；统计问题走 deterministic aggregate；自然语言摘要只作为最后增强。
- 摘要策略：不默认生成自然语言表格摘要。用字段画像代替：类型、空值率、distinct 样例、min/max、top categories。
- 预览设计：左侧显示 Schema、字段、row chunks；右侧 sticky header、数字右对齐、命中 row/col/cell 高亮。
- 质量指标：header 识别置信度、schema 识别置信度、空列/空行比例、行数覆盖率、分隔符置信度、row/cell anchor 可解析率。

### 6.5 XLSX

XLSX 是 workbook，不是单表文件。导航图必须先帮助模型判断 sheet 和字段是否存在。

- `navigation_map`：workbook -> sheet -> table region -> schema -> row chunks。
- sheet metadata：used range、hidden 状态、row/col count、formula ratio、merged cell count、table region count。
- table region metadata：`table_id`、range、headers、schema、key columns、sample rows、confidence。
- `index_nodes`：workbook node、sheet node、table schema node、row chunk、column profile、formula profile。
- `source_anchor`：sheet + table_id + row/col/cell/range，例如 `Sales!A2:H24`。
- 检索策略：跨 sheet 问题先查 workbook/sheet map；字段或口径查 schema；具体记录查 row chunk；聚合问题走 deterministic aggregate。
- 摘要策略：默认不生成 workbook/sheet 自然语言摘要。sheet “描述”应由字段列表、表区域、样例和统计画像组成。只有用户问“总结这个工作簿”时才按需生成。
- 预览设计：左侧叫“工作簿导航”，不是普通目录；右侧有 sheet tabs、sticky header、命中行列高亮、类型格式化、空值淡化。
- 质量指标：sheet 解析数量、table region 识别置信度、schema 识别置信度、公式比例、隐藏/合并单元格标记、超大 workbook 截断状态、sheet/range anchor 可解析率。

### 6.6 DOCX

DOCX 的导航图应以 Word 语义结构为中心，而不是页码。段落号可用于定位，但引用恢复需要 heading path 和 quote selector。

- `navigation_map`：heading style tree、paragraph ranges、tables、lists、images、footnotes/endnotes、headers/footers。
- `index_nodes`：docx section、paragraph group、table、list、image OCR/alt。
- `source_anchor`：paragraph range、table_id、可选 heading path。
- 检索策略：合同/报告问答先查 heading tree；条款定位查 paragraph group；表格问答查 docx_table；图片扫描内容先 OCR。
- 摘要策略：默认不为每个 section 生成摘要。条款类文档尤其应优先给原文段落，避免摘要误改限定条件。
- 预览设计：当前阶段继续结构化 Word preview；标题、列表、表格更接近 Word 阅读体验。后续可选 LibreOffice 转 PDF/PNG，与 PPTX render asset 统一。
- 质量指标：heading style 覆盖率、paragraph anchor 可解析率、table 解析成功率、image-only 内容比例、footnote 覆盖率、超长 section 比例。

### 6.7 PPTX

PPTX 的导航图核心是 deck/slide，而不是文本摘要。用户预览期待原始幻灯片。

- `navigation_map`：deck -> slide outline、slide title、slide text length、notes presence、visual-heavy flag、chart/table/image count、render status。
- `index_nodes`：slide text、notes、OCR text、可选 visual summary、chart/table node。
- `source_anchor`：slide；未来扩展 slide_region + bbox。
- 检索策略：普通文本问题查 slide text + notes；视觉/图表问题先查 OCR text 和 visual-heavy 标记，再按需触发视觉模型；演示结构问题查 deck/slide outline。
- 摘要策略：不默认为每页生成视觉摘要。优先使用 slide XML text、notes、渲染图 OCR。只有 text 少且 visual-heavy，或用户问题明确涉及图表、图片、流程图时，才生成 visual summary。
- 预览设计：后端可选用 LibreOffice headless 将 PPTX 转 PDF/PNG，前端显示 slide image 和缩略图 grid；转换失败 fallback 到文本预览并标记。
- 质量指标：slide anchor 可解析率、text extraction 覆盖率、notes 覆盖率、render success rate、OCR 覆盖率、visual-heavy slide 数量、visual summary 触发次数和成本。

## 7. OCR、视觉内容与摘要取舍

### 7.1 默认处理顺序

视觉内容的处理顺序应从低成本到高成本：

1. 解析原生文本层：PDF text、PPTX shape text、DOCX paragraph、Excel cell text。
2. 生成结构导航图：TOC、heading、sheet/schema、slide outline。
3. 对视觉资产做 OCR：扫描页、slide render、图片占位、图表截图。
4. OCR 文本进入关键词和 embedding 检索，并标记置信度。
5. 只有 OCR 不足以回答、用户问题需要视觉理解、或节点被标记为 visual-heavy 时，触发视觉模型摘要。

### 7.2 何时生成摘要

允许生成摘要的场景：

- 用户显式要求总结文档、章节、sheet 或 slide deck。
- 检索阶段需要压缩一个超长 section，但必须保留可回到原文的 anchors。
- visual-heavy 内容经过 OCR 后仍无法表达图表趋势、流程关系或图片语义。
- 系统处于后台预处理且预算允许，并且摘要被标记为非权威辅助信号。

不应生成摘要的场景：

- 表格 schema 已足够判断字段和范围。
- 合同、法规、技术规范等需要精确措辞的内容。
- 大量 chunk 的 ingest 阶段批量摘要。
- OCR 已能支持关键词匹配和原文取证。

### 7.3 摘要的产品语义

如果生成摘要，必须在数据模型中标记：

- `summary_source`: `model`、`deterministic_profile`、`ocr_derived`。
- `summary_scope`: section/sheet/slide/range。
- `summary_confidence`。
- `not_authoritative: true`，用于提醒模型摘要不是证据本体。

回答最终证据仍应引用原文 anchor，而不是摘要 node 本身，除非用户问题明确是“这个摘要说了什么”。

## 8. 统一预览与跳转设计

### 8.1 取消 PDF-only TocTree 事件

当前 `TocTree` 只 emit page number，导致非 PDF 左侧点击不能统一跳转。下一阶段应改为：

```ts
emit('jump', node.source_anchor)
```

如果没有 `source_anchor`，再 fallback 到 page。

### 8.2 UniversalPreview 统一接收 anchor

DocumentView 和 ChatView 都应维护：

- `previewDocId`
- `previewDocType`
- `previewAnchor`

强结构格式都通过 `previewAnchor` 驱动结构跳转。TXT 不承诺结构树，但分段列表和检索命中仍通过 line anchor 跳转。

### 8.3 Viewer 必须实现 anchor navigation

| Viewer | 必须支持 |
| --- | --- |
| PdfReferenceViewer | page、未来 bbox |
| TextViewer | line range |
| MarkdownViewer | line range + heading path |
| TableViewer | sheet + row/col/cell/range |
| DocxViewer | paragraph range + table_id |
| PptxViewer | slide + 未来 bbox |

### 8.4 移除 hover summary

移除 `.summary-popover`。左侧导航只显示 title、位置和必要状态标记，例如 OCR、visual-heavy、schema confidence。摘要如存在，可以放在固定区域：

- 文档详情面板。
- 节点选中后的底部信息区。
- preview metadata tab。

## 9. Agent 提示词与工具描述同步

### 9.1 当前风险

当前 Agent prompt 和部分 tool description 仍要求使用 `[[文档名 p.x]]`，并说非 PDF 的 `x` 是内容单元序号。这会误导模型生成错误引用，特别是 Excel、Markdown、DOCX、PPTX。

### 9.2 新引用规则

Agent 和前端都应遵守：

1. 优先使用工具返回的 `display_label`。
2. 没有 `display_label` 时使用 `source_anchor` 格式化。
3. 只有都没有时，才使用文本 fallback。
4. 不允许把非 PDF 统一写成 `p.x`。
5. 模型不得手写 sheet、line、row、paragraph、slide 编号；编号必须来自工具结果。
6. 模型可以说“没有在当前文档导航图中看到相关 sheet/章节/字段”，这比盲目进入全文检索更可靠。

### 9.3 工具返回上下文

检索工具应返回两类上下文：

- `document_navigation_hits`：命中的文档、章节、sheet、字段、slide，帮助模型判断是否继续深入。
- `evidence_hits`：已经解析到原文范围的证据，包含 `source_anchor`、`selector_fallbacks`、`display_label` 和 snippet。

这样模型可以先利用导航图做文档选择，再用 evidence hits 做回答取证。

### 9.4 需要同步的文件

- `backend/app/prompts/__init__.py`
- `backend/app/services/tool_executor.py` 中工具描述。
- prompt contract tests，例如 `test_tools_prompt_catalog.py` 或新增 `test_multiformat_citation_prompt.py`。
- frontend citation fallback helper tests。

## 10. API 与数据存储设计

### 10.1 Render assets

新增 render assets 概念，服务 PPTX 原样预览，也可复用到 DOCX 原生版式预览。

建议结构：

```json
{
  "render_assets": [
    {
      "id": "slide_1",
      "type": "image",
      "unit_type": "slide",
      "unit_index": 1,
      "url": "/api/documents/{id}/render-assets/slide_1.png",
      "width": 1920,
      "height": 1080,
      "content_hash": "sha256:...",
      "converter": "libreoffice",
      "converter_version": "..."
    }
  ]
}
```

### 10.2 Render lifecycle

- 上传后解析阶段可生成 preview assets，但转换失败不影响文本索引和导航图。
- 删除文档/文件夹时清理 render assets。
- render assets 路径必须 user-scoped，不能跨用户访问。
- render asset version 应进入 bbox anchor 的稳定性校验。

### 10.3 缓存与重建

- `navigation_map`、`index_nodes`、`render_assets` 分开缓存。
- 文件 hash 未变时复用。
- 只修改摘要策略时，不应强制重建 render assets。
- 只重建 render assets 时，应检查 bbox anchor 是否需要失效或重映射。

## 11. 分阶段落地建议

### Phase A：导航图、引用与跳转统一

- 引入 `navigation_map` 概念，并让工具结果优先返回导航命中。
- 修改 Agent prompt 和 tool descriptions。
- 实现三层引用模型：`source_anchor`、`selector_fallbacks`、`display_label`。
- 统一 `source_anchor` driven jump。
- 移除 TOC hover summary。
- 让所有 preview 左侧点击都传完整 anchor。

优先级最高，因为它直接影响“模型是否知道该查哪个文档”和“回答引用是否可信”。

### Phase B：Markdown、CSV/XLSX 的结构地图升级

- Markdown heading tree + line anchor + GFM 整体渲染。
- CSV schema/profile + row/col/cell anchor。
- Excel 工作簿导航、sheet/table/schema 识别和视觉增强。
- Excel sheet/table/row/col anchor 完整跳转。

优先级第二，因为这些格式结构清晰、低成本、收益快。

### Phase C：OCR-first 视觉文本层

- 为 PDF/PPTX/DOCX 图片或渲染资产接入 OCR。
- OCR text 进入关键词检索和 evidence resolver。
- 记录 OCR 置信度、来源和 anchor。
- 不默认调用视觉模型摘要。

### Phase D：PPTX 原样预览与按需视觉摘要

- 引入 LibreOffice headless 转换。
- PPTX -> PDF/PNG render assets。
- 前端 slide image viewer。
- visual-heavy slide 在 OCR 不足时按需生成 visual summary。

### Phase E：DOCX 结构增强与可选原生版式

- DOCX section/list/table/image/footnote nodes 增强。
- 可选 LibreOffice DOCX -> PDF/PNG 预览。
- 结构化 preview 继续保留作为轻量 fallback。

## 12. 测试策略

### 12.1 Backend adapter tests

每种格式至少覆盖：

- `navigation_map` 结构。
- node 与 navigation node 的关联。
- `source_anchor` 完整性。
- `selector_fallbacks` 生成。
- preview block 与 index node anchor 一致。
- quality_report 指标。
- 大文件截断边界。

### 12.2 Source anchor resolver tests

覆盖：

- Markdown line range + heading path fallback。
- TXT line range + quote fallback。
- CSV row/col/cell/range。
- XLSX sheet + table_id + row/col/cell/range。
- DOCX paragraph range + quote fallback。
- PPTX slide range。
- bbox/render asset version mismatch。
- unsupported / conversion failed fallback。

### 12.3 Frontend tests

覆盖：

- TocTree emit anchor。
- UniversalPreview 分发 anchor。
- 每个 viewer 按 anchor 跳转。
- Excel sheet navigation。
- Markdown GFM rendering。
- PPTX rendered image fallback。
- 引用 chip 使用 `display_label`，点击使用 `source_anchor`。
- anchor 失败时显示近似定位或不可定位状态。

### 12.4 Prompt contract tests

必须测试 prompt 中包含：

- PDF 使用 `p.x`。
- Markdown/TXT 使用 `line.x`。
- Excel/CSV 使用 `row.x`、`cell.x` 或 Excel range label。
- DOCX 使用 `para.x`。
- PPTX 使用 `slide.x`。
- 优先使用 `display_label` 和 `source_anchor`。
- 明确禁止非 PDF 统一使用 `p.x`。
- 明确要求模型不得手写不存在于工具结果中的引用编号。

## 13. 风险与取舍

### 13.1 导航图过粗导致召回不足

导航图不是全文索引。它负责路由和判断，不能替代正文 chunk、schema search、OCR text 和 resolver。实现时需要确保“先看导航图”不会变成“只看导航图”。

### 13.2 摘要减少后，模型可能觉得上下文不够

解决方式不是重新全量摘要，而是让工具支持 progressive retrieval：先返回导航图，再按 anchor 拉取原文、表格样例或 OCR 文本，必要时生成 query-scoped summary。

### 13.3 引用稳定性复杂度

三层引用模型会增加存储字段和 resolver 逻辑，但这是跨格式可信引用的核心。可以先实现 `source_anchor + display_label + content_hash`，再补 quote/path fallback。

### 13.4 LibreOffice 依赖

PPTX/DOCX 原生预览依赖 LibreOffice 或类似转换器。应设计成可选能力：可用则生成 render assets，不可用则明确 fallback 到结构化内容预览。系统启动时检测能力，但不能因为缺 LibreOffice 导致应用不可用。

### 13.5 视觉索引成本

PPTX、DOCX、PDF 的视觉摘要可能消耗模型资源。默认 OCR-first，视觉模型摘要只对 visual-heavy 或用户需要时触发，并纳入模型路由和预算控制。

### 13.6 Excel 复杂性

真实 Excel 工作簿可能有公式、合并单元格、隐藏行列、多个表区域。第一阶段应先做 sheet/table/row/schema，不追求完整 Excel 引擎。

### 13.7 文本引用与结构 anchor 的差异

文本引用不能承载所有 anchor 信息，例如 XLSX sheet、table_id、bbox、render asset version。必须让工具结果和前端 evidence 使用结构化 anchor，文本引用只作为人类可读标签。

## 14. 验收标准

完成后应满足：

- 每个支持格式都有 `navigation_map`，模型可以从中判断文档、章节、sheet、字段或 slide 是否可能包含答案。
- 摘要不再是 ingest 阶段默认必需产物；质量报告不以摘要覆盖率作为核心 gate。
- OCR 文本可以进入关键词匹配和 evidence resolver，视觉摘要按需触发。
- Agent 不再生成非 PDF `p.x` 引用，也不会手写工具结果中不存在的引用编号。
- 所有工具结果优先保留 `source_anchor`、`selector_fallbacks` 和 `display_label`。
- Markdown、Excel、DOCX、PPTX 左侧结构导航点击都能跳转到对应位置；TXT 轻量分段列表和检索命中能够按 line anchor 跳转。
- Excel 左侧为工作簿导航，schema 能清楚说明 sheet/table 有哪些字段。
- Markdown 右侧预览接近 GitHub Markdown 阅读体验。
- PPTX 右侧预览可显示原始 slide 渲染图；转换失败时有清晰 fallback。
- TOC hover 摘要已移除。
- 每种格式有独立 quality report 指标，重点评估结构覆盖、anchor 可解析、schema/OCR/render 质量。
- 所有新增格式能力都有 backend、frontend、prompt contract 测试。

## 15. 推荐结论

下一阶段不应围绕“给每种格式补摘要”展开，而应命名为“多格式导航图与可信引用阶段”。核心顺序建议：

1. 建立 `navigation_map`，让模型先知道每个文档大概有什么。
2. 建立三层引用模型，修正 prompt 和工具描述，禁止非 PDF `p.x`。
3. 统一 `source_anchor` 跳转，移除 TOC hover summary。
4. 先升级 Markdown、CSV/XLSX 这类结构清晰、低成本格式。
5. 建立 OCR-first 的视觉文本层，再按需做 PPTX/DOCX/PDF 的视觉摘要和原生预览。

这样做可以先修正“模型不知道该查哪里”和“回答引用不可信”的核心风险，再逐步提升每种格式的阅读和检索体验。摘要、视觉模型和原生渲染仍然重要，但它们应该是围绕导航图和稳定引用体系展开的增强能力，而不是系统默认的基础假设。
