# PageChat Codex 工作指北

最后更新：2026-06-26

这份文档用来防止后续在错误的 worktree、错误的分支或错误的前后端进程上继续开发。

## 当前应该操作的分支

当前主开发分支是：

```text
codex/pagechat-ui-agent-runtime-integration
```

对应 worktree：

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration
```

当前阶段的前端、后端、Agent Runtime、引用、历史记录、模型供应商配置等联调都应该在这个 worktree 里继续。即使 Codex 线程的默认 cwd 显示为旧目录，也要显式切到上面的 worktree 后再执行命令。

快速确认：

```powershell
git -C "C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration" branch --show-current
```

期望输出：

```text
codex/pagechat-ui-agent-runtime-integration
```

## Worktree 和分支职责

| Worktree | 分支 | 职责 | 当前是否用于启动验证 |
| --- | --- | --- | --- |
| `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration` | `codex/pagechat-ui-agent-runtime-integration` | 当前最新集成分支。负责 UI 重构后的实际前端、显式 Agent Loop Runtime、模型供应商、引用预览、聊天历史、工具链联调。 | 是 |
| `C:\Users\TT_WT\.codex\worktrees\fc17\page_chat` | `agent工具开发：文档内搜索` | 早期 Agent 工具开发分支，包含文档内搜索和工具链重构的历史工作。不要用它启动当前最新版产品。 | 否 |
| `C:\Users\TT_WT\.codex\worktrees\pagechat-frontend` | `codex/pagechat-frontend-redesign` | 前端 Apple 风格设计、demo 迁移和页面重构的阶段性分支。当前最新联调结果已经进入集成分支。 | 否 |
| `C:\Users\TT_WT\.codex\worktrees\pagechat-integration` | `codex/pagechat-product-behavior-closure` | 之前的产品行为收口和集成暂存分支。不是当前最终验证入口。 | 否 |
| `D:\projects\page_chat` | `codex/unified-toc-state-machine` | TOC 构建、PageIndex 状态机、解析管线重构分支。只有继续 TOC 专项时才使用。 | 否 |

原则：不要只看端口是否启动。端口上的进程可能来自旧 worktree。必须同时确认 Source、Branch 和 Commit。

## 本地启动方式

优先使用桌面脚本：

```text
C:\Users\TT_WT\Desktop\start-backend.bat
C:\Users\TT_WT\Desktop\start-frontend.bat
```

这两个脚本会优先启动：

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration
```

后端地址：

```text
http://localhost:8000
```

前端地址：

```text
http://localhost:5173
```

也可以在当前集成 worktree 根目录直接运行：

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration\start-backend.bat
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration\start-frontend.bat
```

启动窗口里必须看到类似信息：

```text
Source: C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration
Branch: codex/pagechat-ui-agent-runtime-integration
```

如果 Source 显示为 `D:\projects\page_chat`，说明启动了旧分支，不是当前最新版。

## 启动后检查

检查端口占用和进程来源：

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen |
  Select-Object LocalPort,OwningProcess

Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -in @(<PID1>, <PID2>) } |
  Select-Object ProcessId,CommandLine
```

检查后端健康：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

检查当前集成分支：

```powershell
git -C "C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration" status --short
git -C "C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration" branch --show-current
```

检查模型供应商预设是否是最新版：

```text
GET http://127.0.0.1:8000/api/settings/model-providers/presets
```

当前最新版应返回多厂商预设，数量约为 13 个，而不是只剩 OpenAI compatible / DashScope compatible。

## 本地开发账号

当前本地开发账号：

```text
Email: admin@pagechat.ai
Password: do not commit plaintext passwords; reset locally when needed
```

这是本地开发验证账号，不要把它当成生产凭据使用。实际密码只在本地会话中告知或通过本地脚本重置，不写入 Git 提交。

## 数据位置

当前集成 worktree 使用的数据库：

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration\backend\data\knowclaw.db
```

旧项目数据库：

```text
D:\projects\page_chat\backend\data\knowclaw.db
```

注意：

- 当前集成库和旧库不是同一份数据。
- 旧库里可能有更多历史文档，但不要未经确认就迁移或覆盖当前集成库。
- 如果前端看到的文档、账号、配置突然变回旧状态，优先检查后端是不是启动到了 `D:\projects\page_chat`。

## 环境变量和依赖

后端脚本会优先使用当前 worktree 的：

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration\backend\.env
```

如果当前 worktree 没有 `.env`，脚本会回退读取：

```text
D:\projects\page_chat\backend\.env
```

Python 虚拟环境同理，优先当前 worktree，必要时回退旧项目虚拟环境：

```text
D:\projects\page_chat\backend\venv\Scripts\python.exe
```

这只是为了方便本地启动，不代表代码来自旧项目。判断代码来源必须看启动窗口里的 Source 和 `app.main` 路径。

前端依赖位于：

```text
C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration\frontend\node_modules
```

PowerShell 下运行前端命令优先使用：

```powershell
npm.cmd test
npm.cmd run build
```

## Agent Runtime Mode

Current default backend runtime:

```text
AGENT_RUNTIME_MODE=flat_tool_loop
```

This is the expected runtime for the current integration branch. The backend no longer needs the desktop script to inject `AGENT_RUNTIME_MODE=flat_tool_loop`.

Rollback switch:

```text
AGENT_RUNTIME_MODE=legacy_loop
```

Use `legacy_loop` only when explicitly debugging the older planner/policy runtime. If the UI shows planner-style behavior after restart, first check the backend process source and environment before changing code.

## 不要做的事

- 不要只因为 `8000` 或 `5173` 能打开，就认为正在运行最新版。
- 不要从 `D:\projects\page_chat` 启动当前 UI/Agent 联调，除非明确在做 TOC 分支。
- 不要把 `pagechat-frontend` 当成当前最终前端，它只是前端重构阶段分支。
- 不要未经确认覆盖、迁移或清空数据库。
- 不要在旧 worktree 里修当前集成问题，除非先明确同步目标分支。

## 当前开发判断标准

当以下条件都成立时，才算正在验证当前最新版：

1. 后端 Source 是 `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`。
2. 前端 Source 是 `C:\Users\TT_WT\.codex\worktrees\pagechat-ui-agent-runtime-integration`。
3. 分支是 `codex/pagechat-ui-agent-runtime-integration`。
4. 登录 `admin@pagechat.ai` 成功。
5. 设置页模型供应商能看到多厂商预设。
6. 文档库来自当前集成 worktree 的 `backend\data\knowclaw.db`。

如果任意一项不成立，先停掉对应端口上的旧进程，再用桌面 `start-backend.bat` / `start-frontend.bat` 重启。
