<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  BookOpen,
  Download,
  Eye,
  File,
  FileCode,
  FileSpreadsheet,
  FileText,
  FileType,
  Folder,
  FolderInput,
  FolderOpen,
  Grid2X2,
  List,
  Loader2,
  Move,
  Plus,
  Presentation,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Square,
  Trash2,
  Upload,
  X,
} from 'lucide-vue-next'
import { documentApi } from '@/api'
import type { ProcessingStep } from '@/api'
import type { Document } from '@/stores/document'
import { useDocumentStore } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'
import type { QualityReport } from '@/types/retrieval'
import {
  documentProgress,
  formatDocumentDate,
  formatDocumentDuration,
  formatDocumentSize,
  formatDocumentTypeLabel,
  isCompletedStatus,
  isProcessingStatus,
  localizedStatusLabel,
  metadataValue,
  documentDetailMetrics,
  DOCUMENT_WORKBENCH_PAGE_SIZE,
  qualityDisplay,
  workbenchIncludeSubfolders,
} from '@/utils/documentWorkbench'
import DocumentContextMenu from '@/components/document/DocumentContextMenu.vue'
import PdfReferenceViewer from '@/components/PdfReferenceViewer.vue'
import ProcessingStepsDialog from '@/components/document/ProcessingStepsDialog.vue'
import TocTree from '@/components/document/TocTree.vue'
import UniversalPreview from '@/components/preview/UniversalPreview.vue'
import CreateFolderDialog from '@/components/folder/CreateFolderDialog.vue'

interface TocItem {
  node_id: string
  title: string
  level: number
  summary: string
  start_page: number
  end_page: number
  children: TocItem[]
}

interface PreviewData {
  id: string
  name: string
  file_type: string
  file_size: number
  status: string
  page_count: number
  description?: string
  processing_duration?: number
  quality_report?: QualityReport | null
  created_at: string
  updated_at: string
  toc: TocItem[]
  index_meta: {
    route_decision?: { execution_mode?: string }
    pre_analysis?: unknown
    toc_quality?: unknown
    visual_page_summaries_count: number
  }
  stats: {
    node_count: number
    text_chars: number
    has_summaries: number
    summary_coverage: string
  }
}

const router = useRouter()
const documentStore = useDocumentStore()
const folderStore = useFolderStore()

const uploading = ref(false)
const uploadError = ref('')
const uploadProgress = ref({ current: 0, total: 0, currentFile: '' })
const deleteConfirmId = ref<string | null>(null)
const searchInput = ref('')
const selectedDocumentId = ref<string | null>(null)

const showPreview = ref(false)
const previewDocId = ref('')
const previewDocName = ref('')
const previewDocType = ref('')
const showPdfPreview = ref(false)
const showUniversalPreview = ref(false)
const previewData = ref<PreviewData | null>(null)
const previewLoading = ref(false)
const pdfViewerRef = ref<InstanceType<typeof PdfReferenceViewer> | null>(null)
const activePreviewTab = ref<'toc' | 'meta'>('toc')

const showMoveModal = ref(false)
const moveDocId = ref<string | null>(null)
const renamingDoc = ref<Document | null>(null)
const renameValue = ref('')
const showCreateFolderDialog = ref(false)
const createFolderParentId = ref<string | null>(null)

const showStepsDialog = ref(false)
const stepsDocName = ref('')
const stepsData = ref<ProcessingStep[]>([])
const stepsLoading = ref(false)

const contextMenuDoc = ref<Document | null>(null)
const contextMenuRef = ref<InstanceType<typeof DocumentContextMenu> | null>(null)

const selectedDocument = computed(() => (
  documentStore.documents.find((doc) => doc.id === selectedDocumentId.value)
  || documentStore.documents[0]
  || null
))

const currentFolderName = computed(() => folderStore.currentFolder?.name || 'All documents')

const recentUpdate = computed(() => {
  const latest = documentStore.documents
    .map((doc) => new Date(doc.updated_at).getTime())
    .filter((time) => Number.isFinite(time))
    .sort((a, b) => b - a)[0]
  return latest ? formatDocumentDate(new Date(latest).toISOString()) : 'Not available'
})

const activeIndexingCount = computed(() =>
  documentStore.documents.filter((doc) => isProcessingStatus(doc.status)).length
)

const totalPages = computed(() => Math.max(1, Math.ceil(documentStore.total / DOCUMENT_WORKBENCH_PAGE_SIZE)))

const pageNumbers = computed(() => {
  const pages = new Set([1, totalPages.value, documentStore.currentPage, documentStore.currentPage - 1, documentStore.currentPage + 1])
  return Array.from(pages)
    .filter((page) => page >= 1 && page <= totalPages.value)
    .sort((a, b) => a - b)
})

const activeFolderLabel = computed(() => {
  if (!folderStore.currentFolderId) return '全部文档'
  return folderStore.currentFolder?.name || currentFolderName.value
})

const selectedDocumentType = computed(() => selectedDocument.value ? formatDocumentTypeLabel(selectedDocument.value.file_type) : 'FILE')

onMounted(() => {
  documentStore.viewMode = 'list'
  documentStore.fetchDocuments(1, '', null, workbenchIncludeSubfolders(null), DOCUMENT_WORKBENCH_PAGE_SIZE)
  folderStore.fetchFolderTree()
  folderStore.fetchFolders()
  document.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
})

watch(() => folderStore.currentFolderId, () => {
  documentStore.currentFolderId = folderStore.currentFolderId
  selectedDocumentId.value = null
  documentStore.fetchDocuments(1, searchInput.value || undefined, folderStore.currentFolderId, workbenchIncludeSubfolders(folderStore.currentFolderId), DOCUMENT_WORKBENCH_PAGE_SIZE)
})

watch(() => documentStore.documents, (docs) => {
  if (!docs.length) {
    selectedDocumentId.value = null
    return
  }
  if (!selectedDocumentId.value || !docs.some((doc) => doc.id === selectedDocumentId.value)) {
    selectedDocumentId.value = docs[0].id
  }
})

function navigateToFolder(folderId: string | null) {
  folderStore.setCurrentFolder(folderId)
}

function openCreateFolder(parentId: string | null = folderStore.currentFolderId) {
  createFolderParentId.value = parentId
  showCreateFolderDialog.value = true
}

async function handleFolderCreated() {
  await folderStore.fetchFolderTree()
  await folderStore.fetchFolders()
}

function handleSearch() {
  documentStore.fetchDocuments(1, searchInput.value || undefined, folderStore.currentFolderId, workbenchIncludeSubfolders(folderStore.currentFolderId), DOCUMENT_WORKBENCH_PAGE_SIZE)
}

function clearSearch() {
  searchInput.value = ''
  documentStore.fetchDocuments(1, undefined, folderStore.currentFolderId, workbenchIncludeSubfolders(folderStore.currentFolderId), DOCUMENT_WORKBENCH_PAGE_SIZE)
}

async function changePage(page: number) {
  if (page < 1 || page > totalPages.value) return
  await documentStore.fetchDocuments(page, searchInput.value || undefined, folderStore.currentFolderId, workbenchIncludeSubfolders(folderStore.currentFolderId), DOCUMENT_WORKBENCH_PAGE_SIZE)
}

async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (!files.length) return

  uploading.value = true
  uploadError.value = ''
  uploadProgress.value = { current: 0, total: files.length, currentFile: '' }

  try {
    await documentStore.uploadDocuments(files, folderStore.currentFolderId, undefined, (current, fileName) => {
      uploadProgress.value = { current, total: files.length, currentFile: fileName }
    })
  } catch (error: any) {
    uploadError.value = error.response?.data?.detail || 'Upload failed'
  } finally {
    uploading.value = false
    input.value = ''
    uploadProgress.value = { current: 0, total: 0, currentFile: '' }
  }
}

async function openPreview(id: string) {
  const doc = documentStore.documents.find((item) => item.id === id)
  if (!doc || !isCompletedStatus(doc.status)) return
  previewDocId.value = doc.id
  previewDocName.value = doc.original_name
  previewDocType.value = doc.file_type || ''
  showPreview.value = true
  previewLoading.value = true
  previewData.value = null
  activePreviewTab.value = 'toc'

  try {
    const { data } = await documentApi.preview(doc.id)
    previewData.value = data
    showPdfPreview.value = doc.file_type?.toLowerCase() === '.pdf'
    showUniversalPreview.value = !showPdfPreview.value
  } catch (error) {
    console.error('Preview failed:', error)
    uploadError.value = 'Preview failed'
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  showPreview.value = false
  previewDocId.value = ''
  previewDocName.value = ''
  previewData.value = null
  showPdfPreview.value = false
  showUniversalPreview.value = false
}

function jumpToPage(pageNum: number) {
  if (!pdfViewerRef.value || !pageNum || pageNum < 1) return
  let attempts = 0
  const tryScroll = () => {
    const el = document.getElementById(`pdf-page-${pageNum}`)
    if (el) {
      pdfViewerRef.value?.scrollToPage(pageNum)
    } else if (attempts < 20) {
      attempts += 1
      setTimeout(tryScroll, 200)
    }
  }
  tryScroll()
}

function handleReindex(id: string) {
  documentStore.reindexDocument(id)
}

function confirmDelete(id: string) {
  deleteConfirmId.value = id
}

async function doDelete() {
  if (!deleteConfirmId.value) return
  await documentStore.deleteDocument(deleteConfirmId.value)
  deleteConfirmId.value = null
}

function handleMove(doc: Document) {
  moveDocId.value = doc.id
  showMoveModal.value = true
}

async function doMove(targetFolderId: string | null) {
  if (!moveDocId.value) return
  await documentStore.moveDocument(moveDocId.value, targetFolderId)
  moveDocId.value = null
  showMoveModal.value = false
}

function handleRename(doc: Document) {
  renamingDoc.value = doc
  renameValue.value = doc.original_name
}

async function doRename() {
  if (!renamingDoc.value || !renameValue.value.trim()) return
  await documentStore.renameDocument(renamingDoc.value.id, renameValue.value.trim())
  renamingDoc.value = null
  renameValue.value = ''
}

async function showProcessingSteps(id: string) {
  const doc = documentStore.documents.find((item) => item.id === id)
  stepsDocName.value = doc?.original_name || ''
  showStepsDialog.value = true
  stepsLoading.value = true
  stepsData.value = []
  try {
    stepsData.value = await documentStore.fetchDocumentSteps(id)
  } finally {
    stepsLoading.value = false
  }
}

function handleBatchMove() {
  if (documentStore.selectedIds.size === 0) return
  moveDocId.value = null
  showMoveModal.value = true
}

async function handleBatchDelete() {
  if (!window.confirm(`Delete ${documentStore.selectedIds.size} selected documents?`)) return
  const ids = Array.from(documentStore.selectedIds)
  await documentStore.batchDelete(ids)
  documentStore.clearSelection()
}

async function handleBatchReindex() {
  await documentStore.batchReindex(Array.from(documentStore.selectedIds))
}

async function handleBatchDownload() {
  await documentStore.batchDownload(Array.from(documentStore.selectedIds))
}

async function doBatchMove(targetFolderId: string | null) {
  await documentStore.batchMove(Array.from(documentStore.selectedIds), targetFolderId)
  showMoveModal.value = false
  documentStore.clearSelection()
}

function handleDocumentContextMenu(e: MouseEvent, doc: Document) {
  e.preventDefault()
  contextMenuDoc.value = doc
  nextTick(() => contextMenuRef.value?.open(e))
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (showPreview.value) closePreview()
  if (showStepsDialog.value) showStepsDialog.value = false
  if (showMoveModal.value) showMoveModal.value = false
  if (deleteConfirmId.value) deleteConfirmId.value = null
  if (documentStore.isBatchMode) documentStore.toggleBatchMode()
}

function selectDocument(doc: Document) {
  selectedDocumentId.value = doc.id
}

function rowSummary(doc: Document): string {
  return doc.description || doc.error_message || 'No summary available yet.'
}

function qualityLabel(report?: QualityReport | null): string {
  return qualityDisplay(report as Record<string, unknown> | null | undefined).label
}

function qualityTone(report?: QualityReport | null): string {
  if (!report?.status) return 'border-border bg-muted/40 text-muted-foreground'
  if (report.status === 'completed') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (report.status === 'needs_review') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (String(report.status).startsWith('failed')) return 'border-red-200 bg-red-50 text-red-700'
  return 'border-border bg-muted/40 text-muted-foreground'
}

function documentIcon(fileType?: string) {
  const ext = (fileType || '').toLowerCase()
  if (ext === '.docx' || ext === '.doc') return FileType
  if (['.xlsx', '.xls', '.csv', '.tsv'].includes(ext)) return FileSpreadsheet
  if (['.txt', '.md', '.markdown', '.json'].includes(ext)) return FileCode
  if (ext === '.pptx' || ext === '.ppt') return Presentation
  if (ext === '.pdf') return FileText
  return File
}

function fileKindClass(fileType?: string) {
  const ext = (fileType || '').toLowerCase()
  if (ext === '.pdf') return 'pdf'
  if (ext === '.docx' || ext === '.doc') return 'word'
  if (['.xlsx', '.xls', '.csv', '.tsv'].includes(ext)) return 'sheet'
  if (ext === '.pptx' || ext === '.ppt') return 'slide'
  if (['.txt', '.md', '.markdown', '.json'].includes(ext)) return 'text'
  return 'default'
}

function statusClass(status?: string) {
  if (isCompletedStatus(status)) return 'done'
  if (String(status || '').startsWith('failed')) return 'failed'
  return 'running'
}

function updatedBy(doc: Document) {
  return doc.folder_path?.split('/').filter(Boolean).slice(-1)[0] || 'admin'
}

function typeAndSize(doc: Document) {
  return `${metadataValue(doc.folder_path || activeFolderLabel.value)} / ${formatDocumentTypeLabel(doc.file_type)} / ${formatDocumentSize(doc.file_size)}`
}

function basicDetailRows(doc: Document) {
  const pageWordMetric = detailMetrics(doc).find((item) => item.label.includes('/'))
  return [
    ['上传人', '未提供'],
    ['上传时间', formatDocumentDate(doc.created_at)],
    ['更新时间', formatDocumentDate(doc.updated_at)],
    ['页数 / 字数', pageWordMetric?.value || '打开预览后统计'],
  ]
}

function previewStatsFor(doc: Document) {
  if (previewData.value?.id !== doc.id) return null
  const rawCoverage = previewData.value.stats?.summary_coverage
  return {
    tocNodes: previewData.value.stats?.node_count,
    textChars: previewData.value.stats?.text_chars,
    summaryCoverage: typeof rawCoverage === 'string'
      ? Number.parseFloat(rawCoverage) / 100
      : rawCoverage,
  }
}

function detailMetrics(doc: Document) {
  return documentDetailMetrics({
    doc: doc as unknown as Record<string, unknown>,
    previewStats: previewStatsFor(doc),
    qualityReport: doc.quality_report as Record<string, unknown> | null | undefined,
  })
}

function qualityItems(doc: Document) {
  return detailMetrics(doc)
    .filter((item) => !item.label.includes('/'))
    .map((item) => [item.label, item.value])
}

function detailQuality(doc: Document) {
  return qualityDisplay(doc.quality_report as Record<string, unknown> | null | undefined)
}

</script>

<template>
  <div class="documents-demo-page">
    <main class="workbench">
      <header class="topbar">
        <div class="topbar-title">
          <button class="icon-text" @click="router.push('/')">
            <ArrowLeft class="h-4 w-4" />
            <span>返回主界面</span>
          </button>
          <div>
            <p>DOCUMENTS</p>
            <h1>文档管理工作台</h1>
          </div>
        </div>

        <div class="topbar-actions">
          <label class="search-box">
            <Search class="h-4 w-4" />
            <input
              v-model="searchInput"
              placeholder="搜索文档、文件夹或标签"
              type="text"
              @keyup.enter="handleSearch"
            />
            <button v-if="searchInput" aria-label="清除搜索" @click.prevent="clearSearch">
              <X class="h-4 w-4" />
            </button>
          </label>
          <label class="primary-btn">
            <Upload class="h-4 w-4" />
            <span>上传文档</span>
            <input class="hidden-input" type="file" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv" multiple @change="handleUpload" />
          </label>
        </div>
      </header>

      <div v-if="uploadError" class="notice error">
        <AlertCircle class="h-4 w-4" />
        <span>{{ uploadError }}</span>
        <button aria-label="关闭" @click="uploadError = ''"><X class="h-4 w-4" /></button>
      </div>
      <div v-if="uploading" class="notice info">
        <Loader2 class="h-4 w-4 animate-spin" />
        <span v-if="uploadProgress.total > 1">正在上传 {{ uploadProgress.current }}/{{ uploadProgress.total }} {{ uploadProgress.currentFile }}</span>
        <span v-else>正在上传文档...</span>
      </div>

      <section class="documents-layout">
        <aside class="surface folder-pane">
          <div class="surface-head">
            <div>
              <p>文件夹</p>
              <h2>资料库</h2>
            </div>
            <button class="icon-btn" aria-label="新建文件夹" title="新建文件夹" @click="openCreateFolder(folderStore.currentFolderId)">
              <Plus class="h-4 w-4" />
            </button>
          </div>

          <div class="folder-list">
            <button :class="{ active: !folderStore.currentFolderId }" @click="navigateToFolder(null)">
              <FolderOpen class="h-4 w-4" />
              <span>全部文档</span>
              <em>{{ documentStore.total }}</em>
            </button>
            <button
              v-for="folder in folderStore.folders"
              :key="folder.id"
              :class="{ active: folderStore.currentFolderId === folder.id }"
              @click="navigateToFolder(folder.id)"
            >
              <Folder class="h-4 w-4" />
              <span>{{ folder.name }}</span>
              <em>--</em>
            </button>
          </div>
        </aside>

        <section class="surface doc-pane">
          <div class="surface-head doc-head">
            <div>
              <p>当前位置 / {{ activeFolderLabel }}</p>
              <h2>全部文档</h2>
            </div>
            <div class="doc-tools">
              <button class="tool-btn" @click="handleSearch">
                <SlidersHorizontal class="h-4 w-4" />
                <span>更新时间</span>
              </button>
              <button :class="['tool-btn', { active: documentStore.isBatchMode }]" @click="documentStore.toggleBatchMode()">
                <Square class="h-4 w-4" />
                <span>批量</span>
              </button>
              <div class="view-toggle">
                <button :class="{ active: documentStore.viewMode === 'list' }" aria-label="列表" @click="documentStore.viewMode = 'list'">
                  <List class="h-4 w-4" />
                </button>
                <button :class="{ active: documentStore.viewMode === 'grid' }" aria-label="网格" @click="documentStore.viewMode = 'grid'">
                  <Grid2X2 class="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>

          <div v-if="documentStore.isBatchMode" class="mode-strip batch-strip">
            <span>已选择 {{ documentStore.selectedIds.size }} 项</span>
            <button @click="documentStore.selectAll()">全选本页</button>
            <button @click="documentStore.deselectAll()">取消选择</button>
            <button @click="handleBatchDownload"><Download class="h-3.5 w-3.5" /> 下载</button>
            <button @click="handleBatchMove"><Move class="h-3.5 w-3.5" /> 移动</button>
            <button @click="handleBatchReindex"><RefreshCw class="h-3.5 w-3.5" /> 重新解析</button>
            <button @click="handleBatchDelete"><Trash2 class="h-3.5 w-3.5" /> 删除</button>
          </div>
          <div v-else class="mode-strip list-insight">
            <span>当前文件夹 {{ documentStore.documents.length }} 个文档</span>
            <em>最近更新 {{ recentUpdate }}</em>
            <em>{{ activeIndexingCount }} 个索引任务进行中</em>
          </div>

          <div class="doc-scroll">
            <div v-if="documentStore.loading" class="empty-state">
              <Loader2 class="h-5 w-5 animate-spin" />
              <span>正在加载文档...</span>
            </div>
            <div v-else-if="documentStore.documents.length === 0" class="empty-state">
              <FileText class="h-9 w-9" />
              <span>当前视图暂无文档</span>
            </div>
            <div v-else-if="documentStore.viewMode === 'list'" class="doc-list">
              <div class="doc-list-header">
                <span>文档</span>
                <span>摘要</span>
                <span>状态</span>
                <span>更新</span>
                <span>操作</span>
              </div>
              <button
                v-for="doc in documentStore.documents"
                :key="doc.id"
                :class="{ active: selectedDocument?.id === doc.id, batch: documentStore.isBatchMode }"
                @click="selectDocument(doc)"
                @contextmenu="(e) => handleDocumentContextMenu(e, doc)"
              >
                <div class="doc-file-cell">
                  <input
                    class="row-check"
                    type="checkbox"
                    :checked="documentStore.selectedIds.has(doc.id)"
                    :class="{ hidden: !documentStore.isBatchMode }"
                    @click.stop
                    @change="documentStore.toggleSelect(doc.id)"
                  />
                  <div :class="['doc-icon', fileKindClass(doc.file_type)]">
                    <component :is="documentIcon(doc.file_type)" class="h-4 w-4" />
                  </div>
                  <div>
                    <strong :title="doc.original_name">{{ doc.original_name }}</strong>
                    <span>{{ typeAndSize(doc) }}</span>
                  </div>
                </div>
                <p class="doc-summary-cell" :title="rowSummary(doc)">{{ rowSummary(doc) }}</p>
                <div class="doc-status-cell">
                  <span :class="['status', statusClass(doc.status)]">{{ localizedStatusLabel(doc.status) }}</span>
                  <em>{{ metadataValue(doc.page_count) }} 页</em>
                  <div v-if="isProcessingStatus(doc.status)" class="progress-track">
                    <i :style="{ width: `${documentProgress(doc.status)}%` }" />
                  </div>
                </div>
                <div class="doc-meta">
                  <span>{{ formatDocumentDate(doc.updated_at) }}</span>
                  <em>{{ updatedBy(doc) }}</em>
                </div>
                <div class="row-actions">
                  <button v-if="isCompletedStatus(doc.status)" title="打开预览" @click.stop="openPreview(doc.id)">
                    <Eye class="h-4 w-4" />
                  </button>
                  <button v-if="isProcessingStatus(doc.status)" title="处理步骤" @click.stop="showProcessingSteps(doc.id)">
                    <BarChart3 class="h-4 w-4" />
                  </button>
                  <button v-if="!isProcessingStatus(doc.status)" title="重新解析" @click.stop="handleReindex(doc.id)">
                    <RefreshCw class="h-4 w-4" />
                  </button>
                  <button title="移动" @click.stop="handleMove(doc)">
                    <FolderInput class="h-4 w-4" />
                  </button>
                  <button title="删除" @click.stop="confirmDelete(doc.id)">
                    <Trash2 class="h-4 w-4" />
                  </button>
                </div>
              </button>
            </div>
            <div v-else class="doc-grid">
              <button
                v-for="doc in documentStore.documents"
                :key="doc.id"
                :class="{ active: selectedDocument?.id === doc.id }"
                @click="selectDocument(doc)"
              >
                <div class="card-line">
                  <div :class="['doc-icon', fileKindClass(doc.file_type)]">
                    <component :is="documentIcon(doc.file_type)" class="h-4 w-4" />
                  </div>
                  <span :class="['status', statusClass(doc.status)]">{{ localizedStatusLabel(doc.status) }}</span>
                </div>
                <strong>{{ doc.original_name }}</strong>
                <p>{{ rowSummary(doc) }}</p>
              </button>
            </div>
          </div>

          <footer class="pagination">
            <div>
              <strong>第 {{ documentStore.currentPage }} 页</strong>
              <span>每页 {{ DOCUMENT_WORKBENCH_PAGE_SIZE }} 个 / 共 {{ documentStore.total }} 个文档 / {{ totalPages }} 页</span>
            </div>
            <div class="page-controls">
              <button :disabled="documentStore.currentPage === 1" @click="changePage(documentStore.currentPage - 1)">上一页</button>
              <button
                v-for="page in pageNumbers"
                :key="page"
                :class="{ active: documentStore.currentPage === page }"
                @click="changePage(page)"
              >
                {{ page }}
              </button>
              <button :disabled="documentStore.currentPage === totalPages" @click="changePage(documentStore.currentPage + 1)">下一页</button>
            </div>
          </footer>
        </section>

        <aside class="surface detail-pane">
          <div class="surface-head">
            <div>
              <p>文档详情</p>
            </div>
          </div>

          <div v-if="!selectedDocument" class="empty-state detail-empty">
            <span>选择一个文档查看详情</span>
          </div>

          <template v-else>
            <div class="detail-identity">
              <div :class="['detail-icon', fileKindClass(selectedDocument.file_type)]">
                <component :is="documentIcon(selectedDocument.file_type)" class="h-5 w-5" />
              </div>
              <div>
                <h3 :title="selectedDocument.original_name">{{ selectedDocument.original_name }}</h3>
                <span>{{ activeFolderLabel }} / {{ selectedDocumentType }} / {{ formatDocumentSize(selectedDocument.file_size) }}</span>
              </div>
            </div>

            <div class="detail-section basic-detail">
              <div class="section-title">
                <FileText class="h-4 w-4" />
                <h4>基础属性</h4>
              </div>
              <div class="property-list">
                <div v-for="[label, value] in basicDetailRows(selectedDocument)" :key="label">
                  <span>{{ label }}</span>
                  <strong>{{ value }}</strong>
                </div>
              </div>
            </div>

            <div class="detail-section index-detail">
              <div class="section-title">
                <RefreshCw class="h-4 w-4" />
                <h4>索引状态</h4>
              </div>
              <div class="status-panel">
                <div class="status-line">
                  <span :class="['status', statusClass(selectedDocument.status)]">{{ localizedStatusLabel(selectedDocument.status) }}</span>
                  <em>{{ metadataValue(selectedDocument.parse_execution_mode || selectedDocument.parse_requested_mode, '智能') }} / {{ formatDocumentDuration(selectedDocument.processing_duration) }} / 最近 {{ formatDocumentDate(selectedDocument.last_reindex_at || selectedDocument.updated_at) }}</em>
                </div>
                <div class="progress-track"><i :style="{ width: `${documentProgress(selectedDocument.status)}%` }" /></div>
              </div>
              <div class="quality-grid">
                <div v-for="[label, value] in qualityItems(selectedDocument)" :key="label">
                  <span>{{ label }}</span>
                  <strong>{{ value }}</strong>
                </div>
              </div>
              <p :class="['quality-note', detailQuality(selectedDocument).tone]">
                {{ detailQuality(selectedDocument).label }}，{{ detailQuality(selectedDocument).message }}
              </p>
            </div>

            <div class="detail-section summary-detail">
              <div class="section-title">
                <BookOpen class="h-4 w-4" />
                <h4>全文摘要</h4>
              </div>
              <p class="summary-scroll">{{ selectedDocument.description || '该文档暂无全文摘要。实际接入时，如果后端返回的全文摘要更长，这一区域内部滚动，不会挤压页面。' }}</p>
            </div>

            <div class="detail-actions">
              <button class="preview-btn" :disabled="!isCompletedStatus(selectedDocument.status)" @click="openPreview(selectedDocument.id)">
                <Eye class="h-4 w-4" />
                <span>打开预览</span>
              </button>
              <button :disabled="isProcessingStatus(selectedDocument.status)" @click="handleReindex(selectedDocument.id)">
                <RefreshCw class="h-4 w-4" />
                <span>重新解析</span>
              </button>
            </div>
          </template>
        </aside>
      </section>
    </main>

    <div v-if="showPreview" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="closePreview">
      <div class="flex h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-background shadow-2xl">
        <div class="flex items-center justify-between border-b px-4 py-3">
          <div class="flex min-w-0 items-center gap-3">
            <FileText class="h-5 w-5 shrink-0 text-muted-foreground" />
            <h3 class="truncate font-medium">{{ previewDocName }}</h3>
            <span v-if="previewData" class="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {{ metadataValue(previewData.page_count) }} pages
            </span>
          </div>
          <button class="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" title="Close" @click="closePreview">
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="flex min-h-0 flex-1">
          <div class="hidden w-72 flex-col overflow-hidden border-r bg-muted/30 lg:flex">
            <div class="flex border-b">
              <button
                :class="['flex-1 py-2.5 text-sm font-medium', activePreviewTab === 'toc' ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground hover:text-foreground']"
                @click="activePreviewTab = 'toc'"
              >
                <BookOpen class="mr-1.5 inline h-4 w-4" />
                TOC
              </button>
              <button
                :class="['flex-1 py-2.5 text-sm font-medium', activePreviewTab === 'meta' ? 'border-b-2 border-primary text-primary' : 'text-muted-foreground hover:text-foreground']"
                @click="activePreviewTab = 'meta'"
              >
                <BarChart3 class="mr-1.5 inline h-4 w-4" />
                Meta
              </button>
            </div>

            <div v-if="activePreviewTab === 'toc'" class="min-h-0 flex-1 overflow-y-auto p-3">
              <div v-if="previewLoading" class="flex justify-center py-8">
                <Loader2 class="h-5 w-5 animate-spin text-primary" />
              </div>
              <TocTree v-else-if="previewData?.toc?.length" :nodes="previewData.toc" :default-expanded="true" @jump="jumpToPage" />
              <div v-else class="py-8 text-center text-sm text-muted-foreground">No TOC available</div>
            </div>

            <div v-else class="min-h-0 flex-1 overflow-y-auto p-3 text-sm">
              <div v-if="previewLoading" class="flex justify-center py-8">
                <Loader2 class="h-5 w-5 animate-spin text-primary" />
              </div>
              <template v-else-if="previewData">
                <dl class="space-y-2">
                  <div class="flex justify-between gap-3"><dt class="text-muted-foreground">Format</dt><dd>{{ previewData.file_type }}</dd></div>
                  <div class="flex justify-between gap-3"><dt class="text-muted-foreground">Size</dt><dd>{{ formatDocumentSize(previewData.file_size) }}</dd></div>
                  <div class="flex justify-between gap-3"><dt class="text-muted-foreground">Duration</dt><dd>{{ formatDocumentDuration(previewData.processing_duration) }}</dd></div>
                  <div class="flex justify-between gap-3"><dt class="text-muted-foreground">Nodes</dt><dd>{{ metadataValue(previewData.stats?.node_count) }}</dd></div>
                  <div class="flex justify-between gap-3"><dt class="text-muted-foreground">Coverage</dt><dd>{{ metadataValue(previewData.stats?.summary_coverage) }}</dd></div>
                  <div class="flex justify-between gap-3"><dt class="text-muted-foreground">Text chars</dt><dd>{{ metadataValue(previewData.stats?.text_chars) }}</dd></div>
                </dl>
                <div :class="['mt-4 rounded-md border p-3 text-xs', qualityTone(previewData.quality_report)]">
                  <div class="flex justify-between gap-2">
                    <span class="font-medium">Quality</span>
                    <span>{{ qualityLabel(previewData.quality_report) }}</span>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <div class="min-w-0 flex-1 overflow-hidden bg-muted/20">
            <div v-if="previewLoading" class="flex h-full items-center justify-center">
              <Loader2 class="h-8 w-8 animate-spin text-primary" />
            </div>
            <PdfReferenceViewer
              v-else-if="showPdfPreview"
              ref="pdfViewerRef"
              :file-url="`/api/documents/${previewDocId}/file`"
              :file-name="previewDocName"
              :visible="true"
              :embedded="true"
              class="h-full"
            />
            <UniversalPreview
              v-else-if="showUniversalPreview"
              :doc-id="previewDocId"
              :doc-name="previewDocName"
              :file-type="previewDocType"
              :raw-only="true"
              class="h-full"
            />
          </div>
        </div>
      </div>
    </div>

    <ProcessingStepsDialog
      :visible="showStepsDialog"
      :document-name="stepsDocName"
      :steps="stepsData"
      :is-loading="stepsLoading"
      @close="showStepsDialog = false"
    />

    <CreateFolderDialog
      v-model:open="showCreateFolderDialog"
      :parent-id="createFolderParentId"
      @created="handleFolderCreated"
    />

    <div v-if="showMoveModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="showMoveModal = false">
      <div class="w-full max-w-sm rounded-lg bg-background p-4 shadow-2xl">
        <h3 class="mb-3 font-semibold">Move to folder</h3>
        <div class="max-h-64 space-y-1 overflow-y-auto">
          <button class="w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted" @click="moveDocId ? doMove(null) : doBatchMove(null)">
            Root
          </button>
          <button v-for="folder in folderStore.folders" :key="folder.id" class="w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted" @click="moveDocId ? doMove(folder.id) : doBatchMove(folder.id)">
            {{ folder.name }}
          </button>
        </div>
        <div class="mt-4 flex justify-end">
          <button class="rounded-md border px-4 py-2 text-sm hover:bg-muted" @click="showMoveModal = false">Cancel</button>
        </div>
      </div>
    </div>

    <div v-if="deleteConfirmId" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="deleteConfirmId = null">
      <div class="w-full max-w-sm rounded-lg bg-background p-4 shadow-2xl">
        <h3 class="mb-2 font-semibold">Confirm delete</h3>
        <p class="mb-4 text-sm text-muted-foreground">This cannot be undone.</p>
        <div class="flex justify-end gap-2">
          <button class="rounded-md border px-4 py-2 text-sm hover:bg-muted" @click="deleteConfirmId = null">Cancel</button>
          <button class="rounded-md bg-destructive px-4 py-2 text-sm text-destructive-foreground hover:bg-destructive/90" @click="doDelete">Delete</button>
        </div>
      </div>
    </div>

    <div v-if="renamingDoc" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" @click.self="renamingDoc = null">
      <div class="w-full max-w-sm rounded-lg bg-background p-4 shadow-2xl">
        <h3 class="mb-3 font-semibold">Rename</h3>
        <input v-model="renameValue" class="mb-4 w-full rounded-md border bg-background px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/20" type="text" @keyup.enter="doRename" />
        <div class="flex justify-end gap-2">
          <button class="rounded-md border px-4 py-2 text-sm hover:bg-muted" @click="renamingDoc = null">Cancel</button>
          <button class="rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90" @click="doRename">Save</button>
        </div>
      </div>
    </div>

    <DocumentContextMenu
      v-if="contextMenuDoc"
      ref="contextMenuRef"
      :document="contextMenuDoc"
      @preview="openPreview"
      @reindex="handleReindex"
      @delete="confirmDelete"
      @move="handleMove"
      @rename="handleRename"
    />

  </div>
</template>

<style scoped>
.documents-demo-page {
  --ink: #101828;
  --muted: #667085;
  --line: rgba(16, 24, 40, 0.1);
  --panel: rgba(255, 255, 255, 0.88);
  --blue: #2563eb;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.12), transparent 28rem),
    linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
  color: var(--ink);
}

.workbench {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 8px 16px 18px;
}

.topbar,
.surface {
  border: 1px solid var(--line);
  background: var(--panel);
  box-shadow: 0 16px 44px rgba(16, 24, 40, 0.08);
  backdrop-filter: blur(14px);
}

.topbar {
  min-height: 86px;
  padding: 16px 18px;
  border-radius: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.topbar-title,
.topbar-actions,
.icon-text,
.primary-btn,
.tool-btn,
.preview-btn,
.folder-list button,
.settings-nav button {
  display: inline-flex;
  align-items: center;
}

.topbar-title {
  gap: 22px;
  min-width: 0;
}

.topbar-title p,
.surface-head p {
  color: var(--muted);
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.topbar-title h1 {
  margin-top: 2px;
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 0;
}

button,
.primary-btn {
  border: 0;
  cursor: pointer;
  font: inherit;
}

button:disabled {
  cursor: not-allowed;
}

.icon-text,
.primary-btn,
.tool-btn,
.icon-btn,
.mode-strip button,
.preview-btn {
  border: 1px solid var(--line);
  background: #fff;
  color: #344054;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}

.icon-text {
  gap: 9px;
  padding: 11px 15px;
  border-radius: 12px;
  font-weight: 650;
}

.topbar-actions {
  gap: 12px;
  flex: 1;
  justify-content: flex-end;
  min-width: 300px;
}

.search-box {
  width: min(430px, 42vw);
  height: 48px;
  padding: 0 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.86);
  color: #98a2b3;
}

.search-box input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ink);
  font-size: 14px;
}

.search-box button {
  color: #98a2b3;
  background: transparent;
}

.primary-btn {
  height: 48px;
  gap: 9px;
  padding: 0 16px;
  border-radius: 14px;
  font-weight: 750;
}

.hidden-input {
  display: none;
}

.notice {
  margin-top: -6px;
  padding: 9px 12px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.notice span {
  flex: 1;
  min-width: 0;
}

.notice.error {
  border: 1px solid #fecaca;
  background: #fff1f2;
  color: #b42318;
}

.notice.info {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}

.documents-layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 300px;
  gap: 12px;
}

.surface {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-radius: 16px;
}

.surface-head {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(16, 24, 40, 0.06);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.surface-head h2 {
  margin-top: 2px;
  font-size: 15px;
  font-weight: 750;
}

.icon-btn {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: grid;
  place-items: center;
}

.folder-list {
  padding: 8px;
  display: grid;
  gap: 4px;
  overflow: auto;
}

.folder-list button {
  min-width: 0;
  gap: 9px;
  padding: 8px 9px;
  border-radius: 11px;
  color: #344054;
  background: transparent;
  text-align: left;
}

.folder-list button.active,
.folder-list button:hover {
  background: #e9effc;
}

.folder-list span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.folder-list em {
  color: #98a2b3;
  font-size: 12px;
  font-style: normal;
}

.doc-pane {
  display: flex;
  flex-direction: column;
}

.doc-head {
  align-items: flex-start;
}

.doc-tools {
  display: flex;
  gap: 8px;
}

.tool-btn {
  height: 38px;
  gap: 8px;
  padding: 0 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 650;
}

.tool-btn.active {
  color: #1d4ed8;
  border-color: rgba(37, 99, 235, 0.24);
  background: rgba(37, 99, 235, 0.08);
}

.view-toggle {
  padding: 4px;
  border: 1px solid var(--line);
  border-radius: 13px;
  display: flex;
  background: rgba(248, 250, 252, 0.8);
}

.view-toggle button {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--muted);
  background: transparent;
}

.view-toggle button.active {
  color: var(--ink);
  background: #fff;
  box-shadow: 0 6px 16px rgba(16, 24, 40, 0.08);
}

.mode-strip {
  flex-shrink: 0;
  margin: 6px 8px 0;
  padding: 5px 7px;
  border: 1px solid rgba(16, 24, 40, 0.08);
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(248, 250, 252, 0.78);
  color: #64748b;
  font-size: 12px;
}

.mode-strip span {
  margin-right: auto;
  color: #344054;
  font-weight: 700;
}

.mode-strip button {
  padding: 5px 8px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #1d4ed8;
  background: #fff;
}

.list-insight em {
  color: #94a3b8;
  font-style: normal;
}

.doc-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.empty-state {
  height: 220px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: 10px;
  color: var(--muted);
  font-size: 13px;
}

.doc-list {
  padding: 8px;
  display: grid;
  gap: 6px;
}

.doc-list-header,
.doc-list > button {
  display: grid;
  grid-template-columns: minmax(260px, 1.05fr) minmax(230px, 1.15fr) 104px 88px 82px;
  gap: 12px;
}

.doc-list-header {
  padding: 0 10px 4px;
  color: #98a2b3;
  font-size: 11px;
  font-weight: 750;
}

.doc-list > button,
.doc-grid > button {
  border: 1px solid transparent;
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.86);
  text-align: left;
  transition: 160ms ease;
}

.doc-list > button {
  min-width: 0;
  padding: 10px 12px;
  align-items: center;
}

.doc-list > button.active,
.doc-list > button:hover,
.doc-grid > button.active,
.doc-grid > button:hover {
  border-color: rgba(37, 99, 235, 0.18);
  background: #fff;
  box-shadow: 0 8px 24px rgba(16, 24, 40, 0.06);
}

.doc-file-cell {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.row-check {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  accent-color: var(--blue);
}

.row-check.hidden {
  opacity: 0;
  pointer-events: none;
}

.doc-icon,
.detail-icon {
  width: 34px;
  height: 34px;
  border: 1px solid transparent;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.doc-icon.pdf,
.detail-icon.pdf {
  color: #ef4444;
  background: #fef2f2;
  border-color: #fecaca;
}

.doc-icon.word,
.detail-icon.word {
  color: #3b82f6;
  background: #eff6ff;
  border-color: #bfdbfe;
}

.doc-icon.sheet,
.detail-icon.sheet {
  color: #22c55e;
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.doc-icon.slide,
.detail-icon.slide {
  color: #f97316;
  background: #fff7ed;
  border-color: #fed7aa;
}

.doc-icon.text,
.detail-icon.text {
  color: #6b7280;
  background: #f9fafb;
  border-color: #e5e7eb;
}

.doc-icon.default,
.detail-icon.default {
  color: #64748b;
  background: #f1f5f9;
  border-color: #e2e8f0;
}

.doc-file-cell > div:last-child {
  min-width: 0;
}

.doc-file-cell strong,
.doc-file-cell span,
.doc-meta span,
.doc-meta em {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-file-cell strong {
  display: block;
  font-size: 13px;
  line-height: 1.3;
}

.doc-file-cell span {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: 11px;
}

.doc-summary-cell,
.doc-grid p,
.summary-scroll {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.45;
}

.doc-summary-cell {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.status {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  border-radius: 999px;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 750;
}

.status.done {
  color: #067647;
  background: #dcfae6;
}

.status.running {
  color: #b54708;
  background: #fef0c7;
}

.status.failed {
  color: #b42318;
  background: #fee4e2;
}

.doc-status-cell {
  display: grid;
  gap: 4px;
  justify-items: start;
}

.doc-status-cell em {
  color: var(--muted);
  font-size: 12px;
}

.doc-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  color: var(--muted);
  font-size: 12px;
}

.doc-status-cell em,
.doc-meta em {
  color: #98a2b3;
  font-size: 11px;
  font-style: normal;
}

.progress-track {
  width: 100%;
  height: 5px;
  border-radius: 999px;
  overflow: hidden;
  background: #e8eef7;
}

.progress-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #3b82f6;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 3px;
  opacity: 0;
  transition: opacity 140ms ease;
}

.doc-list > button:hover .row-actions,
.doc-list > button.active .row-actions {
  opacity: 1;
}

.row-actions button {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: grid;
  place-items: center;
  color: #64748b;
  background: transparent;
}

.row-actions button:hover {
  color: #111827;
  background: rgba(15, 23, 42, 0.06);
}

.doc-grid {
  padding: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.doc-grid > button {
  padding: 14px;
}

.card-line {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.doc-grid strong {
  font-size: 14px;
}

.pagination {
  flex-shrink: 0;
  padding: 7px 10px;
  border-top: 1px solid rgba(16, 24, 40, 0.07);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: rgba(255, 255, 255, 0.68);
}

.pagination > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}

.pagination strong {
  color: #344054;
}

.pagination span {
  color: var(--muted);
}

.page-controls {
  display: flex;
  align-items: center;
  gap: 5px;
}

.page-controls button {
  min-width: 32px;
  height: 30px;
  padding: 0 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: #344054;
  font-size: 12px;
}

.page-controls button.active {
  border-color: transparent;
  background: var(--blue);
  color: #fff;
}

.page-controls button:disabled {
  opacity: 0.45;
}

.detail-pane {
  padding-bottom: 0;
  display: flex;
  flex-direction: column;
}

.detail-empty {
  height: auto;
  flex: 1;
}

.detail-identity,
.detail-section,
.detail-actions {
  margin: 8px 10px;
}

.detail-identity {
  margin-top: 10px;
  margin-bottom: 6px;
  display: flex;
  flex-shrink: 0;
  gap: 12px;
}

.detail-identity h3 {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  font-size: 14px;
  font-weight: 750;
  line-height: 1.35;
}

.detail-identity span {
  display: block;
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
}

.detail-section {
  flex-shrink: 0;
  padding: 8px 9px;
  border: 1px solid rgba(16, 24, 40, 0.08);
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.78);
}

.section-title {
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: #344054;
}

.section-title h4 {
  font-size: 12px;
  font-weight: 750;
}

.property-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.property-list div,
.quality-grid div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.property-list span,
.quality-grid span,
.status-panel p {
  color: var(--muted);
  font-size: 10px;
}

.property-list strong,
.quality-grid strong {
  min-width: 0;
  color: #344054;
  font-size: 12px;
  font-weight: 650;
  word-break: break-word;
}

.status-panel {
  display: grid;
  gap: 4px;
  margin-bottom: 6px;
}

.status-line {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-panel em {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  font-size: 11px;
  font-style: normal;
}

.quality-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
}

.quality-grid div {
  padding: 6px 5px;
  border-radius: 8px;
  background: #fff;
}

.quality-note {
  margin-top: 5px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  padding: 6px 7px;
  font-size: 11px;
  line-height: 1.35;
}

.quality-note.ok {
  color: #067647;
  background: #ecfdf3;
}

.quality-note.warning {
  color: #b54708;
  background: #fffaeb;
}

.quality-note.error {
  color: #b42318;
  background: #fff1f3;
}

.quality-note.muted {
  color: #667085;
  background: #f8fafc;
}

.summary-detail {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.summary-scroll {
  flex: 1;
  min-height: 92px;
  overflow-y: auto;
}

.detail-actions {
  margin-top: auto;
  margin-bottom: 10px;
  flex-shrink: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.detail-actions button {
  min-width: 0;
  height: 34px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #fff;
  color: #344054;
  font-size: 13px;
  font-weight: 650;
}

.detail-actions button:disabled {
  opacity: 0.48;
}

.detail-actions span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1280px) {
  .documents-layout {
    grid-template-columns: 230px minmax(0, 1fr);
  }

  .detail-pane {
    grid-column: 1 / -1;
    min-height: 360px;
  }
}

@media (max-width: 980px) {
  .documents-layout,
  .doc-grid {
    grid-template-columns: 1fr;
  }

  .topbar,
  .topbar-title,
  .topbar-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .search-box {
    width: 100%;
  }
}

@media (max-width: 680px) {
  .workbench {
    padding: 12px;
  }

  .doc-list-header {
    display: none;
  }

  .doc-list > button {
    grid-template-columns: 1fr;
  }

  .mode-strip,
  .pagination {
    flex-wrap: wrap;
  }
}
</style>
