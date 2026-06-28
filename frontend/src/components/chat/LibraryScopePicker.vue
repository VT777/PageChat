<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  Check,
  ChevronRight,
  File,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Folder,
  Presentation,
  Search,
  X,
} from 'lucide-vue-next'
import { documentApi } from '@/api'
import { folderApi, type Folder as FolderModel } from '@/api/folders'
import type { Document } from '@/stores/document'
import { documentPresentationForType } from '@/ui/pagechatContracts'
import { formatDocumentSize, formatDocumentTypeLabel } from '@/utils/documentWorkbench'
import { useI18n } from '@/i18n/messages'

const props = defineProps<{
  selectedDocumentIds: string[]
  selectedFolderIds: string[]
}>()

const emit = defineEmits<{
  close: []
  'toggle-document': [document: Document]
  'toggle-folder': [folder: FolderModel]
}>()

const { t } = useI18n()

const currentFolderId = ref<string | null>(null)
const folderStack = ref<FolderModel[]>([])
const folders = ref<FolderModel[]>([])
const documents = ref<Document[]>([])
const loading = ref(false)
const searchQuery = ref('')

const fileIconMap = {
  File,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Presentation,
}

const breadcrumbItems = computed(() => [
  { id: null as string | null, label: 'root', index: -1 },
  ...folderStack.value.map((folder, index) => ({
    id: folder.id,
    label: folder.name,
    index,
  })),
])

const normalizedSearch = computed(() => searchQuery.value.trim().toLowerCase())
const filteredFolders = computed(() => {
  const query = normalizedSearch.value
  if (!query) return folders.value
  return folders.value.filter((folder) => [folder.name, folder.path].join(' ').toLowerCase().includes(query))
})
const filteredDocuments = computed(() => {
  const query = normalizedSearch.value
  if (!query) return documents.value
  return documents.value.filter((document) => [
    document.original_name,
    document.name,
    document.file_type,
  ].join(' ').toLowerCase().includes(query))
})

function fileIconFor(fileType?: string) {
  return fileIconMap[documentPresentationForType(fileType).icon as keyof typeof fileIconMap] || File
}

async function loadCurrentFolder() {
  loading.value = true
  try {
    const [folderResponse, documentResponse] = await Promise.all([
      folderApi.list(currentFolderId.value),
      documentApi.list({
        page: 1,
        page_size: 100,
        folder_id: currentFolderId.value,
        include_subfolders: false,
      }),
    ])
    folders.value = folderResponse.data.items || []
    documents.value = (documentResponse.data.items || []).filter(
      (document: Document) => document.status === 'completed',
    )
  } catch (error) {
    console.error('Failed to load library picker contents:', error)
    folders.value = []
    documents.value = []
  } finally {
    loading.value = false
  }
}

function openFolder(folder: FolderModel) {
  currentFolderId.value = folder.id
  folderStack.value = [...folderStack.value, folder]
}

function jumpToBreadcrumb(index: number) {
  if (index < 0) {
    currentFolderId.value = null
    folderStack.value = []
    return
  }
  const nextStack = folderStack.value.slice(0, index + 1)
  currentFolderId.value = nextStack[nextStack.length - 1]?.id || null
  folderStack.value = nextStack
}

function isDocumentSelected(id: string) {
  return props.selectedDocumentIds.includes(id)
}

function isFolderSelected(id: string) {
  return props.selectedFolderIds.includes(id)
}

watch(currentFolderId, () => {
  void loadCurrentFolder()
})

onMounted(() => {
  void loadCurrentFolder()
})
</script>

<template>
  <div class="scope-picker library-scope-picker">
    <div class="scope-picker-header">
      <div>
        <strong>{{ t('composer.library') }}</strong>
        <span>{{ t('composer.selectFileHint') }}</span>
      </div>
      <button type="button" @click="emit('close')">
        <X />
      </button>
    </div>

    <div class="library-search">
      <Search />
      <input v-model="searchQuery" type="search" placeholder="Search" />
    </div>

    <div class="library-breadcrumb" aria-label="Current folder">
      <button
        v-for="item in breadcrumbItems"
        :key="item.id || 'root'"
        type="button"
        :class="{ root: item.id === null }"
        @click="jumpToBreadcrumb(item.index)"
      >
        {{ item.label }}
      </button>
    </div>

    <div class="scope-picker-list">
      <div v-if="loading" class="scope-picker-empty">{{ t('composer.loadingFiles') }}</div>
      <template v-else>
        <div
          v-for="folder in filteredFolders"
          :key="folder.id"
          :class="['scope-picker-row', { selected: isFolderSelected(folder.id) }]"
        >
          <button class="scope-select" type="button" @click="emit('toggle-folder', folder)">
            <Check v-if="isFolderSelected(folder.id)" />
          </button>
          <button class="scope-row-main" type="button" @click="openFolder(folder)">
            <span class="scope-picker-icon folder">
              <Folder />
            </span>
            <span class="scope-picker-main">
              <strong>{{ folder.name }}</strong>
              <small>{{ folder.path || 'root' }}</small>
            </span>
            <ChevronRight class="scope-row-open" />
          </button>
        </div>

        <button
          v-for="document in filteredDocuments"
          :key="document.id"
          :class="['scope-picker-row', { selected: isDocumentSelected(document.id) }]"
          type="button"
          @click="emit('toggle-document', document)"
        >
          <span class="scope-select">
            <Check v-if="isDocumentSelected(document.id)" />
          </span>
          <span :class="['scope-picker-icon', documentPresentationForType(document.file_type).tone]">
            <component :is="fileIconFor(document.file_type)" />
          </span>
          <span class="scope-picker-main">
            <strong>{{ document.original_name || document.name }}</strong>
            <small>
              {{ formatDocumentTypeLabel(document.file_type) }}
              <template v-if="document.file_size"> · {{ formatDocumentSize(document.file_size) }}</template>
            </small>
          </span>
        </button>

        <div v-if="filteredFolders.length === 0 && filteredDocuments.length === 0" class="scope-picker-empty">
          {{ t('composer.noFiles') }}
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.scope-picker {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 0;
  z-index: 15;
  width: min(480px, 100%);
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-lg);
  background: var(--kc-surface);
  box-shadow: var(--kc-shadow-popover);
  padding: 9px;
}

.scope-picker-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 4px 8px;
}

.scope-picker-header strong,
.scope-picker-header span {
  display: block;
}

.scope-picker-header strong {
  color: var(--kc-text);
  font-size: 13px;
}

.scope-picker-header span {
  color: var(--kc-text-tertiary);
  font-size: 12px;
  line-height: 17px;
}

.scope-picker-header button {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--kc-text-tertiary);
}

.library-search {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 10px;
}

.library-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  outline: none;
}

.library-breadcrumb {
  display: flex;
  align-items: center;
  gap: 5px;
  overflow-x: auto;
  padding: 8px 2px;
}

.library-breadcrumb button {
  height: 24px;
  flex: 0 0 auto;
  border: 0;
  border-radius: 999px;
  background: transparent;
  padding: 0 8px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.library-breadcrumb button.root {
  color: var(--kc-text);
  font-weight: 700;
}

.library-breadcrumb button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.scope-picker-list {
  display: grid;
  max-height: 308px;
  overflow-y: auto;
  gap: 3px;
}

.scope-picker-row,
.scope-row-main {
  display: flex;
  align-items: center;
  border: 0;
  background: transparent;
  color: var(--kc-text-secondary);
  text-align: left;
}

.scope-picker-row {
  width: 100%;
  min-height: 52px;
  gap: 8px;
  border-radius: var(--kc-radius-md);
  padding: 6px 8px;
}

.scope-picker-row:hover,
.scope-picker-row.selected {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.scope-row-main {
  min-width: 0;
  flex: 1;
  gap: 10px;
  padding: 0;
}

.scope-select {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  place-items: center;
  border: 1px solid var(--kc-border);
  border-radius: 6px;
  background: #fff;
  color: var(--kc-accent);
}

.scope-picker-icon {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border-radius: 9px;
  background: var(--kc-surface-muted);
  color: var(--kc-text-secondary);
}

.scope-picker-icon.pdf { background: #fff1f2; color: #be123c; }
.scope-picker-icon.sheet { background: #ecfdf3; color: #15803d; }
.scope-picker-icon.word { background: #eaf3ff; color: #1d4ed8; }
.scope-picker-icon.deck { background: #fff7ed; color: #c2410c; }
.scope-picker-icon.code { background: #f5f3ff; color: #6d28d9; }
.scope-picker-icon.image { background: #fdf2f8; color: #be185d; }
.scope-picker-icon.folder { background: #eef6ff; color: #2563eb; }

.scope-picker-main {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.scope-picker-main strong,
.scope-picker-main small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-picker-main strong {
  color: var(--kc-text);
  font-size: 12.7px;
  font-weight: 590;
}

.scope-picker-main small {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  line-height: 16px;
}

.scope-row-open {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
  color: var(--kc-text-tertiary);
}

.scope-picker-empty {
  display: grid;
  min-height: 64px;
  place-items: center;
  border: 1px dashed var(--kc-border);
  border-radius: var(--kc-radius-md);
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.scope-picker svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}
</style>