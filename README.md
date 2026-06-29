# PageChat

PageChat 是一个面向复杂文档理解、结构化索引和知识问答的 AI 工作台。它基于 PageIndex 的文档结构化能力，结合 OCR/VLM 解析、模型供应商自定义、网络搜索、可视化文档管理、树状 TOC、引用预览和 Agent 工具调用流程，让用户能够围绕 PDF、扫描件、表格、演示文稿、Word 文档等资料进行可信问答。

PageChat 不是简单的“上传文档后切块检索”。它更关注长文档、视觉型文档和多文件夹知识库场景：先理解文档结构，再按目录、页面、图片、表格和来源锚点组织证据，最后让模型基于可验证材料回答。

> [!NOTE]
> PageChat 仍处于快速开发阶段。当前版本适合本地评估、产品预览和二次开发，还不是面向生产环境的完整部署包。

## 核心能力

- **PageIndex 文档理解**：构建树状目录、页码锚点、节点摘要和来源元数据，支持按文档结构定位证据。
- **OCR / VLM 解析**：支持扫描件、图片型 PDF、图表页等视觉内容，可在设置中配置 OCR/VLM 模型和并发参数。
- **模型供应商自定义**：支持 OpenAI-compatible、DashScope-compatible 等模型供应商，并可为问答、解析、OCR 等任务分别指定模型。
- **多格式适配**：支持 PDF、Markdown、TXT、CSV、TSV、XLSX、DOCX、PPTX 等文件格式。
- **Agent 文档问答**：模型可以通过工具浏览文件夹、读取文档结构、获取页面内容、查看图片证据、文档内搜索、聚合表格和调用网络搜索。
- **可信引用**：回答中的引用可绑定到具体文档、页码、工作表、行范围、幻灯片、段落或网页来源。
- **可视化界面**：包含 Chat、文档管理、文件夹导航、树状 TOC、PDF 预览、来源预览抽屉和设置页。
- **会话持久化**：保存聊天历史、运行事件、选中文档、引用和上下文状态，页面切换后仍能恢复。

## 相比 PageIndex 官方能力的增强

PageIndex 提供了长文档结构化索引的基础能力。PageChat 在此基础上补齐了一个完整产品所需的应用层：

- 多用户文档库：支持文件夹、上传、重新解析、批量操作、下载和预览。
- 产品化 TOC 体验：将 PageIndex 结构转化为前端可交互的树状目录和来源锚点。
- 多模型配置：支持模型供应商、API Key、可用模型、模型能力标签和任务路由设置。
- Agent 工具契约：让模型先浏览文件夹和文档结构，再按需读取证据，避免一次性把整个文档库塞进提示词。
- 引用和预览联动：回答中的证据可以跳转到对应来源，方便用户核查。
- 多格式文档索引：让非 PDF 文件也能进入统一的结构化问答流程。
- 可选网络搜索：在用户开启并需要外部信息时，Agent 可以调用搜索能力并产生网页来源。

## 项目结构

```text
PageChat
+-- backend/                 FastAPI 后端服务
|   +-- app/api/             Auth、Chat、Documents、Folders、Tools、Settings API
|   +-- app/agent/           Agent runtime、事件协议、引用绑定、模型协议适配
|   +-- app/models/          SQLite 表结构、迁移和 Pydantic Schema
|   +-- app/prompts/         Agent 和 PageIndex 提示词
|   +-- app/services/        文档、索引、OCR、模型、搜索、预览等业务服务
+-- frontend/                Vue 3 + TypeScript 前端
|   +-- src/components/      Chat、文档、文件夹、预览、设置等组件
|   +-- src/stores/          Chat、Document、Folder、User 等 Pinia 状态
|   +-- src/views/           聊天、文档管理、登录、设置等页面
|   +-- src/utils/           引用、范围、导出、预览等工具函数
+-- scripts/                 本地开发和验证脚本
```

后端默认使用 SQLite 保存用户、文档元数据、会话历史、运行事件和引用信息。上传文件、索引结果、预览文件和缓存数据位于 `backend/data/`。

## 工作流

1. 用户上传文档到文档库，也可以放入不同文件夹。
2. PageChat 根据文件类型执行解析，构建 PageIndex 风格的结构化索引。
3. 前端展示解析状态、处理步骤、文档预览和树状 TOC。
4. 用户在 Chat 中选择文件或文件夹作为当前问答范围。
5. Agent 根据问题自主调用工具：浏览文件夹、读取文档结构、获取页面或图片证据、搜索文档或聚合表格。
6. 模型基于证据生成回答，并在关键结论后附上引用。
7. 用户点击引用后，可以在右侧预览对应文档、页面或来源。

## 支持的文件格式

| 格式 | 扩展名 | 说明 |
| --- | --- | --- |
| PDF | `.pdf` | 支持页码锚点、PDF 预览、页面图片和视觉内容处理 |
| Markdown | `.md`, `.markdown` | 基于标题结构和行号锚点建立目录 |
| 文本 | `.txt` | 基于行范围构建轻量结构 |
| 表格 | `.csv`, `.tsv`, `.xlsx` | 支持工作表、行范围锚点和表格聚合 |
| Word | `.docx` | 支持标题、段落和目录结构抽取 |
| PowerPoint | `.pptx` | 支持幻灯片级别锚点 |

## Agent 工具链

PageChat 不会把完整文档库一次性发给模型，而是提供一组紧凑工具，让模型按需读取证据：

| 工具 | 作用 |
| --- | --- |
| `view_folder_structure` | 查看当前用户的文件夹树。 |
| `browse_documents` | 在指定文件夹或选中范围内浏览、搜索文档。 |
| `get_document_structure` | 读取文档目录、章节、页码范围和摘要。 |
| `get_page_content` | 读取指定页面或结构化内容单元。 |
| `get_page_image` | 在需要视觉证据时渲染完整 PDF 页面图片。 |
| `get_document_image` | 获取索引中记录的图片、图表或嵌入图像。 |
| `search_within_document` | 在指定文档内进行关键词定位。 |
| `aggregate_tables` | 对 CSV、TSV、XLSX 等表格文档执行简单聚合。 |
| `web_search` | 在已配置并开启时进行网络搜索。 |

## 技术栈

**后端**

- Python 3.11+
- FastAPI + Uvicorn
- SQLite + aiosqlite
- LiteLLM / OpenAI-compatible 模型调用
- PyMuPDF PDF 处理
- OCR 服务和多格式解析服务

**前端**

- Vue 3 + TypeScript
- Vite
- Pinia
- Tailwind CSS
- PDF.js
- Vitest + Playwright

## 环境要求

- Python 3.11 或更高版本
- Node.js 18 或更高版本
- 至少一个可用的大模型供应商 API Key
- 如果需要解析扫描件或图片型文档，需要配置 OCR/VLM 模型

## 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/VT777/PageChat.git
cd PageChat
```

### 2. 配置后端

```bash
cd backend
python -m venv venv
```

激活虚拟环境：

```bash
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

创建 `backend/.env`：

```env
APP_ENV=development
JWT_SECRET=replace-with-a-local-secret

# 默认模型路由。也可以进入系统后在设置界面配置供应商。
LLM_API_KEY=your-model-api-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.6-plus

# 可选：用于扫描件或图片型文档的 OCR/VLM 路由。
OCR_API_KEY=your-ocr-api-key
OCR_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OCR_MODEL=qwen3.5-ocr

# 可选：网络搜索供应商。
ANYSEARCH_API_KEY=your-anysearch-key
```

启动后端：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. 启动前端

```bash
cd ../frontend
npm install
npm run dev
```

访问地址：

- 前端：<http://localhost:5173>
- 后端健康检查：<http://localhost:8000/health>
- API 文档：<http://localhost:8000/docs>

## 配置说明

登录后，大部分产品配置都可以在设置界面完成：

- 模型供应商和 API Key
- 可用模型列表和模型能力
- 问答模型
- 解析模型
- OCR/VLM 模型
- 网络搜索行为
- 界面语言

环境变量仍用于本地启动、密钥、默认模型路由和服务级配置。生产环境必须设置可靠的 `JWT_SECRET` 或 `SECRET_KEY`，后端不会在生产模式下使用开发默认密钥。

## 测试

后端测试：

```bash
cd backend
python -m pytest
```

前端测试：

```bash
cd frontend
npm test
npm run build
```

端到端测试：

```bash
cd frontend
npm run test:e2e
```

## 开发说明

- 后端运行数据会写入 `backend/data/`，不要提交该目录。
- 前端开发服务器默认请求 `http://localhost:8000`。
- 代码中仍可能存在少量历史内部名称或旧注释，产品对外统一命名为 PageChat。
- OCR 是扫描件和图片型文档解析的必要配置；如果未配置 OCR/VLM，相关文档应提示用户配置，而不是静默使用开发默认值。
- 网络搜索是可选能力，只应在已配置且用户允许的情况下参与回答。

## 后续方向

- 完善不同模型供应商的能力识别。
- 稳定常见不同格式的解析质量，包括 PDF、Word、PowerPoint、Excel、Markdown、纯文本和扫描件。
- 支持自定义 Skill，让 Agent 能针对更多文件类型执行 TOC 解析和结构化理解。
- 改进 OCR/VLM 模型选择和解析失败提示。
- 扩展网络搜索路由和网页引用体验。
- 补充 Docker、CI 和生产部署示例。
- 持续清理历史内部名称和旧编码注释。
