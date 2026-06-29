# PageChat

PageChat 是一个面向复杂文档理解与知识问答的 AI 工作台。它以 PageIndex 的文档结构化能力为基础，进一步补齐了产品化使用所需的文档管理、可视化预览、模型供应商配置、OCR/VLM 路由、多格式适配、网络搜索、会话持久化和可追溯引用能力。

项目目标不是做一个简单的 PDF Chat，而是让 AI 能够围绕真实文档库进行可解释、可定位、可复用的检索与问答。

> 当前仓库处于 alpha / preview 阶段，核心能力已经成型，但接口、数据库结构和部分产品细节仍可能调整。

## 核心能力

### 文档管理与可视化

- 支持文档上传、文件夹管理、批量选择、重新解析、删除、移动和下载等基础文档库操作。
- 支持按当前目录浏览文件，不递归混杂展示子目录内容。
- 支持文档预览、引用页预览和右侧证据面板。
- 支持树状 TOC 可视化，便于查看文档章节结构、定位页面和理解文档层级。

### PageIndex 增强

PageChat 基于 PageIndex 的文档索引与目录构建思路，做了面向产品场景的增强：

- 将目录构建、页面定位、OCR 文本、结构化节点和引用证据接入完整问答链路。
- 增强多格式文档适配，不局限于单一 PDF 工作流。
- 将 PageIndex 的结构化结果产品化展示为文档 TOC、页面预览和可点击引用。
- 为 Agent 工具调用提供更紧凑的文档结构、页面内容、图片页和搜索结果契约。
- 支持解析过程中的 OCR/VLM 配置与并发控制，避免把开发环境默认模型当成产品默认行为。

### OCR / VLM

- 支持 OCR 设置与 OCR/VLM 模型路由。
- 对图片型文档，如果未配置 OCR/VLM，会给出明确配置提示。
- 对视觉页可根据问答模型能力选择返回图片证据或 OCR 文本证据。
- 支持 OCR 并发、视觉提示词和解析策略配置。

### 多格式适配

PageChat 的文档处理管线面向多格式扩展，支持将不同来源的文档统一进入解析、索引、预览和引用链路。当前仓库包含 PDF、表格、Word、演示文稿、文本/Markdown 等适配基础。

### 模型自定义

- 支持模型供应商管理。
- 支持 OpenAI-compatible、DashScope-compatible 等供应商接入。
- 支持 API Key 配置、模型列表拉取和模型能力展示。
- 支持为问答、OCR、解析等任务选择不同模型。
- 支持按模型能力区分 LLM、Vision、OCR、Tool Calling、上下文长度等信息。

### Agent 问答

- 默认使用扁平的 LLM-driven tool loop，而不是固定阶段机。
- 模型可以基于当前上下文自主决定是否浏览文档、读取目录、检索页面、获取图片页或调用网络搜索。
- 支持会话级文档/文件夹范围，用户可以指定当前问题只针对某些文件或目录。
- 支持工具执行过程、Processing details、流式回答和可追溯证据。
- 支持撤回、重新生成、复制、导出和删除会话等交互。

### 引用与证据

- 回答中的引用会绑定到具体文档、页面或网页来源。
- 文档引用可打开右侧预览面板并定位到对应页面。
- 网页搜索结果作为链接来源处理，避免把网页强行塞进文档预览逻辑。
- 会话证据可复用，减少重复读取同一页或同一搜索结果。

### 网络搜索

- 支持 AnySearch API 集成。
- Web Search 可以作为 Agent 工具使用，用于回答需要外部实时信息的问题。
- 搜索结果进入统一证据链路，支持作为回答引用来源。

## 技术架构

```text
PageChat
├─ frontend/              Vue 3 + TypeScript + Pinia + Vite
│  ├─ chat UI             对话、工具过程、引用、文件选择
│  ├─ document UI         文档库、目录、预览、批量操作
│  └─ settings UI         模型供应商、OCR、解析、问答设置
│
└─ backend/               FastAPI + SQLite
   ├─ agent               LLM-driven tool loop 与工具契约
   ├─ pageindex           文档结构化、TOC、页面映射
   ├─ services            文档、模型、OCR、搜索、会话与引用服务
   └─ api                 Auth、Chat、Documents、Settings、Folders
```

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- npm
- 至少一个可用的大模型 API Key

### 克隆项目

```bash
git clone https://github.com/VT777/PageChat.git
cd PageChat
```

### 启动后端

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

创建配置文件：

```bash
# Windows PowerShell
Copy-Item ..\.env.example .env

# macOS/Linux
cp ../.env.example .env
```

至少配置：

```env
JWT_SECRET=change-this-to-a-long-random-secret
MODEL_SETTINGS_SECRET=change-this-to-another-long-random-secret
LLM_API_KEY=your-provider-api-key
```

启动后端：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

## 配置说明

PageChat 后端读取 `backend/.env`。

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `APP_ENV` | 否 | 本地默认 `development`，生产环境使用 `production`。 |
| `JWT_SECRET` | 生产必填 | 用户登录 token 签名密钥。 |
| `MODEL_SETTINGS_SECRET` | 是 | 加密保存模型供应商 API Key 的密钥。 |
| `LLM_API_KEY` | 环境 fallback 时需要 | 默认 OpenAI-compatible 模型路由 API Key。产品使用建议在设置页配置供应商。 |
| `LLM_BASE_URL` | 否 | OpenAI-compatible Base URL。 |
| `LLM_MODEL` | 否 | 默认 fallback 模型。 |
| `ALLOW_ENV_MODEL_FALLBACK` | 否 | 是否允许使用环境变量模型作为 fallback。默认关闭。 |
| `OCR_API_KEY` | 否 | OCR 环境 fallback API Key。建议在设置页配置 OCR。 |
| `OCR_BASE_URL` | 否 | OCR OpenAI-compatible Base URL。 |
| `OCR_MODEL` | 否 | OCR 模型名称。 |
| `ANYSEARCH_API_KEY` | 否 | AnySearch 网络搜索 API Key。 |
| `AGENT_RUNTIME_MODE` | 否 | 默认 `flat_tool_loop`。 |

首次启动后，建议在设置页完成：

1. 添加模型供应商与 API Key。
2. 拉取或确认可用模型列表。
3. 为问答、OCR、解析任务选择模型。
4. 如需网络搜索，配置 AnySearch。

## 开发命令

后端测试：

```bash
cd backend
python -m pytest
```

前端测试：

```bash
cd frontend
npm test
```

前端构建：

```bash
cd frontend
npm run build
```

## 数据与安全

运行时数据会写入 `backend/data/`，该目录不会被 Git 跟踪。公开或部署前请勿提交：

- `.env`
- SQLite 数据库
- 上传文档
- 解析产物
- 预览图片
- 日志
- 模型供应商 API Key

## 项目状态

PageChat 目前适合作为预览版体验、二次开发和架构参考。后续重点包括：

- 更完整的安装和部署流程。
- 更稳定的多格式解析质量评估。
- 更完善的模型能力识别与供应商适配。
- 更系统的端到端测试和 CI。

## License

PageChat is released under the MIT License. See [LICENSE](LICENSE).
