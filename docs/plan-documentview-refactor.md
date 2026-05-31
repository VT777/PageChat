# DocumentView 全面重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans

**Goal:** 重构文档管理界面，支持网格/列表视图切换、文件夹管理、右键菜单、批量操作、后端处理进度显示、批量下载，以及更简洁的文件信息展示

**Architecture:** 
- 前端使用现有组件体系（FolderTree, DocumentContextMenu, BatchActions 等）重构 DocumentView.vue
- 后端新增处理步骤详情API和批量下载API
- 采用模块化组件拆分，保持代码可维护性

**Tech Stack:** Vue3 + TypeScript + Pinia + TailwindCSS + Lucide Icons

---

## 变更概览

### 后端变更

| # | 变更 | 文件 | 说明 |
|---|------|------|------|
| 1 | 新增 `processing_duration` 计算 | `app/api/documents.py` | 在 `_attach_parse_meta` 中计算处理用时 |
| 2 | 新增处理步骤详情API | `app/api/documents.py` | `GET /{doc_id}/processing-steps` |
| 3 | 新增批量下载API | `app/api/documents.py` | `POST /batch-download` |
| 4 | 新增 `processing_steps` 工具 | `app/services/pageindex_service.py` 或新模块 | 生成处理步骤日志 |

### 前端变更

| # | 变更 | 文件 | 说明 |
|---|------|------|------|
| 1 | 新增 `DocumentCard.vue` | `components/document/DocumentCard.vue` | 网格视图卡片 |
| 2 | 新增 `DocumentListItem.vue` | `components/document/DocumentListItem.vue` | 列表视图行 |
| 3 | 新增 `ProcessingStepsDialog.vue` | `components/document/ProcessingStepsDialog.vue` | 处理步骤弹窗 |
| 4 | 新增 `ViewToggle.vue` | `components/document/ViewToggle.vue` | 网格/列表切换按钮 |
| 5 | 重写 `DocumentView.vue` | `views/DocumentView.vue` | 主页面重构 |
| 6 | 增强 `document.ts` | `stores/document.ts` | 添加选择状态、批量下载 |
| 7 | 增强 `index.ts` | `api/index.ts` | 添加批量下载、处理步骤接口 |

---

## Task 1: 后端 - 添加处理用时计算

**Files:**
- Modify: `backend/app/api/documents.py`

**Goal:** 在文档列表和详情响应中自动计算并返回 `processing_duration`（处理用时，单位秒）

**实现思路:**
- `created_at` 和 `updated_at` 字段已存在于数据库中
- 当 `status = 'completed'` 时，`processing_duration = updated_at - created_at`
- 不需要新增数据库字段，在 API 序列化层计算

**具体修改:**

```python
# 在 _attach_parse_meta 函数中添加
def _calculate_processing_duration(doc) -> Optional[float]:
    """计算文档处理用时（秒）"""
    if doc.status == 'completed' and doc.created_at and doc.updated_at:
        try:
            from datetime import datetime
            if isinstance(doc.created_at, str):
                created = datetime.fromisoformat(doc.created_at.replace('Z', '+00:00'))
                updated = datetime.fromisoformat(doc.updated_at.replace('Z', '+00:00'))
            else:
                created = doc.created_at
                updated = doc.updated_at
            return (updated - created).total_seconds()
        except Exception:
            return None
    return None

def _attach_parse_meta(doc: DocumentResponse) -> DocumentResponse:
    meta = _load_index_meta_brief(doc.index_path)
    doc.parse_requested_mode = meta.get("requested_mode")
    doc.parse_execution_mode = meta.get("execution_mode")
    doc.parse_reasons = meta.get("reasons") or []
    doc.parse_completion = _parse_completion_from_status(doc.status)
    doc.parse_error_code = _parse_error_code(doc.status)
    doc.processing_duration = _calculate_processing_duration(doc)  # 新增
    return doc
```

---

## Task 2: 后端 - 新增处理步骤详情API

**Files:**
- Modify: `backend/app/api/documents.py`
- Modify: `backend/app/models/schemas.py`

**Goal:** 提供 `GET /api/documents/{doc_id}/processing-steps`，返回文档索引处理的详细步骤和时间线

**Schema 新增:**

```python
# schemas.py
class ProcessingStep(BaseModel):
    step_type: str  # "upload", "analyze", "toc_extraction", "toc_validation", "node_filling", "summary_generation", "completed"
    title: str
    description: str
    status: str  # "pending", "running", "completed", "failed"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    details: Optional[Dict[str, Any]] = None  # 额外信息，如页数、节点数等

class ProcessingStepsResponse(BaseModel):
    doc_id: str
    doc_name: str
    status: str
    total_duration_seconds: Optional[float] = None
    steps: List[ProcessingStep]
    current_step: Optional[str] = None
```

**API 实现思路:**
由于后端没有持久化的处理日志，我们需要从以下数据源重构步骤：

1. **文档状态** `documents.status`:
   - `completed` -> 全部完成
   - `processing:queued` -> 排队中
   - `processing:indexing` -> 正在索引
   - `processing:writing_index` -> 正在写入索引
   - `failed:*` -> 失败

2. **索引文件** `{doc_id}.json`:
   - 读取 `route_decision` 获取执行模式 (smart/fast/balanced)
   - 读取 `structure` 获取节点数
   - 读取 `visual_coverage` 或 `index_mode`

3. **文档元数据**:
   - `page_count` - 总页数
   - `processed_pages` - 已处理页数
   - `created_at` - 开始时间
   - `updated_at` - 完成/更新时间

**生成步骤的伪代码:**

```python
async def get_processing_steps(doc_id: str) -> ProcessingStepsResponse:
    doc = await get_document(doc_id)
    
    steps = []
    
    # Step 1: 上传
    steps.append(ProcessingStep(
        step_type="upload",
        title="文件上传",
        description="文件已上传至服务器",
        status="completed",
        start_time=doc.created_at,
        end_time=doc.created_at  # 瞬时完成
    ))
    
    # Step 2: 文档分析
    if doc.status.startswith("processing") or doc.status == "completed":
        steps.append(ProcessingStep(
            step_type="analyze",
            title="文档分析",
            description=f"分析文档结构，共 {doc.page_count or '?'} 页",
            status="completed",
            details={"page_count": doc.page_count, "text_coverage": "..."}
        ))
    
    # Step 3: 目录提取
    index_data = await load_index(doc_id)
    if index_data:
        route = index_data.get("route_decision", {})
        mode = route.get("execution_mode", "unknown")
        toc_items = len(structure_to_list(index_data.get("structure", [])))
        steps.append(ProcessingStep(
            step_type="toc_extraction",
            title="目录提取",
            description=f"使用 {mode} 模式提取目录，共 {toc_items} 个节点",
            status="completed",
            details={"mode": mode, "node_count": toc_items}
        ))
    
    # Step 4: 节点填充与摘要
    if doc.status == "completed":
        steps.append(ProcessingStep(
            step_type="node_filling",
            title="内容填充",
            description="提取各节点文本内容",
            status="completed"
        ))
        steps.append(ProcessingStep(
            step_type="summary_generation",
            title="摘要生成",
            description="为各章节生成摘要",
            status="completed"
        ))
    
    # 如果还在处理中，添加当前步骤
    current_step = None
    if doc.status.startswith("processing:indexing"):
        current_step = "toc_extraction"
        steps[-1].status = "running"
    elif doc.status.startswith("processing:writing_index"):
        current_step = "node_filling"
    
    # 计算总用时
    total_duration = _calculate_processing_duration(doc)
    
    return ProcessingStepsResponse(
        doc_id=doc_id,
        doc_name=doc.original_name,
        status=doc.status,
        total_duration_seconds=total_duration,
        steps=steps,
        current_step=current_step
    )
```

---

## Task 3: 后端 - 新增批量下载API

**Files:**
- Modify: `backend/app/api/documents.py`

**Goal:** 支持 `POST /api/documents/batch-download`，返回 ZIP 文件

**实现思路:**

```python
from fastapi.responses import StreamingResponse
import zipfile
import io

@router.post("/batch-download")
async def batch_download(
    doc_ids: List[str],
    db: aiosqlite.Connection = Depends(get_db),
    current_user: dict = Depends(require_auth),
):
    """批量下载文档（打包为ZIP）"""
    doc_service = DocumentService(db)
    user_id = current_user["id"]
    
    # 验证所有文档存在且属于当前用户
    docs = []
    for doc_id in doc_ids:
        doc = await doc_service.get_document(doc_id, user_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
        if not os.path.exists(doc.file_path):
            raise HTTPException(status_code=404, detail=f"文档 {doc_id} 文件不存在")
        docs.append(doc)
    
    # 创建 ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            zf.write(doc.file_path, arcname=doc.original_name)
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=batch_download_{len(docs)}.zip"
        }
    )
```

---

## Task 4: 前端 - 创建 DocumentCard.vue（网格视图）

**Files:**
- Create: `frontend/src/components/document/DocumentCard.vue`

**设计参考:**
- 用户提供的参考图：网格卡片，包含文件图标、文件名、简短描述（description/truncated）、页数、上传时间
- 卡片悬停效果，点击进入预览
- 右键呼出菜单

**组件接口:**

```typescript
interface Props {
  document: Document
  selected?: boolean
}

interface Emits {
  click: [doc: Document]        // 点击卡片进入预览
  contextmenu: [doc: Document, event: MouseEvent]
  select: [id: string]          // 复选框选择
}
```

**布局结构:**

```vue
<template>
  <div
    class="document-card"
    :class="{ selected, 'hover-effect': true }"
    @click="handleClick"
    @contextmenu.prevent="handleContextMenu"
  >
    <!-- 选择复选框 (批量模式时显示) -->
    <div v-if="batchMode" class="select-checkbox">
      <input type="checkbox" :checked="selected" @click.stop @change="handleSelect" />
    </div>
    
    <!-- 文件图标 -->
    <FileTypeIcon :fileType="doc.file_type" size="lg" />
    
    <!-- 文件名 -->
    <div class="doc-name">{{ doc.original_name }}</div>
    
    <!-- 描述（如果有） -->
    <div v-if="doc.description" class="doc-description">
      {{ truncatedDescription }}
    </div>
    
    <!-- 元信息行 -->
    <div class="doc-meta">
      <span v-if="doc.page_count">{{ doc.page_count }} 页</span>
      <span>{{ formatDate(doc.created_at) }}</span>
    </div>
    
    <!-- 状态标签 -->
    <div class="doc-status">
      <span :class="statusClass">{{ statusText }}</span>
      <!-- 处理中显示进度条 -->
      <div v-if="isProcessing" class="progress-bar-mini">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>
    
    <!-- 索引模式标签 (completed 时显示) -->
    <div v-if="doc.status === 'completed' && doc.parse_execution_mode" class="doc-mode">
      <span class="mode-badge" :class="doc.parse_execution_mode">
        {{ modeText }}
      </span>
      <span v-if="doc.processing_duration" class="duration-text">
        {{ formatDuration(doc.processing_duration) }}
      </span>
    </div>
  </div>
</template>
```

---

## Task 5: 前端 - 创建 DocumentListItem.vue（列表视图）

**Files:**
- Create: `frontend/src/components/document/DocumentListItem.vue`

**设计参考:**
- 用户提供的参考图：列表行，包含文件图标、文件名、描述、页数、上传时间、操作按钮

**组件接口:** 同 DocumentCard

**布局结构:**

```vue
<template>
  <div
    class="document-list-item"
    :class="{ selected }"
    @click="handleClick"
    @contextmenu.prevent="handleContextMenu"
  >
    <!-- 选择复选框 -->
    <div v-if="batchMode" class="select-col">
      <input type="checkbox" :checked="selected" @click.stop @change="handleSelect" />
    </div>
    
    <!-- 文件图标+名称 -->
    <div class="name-col">
      <FileTypeIcon :fileType="doc.file_type" size="sm" />
      <div class="name-text">
        <div class="doc-name">{{ doc.original_name }}</div>
        <div v-if="doc.description" class="doc-description">{{ truncatedDescription }}</div>
      </div>
    </div>
    
    <!-- 页数 -->
    <div class="pages-col">
      <span v-if="doc.page_count">{{ doc.page_count }} 页</span>
    </div>
    
    <!-- 索引模式 -->
    <div class="mode-col">
      <span v-if="doc.parse_execution_mode" class="mode-badge">
        {{ modeText }}
      </span>
    </div>
    
    <!-- 状态 -->
    <div class="status-col">
      <span :class="statusClass">{{ statusText }}</span>
    </div>
    
    <!-- 处理用时 (completed) -->
    <div class="duration-col">
      <span v-if="doc.processing_duration">{{ formatDuration(doc.processing_duration) }}</span>
    </div>
    
    <!-- 上传时间 -->
    <div class="date-col">{{ formatDate(doc.created_at) }}</div>
    
    <!-- 操作按钮 -->
    <div class="actions-col">
      <button @click.stop="handlePreview" title="预览"><Eye class="w-4 h-4" /></button>
      <button @click.stop="handleReindex" title="重新索引"><RefreshCw class="w-4 h-4" /></button>
      <button @click.stop="handleMove" title="移动"><Move class="w-4 h-4" /></button>
      <button @click.stop="handleDelete" title="删除"><Trash2 class="w-4 h-4" /></button>
      <button @click.stop="handleDownload" title="下载"><Download class="w-4 h-4" /></button>
    </div>
  </div>
</template>
```

---

## Task 6: 前端 - 创建 ProcessingStepsDialog.vue

**Files:**
- Create: `frontend/src/components/document/ProcessingStepsDialog.vue`

**设计思路:**
- 用户希望看到**详细的处理步骤**，而不仅是宽泛的状态
- 点击进度条区域或状态标签上的按钮，弹出步骤详情弹窗
- 显示时间线，包含每个步骤的标题、描述、状态、用时
- 当前运行步骤高亮显示

**组件接口:**

```typescript
interface Props {
  open: boolean
  docId: string
}

interface Emits {
  'update:open': [boolean]
}
```

**布局结构:**

```vue
<template>
  <Teleport to="body">
    <div v-if="open" class="modal-overlay" @click.self="close">
      <div class="modal-content">
        <div class="modal-header">
          <h3>处理进度详情</h3>
          <button @click="close"><X /></button>
        </div>
        
        <div v-if="loading" class="loading">加载中...</div>
        
        <div v-else-if="stepsData" class="steps-content">
          <!-- 总览 -->
          <div class="steps-overview">
            <div class="status-badge" :class="stepsData.status">
              {{ statusText }}
            </div>
            <div v-if="stepsData.total_duration_seconds" class="total-duration">
              总用时: {{ formatDuration(stepsData.total_duration_seconds) }}
            </div>
          </div>
          
          <!-- 步骤时间线 -->
          <div class="steps-timeline">
            <div
              v-for="(step, index) in stepsData.steps"
              :key="step.step_type"
              class="step-item"
              :class="[step.status, { current: step.step_type === stepsData.current_step }]"
            >
              <!-- 步骤序号/图标 -->
              <div class="step-icon">
                <CheckCircle v-if="step.status === 'completed'" />
                <Loader2 v-else-if="step.status === 'running'" class="animate-spin" />
                <Circle v-else />
              </div>
              
              <!-- 步骤信息 -->
              <div class="step-info">
                <div class="step-title">{{ step.title }}</div>
                <div class="step-description">{{ step.description }}</div>
                <div v-if="step.details" class="step-details">
                  <span v-if="step.details.mode">模式: {{ step.details.mode }}</span>
                  <span v-if="step.details.node_count">节点: {{ step.details.node_count }}</span>
                  <span v-if="step.details.page_count">页数: {{ step.details.page_count }}</span>
                </div>
              </div>
              
              <!-- 步骤用时 -->
              <div v-if="step.duration_seconds" class="step-duration">
                {{ formatDuration(step.duration_seconds) }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

---

## Task 7: 前端 - 创建 ViewToggle.vue

**Files:**
- Create: `frontend/src/components/document/ViewToggle.vue`

**设计:**
- 两个图标按钮：网格（Grid）和列表（List）
- 当前激活视图高亮
- 极简风格

```vue
<template>
  <div class="view-toggle">
    <button
      @click="setView('grid')"
      :class="{ active: currentView === 'grid' }"
      title="网格视图"
    >
      <GridIcon class="w-4 h-4" />
    </button>
    <button
      @click="setView('list')"
      :class="{ active: currentView === 'list' }"
      title="列表视图"
    >
      <ListIcon class="w-4 h-4" />
    </button>
  </div>
</template>
```

---

## Task 8: 前端 - 增强 DocumentStore

**Files:**
- Modify: `frontend/src/stores/document.ts`

**新增内容:**

```typescript
// 新增状态
const selectedIds = ref<Set<string>>(new Set())
const batchMode = ref(false)

// 新增 Getters
const hasSelection = computed(() => selectedIds.value.size > 0)
const selectedDocuments = computed(() => 
  documents.value.filter(d => selectedIds.value.has(d.id))
)

// 新增 Actions
function toggleSelection(id: string) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

function selectAll() {
  documents.value.forEach(d => selectedIds.value.add(d.id))
}

function deselectAll() {
  selectedIds.value.clear()
}

function setBatchMode(enabled: boolean) {
  batchMode.value = enabled
  if (!enabled) deselectAll()
}

// 批量操作（并行执行）
async function batchMove(docIds: string[], folder_id: string | null) {
  const promises = docIds.map(id => moveDocument(id, folder_id))
  const results = await Promise.allSettled(promises)
  // 处理结果...
}

async function batchDelete(docIds: string[]) {
  const promises = docIds.map(id => deleteDocument(id))
  const results = await Promise.allSettled(promises)
}

async function batchReindex(docIds: string[]) {
  const promises = docIds.map(id => reindexDocument(id))
  const results = await Promise.allSettled(promises)
}

// 批量下载
async function batchDownload(docIds: string[]) {
  const { data } = await documentApi.batchDownload(docIds)
  // 触发浏览器下载...
}
```

---

## Task 9: 前端 - 增强 API 层

**Files:**
- Modify: `frontend/src/api/index.ts`

**新增接口:**

```typescript
// 处理步骤详情
getProcessingSteps: (id: string) => api.get(`/documents/${id}/processing-steps`),

// 批量下载
batchDownload: (ids: string[]) => api.post('/documents/batch-download', { doc_ids: ids }, {
  responseType: 'blob'
}),
```

---

## Task 10: 前端 - 重写 DocumentView.vue（主页面）

**Files:**
- Rewrite: `frontend/src/views/DocumentView.vue`

**布局结构:**

```
DocumentView
├── Header（顶部工具栏）
│   ├── 左侧: 面包屑路径（All / Folder1 / SubFolder）
│   ├── 中间: 搜索框
│   └── 右侧: 视图切换（网格/列表）
│
├── Main Content（主内容区）
│   ├── Toolbar（工具栏）
│   │   ├── 新建文件夹按钮
│   │   ├── 上传按钮（支持拖拽）
│   │   ├── 选择按钮（进入批量模式）
│   │   └── 批量操作栏（BatchActions.vue，选择后显示）
│   │
│   ├── Document List（文档列表区）
│   │   ├── Grid View: DocumentCard.vue × N
│   │   └── List View: DocumentListItem.vue × N
│   │
│   └── Empty State（空状态）
│
├── Sidebar（左侧边栏 - FolderTree.vue）
│   ├── 文件夹树（支持右键菜单、创建/重命名/删除）
│   └── 文件拖拽到文件夹
│
├── Modals（弹窗层）
│   ├── Preview Modal（已有）
│   ├── ProcessingStepsDialog（处理步骤详情）
│   ├── MoveToFolderDialog（移动文档）
│   ├── CreateFolderDialog（新建文件夹）
│   └── RenameDialog（重命名）
│
└── Context Menus（右键菜单层）
    ├── DocumentContextMenu（文档右键）
    └── FolderContextMenu（文件夹右键）
```

**关键实现细节:**

1. **右键菜单集成:**
   - 文档卡片/列表行绑定 @contextmenu
   - 文件夹树项绑定 @contextmenu
   - 主内容区空白处右键：显示"新建文件夹""粘贴""全选"
   - 左侧边栏空白处右键：显示"新建文件夹"

2. **文件夹内显示子文件夹:**
   - 使用 folderApi.getContents(folder_id) 获取混合内容
   - 在文档列表上方显示子文件夹行/卡片
   - 子文件夹点击后导航进入

3. **批量模式:**
   - 点击"选择"按钮进入批量模式
   - 所有文档显示复选框
   - 底部/顶部显示 BatchActions 栏
   - ESC 键退出批量模式

4. **处理进度显示:**
   - 每个文档卡片/行显示当前状态
   - completed -> 显示模式标签 + 用时
   - processing -> 显示进度条（基于 processed_pages / page_count）+ 点击查看详情按钮
   - failed -> 显示错误提示 + 重试按钮

---

## Task 11: 前端 - 添加处理进度轮询

**Files:**
- Modify: `frontend/src/stores/document.ts`

**实现思路:**
- 对于 status === 'processing' 的文档，每隔 5 秒轮询状态
- 使用 setInterval 或 setTimeout
- 轮询接口：GET /api/documents/{id}（返回最新状态）
- 更新本地 documents 数组中的对应项

```typescript
// 在 store 中添加
let pollingInterval: number | null = null

function startPolling() {
  if (pollingInterval) return
  pollingInterval = window.setInterval(async () => {
    const processingDocs = documents.value.filter(d => d.status.startsWith('processing'))
    if (processingDocs.length === 0) {
      stopPolling()
      return
    }
    // 轮询每个处理中文档的状态
    for (const doc of processingDocs) {
      try {
        const { data } = await documentApi.get(doc.id)
        updateDocumentStatus(doc.id, data.status, data)
      } catch (e) {
        console.error('Polling error:', e)
      }
    }
  }, 5000)
}

function stopPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval)
    pollingInterval = null
  }
}
```

---

## Task 12: 前端 - 添加面包屑导航

**Files:**
- 可创建新组件或内联实现

**设计:**
- 顶部显示当前路径：All > Folder1 > SubFolder
- 点击任意层级可跳转回该层级
- 类似用户参考图的设计

---

## Task 13: 样式统一

**当前项目风格:**
- 使用 Tailwind CSS + shadcn-vue 组件风格
- 主色调：`#2563eb`（blue-600）
- 背景：`#f5f5f5`
- 卡片：白色背景，圆角，阴影

**需要统一:**
- DocumentCard: 白色卡片，圆角 8px，hover 阴影增强，padding 16px
- DocumentListItem: 白色背景，底部边框分隔，hover 背景 `#f8f9fa`
- 状态标签：小圆角 pill 形状
- 按钮：蓝色主按钮，灰色次按钮
- 右键菜单：白色背景，阴影，圆角，hover 背景灰色

---

## 文件清单（完整）

### 需要修改的文件

| # | 文件 | 变更类型 | 说明 |
|---|------|----------|------|
| 1 | `backend/app/api/documents.py` | 修改 | 添加 `processing_duration` 计算、处理步骤API、批量下载API |
| 2 | `backend/app/models/schemas.py` | 修改 | 添加 `ProcessingStep`, `ProcessingStepsResponse` schema |
| 3 | `frontend/src/views/DocumentView.vue` | **重写** | 主页面重构 |
| 4 | `frontend/src/stores/document.ts` | 修改 | 添加选择状态、批量模式、批量下载、轮询 |
| 5 | `frontend/src/api/index.ts` | 修改 | 添加 `getProcessingSteps`, `batchDownload` |

### 需要创建的文件

| # | 文件 | 说明 |
|---|------|------|
| 1 | `frontend/src/components/document/DocumentCard.vue` | 网格视图卡片 |
| 2 | `frontend/src/components/document/DocumentListItem.vue` | 列表视图行 |
| 3 | `frontend/src/components/document/ProcessingStepsDialog.vue` | 处理步骤详情弹窗 |
| 4 | `frontend/src/components/document/ViewToggle.vue` | 视图切换按钮 |
| 5 | `frontend/src/components/document/BreadcrumbNav.vue` | 面包屑导航（可选，可内联） |

### 需要复用的现有文件

| 组件 | 文件 | 用途 |
|------|------|------|
| FolderTree | `components/folder/FolderTree.vue` | 左侧文件夹树 |
| FolderTreeItem | `components/folder/FolderTreeItem.vue` | 树项（已集成右键菜单） |
| FolderContextMenu | `components/folder/FolderContextMenu.vue` | 文件夹右键菜单 |
| CreateFolderDialog | `components/folder/CreateFolderDialog.vue` | 新建文件夹弹窗 |
| DocumentContextMenu | `components/document/DocumentContextMenu.vue` | 文档右键菜单 |
| BatchActions | `components/document/BatchActions.vue` | 批量操作栏 |
| MoveToFolderDialog | `components/document/MoveToFolderDialog.vue` | 移动文档弹窗 |
| FileTypeIcon | `components/document/FileTypeIcon.vue` | 文件类型图标 |
| PdfReferenceViewer | `components/PdfReferenceViewer.vue` | PDF 预览 |
| UniversalPreview | `components/preview/UniversalPreview.vue` | 通用预览 |

---

## 测试计划

### 后端测试

1. **处理用时计算**
   ```python
   # 测试用例
   # 1. completed 文档 - 应返回正整数秒
   # 2. processing 文档 - 应返回 None
   # 3. failed 文档 - 应返回 None
   ```

2. **处理步骤API**
   ```bash
   curl http://localhost:8000/api/documents/{doc_id}/processing-steps
   # 验证返回 steps 数组
   # 验证 completed 文档有所有步骤
   # 验证 processing 文档 current_step 指向正确
   ```

3. **批量下载**
   ```bash
   curl -X POST http://localhost:8000/api/documents/batch-download \
     -H "Authorization: Bearer {token}" \
     -H "Content-Type: application/json" \
     -d '{"doc_ids": ["id1", "id2"]}' \
     --output test.zip
   # 验证 ZIP 包含正确文件
   ```

### 前端测试

1. **视图切换**
   - 点击网格/列表按钮，验证布局切换
   - 刷新页面后保持上次选择的视图（localStorage）

2. **右键菜单**
   - 文档右键 -> 显示 DocumentContextMenu
   - 文件夹右键 -> 显示 FolderContextMenu
   - 空白处右键 -> 显示上下文相关菜单

3. **批量操作**
   - 点击"选择"进入批量模式
   - 勾选多个文档
   - 执行批量移动/删除/重索引/下载
   - ESC 退出批量模式

4. **处理进度**
   - 上传新文档，观察状态变化
   - 点击"查看详情"按钮，验证弹窗显示步骤
   - 验证 completed 后显示模式标签和用时

5. **文件夹管理**
   - 新建文件夹
   - 重命名文件夹
   - 删除文件夹（含确认）
   - 右键菜单触发上述操作

---

## 实施顺序建议

按依赖关系排序：

1. **Phase 1: 后端基础**
   - Task 1: 处理用时计算
   - Task 2: 处理步骤API
   - Task 3: 批量下载API

2. **Phase 2: 前端组件**
   - Task 7: ViewToggle.vue
   - Task 4: DocumentCard.vue
   - Task 5: DocumentListItem.vue
   - Task 6: ProcessingStepsDialog.vue

3. **Phase 3: 前端状态**
   - Task 8: 增强 DocumentStore
   - Task 9: 增强 API 层
   - Task 11: 添加轮询

4. **Phase 4: 主页面重构**
   - Task 10: 重写 DocumentView.vue

---

**Plan complete.**

请选择执行方式：
1. **Subagent-Driven** - 每个 Task 独立子代理执行，我进行审核
2. **Inline Execution** - 我在当前会话逐步执行，批量修改

推荐方式 2（Inline），因为这是一个连贯的重构，需要前后端配合，且组件之间有样式依赖。