# Agent 资料库导航与视觉证据工具设计

日期：2026-06-22

## 1. 背景与目标

重构前 Agent 工具以 `find_related_documents`、`list_folder_tree`、`list_folder_contents`、`get_document_structure`、`get_page_content`、`get_document_image` 为主。它们能完成检索和取证，但工具语义偏工程实现，UI trace 不够像用户可理解的“浏览文件库”，并且 `get_page_content` 与 `get_document_image` 的证据边界不清晰：

- `find_related_documents` 暴露 matched segments、confidence、retrieval source 等检索内部字段，容易让模型把检索片段当最终证据。
- `get_page_content` 会把较长 `text_content` 原样进入模型上下文、SSE 和前端本地会话，造成响应与渲染变慢。
- 当前 `get_document_image(doc_id, page_num)` 实际渲染整页 PDF 图，不等同于官方 PageIndex 的 `get_document_image(image_path)`。
- 官方工具 trace 更像资料库导航：先看文件夹结构，再浏览文档，再读文档结构，再读页内容，最后按 `image_path` 查看具体 figure。

本设计目标是把 Agent 工具重构为官方式资料库导航工具族，同时保留本系统对模型、OCR、TOC 和问答策略的可配置能力。本文只定义工具和数据设计，不包含前端设置页、文档管理页的详细 UI 实施计划。

## 2. 设计依据

对官方 PageIndex 会话工具内容的观察显示，其工具族包括：

1. `Viewed folder structure`
   - 参数：`folder_id`
   - 结果：`tree`、`depth`、`success`、`truncated`、`next_steps`、`total_folders`
2. `Browsed documents`
   - 参数：`sort`、`query`、`folder_id`、`recursive`
   - 结果：`folders`、`documents`、`has_more`、`next_steps`、`next_offset`
   - 文档项包含 `name`、`path`、`status`、`folder_id`、`created_at`、`description`，不返回正文。
3. `Read the document structure`
   - 参数：`part`、`doc_name`、`folder_id`
   - 结果：结构树，节点包含 `title`、`node_id`、`start_index`、`end_index`、`summary`、`nodes`
4. `Read pages`
   - 参数：`pages`、`doc_name`、`folder_id`
   - 结果：`content: [{ page, text }]`、`total_pages`、`returned_pages`、`requested_pages`、`next_steps`
   - 含图页面的 `text` 中包含 markdown 图片引用，例如 `![img-45.jpeg](doc.pdf/img-45.jpeg)`。
5. `Viewed a figure`
   - 参数：`image_path`
   - 结果：`data`、`type: "image"`、`mimeType: "image/jpeg"`

关键结论：官方的图片工具读取的是索引阶段保存的嵌入图片/figure，不是按页码实时渲染整页 PDF。

## 3. 目标与非目标

### 3.1 目标

- 将模型可见工具统一为“资料库导航”语义，避免暴露底层检索实现。
- 保留相关文档发现能力，但以 `browse_documents` 的形式返回紧凑文件/文件夹列表。
- 让模型必须经过结构和源内容取证，不能只根据检索片段回答。
- 将嵌入图片作为一等证据保存和读取，支持 `get_document_image(image_path)`。
- 对含图页采用视觉优先策略：当问题涉及图片、图表、版式或图中内容时，必须查看具体图片。
- 限制大字段进入模型上下文、SSE 和前端会话存储。

### 3.2 非目标

- 不在本设计中重做文档管理页 UI。
- 不在本设计中重做设置页 UI。
- 不移除 BM25/rerank 检索能力；只调整它对模型的暴露方式。
- 不把所有图片页都强制改成只返回图片。页面文本仍可用于定位和引用，但视觉问题必须读取图片证据。

## 4. 工具族设计

### 4.1 `view_folder_structure`

用途：查看当前用户可访问的文件夹树，用于处理用户提到“某个文件夹、资料库、当前范围”的问题。

参数：

```json
{
  "folder_id": "root"
}
```

返回：

```json
{
  "success": true,
  "tree": {
    "id": "root",
    "name": "root",
    "path": "",
    "children": [],
    "file_count": 0,
    "children_count": 1
  },
  "depth": 1,
  "truncated": false,
  "total_folders": 1,
  "next_steps": {
    "summary": "1 folder(s), 1 level(s) deep",
    "options": [
      "Browse folders with documents using browse_documents(folder_id=...)"
    ]
  }
}
```

替代关系：替代或重命名当前 `list_folder_tree`。

### 4.2 `browse_documents`

用途：在文件夹或当前范围内浏览/搜索文档。它是模型可见的文档发现工具，内部可使用 BM25、rerank、folder scope 和文档 metadata。

参数：

```json
{
  "folder_id": "root",
  "query": "快消",
  "recursive": false,
  "sort": "relevance",
  "offset": ""
}
```

字段说明：

- `folder_id` 可省略，默认当前用户根目录。
- `query` 可省略；无 query 时按 `sort` 浏览文档。
- `recursive` 控制是否递归子文件夹。
- `sort` 支持 `relevance`、`created_at`、`name`、`updated_at`。
- `offset` 用于分页加载。

返回：

```json
{
  "success": true,
  "sort": "relevance",
  "folders": [],
  "documents": [
    {
      "doc_id": "internal-doc-id",
      "name": "2026年快消行业AI营销增长白皮书.pdf",
      "path": "test",
      "folder_id": "folder-id",
      "status": "completed",
      "created_at": "2026-06-22T14:14:02.548Z",
      "description": "本报告深度解析...",
      "page_count": 62
    }
  ],
  "has_more": false,
  "next_offset": "",
  "next_steps": {
    "summary": "Showing 0 folder(s) and 3 document(s)",
    "options": [
      "Use get_document_structure() before reading pages",
      "If results do not match the user's intent, retry with recursive=true or a refined query"
    ]
  }
}
```

禁止返回：

- 全文正文
- OCR 正文
- 大段 matched segment
- 原始 embedding/rerank 分数细节

最终实现不再向模型暴露 `find_related_documents`，也不保留其 `ToolExecutor.execute()` 入口。跨文档发现统一走 `browse_documents`，单文档内部定位统一走 `search_within_document`。

### 4.3 `get_document_structure`

用途：读取指定文档的结构树，用于判断应该读取哪些页或章节。

参数：

```json
{
  "doc_id": "optional-doc-id",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "folder_id": "folder-id",
  "part": 1
}
```

解析规则：

- 优先使用 `doc_id`。
- 若没有 `doc_id`，使用 `doc_name + folder_id` 解析唯一文档。
- 若同名文档不唯一，返回歧义错误并给出候选列表。
- `part` 用于长结构分页，默认 1。

返回：

```json
{
  "success": true,
  "doc_id": "internal-doc-id",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "part": 1,
  "has_more_parts": false,
  "structure": [
    {
      "title": "品牌/商品标签",
      "node_id": "0018",
      "start_index": 28,
      "end_index": 36,
      "summary": "本文介绍...",
      "nodes": []
    }
  ],
  "next_steps": {
    "summary": "Document structure retrieved successfully.",
    "options": [
      "Use get_page_content() to extract specific content from pages"
    ]
  }
}
```

### 4.4 `get_page_content`

用途：读取指定页范围的文本、表格文本和图片引用。它提供定位证据，不负责返回图片二进制。

参数：

```json
{
  "doc_id": "optional-doc-id",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "folder_id": "folder-id",
  "pages": "28-36"
}
```

页范围约束：

- 默认最多返回 10 页，超出则截断并提示继续调用。
- `pages` 支持 `"28"`、`"28-36"`、`[28, 29]` 三种输入，后端规范化为字符串范围。

返回：

```json
{
  "success": true,
  "doc_id": "internal-doc-id",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "content": [
    {
      "page": 28,
      "text": "用标签耦合把...",
      "images": [
        {
          "image_path": "2026年快消行业AI营销增长白皮书.pdf/img-45.jpeg",
          "alt": "img-45.jpeg",
          "mimeType": "image/jpeg"
        }
      ],
      "visual_evidence_required": true
    }
  ],
  "total_pages": 62,
  "requested_pages": "28-36",
  "returned_pages": "28-36",
  "next_steps": {
    "summary": "Successfully retrieved content for 9 pages.",
    "options": [
      "Use get_document_image() with image_path to inspect embedded images",
      "When citing, use single page numbers"
    ]
  }
}
```

视觉优先规则：

- 如果用户问“图里有什么、图片、图示、流程图、截图、视觉布局、表格截图”等，模型必须调用 `get_document_image(image_path)`。
- 若页面有 `images`，但问题只问普通文本事实，模型可以先用 `text` 回答；如果事实来自图片附近或 OCR 不确定，必须查看图片。
- `text` 应做长度上限控制。长页可返回截断字段，例如 `text_truncated: true` 和 `continuation_hint`。

### 4.5 `get_document_image`

用途：读取文档中已抽取并持久化的嵌入图片/figure。

参数：

```json
{
  "image_path": "2026年快消行业AI营销增长白皮书.pdf/img-45.jpeg"
}
```

返回：

```json
{
  "success": true,
  "data": "<base64>",
  "type": "image",
  "mimeType": "image/jpeg",
  "image_path": "2026年快消行业AI营销增长白皮书.pdf/img-45.jpeg",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "page": 28
}
```

安全要求：

- `image_path` 必须解析到当前用户可访问文档的索引资产目录。
- 禁止任意文件路径读取。
- 返回给模型的历史消息中应注入真实多模态 image payload，但前端和持久化历史不应保存完整 base64。

### 4.6 `get_page_image`

用途：整页图像 fallback，用于扫描件、没有抽取出 embedded image、用户明确要求“整页给我看”等场景。

参数：

```json
{
  "doc_id": "optional-doc-id",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "folder_id": "folder-id",
  "page": 28
}
```

说明：

- 该工具对应当前 `get_document_image(doc_id, page_num)` 的真实能力。
- 它应改名为 `get_page_image` 或 `render_page_image`，避免和官方式 `get_document_image(image_path)` 混淆。
- 默认不作为首选工具；只有 `get_page_content` 没有 `images`、embedded image 丢失、扫描件或用户需要整页版式时才调用。

## 5. 数据存储设计

### 5.1 Index Artifact

每个文档索引文件应继续保存结构树，同时新增或规范化以下信息：

```json
{
  "doc_id": "internal-doc-id",
  "doc_name": "2026年快消行业AI营销增长白皮书.pdf",
  "page_count": 62,
  "structure": [],
  "pages": [
    {
      "page": 28,
      "text": "用标签耦合把...",
      "text_source": "ocr_or_pdf_text",
      "images": [
        {
          "image_id": "img-45",
          "image_path": "2026年快消行业AI营销增长白皮书.pdf/img-45.jpeg",
          "mimeType": "image/jpeg",
          "page": 28,
          "bbox": null,
          "caption": null
        }
      ]
    }
  ],
  "assets": {
    "images": [
      {
        "image_id": "img-45",
        "image_path": "2026年快消行业AI营销增长白皮书.pdf/img-45.jpeg",
        "storage_path": "data/indexes/assets/<doc_id>/img-45.jpeg",
        "mimeType": "image/jpeg",
        "page": 28,
        "sha256": "..."
      }
    ]
  }
}
```

### 5.2 Asset Storage

建议将嵌入图片保存到受控目录：

```text
backend/data/index_assets/<doc_id>/images/img-45.jpeg
```

对外暴露的 `image_path` 使用稳定逻辑路径：

```text
<doc_name>/img-45.jpeg
```

后端通过 `doc_name + image filename` 或索引里的 `image_path` 映射到真实 `storage_path`。不要把真实磁盘路径暴露给模型。

### 5.3 Page Text 与 OCR 的关系

页面文本仍可由 PDF text layer、OCR markdown 或索引 text 组成，但它的角色是：

- 帮助定位相关页面。
- 帮助识别页面中有哪些图片引用。
- 帮助回答明确来自文本的事实。

它不应替代视觉证据。当问题涉及图片内容时，图片 base64 才是最终视觉证据。

## 6. Agent Prompt 与执行策略

### 6.1 默认流程

```text
view_folder_structure
-> browse_documents
-> get_document_structure
-> get_page_content
-> get_document_image 或 get_page_image
-> answer with citations
```

### 6.2 选择规则

- 用户提到文件夹、资料库范围：先 `view_folder_structure` 或 `browse_documents(folder_id=...)`。
- 用户没有指定文档：先 `browse_documents(query=...)`。
- 用户指定文档：直接 `get_document_structure`。
- factual answer：必须读取源页，不能只依赖 `browse_documents` 或 structure summary。
- visual answer：必须读取 `get_document_image(image_path)` 或 fallback `get_page_image`。
- 表格聚合：继续使用专门的 `aggregate_tables`，但需先确认文档范围。

### 6.3 UI Trace

前端展示应使用用户可读标题：

- `Viewed folder structure · 1 folder`
- `Browsed documents · 3 documents`
- `Read the document structure of "..."` 
- `Read pages 28-36 from "..."`
- `Viewed a figure from "..."`
- `Viewed page 28 from "..."`（整页 fallback）

展开后显示参数和紧凑结果。大字段策略：

- `data` / base64 默认折叠或隐藏，只显示 `mimeType`、大小和预览。
- `content[].text` 可显示截断预览。
- 前端会话存储不保存完整 base64。

## 7. 与当前实现的映射

| 当前能力 | 目标能力 | 处理方式 |
| --- | --- | --- |
| `list_folder_tree` | `view_folder_structure` | 旧工具移除，只保留新工具入口 |
| `list_folder_contents` | `browse_documents` | 旧工具移除，浏览和搜索合并到新工具 |
| `find_related_documents` | `browse_documents` / `search_within_document` | 旧工具移除；跨文档发现用 `browse_documents`，文内定位用 `search_within_document` |
| `get_document_structure(doc_id, compact)` | `get_document_structure(doc_id/doc_name, folder_id, part)` | 增加 doc_name 解析和 part 分页 |
| `get_page_content(doc_id, page_nums)` | `get_page_content(doc_id/doc_name, pages)` | 改返回 `content[]`，解析 images，限制文本 |
| `get_document_image(doc_id, page_num)` | `get_page_image(...)` | 改名为整页 fallback |
| 无 | `get_document_image(image_path)` | 新增 embedded figure 读取 |

## 8. 迁移策略

### 8.1 第一阶段：新工具替换旧入口

- 新增 `browse_documents`，内部复用现有 folder 和 search service。
- 新增 `view_folder_structure`，包装现有 folder tree。
- 移除 `find_related_documents`、`list_folder_tree`、`list_folder_contents`、`list_documents` 的模型可见工具定义和执行入口。
- `get_document_structure` 增加 `doc_name + folder_id` 解析。

### 8.2 第二阶段：图片资产

- 索引阶段保存 PDF embedded image 或 OCR markdown 引用对应图片。
- 为现有索引增加兼容解析：如果只有 `![img-x.jpeg](...)`，先根据索引文件目录寻找资产；找不到则提示 fallback `get_page_image`。
- 新增 `get_document_image(image_path)`。
- 将旧 `get_document_image(doc_id, page_num)` 改名为 `get_page_image`。

### 8.3 第三阶段：上下文与 UI 瘦身

- Agent history sanitizer 截断 `content[].text` 和任何大字段。
- SSE `tool_result` 给 UI 发送 compact result。
- 前端展开工具结果时显示摘要和按需展开，不保存 base64 到 localStorage。

## 9. 测试与验收

### 9.1 后端单元测试

- `browse_documents` 无 query 时按文件夹返回文档。
- `browse_documents(query, folder_id, recursive=false)` 不越过 scope。
- `browse_documents` 不返回正文字段。
- `get_document_structure(doc_name, folder_id)` 能解析唯一文档；同名冲突返回候选。
- `get_page_content(pages="28-36")` 返回规范化页范围和 `content[]`。
- 含 markdown 图片引用的页面返回 `images[]` 和 `visual_evidence_required`。
- `get_document_image(image_path)` 只能读取当前用户有权限的文档资产。
- `get_page_image` 仍可渲染整页 fallback。

### 9.2 Agent 行为测试

- 多文档问题先 `browse_documents`，再 `get_document_structure`，再读页。
- 图片问题必须调用 `get_document_image(image_path)`。
- 找不到 embedded image 时才调用 `get_page_image`。
- 回答不能只引用 `browse_documents` 的 description。

### 9.3 性能与 payload 测试

- `get_page_content` 单次响应大小有上限。
- `tool_result` SSE 不包含完整 base64。
- `messages` 历史不持久化完整图片 base64。
- 长文档结构通过 `part` 分页，不一次性返回无限结构。

## 10. 开放问题

1. 图片抽取应优先使用 PDF 原始 embedded images，还是复用 OCR/markdown 生成的图片资产？
2. `image_path` 是否必须稳定使用 `<doc_name>/img-n.jpeg`，还是允许 `<doc_id>/images/img-n.jpeg` 这种更稳定但不如官方可读的形式？
3. `get_page_content` 文本上限应按字符、token 估算，还是按页数和字段双重限制？
4. 旧会话中的 `get_document_image(doc_id, page_num)` 工具结果是否需要兼容展示？
5. 是否需要为非 PDF 格式也定义 `image_path`，例如 DOCX/PPTX 中的嵌入图片？

## 11. 推荐决策

推荐采用官方兼容但更严格的视觉优先策略：

- 模型可见工具对齐官方资料库导航语义。
- `browse_documents` 保留检索能力，但返回文档级紧凑结果。
- `get_page_content` 返回文本和图片引用，不返回图片二进制。
- `get_document_image` 使用 `image_path` 获取具体嵌入 figure。
- 当前整页截图能力改名为 `get_page_image`，作为 fallback。
- Prompt 要求视觉问题必须查看图片证据，不能仅依赖 OCR 文本。

这套设计能同时解决三个问题：工具 trace 更接近官方、模型不再直接消费底层检索 JSON、视觉证据和 OCR 文本的职责分清。
