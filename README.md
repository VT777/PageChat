# PageChat

PageChat 是一个面向复杂文档理解、结构化索引和可信问答的 AI 文档工作台。它以 PageIndex 的文档结构化能力为基础，补齐了产品化文档库、可视化 TOC、OCR/VLM、多模型供应商、网络搜索、引用预览和 LLM-driven Agent 工具循环，让用户可以围绕 PDF、扫描件、表格、演示文稿、Word 文档等资料进行可核查的问答。

PageChat 不只是“上传文档后切块检索”。它会先构建文档结构，再让 Agent 按文件夹、目录、页面、图片、表格和网页来源逐步读取证据，最后在回答中把引用贴近结论展示，便于用户回到原文核查。

## 核心能力

- **一键部署**：内置 Docker Compose、前后端镜像构建和 Nginx 入口，启动后即可进入界面配置模型供应商。
- **PageIndex 风格 TOC**：构建树状目录、页码锚点、节点摘要和来源元数据，前端可视化展示文档结构。
- **OCR / VLM 解析**：支持扫描件、图片型 PDF、图表页等视觉内容；OCR 模型由用户在设置中配置。
- **多格式适配**：支持 PDF、Markdown、TXT、CSV、TSV、XLSX、DOCX、PPTX 等常见资料格式。
- **模型自定义**：支持 OpenAI-compatible、DashScope-compatible 等供应商，可按问答、解析、OCR/VLM 等任务分别路由模型。
- **LLM-driven Agent Loop**：默认使用扁平工具循环，由模型根据上下文自主决定下一步调用哪个工具或直接回答。
- **网络搜索**：可集成 AnySearch，在用户开启时为需要外部信息的问题补充网页证据。
- **可信引用和预览**：回答引用可绑定到具体文档、页码、表格行、幻灯片、段落、图片或网页来源。
- **可视化界面**：包含 Chat、文档管理、文件夹导航、树状 TOC、PDF 预览、引用预览和模型设置。
- **会话持久化**：保存聊天历史、运行事件、选中文档、证据和引用，页面切换后可恢复上下文。

## 与 PageIndex 官方能力的区别

PageIndex 主要提供长文档结构化索引能力。PageChat 在此基础上增加了面向最终用户和二次开发者的完整应用层：

| 方向 | PageIndex 官方基础能力 | PageChat 增强 |
| --- | --- | --- |
| 文档结构 | 生成结构化索引和页面级信息 | 转成可交互树状 TOC、来源锚点、预览入口 |
| 文档库 | 偏向单文档或索引能力 | 多用户、多文件夹、上传、批量操作、重新解析、下载和预览 |
| 问答流程 | 基于文档索引进行问答 | Agent 自主浏览文件夹、读取目录、定位页面、查看图片和聚合表格 |
| 引用体验 | 返回来源信息 | 引用紧贴结论，可点击打开右侧预览并跳转来源 |
| 模型配置 | 依赖运行环境配置 | UI 配置供应商、API Key、模型能力、问答/解析/OCR 路由 |
| 外部信息 | 以文档为主 | 可选 AnySearch 网络搜索，并把网页作为引用来源 |
| 产品形态 | 文档理解能力组件 | 可部署的前后端应用和可视化文档工作台 |

## TOC 构建流程

```mermaid
flowchart TD
    A["上传文件"] --> B{"识别文件类型"}
    B -->|PDF / 扫描件| C["提取页面、文本、图片和版面信息"]
    B -->|DOCX / PPTX / Markdown / TXT| D["提取标题、段落、幻灯片或行范围"]
    B -->|CSV / TSV / XLSX| E["提取工作表、列、行范围和表格摘要"]
    C --> F{"是否需要 OCR/VLM"}
    F -->|是| G["调用用户配置的 OCR/VLM 模型"]
    F -->|否| H["使用可读文本和页面结构"]
    G --> I["生成页面级 OCR / 视觉证据"]
    H --> I
    D --> J["生成章节节点和来源锚点"]
    E --> K["生成表格节点和行范围锚点"]
    I --> L["构建 PageIndex 风格结构化索引"]
    J --> L
    K --> L
    L --> M["保存文档元数据、TOC、页面、图片和引用锚点"]
    M --> N["前端展示树状 TOC、解析状态和预览"]
    M --> O["Agent 工具按需读取结构和证据"]
```

## 重构后的 Agent 架构

PageChat 默认使用 `flat_tool_loop`。它不是固定阶段机，也不是后端硬编码 “先 plan 再查再答” 的工作流，而是更接近 Claude Code / Codex 风格的扁平 LLM-driven tool loop：模型看到系统提示、用户问题、当前文档范围、可用工具和历史 observation，然后自己决定调用工具或输出答案。

```mermaid
flowchart LR
    U["用户问题 + 选中文档/文件夹 + 会话上下文"] --> R["Agent Runtime"]
    R --> M["模型生成 assistant/tool_call 流"]
    M -->|普通文本| S["流式输出到 Chat / Processing"]
    M -->|tool_call| T["Tool Runner"]
    T --> P["边界校验与参数修复"]
    P --> X["执行工具"]
    X --> O["Observation + compact evidence + citations"]
    O --> R
    M -->|最终回答| A["答案 + 内联引用"]
```

这次重构的关键点：

- **主动权交给模型**：后端不预设固定检索阶段，模型可根据 observation 迭代决策。
- **边界由运行时兜底**：运行时负责用户隔离、文档范围、工具参数修复、网络搜索开关和引用绑定。
- **证据紧凑复用**：工具结果会被压缩成可复用 evidence，减少同一会话中重复读取。
- **过程可视化**：工具调用、processing 文本、引用和最终回答通过 SSE 流式返回前端。

## Agent 工具设计

PageChat 不会把完整文档库一次性塞进模型上下文，而是提供一组边界清晰、输出紧凑的工具。工具结果会尽量返回模型需要的信息：摘要、命中位置、引用锚点、下一步建议，而不是大段无关原文。

| 工具 | 主要用途 | 典型返回 |
| --- | --- | --- |
| `view_folder_structure` | 查看当前用户可访问的文件夹树 | 文件夹层级、文件数量、可继续浏览的位置 |
| `browse_documents` | 在当前范围内浏览或搜索文档 | 文档/文件夹列表、状态、摘要、候选 doc_id |
| `get_document_structure` | 读取完整深层 TOC 和文档组织 | 章节树、页码范围、节点摘要、结构化锚点 |
| `search_within_document` | 文档内关键词定位 | 命中页、片段、匹配原因、建议读取页面 |
| `get_page_content` | 读取页面文本或结构化内容 | 页面文本、OCR 片段、表格/段落引用 |
| `get_page_image` | 获取整页视觉证据 | 页面图片引用、页码、适合视觉模型查看的证据 |
| `get_document_image` | 获取索引中记录的图表或嵌入图片 | 图片引用、来源页、说明和引用锚点 |
| `aggregate_tables` | 对表格文档做轻量聚合 | 工作表、列、统计结果和行范围引用 |
| `web_search` | 调用 AnySearch 获取外部信息 | 网页标题、摘要、URL、网页引用来源 |

工具链路遵循几个原则：

- **先结构、后细节**：概览类问题优先读取 TOC；具体事实再读取页面、图片或表格。
- **引用绑定到来源**：引用不是按 chunk 编号展示，而是尽量绑定到文档、页码、图片、表格范围或网页 URL。
- **OCR 文本作为 fallback**：当问答模型没有 vision 能力时，图片页可使用 OCR 文本；需要视觉判断时再读取页面图片。
- **用户范围优先**：用户指定文件或文件夹后，Agent 应在该范围内行动，不应随意读取其他用户或其他范围内容。
- **网络搜索显式可控**：只有用户开启或问题明确需要外部实时信息时，才暴露并使用 `web_search`。

## 项目结构

```text
PageChat
+-- backend/                 FastAPI 后端服务
|   +-- app/api/             Auth、Chat、Documents、Folders、Settings API
|   +-- app/agent/           Agent runtime、工具循环、事件协议、边界策略
|   +-- app/models/          SQLite 表结构、迁移和 Pydantic Schema
|   +-- app/prompts/         Agent 和 PageIndex 提示词
|   +-- app/services/        文档、索引、OCR、模型、搜索、预览等业务服务
+-- frontend/                Vue 3 + TypeScript 前端
|   +-- src/components/      Chat、文档、文件夹、预览、设置等组件
|   +-- src/stores/          Chat、Document、Folder、User 等 Pinia 状态
|   +-- src/views/           聊天、文档管理、登录、设置等页面
|   +-- src/utils/           引用、范围、导出、PDF 预览等工具函数
+-- deploy/nginx/            Docker 前端入口配置
+-- scripts/                 本地开发和部署验证脚本
+-- docker-compose.yml       一键拉起前后端和持久化数据卷
```

后端默认使用 SQLite 保存用户、文档元数据、会话历史、运行事件、证据和引用信息。Docker 部署时，运行数据保存在 `pagechat-data` 和 `pagechat-logs` volume 中。

## 一键部署

### 1. 克隆项目

```bash
git clone https://github.com/VT777/PageChat.git
cd PageChat
```

### 2. 复制配置

```bash
cp .env.example .env
```

> [!TIP]
> PageChat 不要求启动前必须配置 `LLM_API_KEY`。你可以先拉起服务，再进入设置界面添加模型供应商、API Key、问答模型和 OCR/VLM 模型。

生产或公网部署前，请至少设置：

```env
APP_ENV=production
JWT_SECRET=replace-with-a-long-random-secret
MODEL_SETTINGS_SECRET=replace-with-another-long-random-secret
PAGECHAT_HTTP_PORT=8080
```

### 3. 启动

```bash
docker compose up -d --build
```

Windows 用户也可以直接运行：

```bat
start-pagechat-docker.bat
```

访问地址：

- 前端入口：<http://localhost:8080>
- 后端健康检查：<http://localhost:8000/health>
- API 文档：<http://localhost:8000/docs>

### 4. 查看日志和停止

```bash
docker compose logs -f
docker compose down
```

Windows 辅助脚本：

```bat
logs-pagechat-docker.bat
stop-pagechat-docker.bat
```

## 本地开发

后端：

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

本地开发访问：

- 前端：<http://localhost:5173>
- 后端：<http://localhost:8000>

## 配置说明

登录后，大部分产品配置都可以在设置界面完成：

- 模型供应商和 API Key
- 可用模型列表、模型能力和禁用状态
- 问答模型、解析模型、OCR/VLM 模型
- OCR 并发和解析设置
- AnySearch 网络搜索
- 界面语言

环境变量主要用于服务启动、密钥、端口和可选 fallback。默认产品路径是：先启动服务，再在 UI 中配置模型。

## 支持的文件格式

| 格式 | 扩展名 | 说明 |
| --- | --- | --- |
| PDF | `.pdf` | 页码锚点、PDF 预览、页面图片、OCR/VLM |
| Markdown | `.md`, `.markdown` | 标题结构、行号锚点 |
| 文本 | `.txt` | 行范围和轻量目录 |
| 表格 | `.csv`, `.tsv`, `.xlsx` | 工作表、列、行范围和表格聚合 |
| Word | `.docx` | 标题、段落和目录结构 |
| PowerPoint | `.pptx` | 幻灯片级锚点 |

## 测试

后端测试：

```bash
cd backend
python -m pytest
```

前端测试和构建：

```bash
cd frontend
npm test
npm run build
```

Docker 部署验证：

```bash
python scripts/verify_docker_deploy.py
```

## 后续方向

- 稳定 PDF、Word、PowerPoint、Excel、Markdown、纯文本、扫描件等常见格式的解析质量。
- 支持自定义 Skill，让 Agent 能针对更多文件类型执行 TOC 解析和结构化理解。
- 继续完善模型供应商能力识别、OCR/VLM 路由和引用体验。
- 扩展 AnySearch 的搜索、网页读取和外部来源引用能力。
