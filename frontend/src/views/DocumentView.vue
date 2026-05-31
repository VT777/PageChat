<script setup lang="ts">
import { ref, onMounted, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useDocumentStore } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'
import { documentApi } from '@/api'
import type { ProcessingStep } from '@/api'
import {
  Upload,
  FileText,
  Trash2,
  Loader2,
  RefreshCw,
  Folder,
  AlertCircle,
  FolderOpen,
  ChevronRight,
  ArrowLeft,
  Move,
  X,
  BookOpen,
  BarChart3,
  Search,
  Download,
  Square,
  CheckSquare2,
} from 'lucide-vue-next'
import type { Document } from '@/stores/document'
import PdfReferenceViewer from '@/components/PdfReferenceViewer.vue'
import UniversalPreview from '@/components/preview/UniversalPreview.vue'
import FolderTree from '@/components/folder/FolderTree.vue'
import ViewToggle from '@/components/document/ViewToggle.vue'
import DocumentCard from '@/components/document/DocumentCard.vue'
import DocumentListItem from '@/components/document/DocumentListItem.vue'
import ProcessingStepsDialog from '@/components/document/ProcessingStepsDialog.vue'
import TocTree from '@/components/document/TocTree.vue'
import DocumentContextMenu from '@/components/document/DocumentContextMenu.vue'

const router = useRouter()
const documentStore = useDocumentStore()
const folderStore = useFolderStore()

const uploading = ref(false)
const uploadError = ref('')
const uploadProgress = ref({ current: 0, total: 0, currentFile: '' })
const deleteConfirmId = ref<string | null>(null)
const searchInput = ref('')

// View state
const viewMode = computed({
  get: () => documentStore.viewMode,
  set: (val) => { documentStore.viewMode = val }
})

// Preview state
const showPreview = ref(false)
const previewDocId = ref('')
const previewDocName = ref('')
const previewDocType = ref('')
const showPdfPreview = ref(false)
const showUniversalPreview = ref(false)

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
  created_at: string
  updated_at: string
  toc: TocItem[]
  index_meta: {
    route_decision?: any
    pre_analysis?: any
    toc_quality?: any
    visual_page_summaries_count: number
  }
  stats: {
    node_count: number
    text_chars: number
    has_summaries: number
    summary_coverage: string
  }
}

const previewData = ref<PreviewData | null>(null)
const previewLoading = ref(false)
const pdfViewerRef = ref<InstanceType<typeof PdfReferenceViewer> | null>(null)
const activeTab = ref<'toc' | 'meta'>('toc')

// Move modal
const showMoveModal = ref(false)
const moveDocId = ref<string | null>(null)

// Rename
const renamingDoc = ref<Document | null>(null)
const renameValue = ref('')

// Processing steps dialog
const showStepsDialog = ref(false)
const stepsDocName = ref('')
const stepsData = ref<ProcessingStep[]>([])
const stepsLoading = ref(false)

// Document context menu
const contextMenuDoc = ref<Document | null>(null)
const contextMenuRef = ref<InstanceType<typeof DocumentContextMenu> | null>(null)

function handleDocumentContextMenu(e: MouseEvent, doc: Document) {
  e.preventDefault()
  contextMenuDoc.value = doc
  nextTick(() => {
    contextMenuRef.value?.open(e)
  })
}

onMounted(() => {
  documentStore.fetchDocuments(1, '', null)
  folderStore.fetchFolderTree()
})

watch(() => folderStore.currentFolderId, () => {
  documentStore.currentFolderId = folderStore.currentFolderId
  documentStore.fetchDocuments(1, searchInput.value || undefined, folderStore.currentFolderId)
})

// Breadcrumb navigation
function navigateToFolder(folderId: string | null) {
  folderStore.setCurrentFolder(folderId)
}

// Search
function handleSearch() {
  documentStore.fetchDocuments(1, searchInput.value || undefined, folderStore.currentFolderId)
}

function clearSearch() {
  searchInput.value = ''
  documentStore.fetchDocuments(1, undefined, folderStore.currentFolderId)
}

// Upload (batch)
async function handleUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length === 0) return

  uploading.value = true
  uploadError.value = ''
  uploadProgress.value = { current: 0, total: files.length, currentFile: '' }

  try {
    await documentStore.uploadDocuments(files, folderStore.currentFolderId, undefined, (current: number, fileName: string) => {
      uploadProgress.value = { current, total: files.length, currentFile: fileName }
    })
  } catch (error: any) {
    uploadError.value = error.response?.data?.detail || '上传失败'
  } finally {
    uploading.value = false
    input.value = ''
    uploadProgress.value = { current: 0, total: 0, currentFile: '' }
  }
}

// Preview
async function openPreview(id: string) {
  const doc = documentStore.documents.find(d => d.id === id)
  if (!doc || !doc.status.startsWith('completed')) return
  previewDocId.value = doc.id
  previewDocName.value = doc.original_name
  previewDocType.value = doc.file_type || ''
  showPreview.value = true
  previewLoading.value = true
  previewData.value = null

  try {
    const { data } = await documentApi.preview(doc.id)
    previewData.value = data

    if (doc.file_type?.toLowerCase() === '.pdf') {
      showPdfPreview.value = true
      showUniversalPreview.value = false
    } else {
      showPdfPreview.value = false
      showUniversalPreview.value = true
    }
  } catch (error) {
    console.error('Preview failed:', error)
    uploadError.value = '预览加载失败'
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

// TOC
function jumpToPage(pageNum: number) {
  if (!pdfViewerRef.value || !pageNum || pageNum < 1) return
  // Retry until the page element is rendered, then scroll
  let attempts = 0
  const tryScroll = () => {
    const el = document.getElementById(`pdf-page-${pageNum}`)
    if (el) {
      pdfViewerRef.value!.scrollToPage(pageNum)
    } else if (attempts < 20) {
      attempts++
      setTimeout(tryScroll, 200)
    }
  }
  tryScroll()
}

// Document actions
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

// Processing steps
async function showProcessingSteps(id: string) {
  const doc = documentStore.documents.find(d => d.id === id)
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

// Batch actions
function handleBatchMove() {
  if (documentStore.selectedIds.size === 0) return
  moveDocId.value = null // batch mode
  showMoveModal.value = true
}

async function handleBatchDelete() {
  if (!confirm(`确定要删除选中的 ${documentStore.selectedIds.size} 个文档吗？`)) return
  const ids = Array.from(documentStore.selectedIds)
  await documentStore.batchDelete(ids)
  documentStore.clearSelection()
}

async function handleBatchReindex() {
  const ids = Array.from(documentStore.selectedIds)
  await documentStore.batchReindex(ids)
}

async function handleBatchDownload() {
  const ids = Array.from(documentStore.selectedIds)
  await documentStore.batchDownload(ids)
}

// Move modal for batch
async function doBatchMove(targetFolderId: string | null) {
  const ids = Array.from(documentStore.selectedIds)
  await documentStore.batchMove(ids, targetFolderId)
  showMoveModal.value = false
  documentStore.clearSelection()
}

// Keyboard shortcuts
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (showPreview.value) closePreview()
    if (showStepsDialog.value) showStepsDialog.value = false
    if (showMoveModal.value) showMoveModal.value = false
    if (deleteConfirmId.value) deleteConfirmId.value = null
    if (documentStore.isBatchMode) documentStore.toggleBatchMode()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleKeydown)
})

// Clean up on unmount
// (Vue 3 composition API cleanup is automatic for refs)

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}秒`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return `${mins}分${secs}秒`
  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60
  return `${hours}小时${remainingMins}分`
}
</script>

<template>
  <div class="flex h-full">
    <!-- Sidebar: Folder Tree -->
    <aside class="w-64 border-r bg-background flex-shrink-0 overflow-y-auto hidden md:block">
      <div class="p-4 border-b">
        <h2 class="text-sm font-semibold flex items-center gap-2">
          <Folder class="w-4 h-4" />
          文件夹
        </h2>
      </div>
      <FolderTree
        :folders="folderStore.folderTree"
        :current-folder-id="folderStore.currentFolderId"
        @select="navigateToFolder"
        @create="folderStore.fetchFolderTree()"
      />
    </aside>

    <!-- Main Content -->
    <main class="flex-1 flex flex-col min-w-0 overflow-hidden">
      <!-- Header Toolbar -->
      <div class="border-b bg-background px-4 py-3 flex items-center gap-3 flex-wrap">
        <!-- Breadcrumb -->
        <nav class="flex items-center gap-1 text-sm min-w-0 flex-1">
          <button
            @click="router.push('/')"
            class="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors mr-2"
            title="返回主页"
          >
            <ArrowLeft class="w-4 h-4" />
            <span class="hidden sm:inline">返回</span>
          </button>
          <div class="w-px h-4 bg-border mx-1" />
          <button
            @click="navigateToFolder(null)"
            class="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
            :class="!folderStore.currentFolderId && 'font-medium text-foreground'"
          >
            <FolderOpen class="w-4 h-4" />
            全部文档
          </button>
          <template v-for="folder in folderStore.currentFolderPath" :key="folder.id">
            <ChevronRight class="w-4 h-4 text-muted-foreground" />
            <button
              @click="navigateToFolder(folder.id)"
              class="text-muted-foreground hover:text-foreground transition-colors truncate max-w-[120px]"
              :class="folder.id === folderStore.currentFolderId && 'font-medium text-foreground'"
            >
              {{ folder.name }}
            </button>
          </template>
        </nav>

        <!-- Search -->
        <div class="relative">
          <Search class="w-4 h-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="searchInput"
            @keyup.enter="handleSearch"
            type="text"
            placeholder="搜索文档..."
            class="w-48 lg:w-64 pl-9 pr-8 py-1.5 text-sm rounded-lg border bg-background focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <button
            v-if="searchInput"
            @click="clearSearch"
            class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- View Toggle -->
        <ViewToggle v-model="viewMode" />

        <!-- Upload -->
        <label class="cursor-pointer inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors">
          <Upload class="w-4 h-4" />
          <span class="hidden sm:inline">上传</span>
          <input type="file" class="hidden" @change="handleUpload" accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.csv" multiple />
        </label>

        <!-- Batch Mode Toggle -->
        <button
          @click="documentStore.toggleBatchMode()"
          :class="[
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors',
            documentStore.isBatchMode
              ? 'bg-primary text-primary-foreground border-primary'
              : 'bg-background text-foreground border-border hover:bg-muted'
          ]"
        >
          <CheckSquare2 v-if="documentStore.isBatchMode" class="w-4 h-4" />
          <Square v-else class="w-4 h-4" />
          <span class="hidden sm:inline">批量</span>
        </button>
      </div>

      <!-- Batch Actions Bar -->
      <div
        v-if="documentStore.isBatchMode"
        class="px-4 py-2 border-b bg-primary/5 flex items-center justify-between"
      >
        <div class="flex items-center gap-3">
          <button
            @click="documentStore.selectAll()"
            class="text-sm text-primary hover:underline"
          >
            全选
          </button>
          <button
            @click="documentStore.deselectAll()"
            class="text-sm text-muted-foreground hover:text-foreground"
          >
            取消全选
          </button>
          <span v-if="documentStore.hasSelection" class="text-sm text-muted-foreground">
            已选择 {{ documentStore.selectedIds.size }} 项
          </span>
        </div>
        <div v-if="documentStore.hasSelection" class="flex items-center gap-2">
          <button
            @click="handleBatchDownload"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-background border text-sm hover:bg-muted transition-colors"
          >
            <Download class="w-4 h-4" />
            下载
          </button>
          <button
            @click="handleBatchMove"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-background border text-sm hover:bg-muted transition-colors"
          >
            <Move class="w-4 h-4" />
            移动
          </button>
          <button
            @click="handleBatchReindex"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-background border text-sm hover:bg-muted transition-colors"
          >
            <RefreshCw class="w-4 h-4" />
            重新解析
          </button>
          <button
            @click="handleBatchDelete"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-destructive text-destructive-foreground text-sm hover:bg-destructive/90 transition-colors"
          >
            <Trash2 class="w-4 h-4" />
            删除
          </button>
        </div>
      </div>

      <!-- Upload Error -->
      <div v-if="uploadError" class="px-4 py-2 bg-red-50 dark:bg-red-950/30 border-b border-red-200 dark:border-red-800">
        <div class="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
          <AlertCircle class="w-4 h-4" />
          {{ uploadError }}
          <button @click="uploadError = ''" class="ml-auto hover:text-red-800">
            <X class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- Uploading Indicator -->
      <div v-if="uploading" class="px-4 py-2 bg-blue-50 dark:bg-blue-950/30 border-b">
        <div class="flex items-center gap-2 text-sm text-blue-600 dark:text-blue-400">
          <Loader2 class="w-4 h-4 animate-spin" />
          <span v-if="uploadProgress.total > 1">
            正在上传第 {{ uploadProgress.current }}/{{ uploadProgress.total }} 个文件
            <span v-if="uploadProgress.currentFile" class="text-blue-500 ml-1">({{ uploadProgress.currentFile }})</span>
          </span>
          <span v-else>正在上传文件...</span>
        </div>
      </div>

      <!-- Document List -->
      <div class="flex-1 overflow-y-auto p-4">
        <!-- Empty State -->
        <div v-if="!documentStore.loading && documentStore.documents.length === 0" class="flex flex-col items-center justify-center h-64 text-muted-foreground">
          <FileText class="w-12 h-12 mb-3 opacity-40" />
          <p class="text-sm">暂无文档</p>
          <p class="text-xs mt-1">点击上方"上传"按钮添加文档</p>
        </div>

        <!-- Grid View -->
        <div
          v-else-if="viewMode === 'grid'"
          class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
        >
          <DocumentCard
            v-for="doc in documentStore.documents"
            :key="doc.id"
            :document="doc"
            :selected="documentStore.selectedIds.has(doc.id)"
            :selectable="documentStore.isBatchMode"
            @toggle-select="documentStore.toggleSelect"
            @preview="openPreview"
            @reindex="handleReindex"
            @delete="confirmDelete"
            @move="handleMove"
            @show-steps="showProcessingSteps"
            @contextmenu="(e: MouseEvent) => handleDocumentContextMenu(e, doc)"
          />
        </div>

        <!-- List View -->
        <div v-else class="space-y-2">
          <DocumentListItem
            v-for="doc in documentStore.documents"
            :key="doc.id"
            :document="doc"
            :selected="documentStore.selectedIds.has(doc.id)"
            :selectable="documentStore.isBatchMode"
            @toggle-select="documentStore.toggleSelect"
            @preview="openPreview"
            @reindex="handleReindex"
            @delete="confirmDelete"
            @move="handleMove"
            @show-steps="showProcessingSteps"
            @contextmenu="(e: MouseEvent) => handleDocumentContextMenu(e, doc)"
          />
        </div>

        <!-- Loading -->
        <div v-if="documentStore.loading" class="flex items-center justify-center py-12">
          <Loader2 class="w-6 h-6 animate-spin text-primary" />
          <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
        </div>
      </div>
    </main>

    <!-- Preview Modal -->
    <div
      v-if="showPreview"
      class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      @click.self="closePreview"
    >
      <div class="bg-background rounded-xl shadow-2xl w-full max-w-6xl max-h-[90vh] flex flex-col overflow-hidden">
        <!-- Preview Header -->
        <div class="flex items-center justify-between px-4 py-3 border-b">
          <div class="flex items-center gap-3 min-w-0">
            <FileText class="w-5 h-5 text-muted-foreground flex-shrink-0" />
            <h3 class="font-medium truncate">{{ previewDocName }}</h3>
            <span
              v-if="previewData"
              class="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground"
            >
              {{ previewData.page_count }} 页
            </span>
          </div>
          <button
            @click="closePreview"
            class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
          >
            <X class="w-5 h-5" />
          </button>
        </div>

        <!-- Preview Body -->
        <div class="flex-1 flex overflow-hidden">
          <!-- Sidebar -->
          <div class="w-72 border-r bg-muted/30 flex flex-col overflow-hidden hidden lg:flex">
            <!-- Tabs -->
            <div class="flex border-b">
              <button
                @click="activeTab = 'toc'"
                :class="[
                  'flex-1 py-2.5 text-sm font-medium transition-colors',
                  activeTab === 'toc' ? 'text-primary border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
                ]"
              >
                <BookOpen class="w-4 h-4 inline mr-1.5" />
                目录
              </button>
              <button
                @click="activeTab = 'meta'"
                :class="[
                  'flex-1 py-2.5 text-sm font-medium transition-colors',
                  activeTab === 'meta' ? 'text-primary border-b-2 border-primary' : 'text-muted-foreground hover:text-foreground'
                ]"
              >
                <BarChart3 class="w-4 h-4 inline mr-1.5" />
                信息
              </button>
            </div>

            <!-- TOC Panel -->
            <div v-if="activeTab === 'toc'" class="flex-1 overflow-y-auto p-3">
              <div v-if="previewLoading" class="flex items-center justify-center py-8">
                <Loader2 class="w-5 h-5 animate-spin text-primary" />
              </div>
              <TocTree
                v-else-if="previewData?.toc?.length"
                :nodes="previewData.toc"
                :default-expanded="true"
                @jump="jumpToPage"
              />
              <div v-else class="text-center py-8 text-muted-foreground text-sm">
                暂无目录信息
              </div>
            </div>

            <!-- Meta Panel -->
            <div v-else class="flex-1 overflow-y-auto p-3 space-y-4">
              <div v-if="previewLoading" class="flex items-center justify-center py-8">
                <Loader2 class="w-5 h-5 animate-spin text-primary" />
              </div>
              <template v-else-if="previewData">
                <div>
                  <h4 class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">文件信息</h4>
                  <div class="space-y-2 text-sm">
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">格式</span>
                      <span>{{ previewData.file_type }}</span>
                    </div>
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">大小</span>
                      <span>{{ formatSize(previewData.file_size) }}</span>
                    </div>
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">页数</span>
                      <span>{{ previewData.page_count }}</span>
                    </div>
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">创建时间</span>
                      <span>{{ new Date(previewData.created_at).toLocaleDateString('zh-CN') }}</span>
                    </div>
                  </div>
                </div>

                <div v-if="previewData.processing_duration !== undefined">
                  <h4 class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">解析信息</h4>
                  <div class="space-y-2 text-sm">
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">解析模式</span>
                      <span>{{ previewData.index_meta?.route_decision?.execution_mode || '智能' }}</span>
                    </div>
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">解析用时</span>
                      <span>{{ formatDuration(previewData.processing_duration) }}</span>
                    </div>
                  </div>
                </div>

                <div v-if="previewData.description">
                  <h4 class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">全文摘要</h4>
                  <p class="text-sm text-muted-foreground leading-relaxed">{{ previewData.description }}</p>
                </div>

                <div v-if="previewData.stats">
                  <h4 class="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">索引统计</h4>
                  <div class="space-y-2 text-sm">
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">节点数</span>
                      <span>{{ previewData.stats.node_count }}</span>
                    </div>
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">文本字符</span>
                      <span>{{ previewData.stats.text_chars?.toLocaleString() }}</span>
                    </div>
                    <div class="flex justify-between">
                      <span class="text-muted-foreground">摘要覆盖</span>
                      <span>{{ previewData.stats.summary_coverage }}</span>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- Preview Content -->
          <div class="flex-1 overflow-hidden bg-muted/20">
            <div v-if="previewLoading" class="flex items-center justify-center h-full">
              <Loader2 class="w-8 h-8 animate-spin text-primary" />
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
              class="h-full"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Processing Steps Dialog -->
    <ProcessingStepsDialog
      :visible="showStepsDialog"
      :document-name="stepsDocName"
      :steps="stepsData"
      :is-loading="stepsLoading"
      @close="showStepsDialog = false"
    />

    <!-- Move Modal -->
    <div
      v-if="showMoveModal"
      class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      @click.self="showMoveModal = false"
    >
      <div class="bg-background rounded-xl shadow-2xl w-full max-w-sm p-4">
        <h3 class="font-semibold mb-3">移动到文件夹</h3>
        <div class="space-y-1 max-h-64 overflow-y-auto">
          <button
            @click="moveDocId ? doMove(null) : doBatchMove(null)"
            class="w-full text-left px-3 py-2 rounded-lg hover:bg-muted text-sm"
          >
            📁 根目录
          </button>
          <button
            v-for="folder in folderStore.folders"
            :key="folder.id"
            @click="moveDocId ? doMove(folder.id) : doBatchMove(folder.id)"
            class="w-full text-left px-3 py-2 rounded-lg hover:bg-muted text-sm"
          >
            📁 {{ folder.name }}
          </button>
        </div>
        <div class="mt-4 flex justify-end">
          <button
            @click="showMoveModal = false"
            class="px-4 py-2 rounded-lg border text-sm hover:bg-muted transition-colors"
          >
            取消
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirm -->
    <div
      v-if="deleteConfirmId"
      class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      @click.self="deleteConfirmId = null"
    >
      <div class="bg-background rounded-xl shadow-2xl w-full max-w-sm p-4">
        <h3 class="font-semibold mb-2">确认删除</h3>
        <p class="text-sm text-muted-foreground mb-4">此操作不可恢复，确定要删除该文档吗？</p>
        <div class="flex justify-end gap-2">
          <button
            @click="deleteConfirmId = null"
            class="px-4 py-2 rounded-lg border text-sm hover:bg-muted transition-colors"
          >
            取消
          </button>
          <button
            @click="doDelete"
            class="px-4 py-2 rounded-lg bg-destructive text-destructive-foreground text-sm hover:bg-destructive/90 transition-colors"
          >
            删除
          </button>
        </div>
      </div>
    </div>

    <!-- Rename Modal -->
    <div
      v-if="renamingDoc"
      class="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      @click.self="renamingDoc = null"
    >
      <div class="bg-background rounded-xl shadow-2xl w-full max-w-sm p-4">
        <h3 class="font-semibold mb-3">重命名</h3>
        <input
          v-model="renameValue"
          type="text"
          class="w-full px-3 py-2 rounded-lg border bg-background focus:outline-none focus:ring-2 focus:ring-primary/20 mb-4"
          @keyup.enter="doRename"
        />
        <div class="flex justify-end gap-2">
          <button
            @click="renamingDoc = null"
            class="px-4 py-2 rounded-lg border text-sm hover:bg-muted transition-colors"
          >
            取消
          </button>
          <button
            @click="doRename"
            class="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm hover:bg-primary/90 transition-colors"
          >
            确定
          </button>
        </div>
      </div>
    </div>

    <!-- Document Context Menu -->
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
