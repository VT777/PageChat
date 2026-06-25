# PageChat 集成开发指导

本文档用于指导 PageChat 接下来三条开发线的并行推进与最终集成：

1. agent tool 重构
2. 前端真实开发
3. `codex/unified-toc-state-machine` 分支下的 TOC 构建重构

目标是让三条线最后合成一个可运行、可测试、冲突可控的完整项目。

## 当前工作区

当前已知 worktree 布局：

| 用途 | 分支 | 路径 |
| --- | --- | --- |
| TOC 重构 | `codex/unified-toc-state-machine` | `D:\projects\page_chat` |
| agent tool / 当前会话 | `agent工具开发：文档内搜索` | `C:\Users\TT_WT\.codex\worktrees\fc17\page_chat` |

当前会话中还存在前端 demo 与设计文档草稿：

| 文件/目录 | 说明 |
| --- | --- |
| `DESIGN_SYSTEM.md` | PageChat UI 设计系统草稿 |
| `demos/pagechat-design-demo/` | 独立前端设计 demo |
| `docs/superpowers/specs/2026-06-22-agent-library-navigation-tools-design.md` | 当前已暂存的 agent/tool 设计文档 |

这些内容在正式进入后端 agent tool 重构前，应先整理，避免把 UI demo、工具重构、TOC 重构混在一个提交里。

## 分支职责

每条分支只负责自己的边界，减少冲突。

| 分支 | 负责范围 | 不应负责 |
| --- | --- | --- |
| `codex/unified-toc-state-machine` | `backend/pageindex/*`、TOC pipeline、OCR/解析相关服务、TOC tests | agent tool 协议、前端 UI |
| `agent工具开发：文档内搜索` | agent 工具协议、文档读取工具、图片页返回策略、工具测试、必要的后端配置 API | 大面积前端 UI、TOC 算法重构 |
| `codex/pagechat-frontend-redesign` | `frontend/*`、前端类型、API client、UI 迁移 | 后端核心实现、TOC pipeline |
| `codex/pagechat-integration-base` | 合并后的稳定基线、冲突解决、跨模块验证 | 日常大功能开发 |

## 总体顺序

推荐顺序：

1. 整理当前工作区，保护 demo 和未完成文档。
2. 先稳定 `codex/unified-toc-state-machine`。
3. 从 TOC 稳定点创建 `codex/pagechat-integration-base`。
4. 将集成基线合入 agent 分支，再做 agent tool 重构。
5. 从集成基线开前端分支，将 demo 迁移到真实 `frontend/`。
6. 用集成基线分支按顺序合并 agent 与 frontend。
7. 集成基线通过后，再进入主开发分支或 PR。

不要等三条线都完成后才第一次合并。

## 阶段 0：整理当前工作区

在当前会话 worktree 中执行：

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat
git status --short
```

### 0.1 保护前端 demo

如果接下来先做 agent tool，先把前端 demo 暂存到 stash：

```powershell
git stash push -u -m "pagechat-ui-demo" -- DESIGN_SYSTEM.md demos/pagechat-design-demo
```

说明：

- `-u` 会包含 untracked 文件。
- 只 stash UI demo 与设计系统，不动其他未跟踪目录。
- 后续前端分支会重新应用这个 stash。

### 0.2 处理已暂存文档

如果 `docs/superpowers/specs/2026-06-22-agent-library-navigation-tools-design.md` 暂时不准备提交：

```powershell
git restore --staged docs/superpowers/specs/2026-06-22-agent-library-navigation-tools-design.md
```

这只取消暂存，不删除文件。

## 阶段 1：稳定 TOC 分支

TOC 是底层能力，优先稳定。

```powershell
cd D:\projects\page_chat
git status --short
```

先跑重点测试：

```powershell
python -m pytest backend/tests/test_toc_state_machine.py backend/tests/test_toc_attempt_runner.py backend/tests/test_pageindex_service_balanced_flow.py
```

再跑完整后端测试：

```powershell
python -m pytest backend/tests
```

如果通过，推送 TOC 分支：

```powershell
git push origin codex/unified-toc-state-machine
```

如果失败，先在 TOC 分支内修复。不要在 agent 或 frontend 分支里修 TOC pipeline。

## 阶段 2：创建集成基线

TOC 分支稳定后，从它创建集成基线：

```powershell
cd D:\projects\page_chat
git switch codex/unified-toc-state-machine
git pull --ff-only
git switch -c codex/pagechat-integration-base
git push -u origin codex/pagechat-integration-base
```

后续所有大分支都以 `codex/pagechat-integration-base` 为共同底座。

集成基线原则：

- 只合并稳定成果。
- 只解决跨分支冲突。
- 只做小的 glue code。
- 不直接承载大功能开发。

## 阶段 3：agent tool 重构

回到当前会话 worktree：

```powershell
cd C:\Users\TT_WT\.codex\worktrees\fc17\page_chat
git fetch origin
git merge origin/codex/pagechat-integration-base
```

### 3.1 先落工具 contract

在写实现前，先明确工具契约。至少覆盖：

| 工具 | 目的 | 关键要求 |
| --- | --- | --- |
| `view_folder_structure` | 查看资料库文件夹结构 | 只返回文件夹元信息，不返回正文 |
| `browse_documents` | 浏览或搜索文档 | 返回紧凑文档元信息，不返回全文或 matched segments |
| `get_document_structure` | 获取文档 TOC / 结构 | 使用最新 TOC pipeline 结果，支持长结构分页 |
| `get_page_content` | 获取指定页内容 | 图片页不返回 OCR 全文 |
| `get_document_image` | 获取嵌入图片/图表 | 使用 `get_page_content` 返回的 `image_path` |
| `get_page_image` | 获取整页 PDF 图片 | 作为视觉 fallback |
| `search_within_document` | 指定文档内定位文本 | 必须限定 `document_id` / 文件 ID |

工具结果必须避免以下内容：

- 不返回整篇文档全文。
- 不在图片页同时塞入大段 OCR 文本。
- 不返回不可控的大体积 raw JSON。
- 不让后端以模型不可知的方式偷偷替换模型可见上下文。

### 3.2 实现顺序

推荐实现顺序：

1. 定义工具返回类型。
2. 改 `get_document_page` 的图片页策略。
3. 补强 `get_document_image`。
4. 新增或调整文档内搜索工具。
5. 移除旧 agent 工具入口，避免模型继续调用兼容工具链。
6. 增加后端测试。

### 3.3 agent tool 验收

至少验证：

```powershell
python -m pytest backend/tests
```

建议增加专项测试：

| 场景 | 期望 |
| --- | --- |
| 图片页调用 `get_document_page` | 不返回 OCR 全文 |
| 图片页调用 `get_document_image` | 可获得图片内容或图片引用 |
| 指定文档内搜索 | 必须限定文件 ID / document ID |
| 工具结果结构 | 字段稳定，前端和 agent 可消费 |
| TOC 工具 | 使用 unified TOC 结果 |

agent 分支稳定后：

```powershell
git push origin "agent工具开发：文档内搜索"
```

## 阶段 4：前端真实开发

从集成基线开前端 worktree：

```powershell
git worktree add C:\Users\TT_WT\.codex\worktrees\pagechat-frontend -b codex/pagechat-frontend-redesign origin/codex/pagechat-integration-base
cd C:\Users\TT_WT\.codex\worktrees\pagechat-frontend
```

如果阶段 0 已 stash demo，在前端 worktree 中恢复：

```powershell
git stash list
git stash apply stash^{/pagechat-ui-demo}
```

先单独提交 demo 与设计系统：

```powershell
git add DESIGN_SYSTEM.md demos/pagechat-design-demo
git commit -m "docs(ui): add PageChat design demo"
```

### 4.1 前端实现顺序

推荐顺序：

1. 迁移全局设计系统。
2. 迁移应用骨架：登录、侧边栏、顶栏、主内容区。
3. 重做 Chat 页面：内联工具调用、composer、附件入口。
4. 重做 Documents 页面：列表、路径、文件夹、预览弹窗。
5. 重做 Settings：模型供应商、OCR 设置、解析设置、问答设置。
6. 接入真实 API。

### 4.2 前端验收

在前端 worktree 中执行：

```powershell
cd frontend
npm install
npm run build
npm test
```

如启动预览：

```powershell
npm run dev
```

前端分支稳定后：

```powershell
git push origin codex/pagechat-frontend-redesign
```

## 阶段 5：集成合并

创建或进入集成 worktree：

```powershell
git worktree add C:\Users\TT_WT\.codex\worktrees\pagechat-integration codex/pagechat-integration-base
cd C:\Users\TT_WT\.codex\worktrees\pagechat-integration
git fetch origin
```

### 5.1 先合 agent

```powershell
git merge --no-ff origin/agent工具开发：文档内搜索
python -m pytest backend/tests
git push origin codex/pagechat-integration-base
```

如果冲突集中在 TOC / pageindex：

- 优先保留 `codex/unified-toc-state-machine` 的架构。
- agent 分支只适配新接口，不回退 TOC 实现。

### 5.2 再合 frontend

```powershell
git merge --no-ff origin/codex/pagechat-frontend-redesign
python -m pytest backend/tests
cd frontend
npm run build
npm test
git push origin codex/pagechat-integration-base
```

如果冲突集中在 API 类型或字段：

- 以后端 agent tool contract 为准。
- 前端调整 API client 和类型。
- 不在前端分支临时绕过后端协议。

### 5.3 AnySearch Web Search 集成状态（2026-06-25）

当前 `codex/pagechat-product-behavior-closure` 分支已完成 API-only AnySearch 集成：

- 后端新增 `GET/PUT /api/settings/web-search`，按用户隔离保存 Web Search 配置，API Key 加密存储且只返回脱敏值。
- 后端新增 AnySearch REST client，调用 `POST https://api.anysearch.com/v1/search`，只保留紧凑结果和 `content_preview`，不保存原始网页全文。
- agent 侧新增 gated `web_search` tool：`on-demand` 模式只有用户请求时可用，`auto` 模式允许自动调用。
- Chat 请求已改为结构化 `web_search: true`，不再把 “Web Search enabled” 拼进 prompt。
- 设置弹窗的问答设置页已接入 Web Search provider、mode、zone、language、max results、content types 和可选 API Key 保存。
- 工具 trace 使用内联 `Searched the web` 摘要，不引入底部引用堆。

已验证：

```powershell
py -m pytest backend/tests
cd frontend
npm.cmd test
npm.cmd run build
```

已知边界：

- 本阶段不实现 MCP。
- 截图上传仍是 UI 能力，后端多模态请求与持久化策略需要单独设计。
- OCR/解析/问答模型路由的完整持久化仍是后续计划，不要和 Web Search 配置混为一个提交。

## 冲突处理规则

| 冲突位置 | 处理原则 |
| --- | --- |
| `backend/pageindex/*` | 以 TOC 分支为准 |
| `backend/app/services/*ocr*` | 以 TOC + agent tool 共同需求为准，优先保证图片页策略 |
| agent tool 返回字段 | 以 contract 为准 |
| `frontend/*` | 以前端分支为准，但 API 字段以后端 contract 为准 |
| `docs/*` | 保留集成指导和最终设计文档，删除过期草稿需单独确认 |

不要通过大规模重命名、格式化、批量整理来解决小冲突。

## 每日/每轮开发节奏

每条分支开始工作前：

```powershell
git fetch origin
git status --short
```

如果集成基线有更新，先同步：

```powershell
git merge origin/codex/pagechat-integration-base
```

每轮结束前：

1. 跑该分支最相关测试。
2. 查看 `git diff --stat`。
3. 确认没有混入其他开发线文件。
4. 推送当前分支。

## 最终完成标准

项目进入完整可交付状态前，至少满足：

| 类别 | 标准 |
| --- | --- |
| TOC | unified TOC pipeline 测试通过 |
| agent tool | 工具结果不返回全文，图片页策略正确 |
| frontend | Chat、Documents、Settings 接入真实 API |
| 后端测试 | `python -m pytest backend/tests` 通过 |
| 前端构建 | `npm run build` 通过 |
| 前端测试 | `npm test` 通过 |
| 集成分支 | `codex/pagechat-integration-base` 包含所有稳定成果 |

只有集成分支满足以上条件后，再考虑合入主开发分支或创建 PR。

## 阶段 6：截图上传与多模态聊天完成状态（2026-06-25）

当前 `codex/pagechat-product-behavior-closure` 分支已完成截图/图片作为聊天附件的真实后端与前端链路。

已完成能力：

- 前端 Chat Composer 支持选择/粘贴 PNG、JPEG、WebP 图片，发送前调用 `POST /api/chat/attachments` 上传。
- `/api/chat/stream` 只接收 `attachment_ids`，不接收图片二进制、base64 或 `data:image`。
- 后端新增 `chat_attachments` 表和 `messages.attachments_json`，图片文件存储在 `CHAT_ATTACHMENTS_DIR / user_id / attachment_id.ext`。
- 后端只在当前模型请求中临时构造 OpenAI 兼容的 multimodal `image_url` data URL，数据库、SSE、前端 localStorage、可复用 agent history 都只保留元信息。
- 前端发送后的图片缩略图通过带鉴权的 `chatApi.fetchAttachmentBlob()` 拉取 blob，再生成临时 object URL；不直接暴露未鉴权图片 URL。
- 未发送的已上传附件可以删除；已绑定到消息的附件删除接口返回 conflict。

接口与字段：

- `POST /api/chat/attachments`：上传聊天图片附件，返回附件元信息。
- `GET /api/chat/attachments/{attachment_id}/content`：获取当前用户拥有的附件内容，仅用于 UI 预览。
- `DELETE /api/chat/attachments/{attachment_id}`：删除未绑定的草稿附件。
- `ChatRequest.attachment_ids`：聊天流请求携带附件 ID 列表，当前限制最多 6 张图。
- 消息返回中的 `attachments`：仅包含 `attachment_id`、`original_name`、`mime_type`、`size_bytes`、`width`、`height`、`content_url` 等元信息。

已验证：

```powershell
py -m pytest backend/tests/test_chat_attachments_api.py backend/tests/test_agent_service_sanitize.py backend/tests/test_chat_scope_contract.py -v
cd frontend
npm.cmd test -- chat
cd ..
py -m pytest backend/tests
cd frontend
npm.cmd test
npm.cmd run build
```

验证结果：

- 后端全量：`660 passed, 19 skipped`
- 前端全量：`75 passed`
- 前端构建：通过

已知限制：

- 当前不支持 image-only message，仍要求用户提供文本问题。
- 当前不做截图 OCR；模型需要依赖视觉能力直接看图。
- 如果问答模型不支持 vision，后续应在模型配置/问答设置中做能力提示或路由校验。
- 旧的孤儿附件清理只覆盖前端主动删除，尚未加入定时清理任务。
- 大图只做类型和大小校验，暂未做服务端压缩/缩放。

推荐下一步：

1. 完成 OCR、解析、问答设置的后端持久化与前端真实接入。
2. 补齐 Documents 后端动作：文件夹递归下载、重新解析、移动、删除。
3. 清理真实用户流中的 demo fallback，并把当前产品闭环分支合入集成基线。
