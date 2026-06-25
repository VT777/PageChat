<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'
import { Bot, Check, Copy, RefreshCw, RotateCcw, Sparkles, Square, Undo2, User } from 'lucide-vue-next'
import AppShell from '@/components/layout/AppShell.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import CitationPreviewDrawer from '@/components/chat/CitationPreviewDrawer.vue'
import InlineToolStep from '@/components/chat/InlineToolStep.vue'
import ThinkingBlock from '@/components/chat/ThinkingBlock.vue'
import { useChatStore } from '@/stores/chat'
import { useDocumentStore } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'
import { chatApi, documentApi } from '@/api'
import type { DocumentChatContext, Message } from '@/stores/chat'
import type { ChatAttachmentMetadata, ChatAttachmentPreview } from '@/types/chatAttachments'
import type { ChatScopeRequest } from '@/types/retrieval'
import { describeScopeTrace } from '@/utils/retrievalScope'
import { answerStartScrollTop, isNearBottom } from '@/utils/chatScroll'
import { bindInlineCitations, extractInlineCitations, type BoundInlineCitation } from '@/utils/citations'
import { parseDocumentChatRouteQuery, parseFolderChatRouteContexts } from '@/ui/pagechatContracts'

interface ComposerPayload {
  text: string
  webSearch: boolean
  documentIds: string[]
  folderIds: string[]
  attachments: ChatAttachmentMetadata[]
}

const chatStore = useChatStore()
const documentStore = useDocumentStore()
const folderStore = useFolderStore()
const route = useRoute()
const scrollRef = ref<HTMLDivElement | null>(null)
const composerRef = ref<InstanceType<typeof ChatComposer> | null>(null)
const shouldFollowStream = ref(true)
const latestAnswerStartRef = ref<HTMLElement | null>(null)
const copiedMessageId = ref<string | null>(null)
const activeCitation = ref<BoundInlineCitation | null>(null)
const pendingRollback = ref<{
  prompt: string
  deletedCount: number
  targetRole: 'user' | 'assistant'
} | null>(null)
const attachmentPreviews = ref<Record<string, ChatAttachmentPreview>>({})
const previewObjectUrls = new Map<string, string>()

const prompts = [
  '总结当前文件夹里的关键结论',
  '找出这份报告里和收入增长相关的证据',
  '对比两个版本的合同条款差异',
  '根据目录结构帮我定位风险章节',
]

const routeDocumentContext = computed(() => {
  const contexts = parseDocumentChatRouteQuery(route.query as Record<string, unknown>)
  if (contexts.length > 0) return contexts
  const storedContexts = chatStore.documentContexts.filter(isDocumentContext)
  return storedContexts.length > 0 ? storedContexts : null
})
const routeFolderContext = computed(() => {
  const contexts = parseFolderChatRouteContexts(route.query as Record<string, unknown>)
  if (contexts.length > 0) return contexts
  const storedContexts = chatStore.documentContexts.filter(isFolderContext)
  return storedContexts.length > 0 ? storedContexts : null
})

function isDocumentContext(context: DocumentChatContext) {
  return context.type !== 'folder'
}

function isFolderContext(context: DocumentChatContext) {
  return context.type === 'folder'
}

function hasRouteContext(query = route.query) {
  return (
    query.documentId !== undefined ||
    query.documentIds !== undefined ||
    query.folderId !== undefined ||
    query.folderIds !== undefined
  )
}

function syncRouteDocumentContexts(query = route.query) {
  if (!hasRouteContext(query)) return
  const documentContexts = parseDocumentChatRouteQuery(query as Record<string, unknown>)
  const folderContexts = parseFolderChatRouteContexts(query as Record<string, unknown>)
  chatStore.setDocumentContexts(documentContexts)
  chatStore.setFolderContexts(folderContexts)
}

function isDraftChatIntent(query = route.query) {
  return query.draft !== undefined || query.newChat !== undefined
}

const messageSignature = computed(() =>
  chatStore.messages.map((message) => [
    message.id,
    message.content.length,
    message.thinking.length,
    message.toolSteps.length,
    (message.attachments || []).map((item) => item.attachment_id).join(','),
    message.isLoading ? 1 : 0,
  ].join(':')).join('|')
)

function buildScope(payload: ComposerPayload): ChatScopeRequest | undefined {
  if (payload.documentIds.length > 0) {
    return { document_ids: payload.documentIds, strict_scope: true }
  }
  if (payload.folderIds.length > 0) {
    return { folder_id: payload.folderIds[0], include_subfolders: true, strict_scope: true }
  }
  return undefined
}

async function handleSubmit(payload: ComposerPayload) {
  pendingRollback.value = null
  chatStore.clearRollbackHistory()
  await chatStore.sendMessage(payload.text, {
    ...buildScope(payload),
    web_search: payload.webSearch,
    attachment_ids: payload.attachments.map((item) => item.attachment_id),
    attachments: payload.attachments,
  })
  await nextTick()
  scrollToBottom()
}

function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    return marked.parse(content, { breaks: true, gfm: true }) as string
  } catch {
    return content
  }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function citationBindingsForMessage(message: Message): BoundInlineCitation[] {
  return bindInlineCitations(
    message.content,
    message.evidenceItems || [],
    documentStore.documents,
  )
}

function contentWithCitationPlaceholders(content: string): string {
  const citations = extractInlineCitations(content)
  if (citations.length === 0) return content

  let cursor = 0
  const parts: string[] = []
  for (const citation of citations) {
    parts.push(content.slice(cursor, citation.start))
    parts.push(`PAGECHAT_CITATION_${citation.index}`)
    cursor = citation.end
  }
  parts.push(content.slice(cursor))
  return parts.join('')
}

function renderMessageMarkdown(message: Message): string {
  const bindings = citationBindingsForMessage(message)
  if (bindings.length === 0) return renderMarkdown(message.content)

  let html = renderMarkdown(contentWithCitationPlaceholders(message.content))
  for (const binding of bindings) {
    const placeholder = `PAGECHAT_CITATION_${binding.index}`
    const title = binding.resolved ? '打开来源预览' : '查找并打开来源预览'
    const button = [
      `<button type="button" class="inline-citation"`,
      ` data-citation-index="${binding.index}"`,
      ` title="${title}">`,
      escapeHtml(binding.displayLabel),
      '</button>',
    ].join('')
    html = html.replace(placeholder, button)
  }
  return html
}

function scopeLabel(message: Message): string {
  if (!message.retrievalScope) return ''
  return describeScopeTrace(message.retrievalScope)
}

function scrollToBottom() {
  const el = scrollRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

function handleChatScroll() {
  const el = scrollRef.value
  if (!el) return
  shouldFollowStream.value = isNearBottom({
    scrollTop: el.scrollTop,
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
  })
}

function scrollToLatestAnswerStart() {
  const el = scrollRef.value
  const target = latestAnswerStartRef.value
  if (!el || !target) return
  el.scrollTop = answerStartScrollTop(
    {
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    },
    target.offsetTop,
  )
}

function setLatestAnswerStartRef(message: Message, element: unknown) {
  if (message.role === 'assistant' && !message.isLoading && element instanceof HTMLElement) {
    latestAnswerStartRef.value = element
  }
}

function placePromptInComposer(prompt: string) {
  composerRef.value?.setText(prompt)
  composerRef.value?.focus()
}

function usePrompt(prompt: string) {
  handleSubmit({
    text: prompt,
    webSearch: false,
    documentIds: [],
    folderIds: [],
    attachments: [],
  })
}

function attachmentPreviewFor(attachment: ChatAttachmentMetadata): ChatAttachmentPreview {
  return attachmentPreviews.value[attachment.attachment_id] || {
    ...attachment,
    preview_status: attachment.content_url ? 'idle' : 'failed',
  }
}

async function loadAttachmentPreview(attachment: ChatAttachmentMetadata) {
  if (!attachment.content_url || attachmentPreviews.value[attachment.attachment_id]?.preview_status === 'loading') {
    return
  }
  const existing = attachmentPreviews.value[attachment.attachment_id]
  if (existing?.preview_status === 'ready' || existing?.preview_status === 'failed') {
    return
  }

  attachmentPreviews.value = {
    ...attachmentPreviews.value,
    [attachment.attachment_id]: {
      ...attachment,
      preview_status: 'loading',
    },
  }

  try {
    const response = await chatApi.fetchAttachmentBlob(attachment.attachment_id)
    const previewUrl = URL.createObjectURL(response.data as Blob)
    const oldUrl = previewObjectUrls.get(attachment.attachment_id)
    if (oldUrl) URL.revokeObjectURL(oldUrl)
    previewObjectUrls.set(attachment.attachment_id, previewUrl)
    attachmentPreviews.value = {
      ...attachmentPreviews.value,
      [attachment.attachment_id]: {
        ...attachment,
        preview_url: previewUrl,
        preview_status: 'ready',
      },
    }
  } catch (error) {
    console.error('Failed to load attachment preview:', error)
    attachmentPreviews.value = {
      ...attachmentPreviews.value,
      [attachment.attachment_id]: {
        ...attachment,
        preview_status: 'failed',
      },
    }
  }
}

async function resolveCitationDocument(binding: BoundInlineCitation): Promise<BoundInlineCitation> {
  if (binding.docId) return binding
  try {
    const documents = await documentApi.searchByName(binding.documentName)
    const matched = Array.isArray(documents)
      ? documents.find((item: any) => {
        const name = String(item.original_name || item.name || '').toLowerCase()
        return name === binding.documentName.toLowerCase()
          || name.replace(/\.[^.]+$/, '') === binding.documentName.toLowerCase().replace(/\.[^.]+$/, '')
      })
      : null
    if (!matched) return binding
    return {
      ...binding,
      docId: String(matched.id),
      documentName: String(matched.original_name || matched.name || binding.documentName),
      fileType: String(matched.file_type || binding.fileType),
      resolved: true,
    }
  } catch (error) {
    console.error('Failed to resolve citation document:', error)
    return binding
  }
}

async function handleAssistantContentClick(event: MouseEvent, message: Message) {
  const target = event.target instanceof HTMLElement
    ? event.target.closest<HTMLButtonElement>('[data-citation-index]')
    : null
  if (!target) return
  const citationIndex = Number(target.dataset.citationIndex)
  const binding = citationBindingsForMessage(message).find((item) => item.index === citationIndex)
  if (!binding) return
  activeCitation.value = await resolveCitationDocument(binding)
}

function closeCitationPreview() {
  activeCitation.value = null
}

function ensureAttachmentPreviews() {
  for (const message of chatStore.messages) {
    for (const attachment of message.attachments || []) {
      loadAttachmentPreview(attachment)
    }
  }
}

async function copyMessage(message: Message) {
  try {
    await navigator.clipboard.writeText(message.content)
    copiedMessageId.value = message.id
    window.setTimeout(() => {
      if (copiedMessageId.value === message.id) copiedMessageId.value = null
    }, 1400)
  } catch (error) {
    console.error('Failed to copy message:', error)
  }
}

async function rollbackMessage(message: Message) {
  const result = chatStore.rollbackToMessage(message.id)
  const prompt = message.role === 'user' ? message.content : result.content || ''
  pendingRollback.value = {
    prompt,
    deletedCount: result.deletedCount,
    targetRole: result.targetRole || message.role,
  }
  chatStore.saveCurrentSession()
  await nextTick()
  scrollToBottom()
  placePromptInComposer(prompt)
}

async function restoreRollback() {
  chatStore.restoreRollback()
  pendingRollback.value = null
  composerRef.value?.setText('')
  chatStore.saveCurrentSession()
  await nextTick()
  scrollToBottom()
}

async function regenerateUserMessage(message: Message) {
  if (chatStore.isLoading) return
  const index = chatStore.messages.findIndex((item) => item.id === message.id)
  if (index === -1) return
  const content = message.content
  chatStore.messages.splice(index)
  await chatStore.sendMessage(content)
}

async function regenerateAssistantMessage(message: Message) {
  if (chatStore.isLoading) return
  await chatStore.regenerateMessage(message.id)
}

watch(messageSignature, async () => {
  ensureAttachmentPreviews()
  await nextTick()
  if (chatStore.isLoading && shouldFollowStream.value) {
    scrollToBottom()
  } else if (!chatStore.isLoading) {
    scrollToLatestAnswerStart()
  }
})

watch(() => route.query, (query) => {
  if (isDraftChatIntent(query)) {
    chatStore.openDraftChat()
    return
  }
  syncRouteDocumentContexts(query)
}, { immediate: true })

onMounted(() => {
  const hasRouteDocumentContext = parseDocumentChatRouteQuery(route.query as Record<string, unknown>).length > 0
  const hasRouteFolderContext = parseFolderChatRouteContexts(route.query as Record<string, unknown>).length > 0
  const shouldOpenDraftChat = isDraftChatIntent()
  chatStore.loadConversationsFromStorage({
    restoreLastActive: !shouldOpenDraftChat && !hasRouteDocumentContext && !hasRouteFolderContext,
    restoreDraft: !shouldOpenDraftChat && !hasRouteDocumentContext && !hasRouteFolderContext,
  })
  if (shouldOpenDraftChat) {
    chatStore.openDraftChat()
  }
  syncRouteDocumentContexts()
  documentStore.fetchDocuments(1, undefined, null, false, 20)
  folderStore.fetchFolders()
  nextTick(scrollToBottom)
  ensureAttachmentPreviews()
})

onBeforeUnmount(() => {
  for (const url of previewObjectUrls.values()) {
    URL.revokeObjectURL(url)
  }
  previewObjectUrls.clear()
})
</script>

<template>
  <AppShell title="Chat">
    <div class="chat-page">
      <div ref="scrollRef" class="chat-scroll" @scroll="handleChatScroll">
        <div class="chat-column">
          <section v-if="chatStore.messages.length === 0" class="empty-chat">
            <div class="empty-mark">
              <Sparkles />
            </div>
            <h2>Ask PageChat</h2>
            <p>Use your documents, folders, screenshots, and web context from one focused conversation.</p>
            <div class="prompt-grid">
              <button v-for="prompt in prompts" :key="prompt" type="button" @click="usePrompt(prompt)">
                {{ prompt }}
              </button>
            </div>
          </section>

          <article
            v-for="message in chatStore.messages"
            :key="message.id"
            :ref="(el) => setLatestAnswerStartRef(message, el)"
            :class="['message-row', message.role]"
          >
            <div v-if="message.role === 'assistant'" class="message-avatar assistant">
              <Bot />
            </div>

            <div class="message-body">
              <div class="message-meta">
                <span>{{ message.role === 'user' ? 'You' : 'PageChat' }}</span>
                <span v-if="scopeLabel(message)" class="scope-note">{{ scopeLabel(message) }}</span>
              </div>

              <template v-if="message.role === 'user'">
                <div class="user-message-shell">
                  <div class="user-bubble">
                    {{ message.content }}
                  </div>
                  <div class="bubble-actions" aria-label="Message actions">
                    <button type="button" title="复制" aria-label="复制" @click="copyMessage(message)">
                      <Check v-if="copiedMessageId === message.id" />
                      <Copy v-else />
                    </button>
                    <button type="button" title="撤回" aria-label="撤回" @click="rollbackMessage(message)">
                      <Undo2 />
                    </button>
                    <button type="button" title="重新生成" aria-label="重新生成" @click="regenerateUserMessage(message)">
                      <RotateCcw />
                    </button>
                  </div>
                </div>
                <div v-if="message.attachments?.length" class="sent-attachments">
                  <div
                    v-for="attachment in message.attachments"
                    :key="attachment.attachment_id"
                    class="sent-attachment"
                    :title="attachment.original_name"
                  >
                    <img
                      v-if="attachmentPreviewFor(attachment).preview_url"
                      :src="attachmentPreviewFor(attachment).preview_url"
                      :alt="attachment.original_name"
                    />
                    <span v-else class="sent-attachment-placeholder">
                      {{ attachmentPreviewFor(attachment).preview_status === 'loading' ? '加载中' : '图片' }}
                    </span>
                    <span class="sent-attachment-name">{{ attachment.original_name }}</span>
                  </div>
                </div>
              </template>

              <template v-else>
                <ThinkingBlock
                  v-if="message.thinking"
                  :content="message.thinking"
                  :active="message.isLoading && !message.content"
                />

                <div v-if="message.toolSteps.length > 0" class="inline-tools">
                  <InlineToolStep
                    v-for="(step, index) in message.toolSteps"
                    :key="`${message.id}-${index}-${step.toolName}`"
                    :step="step"
                  />
                </div>

                <div
                  v-if="message.content"
                  class="assistant-content"
                  v-html="renderMessageMarkdown(message)"
                  @click="handleAssistantContentClick($event, message)"
                />
                <div v-else-if="message.isLoading" class="assistant-loading">
                  <span />
                  <span />
                  <span />
                </div>

                <div v-if="message.content && !message.isLoading" class="assistant-actions">
                  <button type="button" title="复制" aria-label="复制" @click="copyMessage(message)">
                    <Check v-if="copiedMessageId === message.id" />
                    <Copy v-else />
                  </button>
                  <button type="button" title="重新生成" aria-label="重新生成" @click="regenerateAssistantMessage(message)">
                    <RefreshCw />
                  </button>
                </div>
              </template>
            </div>

            <div v-if="message.role === 'user'" class="message-avatar user">
              <User />
            </div>
          </article>
        </div>
      </div>

      <div class="composer-zone">
        <div class="composer-stack">
          <div v-if="pendingRollback" class="rollback-toast">
            <Undo2 />
            <span>
              已撤回 {{ pendingRollback.deletedCount }} 条消息，原提示词已放入输入框
            </span>
            <button type="button" @click="restoreRollback">
              <RotateCcw />
              还原
            </button>
          </div>
          <ChatComposer
            ref="composerRef"
            :disabled="chatStore.isLoading"
            :initial-document-context="routeDocumentContext"
            :initial-folder-context="routeFolderContext"
            @submit="handleSubmit"
          />
          <button v-if="chatStore.isLoading" class="stop-button" type="button" @click="chatStore.stopGeneration">
            <Square />
            Stop generating
          </button>
        </div>
      </div>
      <CitationPreviewDrawer
        :open="Boolean(activeCitation)"
        :doc-id="activeCitation?.docId"
        :document-name="activeCitation?.documentName || ''"
        :display-label="activeCitation?.displayLabel || ''"
        :file-type="activeCitation?.fileType || '.pdf'"
        :source-anchor="activeCitation?.sourceAnchor || null"
        @close="closeCitationPreview"
      />
    </div>
  </AppShell>
</template>

<style scoped>
.chat-page {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: minmax(0, 1fr) auto;
  overflow: hidden;
}

.chat-scroll {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.chat-column {
  width: min(900px, calc(100% - 48px));
  min-height: 100%;
  margin: 0 auto;
  padding: 34px 0 28px;
}

.empty-chat {
  display: grid;
  min-height: 55vh;
  align-content: center;
  justify-items: center;
  text-align: center;
}

.empty-mark {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 1px solid rgba(47, 128, 237, 0.2);
  border-radius: 12px;
  background: #eaf3ff;
  color: var(--kc-accent);
}

.empty-mark svg {
  width: 18px;
  height: 18px;
}

.empty-chat h2 {
  margin: 14px 0 6px;
  color: var(--kc-text);
  font-size: 24px;
  font-weight: 650;
  line-height: 32px;
}

.empty-chat p {
  max-width: 520px;
  margin: 0;
  color: var(--kc-text-secondary);
  font-size: 13px;
  line-height: 21px;
}

.prompt-grid {
  display: grid;
  width: min(680px, 100%);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 24px;
}

.prompt-grid button {
  min-height: 44px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: rgba(255, 255, 255, 0.72);
  padding: 0 14px;
  color: var(--kc-text-secondary);
  text-align: left;
  font-size: 12.5px;
}

.prompt-grid button:hover {
  border-color: rgba(47, 128, 237, 0.28);
  background: #fff;
  color: var(--kc-text);
}

.message-row {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 30px;
  gap: 10px;
  margin-bottom: 24px;
}

.message-row.user .message-body {
  display: flex;
  grid-column: 2;
  width: 100%;
  max-width: none;
  flex-direction: column;
  align-items: flex-end;
  justify-self: stretch;
}

.message-row.user .message-avatar.user {
  grid-column: 3;
  grid-row: 1;
}

.message-row.assistant .message-body {
  justify-self: start;
  width: min(760px, 100%);
}

.message-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 999px;
}

.message-avatar svg {
  width: 15px;
  height: 15px;
  stroke-width: 1.8;
}

.message-avatar.assistant {
  background: #eaf3ff;
  color: var(--kc-accent);
}

.message-avatar.user {
  background: var(--kc-text);
  color: #fff;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  font-weight: 560;
}

.message-row.user .message-meta {
  justify-content: flex-end;
}

.scope-note {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-bubble {
  width: fit-content;
  min-width: 0;
  max-width: 100%;
  border: 1px solid rgba(42, 111, 224, 0.18);
  border-radius: 17px 17px 5px;
  background: linear-gradient(180deg, #2f80ed 0%, #236bd7 100%);
  box-shadow: 0 12px 28px rgba(47, 128, 237, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.18);
  color: #fff;
  padding: 11px 15px;
  font-size: 13.5px;
  font-weight: 520;
  line-height: 22px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  word-break: break-word;
}

.user-message-shell {
  position: relative;
  display: inline-flex;
  max-width: min(680px, 82%);
  justify-content: flex-end;
}

.user-message-shell::after {
  content: "";
  position: absolute;
  right: 0;
  bottom: -42px;
  z-index: 1;
  width: 148px;
  height: 42px;
}

.bubble-actions {
  position: absolute;
  right: 7px;
  bottom: -38px;
  z-index: 2;
  display: inline-flex;
  gap: 4px;
  border: 1px solid rgba(229, 231, 235, 0.82);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  padding: 3px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12);
  opacity: 0;
  pointer-events: none;
  transform: translateY(-6px) scale(0.98);
  transition: opacity 160ms ease, transform 160ms ease;
  backdrop-filter: blur(18px);
}

.user-message-shell:hover .bubble-actions,
.bubble-actions:focus-within {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0) scale(1);
}

.sent-attachments {
  display: flex;
  max-width: min(680px, 82%);
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 7px;
  margin-top: 7px;
}

.sent-attachment {
  display: grid;
  width: 118px;
  overflow: hidden;
  border: 1px solid rgba(209, 213, 219, 0.78);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
}

.sent-attachment img,
.sent-attachment-placeholder {
  width: 100%;
  height: 72px;
}

.sent-attachment img {
  object-fit: cover;
}

.sent-attachment-placeholder {
  display: grid;
  place-items: center;
  background: var(--kc-surface-muted);
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.sent-attachment-name {
  min-width: 0;
  overflow: hidden;
  padding: 6px 7px 7px;
  color: var(--kc-text-secondary);
  font-size: 11px;
  line-height: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bubble-actions button,
.assistant-actions button {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--kc-text-tertiary);
}

.bubble-actions button:hover,
.assistant-actions button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.bubble-actions svg,
.assistant-actions svg {
  width: 14px;
  height: 14px;
  stroke-width: 1.9;
}

.thinking-line {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 6px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.thinking-line svg {
  width: 14px;
  height: 14px;
}

.inline-tools {
  display: grid;
  gap: 2px;
  margin: 4px 0 10px;
}

.assistant-content {
  color: var(--kc-text);
  font-size: 13.5px;
  line-height: 22px;
}

.assistant-content :deep(p) {
  margin: 0 0 10px;
}

.assistant-content :deep(ul),
.assistant-content :deep(ol) {
  margin: 8px 0 10px 18px;
}

.assistant-content :deep(li) {
  margin: 3px 0;
}

.assistant-content :deep(code) {
  border-radius: var(--kc-radius-xs);
  background: var(--kc-surface-muted);
  padding: 1px 4px;
  font-size: 12px;
}

.assistant-content :deep(pre) {
  overflow: auto;
  border: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-md);
  background: #f8fafc;
  padding: 12px;
}

.assistant-loading {
  display: flex;
  align-items: center;
  gap: 5px;
  height: 24px;
}

.assistant-loading span {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: var(--kc-text-tertiary);
  animation: typing 1.2s infinite ease-in-out;
}

.assistant-loading span:nth-child(2) {
  animation-delay: 120ms;
}

.assistant-loading span:nth-child(3) {
  animation-delay: 240ms;
}

.assistant-actions {
  display: inline-flex;
  gap: 3px;
  margin-top: 5px;
  padding: 2px 0;
}

.composer-zone {
  display: flex;
  justify-content: center;
  border-top: 1px solid rgba(229, 231, 235, 0.72);
  background: linear-gradient(180deg, rgba(246, 247, 249, 0), var(--kc-bg) 22%);
  padding: 14px 24px 18px;
}

.composer-stack {
  display: grid;
  width: min(860px, calc(100vw - 360px));
  gap: 8px;
}

.assistant-content :deep(.inline-citation) {
  display: inline-flex;
  max-width: min(100%, 320px);
  align-items: center;
  vertical-align: baseline;
  border: 1px solid rgba(47, 128, 237, 0.2);
  border-radius: 999px;
  background: #eef6ff;
  padding: 1px 7px;
  color: #145eb8;
  font-size: 11.5px;
  font-weight: 620;
  line-height: 17px;
  text-decoration: none;
}

.assistant-content :deep(.inline-citation:hover) {
  border-color: rgba(47, 128, 237, 0.36);
  background: #deefff;
}

.stop-button {
  justify-self: center;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  border: 1px solid rgba(209, 213, 219, 0.86);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.1);
  padding: 0 12px;
  color: var(--kc-text-secondary);
  font-size: 12px;
  font-weight: 600;
  backdrop-filter: blur(18px);
}

.stop-button:hover {
  border-color: rgba(239, 68, 68, 0.28);
  color: var(--kc-danger);
}

.stop-button svg {
  width: 13px;
  height: 13px;
  stroke-width: 2;
}

.rollback-toast {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(47, 128, 237, 0.18);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.1);
  padding: 6px 8px 6px 11px;
  color: var(--kc-text-secondary);
  font-size: 12px;
  line-height: 18px;
  backdrop-filter: blur(18px);
}

.rollback-toast > svg {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  color: var(--kc-accent);
}

.rollback-toast span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rollback-toast button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  height: 26px;
  border: 0;
  border-radius: 999px;
  background: #eaf3ff;
  padding: 0 9px;
  color: #145eb8;
  font-size: 12px;
  font-weight: 600;
}

.rollback-toast button:hover {
  background: #dcecff;
}

.rollback-toast button svg {
  width: 13px;
  height: 13px;
}

@keyframes typing {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.35;
  }
  40% {
    transform: translateY(-3px);
    opacity: 1;
  }
}

@media (max-width: 760px) {
  .chat-column {
    width: calc(100% - 28px);
  }

  .prompt-grid {
    grid-template-columns: 1fr;
  }

  .user-message-shell {
    max-width: 100%;
  }
  
  .composer-stack {
    width: calc(100vw - 108px);
  }
}
</style>
