<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Check,
  Download,
  File,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Folder,
  FolderOpen,
  ListTree,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Move,
  Plus,
  Presentation,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-vue-next'
import AppShell from '@/components/layout/AppShell.vue'
import PdfReferenceViewer from '@/components/PdfReferenceViewer.vue'
import UniversalPreview from '@/components/preview/UniversalPreview.vue'
import TocTree from '@/components/document/TocTree.vue'
import CreateFolderDialog from '@/components/folder/CreateFolderDialog.vue'
import { documentApi } from '@/api'
import type { Document } from '@/stores/document'
import { useDocumentStore } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'
import {
  DOCUMENT_WORKBENCH_PAGE_SIZE,
  documentFailureMessage,
  documentProgress,
  formatDocumentDate,
  formatDocumentDuration,
  formatDocumentSize,
  formatDocumentTypeLabel,
  isCompletedStatus,
  isProcessingStatus,
  localizedStatusLabel,
  metadataValue,
  qualityDisplay,
  workbenchIncludeSubfolders,
} from '@/utils/documentWorkbench'
import {
  buildDocumentBreadcrumb,
  buildDocumentChatRoute,
  buildFolderChatRoute,
  DOCUMENT_SELECTION_ACTIONS,
  documentPresentationForType,
  hasSelectableLibraryItems,
  selectableDocumentIds,
} from '@/ui/pagechatContracts'
import type { DocumentSelectionActionId } from '@/ui/pagechatContracts'
import { calculatePopoverPosition, type PopoverSize } from '@/ui/popoverPosition'
import type { Folder as FolderModel, FolderTreeItem } from '@/api/folders'
import { useI18n } from '@/i18n/messages'

interface TocItem {
  node_id: string
  title: string
  level: number
  summary?: string
  start_page: number
  end_page: number
  children?: TocItem[]
}

interface PreviewData {
  id: string
  name: string
  original_name?: string
  file_type: string
  file_size: number
  status: string
  page_count?: number
  processing_duration?: number
  created_at?: string
  updated_at?: string
  toc?: TocItem[]
  index_meta?: {
    route_decision?: { execution_mode?: string }
    visual_page_summaries_count?: number
  }
  stats?: {
    node_count?: number
    text_chars?: number
    summary_coverage?: string
  }
  quality_report?: Record<string, unknown> | null
}

interface PreviewTocNode {
  node_id: string
  title: string
  level: number
  summary: string
  start_page: number | null
  end_page: number | null
  children: PreviewTocNode[]
}

const documentStore = useDocumentStore()
const folderStore = useFolderStore()
const router = useRouter()
const { localizeText: lt, localizeError, isChinese } = useI18n()

const searchInput = ref('')
const uploading = ref(false)
const uploadError = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const showCreateFolderDialog = ref(false)
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewData = ref<PreviewData | null>(null)
const previewDocument = ref<Document | null>(null)
const activePreviewTab = ref<'toc' | 'info'>('toc')
const pdfViewerRef = ref<InstanceType<typeof PdfReferenceViewer> | null>(null)
const rowMenuDocumentId = ref<string | null>(null)
const rowMenuFolderId = ref<string | null>(null)
const rowMenuRef = ref<HTMLElement | null>(null)
const rowMenuPosition = ref({ top: 0, left: 0, maxHeight: 320 })
const selectionActionBusy = ref<DocumentSelectionActionId | null>(null)
const moveDialogOpen = ref(false)
const moveTargetFolderId = ref<string | null>(null)
const selectedFolderIds = ref<Set<string>>(new Set())
const operationNotice = ref('')

const breadcrumbs = computed(() => buildDocumentBreadcrumb(folderStore.currentFolderPath))
const currentFolders = computed<FolderModel[]>(() =>
  folderStore.folders
)
const displayDocuments = computed(() =>
  documentStore.documents
)
const displayTotal = computed(() => currentFolders.value.length + documentStore.total)
const rowMenuDocument = computed(() =>
  displayDocuments.value.find((document) => document.id === rowMenuDocumentId.value) || null
)
const rowMenuFolder = computed(() =>
  currentFolders.value.find((folder) => folder.id === rowMenuFolderId.value) || null
)
const selectableCurrentDocumentIds = computed(() =>
  selectableDocumentIds(displayDocuments.value.map((document) => ({
    id: document.id,
    selectable: true,
  })))
)
const selectableCurrentFolderIds = computed(() => currentFolders.value.map((folder) => folder.id))
const selectedDocumentIds = computed(() =>
  Array.from(documentStore.selectedIds)
    .filter((id) => selectableCurrentDocumentIds.value.includes(id))
)
const selectedFolderIdList = computed(() =>
  Array.from(selectedFolderIds.value)
    .filter((id) => selectableCurrentFolderIds.value.includes(id))
)
const actionableSelectedDocumentIds = computed(() =>
  selectedDocumentIds.value
)
const actionableSelectedFolderIds = computed(() =>
  selectedFolderIdList.value
)
const allSelected = computed(() =>
  (selectableCurrentDocumentIds.value.length + selectableCurrentFolderIds.value.length) > 0 &&
  selectableCurrentDocumentIds.value.every((id) => documentStore.selectedIds.has(id)) &&
  selectableCurrentFolderIds.value.every((id) => selectedFolderIds.value.has(id))
)
const selectedCount = computed(() => selectedDocumentIds.value.length + selectedFolderIdList.value.length)
const selectionSummary = computed(() => buildSelectionSummary({
  documentCount: selectedDocumentIds.value.length,
  folderCount: selectedFolderIdList.value.length,
}))
const selectionActions = computed(() => DOCUMENT_SELECTION_ACTIONS)
const selectedDocuments = computed(() =>
  displayDocuments.value.filter((document) => selectedDocumentIds.value.includes(document.id))
)
const selectedFolders = computed(() =>
  currentFolders.value.filter((folder) => selectedFolderIdList.value.includes(folder.id))
)
const selectedItemLabel = computed(() =>
  selectedDocuments.value[0]?.original_name ||
  selectedDocuments.value[0]?.name ||
  selectedFolders.value[0]?.name ||
  lt('所选项目')
)
const previewQuality = computed(() => qualityDisplay(previewData.value?.quality_report))
const previewToc = computed(() => normalizeToc(previewData.value?.toc || []))
const previewRoute = computed(() => {
  const mode = previewData.value?.index_meta?.route_decision?.execution_mode
  if (mode) return mode
  if (previewDocument.value?.parse_execution_mode) return previewDocument.value.parse_execution_mode
  return 'smart'
})

const iconMap = {
  File,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Folder,
  Presentation,
}

const selectionActionIconMap = {
  Download,
  MessageSquare,
  Move,
  RefreshCw,
  Trash2,
}

function selectionActionIconFor(icon: string) {
  return selectionActionIconMap[icon as keyof typeof selectionActionIconMap] || File
}

interface FolderPickerOption {
  id: string | null
  name: string
  path: string
  depth: number
}

function flattenFolderTree(nodes: FolderTreeItem[], depth = 0): FolderPickerOption[] {
  return nodes.flatMap((folder) => [
    {
      id: folder.id,
      name: folder.name,
      path: folder.path || folder.name,
      depth,
    },
    ...flattenFolderTree(folder.children || [], depth + 1),
  ])
}

function buildSelectionSummary(input: { documentCount: number; folderCount: number }): string {
  if (!isChinese.value) {
    const parts: string[] = []
    if (input.documentCount > 0) parts.push(`${input.documentCount} ${input.documentCount === 1 ? 'file' : 'files'}`)
    if (input.folderCount > 0) parts.push(`${input.folderCount} ${input.folderCount === 1 ? 'folder' : 'folders'}`)
    return `Selected ${parts.join(' and ') || '0 items'}`
  }
  const parts: string[] = []
  if (input.documentCount > 0) parts.push(`${input.documentCount} 个文件`)
  if (input.folderCount > 0) parts.push(`${input.folderCount} 个文件夹`)
  return `已选择 ${parts.join('、') || '0 个项目'}`
}

const moveFolderOptions = computed<FolderPickerOption[]>(() => [
  { id: null, name: 'root', path: 'root', depth: 0 },
  ...flattenFolderTree(folderStore.folderTree),
])

const moveTargetLabel = computed(() =>
  moveFolderOptions.value.find((folder) => folder.id === moveTargetFolderId.value)?.name || 'root'
)

function fileIconFor(fileType?: string) {
  return iconMap[documentPresentationForType(fileType).icon as keyof typeof iconMap] || File
}

function fileToneFor(fileType?: string) {
  return documentPresentationForType(fileType).tone
}

function isRowMenuOpen(document: Document) {
  return rowMenuDocumentId.value === document.id
}

function isFolderMenuOpen(folder: FolderModel) {
  return rowMenuFolderId.value === folder.id
}

const DEFAULT_ROW_MENU_SIZE: PopoverSize = {
  width: 176,
  height: 216,
}

function menuPositionForButton(button: HTMLElement, popoverSize = DEFAULT_ROW_MENU_SIZE) {
  const rect = button.getBoundingClientRect()
  return calculatePopoverPosition({
    anchorRect: {
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
    },
    popoverSize,
    viewportSize: {
      width: window.innerWidth,
      height: window.innerHeight,
    },
  })
}

async function toggleRowMenu(document: Document, event: Event) {
  const target = event.currentTarget as HTMLElement
  if (isRowMenuOpen(document)) {
    closeRowMenu()
    return
  }
  rowMenuFolderId.value = null
  rowMenuPosition.value = menuPositionForButton(target)
  rowMenuDocumentId.value = document.id
  await nextTick()
  if (rowMenuDocumentId.value !== document.id || !rowMenuRef.value) return

  const measuredRect = rowMenuRef.value.getBoundingClientRect()
  rowMenuPosition.value = menuPositionForButton(target, {
    width: measuredRect.width || DEFAULT_ROW_MENU_SIZE.width,
    height: rowMenuRef.value.scrollHeight || measuredRect.height || DEFAULT_ROW_MENU_SIZE.height,
  })
}

async function toggleFolderMenu(folder: FolderModel, event: Event) {
  const target = event.currentTarget as HTMLElement
  if (isFolderMenuOpen(folder)) {
    closeRowMenu()
    return
  }
  rowMenuDocumentId.value = null
  rowMenuPosition.value = menuPositionForButton(target)
  rowMenuFolderId.value = folder.id
  await nextTick()
  if (rowMenuFolderId.value !== folder.id || !rowMenuRef.value) return

  const measuredRect = rowMenuRef.value.getBoundingClientRect()
  rowMenuPosition.value = menuPositionForButton(target, {
    width: measuredRect.width || DEFAULT_ROW_MENU_SIZE.width,
    height: rowMenuRef.value.scrollHeight || measuredRect.height || DEFAULT_ROW_MENU_SIZE.height,
  })
}

function closeRowMenu() {
  rowMenuDocumentId.value = null
  rowMenuFolderId.value = null
}

function chatWithDocument(document: Document) {
  closeRowMenu()
  router.push(buildDocumentChatRoute(document))
}

function chatWithFolder(folder: FolderModel) {
  closeRowMenu()
  router.push(buildFolderChatRoute(folder))
}

function chatWithSelection() {
  if (selectedCount.value === 0) return
  closeRowMenu()
  if (selectedDocuments.value.length > 0) {
    const documentRoute = buildDocumentChatRoute(selectedDocuments.value)
    const folderRoute = selectedFolders.value.length > 0
      ? buildFolderChatRoute(selectedFolders.value)
      : { path: '/', query: {} }
    const route = {
      path: documentRoute.path,
      query: Object.fromEntries(
        Object.entries({ ...documentRoute.query, ...folderRoute.query }).filter((entry): entry is [string, string] =>
          typeof entry[1] === 'string',
        ),
      ),
    }
    router.push(route)
  } else if (selectedFolders.value[0]) {
    router.push(buildFolderChatRoute(selectedFolders.value))
  }
  documentStore.deselectAll()
  selectedFolderIds.value.clear()
}

function normalizeToc(nodes: TocItem[]): PreviewTocNode[] {
  return nodes.map((node) => ({
    node_id: node.node_id,
    title: node.title,
    level: node.level,
    summary: node.summary || '',
    start_page: node.start_page,
    end_page: node.end_page,
    children: normalizeToc(node.children || []),
  }))
}

function goToFolder(folderId: string | null) {
  closeRowMenu()
  folderStore.setCurrentFolder(folderId)
}

function refreshDocuments() {
  operationNotice.value = ''
  documentStore.fetchDocuments(
    1,
    searchInput.value || undefined,
    folderStore.currentFolderId,
    workbenchIncludeSubfolders(folderStore.currentFolderId),
    DOCUMENT_WORKBENCH_PAGE_SIZE,
  )
}

function clearSearch() {
  searchInput.value = ''
  refreshDocuments()
}

function toggleAll() {
  closeRowMenu()
  if (allSelected.value) {
    selectableCurrentDocumentIds.value.forEach((id) => documentStore.selectedIds.delete(id))
    selectableCurrentFolderIds.value.forEach((id) => selectedFolderIds.value.delete(id))
    return
  }
  selectableCurrentDocumentIds.value.forEach((id) => documentStore.selectedIds.add(id))
  selectableCurrentFolderIds.value.forEach((id) => selectedFolderIds.value.add(id))
}

function toggleDocumentSelection(document: Document) {
  closeRowMenu()
  documentStore.toggleSelect(document.id)
}

function toggleFolderSelection(folder: FolderModel) {
  closeRowMenu()
  if (selectedFolderIds.value.has(folder.id)) {
    selectedFolderIds.value.delete(folder.id)
    return
  }
  selectedFolderIds.value.add(folder.id)
}

function clearSelectedDocuments() {
  closeRowMenu()
  documentStore.deselectAll()
  selectedFolderIds.value.clear()
}

async function uploadFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length === 0) return

  uploading.value = true
  uploadError.value = ''
  try {
    await documentStore.uploadDocuments(files, folderStore.currentFolderId, 'smart')
    refreshDocuments()
  } catch (error: any) {
    uploadError.value = localizeError(error?.response?.data?.detail || 'Upload failed')
  } finally {
    uploading.value = false
    input.value = ''
  }
}

async function openPreview(document: Document) {
  if (!isCompletedStatus(document.status)) return
  closeRowMenu()
  previewDocument.value = document
  previewOpen.value = true
  activePreviewTab.value = 'toc'
  previewData.value = null

  previewLoading.value = true

  try {
    const { data } = await documentApi.preview(document.id)
    previewData.value = data
  } catch (error: any) {
    uploadError.value = localizeError(error?.response?.data?.detail || 'Preview failed')
  } finally {
    previewLoading.value = false
  }
}

function closePreview() {
  previewOpen.value = false
  previewDocument.value = null
  previewData.value = null
}

function jumpToPage(pageNum: number) {
  pdfViewerRef.value?.scrollToPage(pageNum)
}

function showFolderBackendNotice(action: string) {
  uploadError.value = ''
  operationNotice.value = lt(`文件夹${action}需要后端接口支持，当前先保留入口和选择状态。`)
}

async function deleteSelected() {
  const documentIds = actionableSelectedDocumentIds.value
  const folderIds = actionableSelectedFolderIds.value
  if (documentIds.length === 0 && folderIds.length === 0) {
    return
  }
  selectionActionBusy.value = 'delete'
  uploadError.value = ''
  operationNotice.value = ''
  try {
    if (documentIds.length > 0) {
      await documentStore.batchDelete(documentIds)
    }
    for (const folderId of folderIds) {
      await folderStore.deleteFolder(folderId)
    }
    documentStore.deselectAll()
    selectedFolderIds.value.clear()
    refreshDocuments()
  } catch (error: any) {
    uploadError.value = localizeError(error?.response?.data?.detail || 'Delete failed')
  } finally {
    selectionActionBusy.value = null
  }
}

async function deleteOne(document: Document) {
  closeRowMenu()
  await documentStore.deleteDocument(document.id)
  refreshDocuments()
}

async function reindexOne(document: Document) {
  closeRowMenu()
  await documentStore.reindexDocument(document.id, 'smart')
}

async function downloadOne(document: Document) {
  closeRowMenu()
  await documentStore.batchDownload([document.id])
}

async function deleteOneFolder(folder: FolderModel) {
  closeRowMenu()
  await folderStore.deleteFolder(folder.id)
  await folderStore.fetchFolders(folderStore.currentFolderId)
}

function reindexFolder(folder: FolderModel) {
  closeRowMenu()
  void folder
  showFolderBackendNotice('重新解析')
}

function downloadFolder(folder: FolderModel) {
  closeRowMenu()
  void folder
  showFolderBackendNotice('下载')
}

function moveOneFolder(folder: FolderModel) {
  closeRowMenu()
  documentStore.deselectAll()
  selectedFolderIds.value = new Set([folder.id])
  openMoveDialog()
}

async function copyDocumentName(document: Document) {
  closeRowMenu()
  try {
    await navigator.clipboard.writeText(document.original_name || document.name)
  } catch (error) {
    console.error('Failed to copy document name:', error)
  }
}

async function reindexSelected() {
  const ids = actionableSelectedDocumentIds.value
  if (ids.length === 0) {
    if (selectedFolderIdList.value.length > 0) showFolderBackendNotice('重新解析')
    return
  }
  selectionActionBusy.value = 'reindex'
  uploadError.value = ''
  operationNotice.value = ''
  try {
    await documentStore.batchReindex(ids)
    documentStore.deselectAll()
  } catch (error: any) {
    uploadError.value = localizeError(error?.response?.data?.detail || 'Reprocess failed')
  } finally {
    selectionActionBusy.value = null
  }
}

async function downloadSelected() {
  const ids = actionableSelectedDocumentIds.value
  if (ids.length === 0) {
    if (selectedFolderIdList.value.length > 0) showFolderBackendNotice('下载')
    return
  }
  selectionActionBusy.value = 'download'
  uploadError.value = ''
  operationNotice.value = ''
  try {
    await documentStore.batchDownload(ids)
    if (selectedFolderIdList.value.length > 0) showFolderBackendNotice('下载')
  } catch (error: any) {
    uploadError.value = localizeError(error?.response?.data?.detail || 'Download failed')
  } finally {
    selectionActionBusy.value = null
  }
}

function openMoveDialog() {
  if (selectedCount.value === 0) return
  closeRowMenu()
  moveTargetFolderId.value = null
  moveDialogOpen.value = true
}

function closeMoveDialog() {
  if (selectionActionBusy.value === 'move') return
  moveDialogOpen.value = false
}

async function moveSelected() {
  const documentIds = actionableSelectedDocumentIds.value
  const folderIds = actionableSelectedFolderIds.value
  if (documentIds.length === 0 && folderIds.length === 0) {
    return
  }
  selectionActionBusy.value = 'move'
  uploadError.value = ''
  operationNotice.value = ''
  try {
    if (documentIds.length > 0) {
      await documentStore.batchMove(documentIds, moveTargetFolderId.value)
    }
    for (const folderId of folderIds) {
      if (folderId !== moveTargetFolderId.value) {
        await folderStore.moveFolder(folderId, moveTargetFolderId.value)
      }
    }
    documentStore.deselectAll()
    selectedFolderIds.value.clear()
    moveDialogOpen.value = false
    await folderStore.fetchFolderTree()
    await folderStore.fetchFolders(folderStore.currentFolderId)
    refreshDocuments()
  } catch (error: any) {
    uploadError.value = localizeError(error?.response?.data?.detail || 'Move failed')
  } finally {
    selectionActionBusy.value = null
  }
}

function runSelectionAction(actionId: DocumentSelectionActionId) {
  if (selectionActionBusy.value) return
  if (actionId === 'chat') {
    chatWithSelection()
    return
  }
  if (actionId === 'download') {
    downloadSelected()
    return
  }
  if (actionId === 'reindex') {
    reindexSelected()
    return
  }
  if (actionId === 'move') {
    openMoveDialog()
    return
  }
  if (actionId === 'delete') {
    deleteSelected()
  }
}

function isSelectionActionDisabled(actionId: DocumentSelectionActionId) {
  if (selectionActionBusy.value) return true
  if (actionId === 'chat') return selectedCount.value === 0
  return selectedCount.value === 0
}

async function handleFolderCreated() {
  await folderStore.fetchFolderTree()
  await folderStore.fetchFolders(folderStore.currentFolderId)
}

watch(() => folderStore.currentFolderId, (folderId) => {
  documentStore.currentFolderId = folderId
  documentStore.deselectAll()
  selectedFolderIds.value.clear()
  folderStore.fetchFolders(folderId)
  refreshDocuments()
})

watch([searchInput, () => folderStore.currentFolderId], () => {
  closeRowMenu()
})

onMounted(() => {
  document.addEventListener('click', closeRowMenu)
  window.addEventListener('resize', closeRowMenu)
  documentStore.viewMode = 'list'
  documentStore.clearSelection()
  selectedFolderIds.value.clear()
  folderStore.fetchFolderTree()
  folderStore.fetchFolders(null)
  refreshDocuments()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeRowMenu)
  window.removeEventListener('resize', closeRowMenu)
  documentStore.deselectAll()
  selectedFolderIds.value.clear()
})
</script>

<template>
  <AppShell title="Documents">
    <div class="documents-page">
      <div class="documents-toolbar">
        <div class="breadcrumb">
          <button
            v-for="(crumb, index) in breadcrumbs"
            :key="crumb.id || 'root'"
            :class="{ root: crumb.isRoot }"
            type="button"
            @click="goToFolder(crumb.id)"
          >
            {{ crumb.label }}
            <span v-if="index < breadcrumbs.length - 1">/</span>
          </button>
        </div>

        <div class="toolbar-actions">
          <div class="search-box">
            <Search />
            <input
              v-model="searchInput"
              placeholder="Search files"
              @keyup.enter="refreshDocuments"
            />
            <button v-if="searchInput" type="button" @click="clearSearch">
              <X />
            </button>
          </div>
          <button class="toolbar-button" type="button" @click="showCreateFolderDialog = true">
            <Plus />
            <span>Folder</span>
          </button>
          <button class="toolbar-button primary" type="button" :disabled="uploading" @click="fileInputRef?.click()">
            <Loader2 v-if="uploading" class="spin" />
            <Upload v-else />
            <span>Upload</span>
          </button>
          <input ref="fileInputRef" class="hidden-input" type="file" multiple @change="uploadFiles" />
        </div>
      </div>

      <div v-if="uploadError" class="error-banner">
        {{ uploadError }}
      </div>
      <div v-if="operationNotice" class="notice-banner">
        {{ operationNotice }}
      </div>

      <div v-if="selectedCount > 0" class="selection-bar">
        <div class="selection-summary">
          <strong>{{ selectionSummary }}</strong>
          <button type="button" @click="clearSelectedDocuments">{{ lt('取消选择') }}</button>
        </div>
        <div class="selection-actions">
          <button
            v-for="action in selectionActions"
            :key="action.id"
            :class="{ danger: action.tone === 'danger' }"
            type="button"
            :disabled="isSelectionActionDisabled(action.id)"
            @click="runSelectionAction(action.id)"
          >
            <Loader2 v-if="selectionActionBusy === action.id" class="spin" />
            <component v-else :is="selectionActionIconFor(action.icon)" />
            {{ lt(action.label) }}
          </button>
        </div>
      </div>

      <div class="documents-list" @scroll="closeRowMenu">
        <div class="list-header">
          <button
            :class="['checkbox', { checked: allSelected }]"
            type="button"
            :disabled="!hasSelectableLibraryItems(selectableCurrentDocumentIds, selectableCurrentFolderIds)"
            @click="toggleAll"
          >
            <Check v-if="allSelected" />
          </button>
          <span>All Files</span>
          <span class="list-total">{{ displayTotal }} items</span>
        </div>

        <div
          v-for="folder in currentFolders"
          :key="folder.id"
          :class="[
            'file-row',
            'folder-row',
            {
              selected: selectedFolderIds.has(folder.id),
              'menu-open': isFolderMenuOpen(folder),
            },
          ]"
          @click="goToFolder(folder.id)"
        >
          <button
            :class="['checkbox', { checked: selectedFolderIds.has(folder.id) }]"
            type="button"
            @click.stop="toggleFolderSelection(folder)"
          >
            <Check v-if="selectedFolderIds.has(folder.id)" />
          </button>
          <span class="file-icon folder">
            <FolderOpen />
          </span>
          <span class="file-main">
            <strong>{{ folder.name }}</strong>
            <small>{{ folder.path || 'Folder' }}</small>
          </span>
          <span class="file-meta">Folder</span>
          <span class="file-meta">{{ formatDocumentDate(folder.updated_at) }}</span>
          <div class="row-actions">
            <button type="button" title="Chat" @click.stop="chatWithFolder(folder)">
              <MessageSquare />
            </button>
            <button type="button" title="More" @click.stop="toggleFolderMenu(folder, $event)">
              <MoreHorizontal />
            </button>
          </div>
        </div>

        <div
          v-for="document in displayDocuments"
          :key="document.id"
          :class="[
            'file-row',
            {
              selected: documentStore.selectedIds.has(document.id),
              'menu-open': isRowMenuOpen(document),
            },
          ]"
          @click="openPreview(document)"
        >
          <button
            :class="['checkbox', { checked: documentStore.selectedIds.has(document.id) }]"
            type="button"
            @click.stop="toggleDocumentSelection(document)"
          >
            <Check v-if="documentStore.selectedIds.has(document.id)" />
          </button>
          <span :class="['file-icon', fileToneFor(document.file_type)]">
            <component :is="fileIconFor(document.file_type)" />
          </span>
          <span class="file-main">
            <strong>{{ document.original_name || document.name }}</strong>
            <small>
              {{ formatDocumentTypeLabel(document.file_type) }}
              <template v-if="document.page_count"> · {{ document.page_count }} pages</template>
              <template v-if="isProcessingStatus(document.status)"> · {{ documentProgress(document.status) }}%</template>
            </small>
            <small v-if="documentFailureMessage(document)" class="file-error-hint">
              {{ documentFailureMessage(document) }}
            </small>
          </span>
          <span :class="['status-pill', document.status]">{{ localizedStatusLabel(document.status) }}</span>
          <span class="file-meta">{{ formatDocumentDate(document.updated_at) }}</span>
          <div class="row-actions">
            <button type="button" title="Chat" @click.stop="chatWithDocument(document)">
              <MessageSquare />
            </button>
            <button type="button" title="More" @click.stop="toggleRowMenu(document, $event)">
              <MoreHorizontal />
            </button>
          </div>
        </div>

        <div v-if="documentStore.loading" class="list-state">
          <Loader2 class="spin" />
          Loading documents...
        </div>
        <div v-else-if="currentFolders.length === 0 && displayDocuments.length === 0" class="list-state">
          No documents in this folder
        </div>
      </div>

      <CreateFolderDialog
        v-model:open="showCreateFolderDialog"
        :parent-id="folderStore.currentFolderId"
        @created="handleFolderCreated"
      />

      <Teleport to="body">
        <div v-if="moveDialogOpen" class="move-overlay" @click="closeMoveDialog">
          <section class="move-modal" @click.stop>
            <header class="move-header">
              <div>
                <h2>{{ lt('移动项目') }}</h2>
                <p>{{ selectionSummary }} · {{ lt('目标位置') }} {{ moveTargetLabel }}</p>
              </div>
              <button type="button" :disabled="selectionActionBusy === 'move'" @click="closeMoveDialog">
                <X />
              </button>
            </header>

            <div class="move-body">
              <div class="move-selected">
                <span>{{ lt('将移动') }}</span>
                <strong>{{ selectedItemLabel }}</strong>
                <small v-if="selectedCount > 1">{{ lt('另有') }} {{ selectedCount - 1 }} {{ lt('个项目') }}</small>
              </div>

              <div class="folder-picker" role="listbox" :aria-label="lt('选择目标文件夹')">
                <button
                  v-for="folder in moveFolderOptions"
                  :key="folder.id || 'root'"
                  :class="{ active: moveTargetFolderId === folder.id }"
                  type="button"
                  role="option"
                  :aria-selected="moveTargetFolderId === folder.id"
                  :style="{ paddingLeft: `${12 + folder.depth * 18}px` }"
                  @click="moveTargetFolderId = folder.id"
                >
                  <FolderOpen v-if="folder.id === null" />
                  <Folder v-else />
                  <span>{{ folder.name }}</span>
                  <small>{{ folder.path }}</small>
                  <Check v-if="moveTargetFolderId === folder.id" />
                </button>
              </div>
            </div>

            <footer class="move-footer">
              <button type="button" :disabled="selectionActionBusy === 'move'" @click="closeMoveDialog">
                {{ lt('取消') }}
              </button>
              <button class="primary" type="button" :disabled="selectionActionBusy === 'move'" @click="moveSelected">
                <Loader2 v-if="selectionActionBusy === 'move'" class="spin" />
                <Move v-else />
                {{ lt('移动到这里') }}
              </button>
            </footer>
          </section>
        </div>
      </Teleport>

      <Teleport to="body">
        <div
          v-if="rowMenuDocument"
          ref="rowMenuRef"
          class="row-menu"
          :style="{
            top: `${rowMenuPosition.top}px`,
            left: `${rowMenuPosition.left}px`,
            maxHeight: `${rowMenuPosition.maxHeight}px`,
          }"
          @click.stop
        >
          <button type="button" @click="chatWithDocument(rowMenuDocument)">
            <MessageSquare />
            <span>{{ lt('在聊天中使用') }}</span>
          </button>
          <button type="button" @click="openPreview(rowMenuDocument)">
            <FileText />
            <span>{{ lt('打开预览') }}</span>
          </button>
          <button type="button" @click="copyDocumentName(rowMenuDocument)">
            <File />
            <span>{{ lt('复制文件名') }}</span>
          </button>
          <button type="button" @click="downloadOne(rowMenuDocument)">
            <Download />
            <span>{{ lt('下载') }}</span>
          </button>
          <button type="button" @click="reindexOne(rowMenuDocument)">
            <RefreshCw />
            <span>{{ lt('重新解析') }}</span>
          </button>
          <button class="danger" type="button" @click="deleteOne(rowMenuDocument)">
            <Trash2 />
            <span>{{ lt('删除') }}</span>
          </button>
        </div>
      </Teleport>

      <Teleport to="body">
        <div
          v-if="rowMenuFolder"
          ref="rowMenuRef"
          class="row-menu"
          :style="{
            top: `${rowMenuPosition.top}px`,
            left: `${rowMenuPosition.left}px`,
            maxHeight: `${rowMenuPosition.maxHeight}px`,
          }"
          @click.stop
        >
          <button type="button" @click="chatWithFolder(rowMenuFolder)">
            <MessageSquare />
            <span>{{ lt('在聊天中使用') }}</span>
          </button>
          <button type="button" @click="goToFolder(rowMenuFolder.id)">
            <FolderOpen />
            <span>{{ lt('打开文件夹') }}</span>
          </button>
          <button type="button" @click="downloadFolder(rowMenuFolder)">
            <Download />
            <span>{{ lt('下载') }}</span>
          </button>
          <button type="button" @click="reindexFolder(rowMenuFolder)">
            <RefreshCw />
            <span>{{ lt('重新解析') }}</span>
          </button>
          <button type="button" @click="moveOneFolder(rowMenuFolder)">
            <Move />
            <span>{{ lt('移动') }}</span>
          </button>
          <button class="danger" type="button" @click="deleteOneFolder(rowMenuFolder)">
            <Trash2 />
            <span>{{ lt('删除') }}</span>
          </button>
        </div>
      </Teleport>

      <Teleport to="body">
        <div v-if="previewOpen" class="preview-overlay" @click="closePreview">
          <section class="preview-modal" @click.stop>
            <header class="preview-header">
              <div>
                <h2>{{ previewDocument?.original_name || previewDocument?.name }}</h2>
                <p>{{ formatDocumentTypeLabel(previewDocument?.file_type) }} · {{ localizedStatusLabel(previewDocument?.status) }}</p>
              </div>
              <button type="button" @click="closePreview">
                <X />
              </button>
            </header>

            <div class="preview-body">
              <aside class="preview-side">
                <div class="preview-tabs">
                  <button :class="{ active: activePreviewTab === 'toc' }" type="button" @click="activePreviewTab = 'toc'">
                    <ListTree />
                    TOC
                  </button>
                  <button :class="{ active: activePreviewTab === 'info' }" type="button" @click="activePreviewTab = 'info'">
                    <FileText />
                    {{ lt('信息') }}
                  </button>
                </div>

                <div class="preview-side-content">
                  <div v-if="previewLoading" class="preview-loading">
                    <Loader2 class="spin" />
                    Loading preview...
                  </div>
                  <TocTree
                    v-else-if="activePreviewTab === 'toc'"
                    :nodes="previewToc"
                    @jump="jumpToPage"
                  />
                  <div v-else class="info-panel">
                    <dl>
                      <div>
                        <dt>{{ lt('原始文件名') }}</dt>
                        <dd>{{ previewDocument?.original_name || previewData?.original_name || previewData?.name }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('文件类型') }}</dt>
                        <dd>{{ formatDocumentTypeLabel(previewDocument?.file_type || previewData?.file_type) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('文件大小') }}</dt>
                        <dd>{{ formatDocumentSize(previewDocument?.file_size || previewData?.file_size) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('所在路径') }}</dt>
                        <dd>{{ previewDocument?.folder_path || previewDocument?.file_path || 'root' }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('页数') }}</dt>
                        <dd>{{ metadataValue(previewDocument?.page_count || previewData?.page_count) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('解析路径') }}</dt>
                        <dd>{{ previewRoute }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('解析总用时') }}</dt>
                        <dd>{{ formatDocumentDuration(previewDocument?.processing_duration || previewData?.processing_duration) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('TOC 节点数') }}</dt>
                        <dd>{{ metadataValue(previewData?.stats?.node_count) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('文本字符数') }}</dt>
                        <dd>{{ metadataValue(previewData?.stats?.text_chars) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('摘要覆盖率') }}</dt>
                        <dd>{{ metadataValue(previewData?.stats?.summary_coverage) }}</dd>
                      </div>
                      <div>
                        <dt>{{ lt('质量报告') }}</dt>
                        <dd>{{ previewQuality.label }} · {{ previewQuality.message }}</dd>
                      </div>
                    </dl>
                  </div>
                </div>
              </aside>

              <main class="preview-document">
                <div v-if="previewLoading" class="preview-loading">
                  <Loader2 class="spin" />
                  Loading preview...
                </div>
                <PdfReferenceViewer
                  v-else-if="previewDocument?.file_type?.toLowerCase() === '.pdf'"
                  ref="pdfViewerRef"
                  :file-url="`/api/documents/${previewDocument.id}/file`"
                  :file-name="previewDocument.original_name || previewDocument.name"
                  :visible="previewOpen"
                  embedded
                  @close="closePreview"
                />
                <UniversalPreview
                  v-else-if="previewDocument"
                  :doc-id="previewDocument.id"
                  :doc-name="previewDocument.original_name || previewDocument.name"
                  :file-type="previewDocument.file_type || ''"
                  raw-only
                />
              </main>
            </div>
          </section>
        </div>
      </Teleport>
    </div>
  </AppShell>
</template>

<style scoped>
.documents-page {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  overflow: hidden;
  padding: 18px 24px 22px;
}

.documents-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.breadcrumb {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.breadcrumb button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 0;
  background: transparent;
  color: var(--kc-text-secondary);
  font-size: 13px;
}

.breadcrumb button.root {
  color: var(--kc-text);
  font-weight: 750;
}

.breadcrumb span {
  color: var(--kc-text-tertiary);
  font-weight: 400;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 250px;
  height: 34px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: var(--kc-surface);
  padding: 0 9px;
}

.search-box input {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  color: var(--kc-text);
  font-size: 12.5px;
  outline: none;
}

.search-box button,
.toolbar-button,
.selection-bar button,
.row-actions button,
.preview-header button,
.move-header button,
.move-footer button {
  border: 0;
  background: transparent;
}

.search-box svg,
.toolbar-button svg,
.selection-bar svg,
.file-icon svg,
.row-actions svg,
.preview-header svg,
.preview-tabs svg,
.checkbox svg,
.list-state svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}

.toolbar-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: var(--kc-surface);
  padding: 0 12px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  font-weight: 560;
}

.toolbar-button.primary {
  border-color: var(--kc-text);
  background: var(--kc-text);
  color: #fff;
}

.toolbar-button:disabled {
  opacity: 0.55;
}

.selection-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
  border: 1px solid rgba(47, 128, 237, 0.24);
  border-radius: var(--kc-radius-md);
  background: #eaf3ff;
  padding: 0 12px;
  color: #145eb8;
  font-size: 12.5px;
}

.selection-summary,
.selection-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.selection-summary strong {
  color: #124f99;
  font-weight: 650;
}

.selection-summary button {
  color: #4d7bb7;
}

.selection-bar button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  border-radius: var(--kc-radius-sm);
  padding: 0 8px;
  color: inherit;
  font-weight: 560;
}

.selection-bar button:hover {
  background: rgba(47, 128, 237, 0.12);
}

.selection-bar button:disabled {
  cursor: default;
  opacity: 0.62;
}

.selection-bar button.danger {
  color: var(--kc-danger);
}

.documents-list {
  min-height: 0;
  overflow-y: auto;
  border-top: 1px solid var(--kc-border);
  border-bottom: 1px solid var(--kc-border);
  background: rgba(255, 255, 255, 0.58);
}

.list-header,
.file-row {
  display: grid;
  grid-template-columns: 34px 42px minmax(220px, 1fr) minmax(100px, 140px) minmax(120px, 160px) 74px;
  align-items: center;
  gap: 10px;
  min-height: 54px;
  border-bottom: 1px solid var(--kc-border-soft);
  padding: 0 14px;
}

.list-header {
  position: sticky;
  top: 0;
  z-index: 5;
  min-height: 42px;
  background: rgba(246, 247, 249, 0.94);
  color: var(--kc-text-secondary);
  font-size: 12px;
  font-weight: 650;
  backdrop-filter: blur(18px);
}

.list-total {
  grid-column: 4 / span 2;
  justify-self: end;
  color: var(--kc-text-tertiary);
  font-weight: 500;
}

.list-header > span:not(.list-total) {
  grid-column: 2 / span 2;
  white-space: nowrap;
}

.file-row {
  width: 100%;
  border-right: 0;
  border-left: 0;
  background: transparent;
  color: var(--kc-text);
  text-align: left;
}

.file-row:hover {
  background: #fff;
}

.file-row.selected {
  background: #f7fbff;
}

.file-row.menu-open {
  background: #fff;
}

.file-row.sample {
  cursor: pointer;
}

.folder-row {
  cursor: pointer;
}

.checkbox {
  display: grid;
  width: 18px;
  height: 18px;
  place-items: center;
  border: 1px solid #cfd6df;
  border-radius: var(--kc-radius-xs);
  background: #fff;
  color: #fff;
}

.checkbox.checked {
  border-color: var(--kc-accent);
  background: var(--kc-accent);
}

.checkbox:disabled {
  border-color: #dce2ea;
  background: rgba(255, 255, 255, 0.7);
  cursor: default;
  opacity: 0.55;
}

.checkbox.ghost {
  border-color: transparent;
  background: transparent;
}

.file-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid transparent;
  border-radius: var(--kc-radius-md);
  background: var(--kc-surface-muted);
  color: var(--kc-text-secondary);
}

.file-icon.folder,
.file-icon.word {
  background: #eff6ff;
  color: #2563eb;
}

.file-icon.pdf {
  background: #fef2f2;
  color: #dc2626;
}

.file-icon.sheet {
  background: #ecfdf3;
  color: #15803d;
}

.file-icon.deck {
  background: #fff7ed;
  color: #ea580c;
}

.file-icon.code {
  background: #f8fafc;
  color: #475569;
}

.file-icon.image {
  background: #f0f9ff;
  color: #0284c7;
}

.file-main {
  min-width: 0;
}

.file-main strong,
.file-main small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-main strong {
  font-size: 13px;
  font-weight: 600;
}

.file-main small,
.file-meta {
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.file-main .file-error-hint {
  margin-top: 2px;
  color: #b42318;
  line-height: 16px;
  overflow: visible;
  text-overflow: clip;
  white-space: normal;
}

.status-pill {
  display: inline-flex;
  width: fit-content;
  max-width: 132px;
  align-items: center;
  border-radius: 999px;
  background: var(--kc-surface-muted);
  padding: 4px 8px;
  color: var(--kc-text-secondary);
  font-size: 11.5px;
}

.status-pill.completed {
  background: #ecfdf3;
  color: #15803d;
}

.status-pill.pending,
.status-pill[class*="processing"] {
  background: #eff6ff;
  color: #1d4ed8;
}

.status-pill[class*="failed"] {
  background: #fef2f2;
  color: #dc2626;
}

.row-actions {
  position: relative;
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  opacity: 0;
}

.file-row:hover .row-actions,
.file-row.menu-open .row-actions {
  opacity: 1;
}

.row-actions button {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: var(--kc-radius-sm);
  color: var(--kc-text-tertiary);
}

.row-actions button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.row-menu {
  position: fixed;
  z-index: 80;
  display: grid;
  width: 176px;
  box-sizing: border-box;
  gap: 2px;
  overflow-y: auto;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-lg);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: var(--kc-shadow-popover);
  padding: 6px;
  backdrop-filter: blur(18px);
}

.row-menu button {
  display: flex;
  width: 100%;
  height: 32px;
  align-items: center;
  gap: 9px;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  padding: 0 9px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  text-align: left;
}

.row-menu button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.row-menu button:disabled {
  color: var(--kc-text-tertiary);
  cursor: default;
  opacity: 0.45;
}

.row-menu button:disabled:hover {
  background: transparent;
}

.row-menu button.danger {
  color: var(--kc-danger);
}

.row-menu svg {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
  stroke-width: 1.85;
}

.move-overlay {
  position: fixed;
  inset: 0;
  z-index: 75;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.22);
  backdrop-filter: blur(6px);
}

.move-modal {
  display: grid;
  width: min(520px, calc(100vw - 48px));
  max-height: min(620px, calc(100vh - 48px));
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: var(--kc-radius-lg);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: var(--kc-shadow-modal);
}

.move-header,
.move-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--kc-border);
  padding: 14px 16px;
}

.move-header h2,
.move-header p {
  margin: 0;
}

.move-header h2 {
  font-size: 15px;
  font-weight: 650;
}

.move-header p {
  margin-top: 3px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.move-header button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 999px;
  color: var(--kc-text-secondary);
}

.move-header button:hover {
  background: var(--kc-surface-muted);
}

.move-body {
  display: grid;
  min-height: 0;
  gap: 12px;
  padding: 14px 16px;
}

.move-selected {
  display: grid;
  gap: 3px;
  border: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-md);
  background: var(--kc-surface-muted);
  padding: 10px 12px;
}

.move-selected span,
.move-selected small {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
}

.move-selected strong {
  overflow: hidden;
  color: var(--kc-text);
  font-size: 12.5px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-picker {
  display: grid;
  max-height: 360px;
  overflow-y: auto;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
}

.folder-picker button {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr) auto 18px;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  border: 0;
  border-bottom: 1px solid var(--kc-border-soft);
  background: transparent;
  padding: 0 12px;
  color: var(--kc-text-secondary);
  text-align: left;
}

.folder-picker button:last-child {
  border-bottom: 0;
}

.folder-picker button:hover,
.folder-picker button.active {
  background: #f7fbff;
  color: var(--kc-text);
}

.folder-picker svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}

.folder-picker span {
  min-width: 0;
  overflow: hidden;
  font-size: 12.5px;
  font-weight: 560;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-picker small {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
}

.folder-picker button > svg:last-child {
  color: var(--kc-accent);
}

.move-footer {
  justify-content: flex-end;
  border-top: 1px solid var(--kc-border);
  border-bottom: 0;
  background: #fbfcfd;
}

.move-footer button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  border-radius: var(--kc-radius-md);
  padding: 0 12px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  font-weight: 560;
}

.move-footer button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.move-footer button.primary {
  background: var(--kc-text);
  color: #fff;
}

.move-footer button:disabled {
  cursor: default;
  opacity: 0.62;
}

.row-more {
  justify-self: end;
  width: 16px;
  height: 16px;
  color: var(--kc-text-tertiary);
}

.list-state,
.error-banner,
.notice-banner,
.preview-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--kc-text-tertiary);
  font-size: 13px;
}

.list-state {
  min-height: 160px;
}

.error-banner {
  justify-content: flex-start;
  border: 1px solid #fecaca;
  border-radius: var(--kc-radius-md);
  background: #fef2f2;
  padding: 10px 12px;
  color: #b91c1c;
}

.notice-banner {
  justify-content: flex-start;
  border: 1px solid rgba(47, 128, 237, 0.22);
  border-radius: var(--kc-radius-md);
  background: #f3f8ff;
  padding: 10px 12px;
  color: #145eb8;
}

.preview-overlay {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.24);
  backdrop-filter: blur(6px);
}

.preview-modal {
  display: grid;
  width: min(1280px, calc(100vw - 72px));
  height: calc(100vh - 72px);
  min-height: 0;
  grid-template-rows: 58px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: var(--kc-radius-lg);
  background: var(--kc-surface);
  box-shadow: var(--kc-shadow-modal);
}

.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--kc-border);
  padding: 0 16px 0 20px;
}

.preview-header h2,
.preview-header p {
  margin: 0;
}

.preview-header h2 {
  max-width: 840px;
  overflow: hidden;
  font-size: 15px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-header p {
  margin-top: 2px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.preview-header button {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 999px;
  color: var(--kc-text-secondary);
}

.preview-header button:hover {
  background: var(--kc-surface-muted);
}

.preview-body {
  display: grid;
  min-height: 0;
  grid-template-columns: 330px minmax(0, 1fr);
}

.preview-side {
  display: grid;
  min-height: 0;
  grid-template-columns: 72px minmax(0, 1fr);
  border-right: 1px solid var(--kc-border);
  background: #fbfcfd;
}

.preview-tabs {
  display: grid;
  align-content: start;
  gap: 6px;
  border-right: 1px solid var(--kc-border-soft);
  padding: 12px 8px;
}

.preview-tabs button {
  display: grid;
  gap: 4px;
  min-height: 52px;
  place-items: center;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.preview-tabs button.active {
  background: #eaf3ff;
  color: #145eb8;
}

.preview-side-content,
.preview-document {
  min-height: 0;
  overflow: auto;
}

.preview-side-content {
  padding: 14px;
}

.preview-document {
  background: var(--kc-bg);
}

.info-panel dl {
  display: grid;
  gap: 12px;
  margin: 0;
}

.info-panel div {
  display: grid;
  gap: 3px;
}

.info-panel dt {
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.info-panel dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: var(--kc-text);
  font-size: 12.5px;
  line-height: 18px;
}

.sample-preview {
  display: grid;
  align-content: start;
  gap: 14px;
  min-height: 100%;
  padding: 28px;
}

.sample-sheet {
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-lg);
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
}

.sample-sheet {
  overflow: hidden;
}

.sample-sheet header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--kc-border-soft);
  padding: 16px 18px;
}

.sample-sheet header span,
.sample-sheet header strong {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  font-weight: 560;
}

.sample-sheet h3 {
  margin: 0;
}

.sample-sheet h3 {
  margin-top: 3px;
  color: var(--kc-text);
  font-size: 15px;
  font-weight: 650;
}

.sample-sheet table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.sample-sheet th,
.sample-sheet td {
  border-bottom: 1px solid var(--kc-border-soft);
  padding: 12px 14px;
  text-align: left;
}

.sample-sheet th {
  background: #f8fafc;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  font-weight: 650;
}

.sample-sheet td {
  color: var(--kc-text-secondary);
}

.sample-sheet tr:last-child td {
  border-bottom: 0;
}

.sample-sheet td.positive {
  color: #15803d;
  font-weight: 650;
}

.sample-sheet td.negative {
  color: #dc2626;
  font-weight: 650;
}

.hidden-input {
  display: none;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 980px) {
  .list-header,
  .file-row {
    grid-template-columns: 30px 38px minmax(160px, 1fr) 96px 66px;
  }

  .file-meta {
    display: none;
  }

  .preview-body {
    grid-template-columns: 290px minmax(0, 1fr);
  }
}
</style>
