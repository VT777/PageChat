# KnowClaw v0.2.5

基于 PageIndex 官方交互流程的智能文档问答系统。支持 PDF 文档上传、自动索引、多轮对话问答，具备视觉理解能力（可读取图表、表格内容）。

## 功能特性

- **📄 文档管理**：支持 PDF 文档上传、自动解析、结构化索引
- **💬 智能问答**：基于文档内容的多轮对话，支持追问和上下文理解
- **🔍 页面定位**：自动识别相关内容所在页面，支持视觉分析（图表、表格）
- **⚡ 会话缓存**：同一对话中已读取的页面和目录结构会被缓存，避免重复读取
- **📱 现代化界面**：基于 Vue 3 + Tailwind CSS 的响应式前端

## 技术栈

### 后端
- Python 3.11+
- FastAPI + Uvicorn
- SQLite (文档元数据存储)
- OpenAI API (通义千问模型)
- PyMuPDF (PDF 处理)

### 前端
- Vue 3 + TypeScript
- Vite (构建工具)
- Tailwind CSS (样式)
- Lucide Vue (图标)

## 快速开始

### 环境要求
- Python 3.11 或更高版本
- Node.js 18 或更高版本
- 通义千问 API Key

### 安装步骤

1. **克隆仓库**
```bash
git clone https://github.com/yourusername/knowclaw.git
cd knowclaw
```

2. **配置后端环境**
```bash
cd backend

# 创建虚拟环境
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

3. **配置环境变量**
```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入你的通义千问 API Key
# DASHSCOPE_API_KEY=your_api_key_here
```

4. **启动后端**
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

5. **配置前端**
```bash
cd ../frontend
npm install
```

6. **启动前端**
```bash
npm run dev
```

7. **访问应用**
打开浏览器访问 http://localhost:5173

## 使用说明

### 上传文档
1. 点击左侧"文档管理"
2. 拖拽或选择 PDF 文件上传
3. 等待文档索引完成（状态变为"已完成"）

### 开始对话
1. 点击左侧"对话"或直接在输入框输入问题
2. 系统会自动：
   - 查找相关文档（多文档场景）
   - 获取文档目录结构
   - 读取相关页面内容
   - 生成带引用标记的答案

### 引用格式
回答中的引用格式为 `[[文档名 p.页码]]`，例如：
> B站日均活跃用户1.0亿 [[哔哩哔哩2024公司简介.pdf p.3]]

### 多轮对话
- 同一对话中，已读取的页面会自动缓存
- 再问相关内容时不会重复读取
- 支持追问和上下文理解

## 项目结构

```
knowclaw/
├── backend/                 # 后端服务
│   ├── app/                # 应用代码
│   │   ├── api/           # API 路由
│   │   ├── core/          # 核心配置和 LLM 客户端
│   │   ├── models/        # 数据模型
│   │   ├── prompts/       # 提示词管理
│   │   └── services/      # 业务逻辑
│   ├── data/              # 数据存储（不上传到 git）
│   ├── logs/              # 日志文件（不上传到 git）
│   └── tests/             # 测试用例
├── frontend/              # 前端应用
│   ├── src/
│   │   ├── api/          # API 客户端
│   │   ├── components/   # 组件
│   │   ├── stores/       # Pinia 状态管理
│   │   ├── types/        # TypeScript 类型
│   │   └── views/        # 页面视图
│   └── public/
└── README.md
```

## 核心工具

系统使用以下工具与文档交互：

1. **get_document_structure**：获取文档目录结构
2. **get_page_content**：获取指定页面内容（支持视觉分析）
3. **find_related_documents**：查找相关文档（多文档场景）
4. **list_documents**：列出所有已上传文档

## 配置说明

### 后端配置 (.env)

```env
# API 配置
DASHSCOPE_API_KEY=your_api_key_here
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 模型配置
LLM_FLASH_MODEL=qwen-turbo
LLM_PLUS_MODEL=qwen3.5-plus

# 应用配置
APP_NAME=KnowClaw
APP_VERSION=0.2.5
DEBUG=true
```

### 前端配置

前端配置位于 `frontend/src/api/index.ts`：
```typescript
const API_BASE_URL = 'http://localhost:8000'
```

## 更新日志

### v0.2.5 (当前版本)
**性能优化与架构改进**
- [x] 提示词优化：Token 消耗减少 25%，响应时间提升 20%
- [x] 并发优化：摘要生成并发从 2 提升到 5，处理速度提升 2.5 倍
- [x] 模型降级：PageIndex 索引从 plus 改为 flash，节省 40-50% 成本
- [x] 节点摘要：get_page_content 工具返回新增 node_summary 字段
- [x] 限流保护：添加指数退避重试机制
- [x] 新增 8 个专业提示词（查询扩展、搜索路由、答案验证等）

### v0.1
- [x] 基础文档上传和索引
- [x] 多轮对话问答
- [x] 页面级视觉分析
- [x] 会话级缓存
- [x] 引用标记

### 未来版本
- [ ] 支持更多文档格式（Word、PPT 等）
- [ ] 向量检索增强
- [ ] 用户认证系统
- [ ] 文档分享功能

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建你的功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 许可证

MIT License

## 致谢

- 基于 PageIndex 官方交互流程设计
- 使用通义千问大语言模型
- 感谢开源社区的支持
