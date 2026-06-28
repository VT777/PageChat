<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ArrowUp,
  Brain,
  Check,
  FileText,
  Folder,
  Globe,
  ImagePlus,
  Plus,
  X,
} from 'lucide-vue-next'
import type { Document } from '@/stores/document'
import { useChatStore } from '@/stores/chat'
import { chatApi } from '@/api'
import type { Folder as FolderModel } from '@/api/folders'
import type { ChatAttachmentMetadata, ComposerImageAttachment } from '@/types/chatAttachments'
import {
  COMPOSER_ACTIONS,
  documentOnlyChatContexts,
  resolveDocumentChatContext,
} from '@/ui/pagechatContracts'
import { useI18n } from '@/i18n/messages'

interface ComposerSubmitPayload {
  text: string
  webSearch: boolean
  thinkingEnabled: boolean
  documentIds: string[]
  folderIds: string[]
  attachments: ChatAttachmentMetadata[]
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

const chatStore = useChatStore()
const { t, composerActionLabel } = useI18n()

const text = ref('')
const showMenu = ref(false)
const showLibraryPicker = ref(false)
const webSearch = ref(false)
const THINKING_STORAGE_KEY = 'pagechat_thinking_enabled'
const thinkingEnabled = ref(readStoredThinkingPreference())
const selectedDocumentIds = ref<string[]>([])
const selectedFolderIds = ref<string[]>([])
const selectedPickerDocuments = ref<Document[]>([])
const selectedPickerFolders = ref<FolderModel[]>([])
const images = ref<ComposerImageAttachment[]>([])
const imageInputRef = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

const isUploadingImages = computed(() => images.value.some((image) => image.status === 'uploading'))
const canSend = computed(() => text.value.trim().length > 0 && !props.disabled && !isUploadingImages.value)
const initialDocumentContexts = computed(() => {
  return documentOnlyChatContexts(toContextArray(props.initialDocumentContext))
})
const selectedDocumentChips = computed(() =>
  selectedDocumentIds.value.map(documentContextForId)
)
const isDraftChat = computed(() => !chatStore.currentSessionId)
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
function readStoredThinkingPreference() {
  if (typeof localStorage === 'undefined') return false
  return localStorage.getItem(THINKING_STORAGE_KEY) === 'true'
}

function toggleThinking() {
  thinkingEnabled.value = !thinkingEnabled.value
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(THINKING_STORAGE_KEY, String(thinkingEnabled.value))
  }
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
  if (actionId === 'library') {
    showLibraryPicker.value = true
    showMenu.value = false
  }
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
      localId: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      previewUrl: URL.createObjectURL(file),
      file,
      status: 'local' as const,
    }))
  images.value = [...images.value, ...next].slice(0, 6)
}

async function removeImage(localId: string) {
  const image = images.value.find((item) => item.localId === localId)
  if (image) {
    URL.revokeObjectURL(image.previewUrl)
    if (image.remote?.attachment_id && image.status === 'uploaded') {
      try {
        await chatApi.deleteAttachment(image.remote.attachment_id)
      } catch (error) {
        console.error('Failed to delete draft attachment:', error)
      }
    }
  }
  images.value = images.value.filter((item) => item.localId !== localId)
}

function toggleLibraryDocument(document: Document) {
  if (selectedDocumentIds.value.includes(document.id)) {
    selectedDocumentIds.value = selectedDocumentIds.value.filter((item) => item !== document.id)
    selectedPickerDocuments.value = selectedPickerDocuments.value.filter((item) => item.id !== document.id)
    syncDocumentContextsToStore()
    return
  }
  selectedDocumentIds.value = [...selectedDocumentIds.value, document.id]
  selectedPickerDocuments.value = [
    ...selectedPickerDocuments.value.filter((item) => item.id !== document.id),
    document,
  ]
  syncDocumentContextsToStore()
}

function toggleLibraryFolder(folder: FolderModel) {
  if (selectedFolderIds.value.includes(folder.id)) {
    selectedFolderIds.value = selectedFolderIds.value.filter((item) => item !== folder.id)
    selectedPickerFolders.value = selectedPickerFolders.value.filter((item) => item.id !== folder.id)
    syncFolderContextsToStore()
    return
  }
  selectedFolderIds.value = [...selectedFolderIds.value, folder.id]
  selectedPickerFolders.value = [
    ...selectedPickerFolders.value.filter((item) => item.id !== folder.id),
    folder,
  ]
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

async function uploadImagesForSubmit(): Promise<ChatAttachmentMetadata[]> {
  const uploaded: ChatAttachmentMetadata[] = []
  for (const image of images.value) {
    if (image.remote && image.status === 'uploaded') {
      uploaded.push(image.remote)
      continue
    }
    image.status = 'uploading'
    image.error = undefined
    try {
      const response = await chatApi.uploadAttachment(image.file)
      const metadata = response.data as ChatAttachmentMetadata
      image.remote = metadata
      image.status = 'uploaded'
      uploaded.push(metadata)
    } catch (error) {
      image.status = 'failed'
      image.error = '上传失败'
      throw error
    }
  }
  return uploaded
}

async function submit() {
  if (!canSend.value) return
  let attachments: ChatAttachmentMetadata[] = []
  try {
    attachments = await uploadImagesForSubmit()
  } catch (error) {
    console.error('Failed to upload chat attachments:', error)
    return
  }
  emit('submit', {
    text: text.value.trim(),
    webSearch: webSearch.value,
    thinkingEnabled: thinkingEnabled.value,
    documentIds: selectedDocumentIds.value,
    folderIds: selectedFolderIds.value,
    attachments,
  })
  text.value = ''
  images.value.forEach((image) => URL.revokeObjectURL(image.previewUrl))
  images.value = []
}

function documentContextForId(id: string) {
  return resolveDocumentChatContext(id, initialDocumentContexts.value, selectedPickerDocuments.value)
}

function folderContextForId(id: string) {
  const folder = selectedPickerFolders.value.find((item) => item.id === id)
  if (folder) return { id: folder.id, label: folder.name, type: 'folder' as const }
  const initialContext = initialFolderContexts.value.find((item) => item.id === id)
  if (initialContext) return { ...initialContext, type: 'folder' as const }
  return { id, label: id, type: 'folder' as const }
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

onBeforeUnmount(() => {
  images.value.forEach((image) => {
    URL.revokeObjectURL(image.previewUrl)
    if (image.remote?.attachment_id && image.status === 'uploaded') {
      chatApi.deleteAttachment(image.remote.attachment_id).catch((error) => {
        console.error('Failed to delete draft attachment:', error)
      })
    }
  })
})
</script>

<template>
  <div class="composer-shell">
    <LibraryScopePicker
      v-if="showLibraryPicker"
      :selected-document-ids="selectedDocumentIds"
      :selected-folder-ids="selectedFolderIds"
      @close="showLibraryPicker = false"
      @toggle-document="toggleLibraryDocument"
      @toggle-folder="toggleLibraryFolder"
    />

    <div class="composer-card">
      <div v-if="images.length > 0" class="image-strip">
        <div
          v-for="image in images"
          :key="image.localId"
          :class="['image-chip', image.status]"
          :title="image.error || image.name"
        >
          <img :src="image.previewUrl" :alt="image.name" />
          <span v-if="image.status === 'uploading'" class="image-status">上传中</span>
          <span v-else-if="image.status === 'failed'" class="image-status error">失败</span>
          <button type="button" @click="removeImage(image.localId)">
            <X />
          </button>
        </div>
      </div>

      <textarea
        ref="textareaRef"
        v-model="text"
        :disabled="disabled"
        rows="1"
        :placeholder="t('composer.placeholder')"
        @keydown="handleKeydown"
        @paste="handlePaste"
      />

      <div class="composer-footer">
        <div class="composer-left">
          <button
            :class="['composer-plus', { active: showMenu }]"
            type="button"
            :aria-label="t('composer.addContext')"
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
              <span>{{ composerActionLabel(action.id) }}</span>
              <Check v-if="action.id === 'web-search' && webSearch" class="menu-check" />
            </button>
          </div>

          <button v-if="webSearch" class="context-chip active" type="button" @click="webSearch = false">
            <span class="chip-icon"><Globe /></span>
            <span>搜索</span>
          </button>
          <button
            :class="['thinking-toggle', { active: thinkingEnabled }]"
            type="button"
            :aria-pressed="thinkingEnabled"
            :title="t('composer.reasoningTitle')"
            @click="toggleThinking"
          >
            <Brain />
            <span>{{ t('composer.thinking') }}</span>
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
.thinking-toggle svg,
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

.thinking-toggle {
  display: inline-flex;
  height: 28px;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--kc-border);
  border-radius: 999px;
  background: #fff;
  padding: 0 9px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
}

.thinking-toggle.active {
  border-color: rgba(47, 128, 237, 0.28);
  background: #eaf3ff;
  color: #145eb8;
}

.thinking-toggle:hover {
  color: var(--kc-text);
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

.image-chip.uploading img,
.image-chip.failed img {
  opacity: 0.58;
}

.image-status {
  position: absolute;
  left: 5px;
  bottom: 5px;
  border-radius: 999px;
  background: rgba(17, 24, 39, 0.72);
  padding: 2px 6px;
  color: #fff;
  font-size: 10px;
  line-height: 14px;
}

.image-status.error {
  background: rgba(190, 18, 60, 0.88);
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
