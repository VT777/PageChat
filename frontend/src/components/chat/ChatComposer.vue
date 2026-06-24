<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowUp,
  Check,
  File,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Folder,
  Globe,
  ImagePlus,
  Plus,
  Presentation,
  X,
} from 'lucide-vue-next'
import { useDocumentStore } from '@/stores/document'
import type { Document } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'
import { useChatStore } from '@/stores/chat'
import type { Folder as FolderModel } from '@/api/folders'
import {
  COMPOSER_ACTIONS,
  documentOnlyChatContexts,
  documentPresentationForType,
  resolveDocumentChatContext,
} from '@/ui/pagechatContracts'
import {
  DEMO_LIBRARY_DOCUMENTS,
  DEMO_LIBRARY_FOLDERS,
  DEMO_FOLDER_ID,
  shouldShowDemoLibrary,
} from '@/ui/demoLibrary'
import { formatDocumentSize, formatDocumentTypeLabel } from '@/utils/documentWorkbench'

interface ImageAttachment {
  id: string
  name: string
  url: string
  file: File
}

interface ComposerSubmitPayload {
  text: string
  webSearch: boolean
  documentIds: string[]
  folderIds: string[]
  images: ImageAttachment[]
}

interface InitialDocumentContext {
  id: string
  label: string
  type?: 'document' | 'folder'
}

const props = withDefaults(defineProps<{
  disabled?: boolean
  initialDocumentContext?: InitialDocumentContext | InitialDocumentContext[] | null
  initialFolderContext?: InitialDocumentContext | InitialDocumentContext[] | null
}>(), {
  disabled: false,
  initialDocumentContext: null,
  initialFolderContext: null,
})

const emit = defineEmits<{
  submit: [payload: ComposerSubmitPayload]
}>()

const documentStore = useDocumentStore()
const folderStore = useFolderStore()
const chatStore = useChatStore()

const text = ref('')
const showMenu = ref(false)
const pickerMode = ref<'file' | 'folder' | null>(null)
const webSearch = ref(false)
const selectedDocumentIds = ref<string[]>([])
const selectedFolderIds = ref<string[]>([])
const images = ref<ImageAttachment[]>([])
const imageInputRef = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const canSend = computed(() => text.value.trim().length > 0 && !props.disabled)
const initialDocumentContexts = computed(() => {
  return documentOnlyChatContexts(toContextArray(props.initialDocumentContext))
})
const selectedDocumentChips = computed(() =>
  selectedDocumentIds.value.map(documentContextForId)
)
const isDraftChat = computed(() => !chatStore.currentSessionId)
const useDemoPickerData = computed(() => shouldShowDemoLibrary({
  loading: documentStore.loading || folderStore.loading,
  folderCount: folderStore.folders.length,
  documentCount: documentStore.documents.length,
  searchQuery: '',
}))
const pickerDocuments = computed<Document[]>(() =>
  useDemoPickerData.value ? DEMO_LIBRARY_DOCUMENTS : documentStore.documents
)
const pickerFolders = computed<FolderModel[]>(() =>
  useDemoPickerData.value ? DEMO_LIBRARY_FOLDERS : folderStore.folders
)
const initialFolderContexts = computed(() => {
  return toFolderContexts(props.initialFolderContext)
})
const selectedFolderChips = computed(() =>
  selectedFolderIds.value.map(folderContextForId)
)

const actionIconMap = {
  ImagePlus,
  Globe,
  FileText,
  Folder,
}
const fileIconMap = {
  File,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType,
  Presentation,
}

function triggerAction(actionId: string) {
  if (actionId === 'image') {
    imageInputRef.value?.click()
    showMenu.value = false
    return
  }
  if (actionId === 'web-search') {
    webSearch.value = !webSearch.value
    showMenu.value = false
    return
  }
  pickerMode.value = actionId === 'file' ? 'file' : 'folder'
  showMenu.value = false
}

function toContextArray(context: InitialDocumentContext | InitialDocumentContext[] | null) {
  if (Array.isArray(context)) return context
  return context ? [context] : []
}

function toFolderContexts(context: InitialDocumentContext | InitialDocumentContext[] | null) {
  return toContextArray(context).map((item) => ({
    ...item,
    type: 'folder' as const,
  }))
}

function handleImageChange(event: Event) {
  const input = event.target as HTMLInputElement
  addImages(Array.from(input.files || []))
  input.value = ''
}

function addImages(files: File[]) {
  const next = files
    .filter((file) => file.type.startsWith('image/'))
    .map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      url: URL.createObjectURL(file),
      file,
    }))
  images.value = [...images.value, ...next].slice(0, 6)
}

function removeImage(id: string) {
  const image = images.value.find((item) => item.id === id)
  if (image) URL.revokeObjectURL(image.url)
  images.value = images.value.filter((item) => item.id !== id)
}

function toggleDocument(id: string) {
  if (selectedDocumentIds.value.includes(id)) {
    selectedDocumentIds.value = selectedDocumentIds.value.filter((item) => item !== id)
    syncDocumentContextsToStore()
    return
  }
  selectedDocumentIds.value = [...selectedDocumentIds.value, id]
  syncDocumentContextsToStore()
}

function selectFolder(id: string) {
  if (selectedFolderIds.value.includes(id)) {
    selectedFolderIds.value = selectedFolderIds.value.filter((item) => item !== id)
    syncFolderContextsToStore()
    return
  }
  selectedFolderIds.value = [...selectedFolderIds.value, id]
  syncFolderContextsToStore()
}

function removeDocumentScope(id: string) {
  selectedDocumentIds.value = selectedDocumentIds.value.filter((item) => item !== id)
  syncDocumentContextsToStore()
}

function removeFolderScope(id: string) {
  selectedFolderIds.value = selectedFolderIds.value.filter((item) => item !== id)
  syncFolderContextsToStore()
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || [])
  if (files.some((file) => file.type.startsWith('image/'))) {
    addImages(files)
  }
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submit()
  }
}

function submit() {
  if (!canSend.value) return
  emit('submit', {
    text: text.value.trim(),
    webSearch: webSearch.value,
    documentIds: selectedDocumentIds.value,
    folderIds: selectedFolderIds.value,
    images: images.value,
  })
  text.value = ''
  images.value.forEach((image) => URL.revokeObjectURL(image.url))
  images.value = []
}

function documentContextForId(id: string) {
  return resolveDocumentChatContext(id, initialDocumentContexts.value, pickerDocuments.value)
}

function folderContextForId(id: string) {
  const folder = pickerFolders.value.find((item) => item.id === id)
  if (folder) return { id: folder.id, label: folder.name, type: 'folder' as const }
  const initialContext = initialFolderContexts.value.find((item) => item.id === id)
  if (initialContext) return { ...initialContext, type: 'folder' as const }
  return { id, label: id, type: 'folder' as const }
}

function fileIconFor(fileType?: string) {
  return fileIconMap[documentPresentationForType(fileType).icon as keyof typeof fileIconMap] || File
}

function folderDetail(folder: FolderModel) {
  const documentCount = folder.id === DEMO_FOLDER_ID ? DEMO_LIBRARY_DOCUMENTS.length : null
  return [
    documentCount ? `${documentCount} 个文件` : '文件夹',
    folder.path || 'root',
  ].join(' · ')
}

function syncDocumentContextsToStore() {
  if (selectedDocumentIds.value.length === 0) {
    chatStore.clearDocumentContexts()
    return
  }
  chatStore.setDocumentContexts(selectedDocumentIds.value.map(documentContextForId))
}

function syncFolderContextsToStore() {
  if (selectedFolderIds.value.length === 0) {
    chatStore.clearFolderContexts()
    return
  }
  chatStore.setFolderContexts(selectedFolderIds.value.map(folderContextForId))
}

function setText(value: string) {
  text.value = value
}

function focus() {
  textareaRef.value?.focus()
}

defineExpose({
  setText,
  focus,
})

watch(() => props.initialDocumentContext, (context) => {
  const contexts = documentOnlyChatContexts(toContextArray(context))
  selectedDocumentIds.value = contexts.map((item) => item.id)
}, { immediate: true })

watch(() => props.initialFolderContext, (context) => {
  const contexts = toFolderContexts(context)
  selectedFolderIds.value = contexts.map((item) => item.id)
}, { immediate: true })

watch(() => chatStore.currentSessionId, (sessionId) => {
  if (sessionId) {
    text.value = ''
    return
  }
  if (text.value !== chatStore.draftComposerText) {
    text.value = chatStore.draftComposerText
  }
}, { immediate: true })

watch(() => chatStore.draftComposerText, (value) => {
  if (isDraftChat.value && text.value !== value) {
    text.value = value
  }
})

watch(text, (value) => {
  if (isDraftChat.value && value !== chatStore.draftComposerText) {
    chatStore.setDraftComposerText(value)
  }
})

onMounted(() => {
  if (documentStore.documents.length === 0) {
    documentStore.fetchDocuments(1, undefined, null, true, 20)
  }
  if (folderStore.folders.length === 0) {
    folderStore.fetchFolders()
  }
})

onBeforeUnmount(() => {
  images.value.forEach((image) => URL.revokeObjectURL(image.url))
})
</script>

<template>
  <div class="composer-shell">
    <div v-if="pickerMode" class="scope-picker">
      <div class="scope-picker-header">
        <div>
          <strong>{{ pickerMode === 'file' ? '选择文件' : '选择文件夹' }}</strong>
          <span>{{ pickerMode === 'file' ? '限定这次回答使用的文档' : '限定这次回答使用的文件夹' }}</span>
        </div>
        <button type="button" @click="pickerMode = null">
          <X />
        </button>
      </div>

      <div v-if="pickerMode === 'file'" class="scope-picker-list">
        <button
          v-for="document in pickerDocuments.slice(0, 12)"
          :key="document.id"
          :class="['scope-picker-row', { selected: selectedDocumentIds.includes(document.id) }]"
          type="button"
          @click="toggleDocument(document.id)"
        >
          <span :class="['scope-picker-icon', documentPresentationForType(document.file_type).tone]">
            <component :is="fileIconFor(document.file_type)" />
          </span>
          <span class="scope-picker-main">
            <strong>{{ document.original_name || document.name }}</strong>
            <small>
              {{ formatDocumentTypeLabel(document.file_type) }}
              <template v-if="document.file_size"> · {{ formatDocumentSize(document.file_size) }}</template>
              <template v-if="document.folder_path"> · {{ document.folder_path }}</template>
            </small>
          </span>
          <Check v-if="selectedDocumentIds.includes(document.id)" class="scope-picker-check" />
        </button>
        <div v-if="pickerDocuments.length === 0" class="scope-picker-empty">
          暂无可选择文件
        </div>
      </div>

      <div v-else class="scope-picker-list">
        <button
          v-for="folder in pickerFolders.slice(0, 12)"
          :key="folder.id"
          :class="['scope-picker-row', { selected: selectedFolderIds.includes(folder.id) }]"
          type="button"
          @click="selectFolder(folder.id)"
        >
          <span class="scope-picker-icon folder">
            <Folder />
          </span>
          <span class="scope-picker-main">
            <strong>{{ folder.name }}</strong>
            <small>{{ folderDetail(folder) }}</small>
          </span>
          <Check v-if="selectedFolderIds.includes(folder.id)" class="scope-picker-check" />
        </button>
        <div v-if="pickerFolders.length === 0" class="scope-picker-empty">
          暂无可选择文件夹
        </div>
      </div>
    </div>

    <div class="composer-card">
      <div v-if="images.length > 0" class="image-strip">
        <div v-for="image in images" :key="image.id" class="image-chip">
          <img :src="image.url" :alt="image.name" />
          <button type="button" @click="removeImage(image.id)">
            <X />
          </button>
        </div>
      </div>

      <textarea
        ref="textareaRef"
        v-model="text"
        :disabled="disabled"
        rows="1"
        placeholder="Ask PageChat about your documents..."
        @keydown="handleKeydown"
        @paste="handlePaste"
      />

      <div class="composer-footer">
        <div class="composer-left">
          <button
            :class="['composer-plus', { active: showMenu }]"
            type="button"
            aria-label="Add context"
            @click="showMenu = !showMenu"
          >
            <Plus />
          </button>

          <div v-if="showMenu" class="composer-menu">
            <button
              v-for="action in COMPOSER_ACTIONS"
              :key="action.id"
              :class="{ selected: action.id === 'web-search' && webSearch }"
              type="button"
              @click="triggerAction(action.id)"
            >
              <component :is="actionIconMap[action.icon as keyof typeof actionIconMap]" />
              <span>{{ action.label }}</span>
              <Check v-if="action.id === 'web-search' && webSearch" class="menu-check" />
            </button>
          </div>

          <button v-if="webSearch" class="context-chip active" type="button" @click="webSearch = false">
            <span class="chip-icon"><Globe /></span>
            <span>搜索</span>
          </button>
          <button
            v-for="document in selectedDocumentChips"
            :key="document.id"
            class="context-chip"
            type="button"
            :title="document.label"
            @click="removeDocumentScope(document.id)"
          >
            <span class="chip-icon"><FileText /></span>
            <span>{{ document.label }}</span>
          </button>
          <button
            v-for="folder in selectedFolderChips"
            :key="folder.id"
            class="context-chip"
            type="button"
            :title="folder.label"
            @click="removeFolderScope(folder.id)"
          >
            <span class="chip-icon"><Folder /></span>
            <span>{{ folder.label }}</span>
          </button>
        </div>

        <button class="send-button" type="button" :disabled="!canSend" @click="submit">
          <ArrowUp />
        </button>
      </div>
    </div>

    <input
      ref="imageInputRef"
      class="hidden-input"
      type="file"
      accept="image/*"
      multiple
      @change="handleImageChange"
    />
  </div>
</template>

<style scoped>
.composer-shell {
  position: relative;
  width: min(860px, calc(100vw - 360px));
}

.composer-card {
  border: 1px solid rgba(209, 213, 219, 0.9);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 18px 48px rgba(15, 23, 42, 0.11);
  padding: 10px;
}

textarea {
  display: block;
  width: 100%;
  max-height: 140px;
  min-height: 34px;
  resize: none;
  border: 0;
  background: transparent;
  padding: 6px 8px;
  color: var(--kc-text);
  font-size: 13px;
  line-height: 20px;
  outline: none;
}

textarea:focus {
  box-shadow: none;
}

.composer-footer {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  min-height: 36px;
}

.composer-left {
  position: relative;
  display: flex;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.composer-plus,
.send-button {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  transition: background 150ms ease, color 150ms ease, opacity 150ms ease;
}

.composer-plus {
  background: var(--kc-surface-muted);
  color: var(--kc-text-secondary);
}

.composer-plus.active,
.composer-plus:hover {
  background: #eaf3ff;
  color: var(--kc-accent);
}

.send-button {
  background: var(--kc-text);
  color: #fff;
}

.send-button:disabled {
  cursor: default;
  opacity: 0.36;
}

.composer-plus svg,
.send-button svg,
.composer-menu svg,
.context-chip svg,
.scope-picker svg,
.image-chip button svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}

.composer-menu {
  position: absolute;
  bottom: 40px;
  left: 0;
  z-index: 20;
  width: 198px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-lg);
  background: var(--kc-surface);
  box-shadow: var(--kc-shadow-popover);
  padding: 6px;
}

.composer-menu button,
.scope-picker-row {
  display: flex;
  align-items: center;
  width: 100%;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  color: var(--kc-text-secondary);
  text-align: left;
}

.composer-menu button {
  gap: 10px;
  height: 34px;
  padding: 0 9px;
  font-size: 13px;
}

.composer-menu button:hover,
.composer-menu button.selected,
.scope-picker-row:hover,
.scope-picker-row.selected {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.composer-menu span,
.context-chip span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-check {
  margin-left: auto;
  color: var(--kc-accent);
}

.context-chip {
  display: inline-flex;
  max-width: 240px;
  align-items: center;
  gap: 6px;
  height: 28px;
  border: 1px solid var(--kc-border);
  border-radius: 999px;
  background: #fff;
  padding: 0 10px 0 6px;
  color: var(--kc-text-secondary);
  font-size: 12px;
}

.context-chip.active {
  border-color: rgba(47, 128, 237, 0.28);
  background: #eaf3ff;
  color: #145eb8;
}

.chip-icon {
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 999px;
}

.context-chip:hover .chip-icon {
  background: rgba(15, 23, 42, 0.08);
}

.context-chip:hover .chip-icon svg {
  display: none;
}

.context-chip:hover .chip-icon::before {
  content: "×";
  font-size: 15px;
  line-height: 1;
}

.image-strip {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 2px 8px;
}

.image-chip {
  position: relative;
  width: 78px;
  height: 58px;
  flex: 0 0 78px;
  overflow: hidden;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: var(--kc-surface-muted);
}

.image-chip img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.image-chip button {
  position: absolute;
  top: 4px;
  right: 4px;
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.72);
  color: #fff;
}

.scope-picker {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 0;
  z-index: 15;
  width: min(460px, 100%);
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

.scope-picker-header strong {
  display: block;
  color: var(--kc-text);
  font-size: 13px;
}

.scope-picker-header span {
  display: block;
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

.scope-picker-list {
  display: grid;
  max-height: 292px;
  overflow-y: auto;
  gap: 3px;
}

.scope-picker-row {
  gap: 10px;
  min-height: 52px;
  padding: 7px 8px;
  font-size: 12.5px;
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

.scope-picker-icon.pdf {
  background: #fff1f2;
  color: #be123c;
}

.scope-picker-icon.sheet {
  background: #ecfdf3;
  color: #15803d;
}

.scope-picker-icon.word {
  background: #eaf3ff;
  color: #1d4ed8;
}

.scope-picker-icon.deck {
  background: #fff7ed;
  color: #c2410c;
}

.scope-picker-icon.code {
  background: #f5f3ff;
  color: #6d28d9;
}

.scope-picker-icon.image {
  background: #fdf2f8;
  color: #be185d;
}

.scope-picker-icon.folder {
  background: #eef6ff;
  color: #2563eb;
}

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

.scope-picker-check {
  flex: 0 0 auto;
  margin-left: auto;
  color: var(--kc-accent);
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

.hidden-input {
  display: none;
}

@media (max-width: 900px) {
  .composer-shell {
    width: calc(100vw - 108px);
  }
}
</style>
