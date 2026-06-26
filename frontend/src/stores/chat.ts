import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi } from '@/api'
import { buildConversationExportMarkdown } from '@/ui/pagechatContracts'
import { createBufferedStreamText, type BufferedStreamText } from '@/composables/useBufferedStreamText'
import type {
  AnswerDelta,
  Citation,
  CitationAdded,
  ProgressEvent,
  RunCompleted,
  RunFailed,
  RunStarted,
  StreamEnvelope,
  ToolCompleted,
  ToolStarted,
} from '@/types/stream'
import type { ChatScopeRequest, RetrievalScopeTrace } from '@/types/retrieval'
import type { SourceAnchor } from '@/types/preview'
import type { ChatAttachmentMetadata } from '@/types/chatAttachments'

export interface DocumentChatContext {
  id: string
  label: string
  type?: 'document' | 'folder'
}

export interface EvidenceItem {
  type?: 'document' | 'web'
  docId?: string
  documentName?: string
  displayLabel?: string
  sourceAnchor?: SourceAnchor | null
  retrievalSource?: string
  sourceId?: string
  title?: string
  url?: string
  domain?: string
  snippet?: string
  contentPreview?: string
  provider?: string
}

export interface ToolStep {
  toolName: string
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
  status: 'calling' | 'done'
  seq?: number
  ts?: string
  elapsedMs?: number
  searchMethod?: string
  resultsCount?: number
}

export interface ProgressStep {
  message: string
  seq?: number
  ts?: string
}

interface DisplayBufferEntry {
  messageId: string
  buffer: BufferedStreamText
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  displayContent?: string
  thinking: string
  toolSteps: ToolStep[]
  isLoading: boolean
  timestamp?: number
  retrievalScope?: RetrievalScopeTrace | null
  retrievalFallbacks?: string[]
  evidenceItems?: EvidenceItem[]
  attachments?: ChatAttachmentMetadata[]
  citations?: Citation[]
  progressSteps?: ProgressStep[]
}

export interface RollbackState {
  messages: Message[]
  timestamp: number
}

export interface Conversation {
  id: string
  title: string
  firstMessage: string
  timestamp: number
  messageCount: number
}

interface StoredChatSession {
  messages?: Message[]
  conversationId?: string | null
  documentContexts?: DocumentChatContext[]
  timestamp?: number
}

interface StoredChatSessions {
  lastActiveSessionId: string | null
  sessions: Record<string, StoredChatSession>
}

interface ChatSendOptions extends ChatScopeRequest {
  attachment_ids?: string[]
  attachments?: ChatAttachmentMetadata[]
}

const STORAGE_KEY = 'pagechat_chat_sessions'
const SESSIONS_DATA_KEY = 'pagechat_sessions_data'
const DOCUMENT_CONTEXTS_KEY = 'pagechat_document_contexts'
const DRAFT_COMPOSER_TEXT_KEY = 'pagechat_draft_composer_text'
const LEGACY_STORAGE_KEY = 'know' + 'claw_chat_sessions'
const LEGACY_SESSIONS_DATA_KEY = 'know' + 'claw_sessions_data'

let _msgIDCounter = 0
function _generateMsgID(): string {
  _msgIDCounter++
  return `${Date.now()}-${_msgIDCounter}`
}

function sanitizeAttachmentMetadata(attachments?: ChatAttachmentMetadata[]): ChatAttachmentMetadata[] {
  if (!attachments || attachments.length === 0) return []
  return attachments
    .filter((item) => item && item.attachment_id)
    .map((item) => ({
      attachment_id: item.attachment_id,
      original_name: item.original_name || 'image',
      mime_type: item.mime_type,
      size_bytes: item.size_bytes,
      width: item.width ?? null,
      height: item.height ?? null,
      content_url: item.content_url,
    }))
}

export const useChatStore = defineStore('chat', () => {
  // 当前会话的消息
  const messages = ref<Message[]>([])
  const conversationId = ref<string | null>(null)
  const isLoading = ref(false)
  const rollbackHistory = ref<RollbackState[]>([])
  const documentContexts = ref<DocumentChatContext[]>([])
  const draftComposerText = ref('')
  const activeStreamController = ref<AbortController | null>(null)
  const displayBuffers = new Map<string, DisplayBufferEntry>()
  
  // 对话历史记录列表
  const conversations = ref<Conversation[]>([])
  const currentSessionId = ref<string | null>(null)

  function contextType(context: DocumentChatContext): 'document' | 'folder' {
    return context.type === 'folder' ? 'folder' : 'document'
  }

  function normalizeDocumentContexts(contexts: DocumentChatContext[]): DocumentChatContext[] {
    const normalized = contexts
      .filter((context) => context.id)
      .map((context) => {
        const normalized: DocumentChatContext = {
          id: context.id,
          label: context.label || context.id,
        }
        if (contextType(context) === 'folder') normalized.type = 'folder'
        return normalized
      })
    const byId = new Map<string, DocumentChatContext>()
    for (const context of normalized) {
      const existing = byId.get(context.id)
      if (!existing || context.type === 'folder' || existing.type !== 'folder') {
        byId.set(context.id, context)
      }
    }
    return Array.from(byId.values())
  }

  function replaceContextsByType(type: 'document' | 'folder', contexts: DocumentChatContext[]) {
    const normalized = normalizeDocumentContexts(
      contexts.map((context) => ({
        ...context,
        type,
      })),
    )
    const replacementIds = new Set(normalized.map((context) => context.id))
    documentContexts.value = [
      ...documentContexts.value.filter((context) =>
        contextType(context) !== type && !replacementIds.has(context.id),
      ),
      ...normalized,
    ]
    if (currentSessionId.value) {
      saveCurrentSession()
    } else {
      persistDraftDocumentContexts()
    }
  }

  function persistDraftDocumentContexts() {
    try {
      if (documentContexts.value.length > 0) {
        localStorage.setItem(DOCUMENT_CONTEXTS_KEY, JSON.stringify(documentContexts.value))
      } else {
        localStorage.removeItem(DOCUMENT_CONTEXTS_KEY)
      }
    } catch (e) {
      console.error('Failed to persist document contexts:', e)
    }
  }

  function clearPersistedDraftDocumentContexts() {
    try {
      localStorage.removeItem(DOCUMENT_CONTEXTS_KEY)
    } catch (e) {
      console.error('Failed to clear draft document contexts:', e)
    }
  }

  function loadDraftDocumentContexts(): DocumentChatContext[] {
    try {
      const stored = localStorage.getItem(DOCUMENT_CONTEXTS_KEY)
      if (!stored) return []
      const parsed = JSON.parse(stored)
      const contexts = Array.isArray(parsed)
        ? parsed.filter((context): context is DocumentChatContext =>
          typeof context?.id === 'string' && typeof context?.label === 'string',
        )
        : []
      return normalizeDocumentContexts(contexts)
    } catch (e) {
      console.error('Failed to load document contexts:', e)
      return []
    }
  }

  function persistDraftComposerText() {
    try {
      const value = draftComposerText.value.trim()
      if (value.length > 0) {
        localStorage.setItem(DRAFT_COMPOSER_TEXT_KEY, draftComposerText.value)
      } else {
        localStorage.removeItem(DRAFT_COMPOSER_TEXT_KEY)
      }
    } catch (e) {
      console.error('Failed to persist draft composer text:', e)
    }
  }

  function clearPersistedDraftComposerText() {
    try {
      localStorage.removeItem(DRAFT_COMPOSER_TEXT_KEY)
    } catch (e) {
      console.error('Failed to clear draft composer text:', e)
    }
  }

  function loadDraftComposerText(): string {
    try {
      return localStorage.getItem(DRAFT_COMPOSER_TEXT_KEY) || ''
    } catch (e) {
      console.error('Failed to load draft composer text:', e)
      return ''
    }
  }

  function setDraftComposerText(text: string) {
    draftComposerText.value = text
    persistDraftComposerText()
  }

  function clearDraftComposerText() {
    draftComposerText.value = ''
    clearPersistedDraftComposerText()
  }

  function mergeConversationMetadata(primary: Conversation, secondary?: Conversation): Conversation {
    if (!secondary) return { ...primary }
    return {
      id: primary.id,
      title: primary.title || secondary.title,
      firstMessage: primary.firstMessage || secondary.firstMessage,
      timestamp: Math.max(primary.timestamp || 0, secondary.timestamp || 0),
      messageCount: Math.max(primary.messageCount || 0, secondary.messageCount || 0),
    }
  }

  function dedupeConversationsById() {
    const mergedById = new Map<string, Conversation>()
    for (const conversation of conversations.value) {
      const existing = mergedById.get(conversation.id)
      if (!existing) {
        mergedById.set(conversation.id, { ...conversation })
        continue
      }
      const newer = (conversation.timestamp || 0) > (existing.timestamp || 0) ? conversation : existing
      const older = newer === conversation ? existing : conversation
      mergedById.set(conversation.id, mergeConversationMetadata(newer, older))
    }

    const seen = new Set<string>()
    const deduped: Conversation[] = []
    for (const conversation of conversations.value) {
      if (seen.has(conversation.id)) continue
      seen.add(conversation.id)
      const merged = mergedById.get(conversation.id)
      if (merged) deduped.push(merged)
    }

    if (deduped.length !== conversations.value.length) {
      conversations.value = deduped
      saveConversationsToStorage()
    }
  }

  function parseSessionsData(raw: string | null): StoredChatSessions {
    if (!raw) {
      return { lastActiveSessionId: null, sessions: {} }
    }
    const parsed = JSON.parse(raw)
    return {
      lastActiveSessionId: parsed.lastActiveSessionId || null,
      sessions: parsed.sessions || {},
    }
  }

  function loadStoredSession(sessionId: string): StoredChatSession | null {
    const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY) || localStorage.getItem(LEGACY_SESSIONS_DATA_KEY)
    if (!sessionsData) return null
    const data = parseSessionsData(sessionsData)
    return data.sessions[sessionId] || null
  }

  function normalizeBackendMessage(raw: any): Message {
    const role: Message['role'] = raw?.role === 'assistant' ? 'assistant' : 'user'
    const rawAttachments = Array.isArray(raw?.attachments)
      ? raw.attachments
      : Array.isArray(raw?.attachments_json)
        ? raw.attachments_json
        : []
    return {
      id: String(raw?.id || _generateMsgID()),
      role,
      content: String(raw?.content || ''),
      displayContent: role === 'assistant' ? String(raw?.content || '') : undefined,
      thinking: String(raw?.thinking || raw?.thinking_content || ''),
      toolSteps: Array.isArray(raw?.agent_steps) ? raw.agent_steps : [],
      isLoading: raw?.status === 'streaming',
      timestamp: raw?.created_at ? new Date(raw.created_at).getTime() : Date.now(),
      attachments: sanitizeAttachmentMetadata(rawAttachments),
      citations: Array.isArray(raw?.citations) ? raw.citations : [],
      progressSteps: Array.isArray(raw?.progressSteps) ? raw.progressSteps : [],
    }
  }

  function writeSessionsData(data: StoredChatSessions) {
    localStorage.setItem(SESSIONS_DATA_KEY, JSON.stringify(data))
  }

  // 从localStorage加载会话历史
  function loadConversationsFromStorage(options: { restoreLastActive?: boolean; restoreDraft?: boolean } = {}) {
    try {
      const restoreLastActive = options.restoreLastActive ?? true
      const restoreDraft = options.restoreDraft ?? true
      let loadedSession = false
      const stored = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_STORAGE_KEY)
      if (stored) {
        conversations.value = JSON.parse(stored)
        localStorage.setItem(STORAGE_KEY, stored)
        dedupeConversationsById()
      }
      
      // 加载所有会话的数据
      const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY) || localStorage.getItem(LEGACY_SESSIONS_DATA_KEY)
      if (sessionsData) {
        const data = parseSessionsData(sessionsData)
        localStorage.setItem(SESSIONS_DATA_KEY, sessionsData)
        // 找到最近活跃的会话并加载
        const lastActiveSessionId = data.lastActiveSessionId
        if (restoreLastActive && lastActiveSessionId && data.sessions && data.sessions[lastActiveSessionId]) {
          const session = data.sessions[lastActiveSessionId]
          messages.value = session.messages || []
          conversationId.value = session.conversationId || null
          documentContexts.value = Array.isArray(session.documentContexts)
            ? normalizeDocumentContexts(session.documentContexts)
            : []
          currentSessionId.value = lastActiveSessionId
          loadedSession = true
          console.log('Loaded session:', lastActiveSessionId, 'with', messages.value.length, 'messages')
        }
      }
      if (restoreDraft && !loadedSession && documentContexts.value.length === 0) {
        documentContexts.value = loadDraftDocumentContexts()
      }
      if (restoreDraft && !loadedSession && draftComposerText.value.length === 0) {
        draftComposerText.value = loadDraftComposerText()
      }
    } catch (e) {
      console.error('Failed to load conversations from storage:', e)
    }
  }
  
  // 保存会话历史到localStorage
  function saveConversationsToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.value))
    } catch (e) {
      console.error('Failed to save conversations to storage:', e)
    }
  }
  
  // 保存当前会话状态到对应的session
  function saveCurrentSession() {
    try {
      if (!currentSessionId.value) return
      
      // 获取现有数据
      let data: StoredChatSessions = {
        lastActiveSessionId: null,
        sessions: {}
      }
      
      const existing = localStorage.getItem(SESSIONS_DATA_KEY)
      if (existing) {
        data = parseSessionsData(existing)
      }
      
      // 保存当前会话
      data.sessions[currentSessionId.value] = {
        messages: messages.value,
        conversationId: conversationId.value,
        documentContexts: documentContexts.value,
        timestamp: Date.now()
      }
      
      // 设置为最近活跃
      data.lastActiveSessionId = currentSessionId.value
      
      localStorage.setItem(SESSIONS_DATA_KEY, JSON.stringify(data))
      console.log('Saved session:', currentSessionId.value, 'with', messages.value.length, 'messages')
    } catch (e) {
      console.error('Failed to save current session:', e)
    }
  }

  function addUserMessage(content: string, attachments?: ChatAttachmentMetadata[]) {
    const safeAttachments = sanitizeAttachmentMetadata(attachments)
    messages.value.push({
      id: _generateMsgID(),
      role: 'user',
      content,
      thinking: '',
      toolSteps: [],
      isLoading: false,
      timestamp: Date.now(),
      attachments: safeAttachments,
    })
    
    // 检查是否已有当前对话记录
    let currentConv = conversations.value.find(c => c.id === currentSessionId.value)
    let createdNewSession = false
    
    if (!currentConv) {
      // 如果没有找到对话记录（可能是新会话或ID丢失），创建新的
      const newSessionId = `session-${Date.now()}-${++_msgIDCounter}`
      currentSessionId.value = newSessionId
      createdNewSession = true
      
      const newConversation: Conversation = {
        id: newSessionId,
        title: content.slice(0, 30) + (content.length > 30 ? '...' : ''),
        firstMessage: content,
        timestamp: Date.now(),
        messageCount: messages.value.length
      }
      
      // 添加到历史记录开头
      conversations.value.unshift(newConversation)
      
      // 限制历史记录数量（保留最近50条）
      if (conversations.value.length > 50) {
        conversations.value = conversations.value.slice(0, 50)
      }
      
      console.log('Created new conversation:', newConversation.id, 'with', messages.value.length, 'messages')
    } else {
      // 更新现有对话的消息数
      currentConv.messageCount = messages.value.length
      currentConv.timestamp = Date.now()
      console.log('Updated conversation:', currentConv.id, 'now has', messages.value.length, 'messages')
    }
    
    // 保存到存储
    saveConversationsToStorage()
    
    // 保存当前会话状态
    saveCurrentSession()
    if (createdNewSession) {
      clearPersistedDraftDocumentContexts()
      clearDraftComposerText()
    }
  }

  function deleteMessage(messageId: string) {
    const index = messages.value.findIndex((m) => m.id === messageId)
    if (index !== -1) {
      disposeDisplayBuffer(messages.value[index].id)
      messages.value.splice(index, 1)
    }
  }

  // 撤回功能：撤回到指定消息，删除该消息及其之后的所有消息
  function rollbackToMessage(messageId: string): { 
    content: string | null; 
    deletedCount: number;
    targetRole: 'user' | 'assistant' | null;
  } {
    const index = messages.value.findIndex((m) => m.id === messageId)
    
    if (index === -1) {
      return { content: null, deletedCount: 0, targetRole: null }
    }

    const targetMessage = messages.value[index]

    // 保存回滚前的状态
    const state: RollbackState = {
      messages: JSON.parse(JSON.stringify(messages.value)),
      timestamp: Date.now(),
    }
    rollbackHistory.value.push(state)

    // 计算要删除的消息（包含 index 及之后的所有消息）
    const deletedMessages = messages.value.slice(index)
    deletedMessages.forEach((message) => disposeDisplayBuffer(message.id))
    
    // 保留 index 之前的所有消息
    messages.value = messages.value.slice(0, index)

    // 找到当前最后一条用户消息的内容
    let userContent: string | null = null
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        userContent = messages.value[i].content
        break
      }
    }

    return {
      content: userContent,
      deletedCount: deletedMessages.length,
      targetRole: targetMessage.role,
    }
  }

  // 恢复回滚
  function restoreRollback() {
    const state = rollbackHistory.value.pop()
    if (state) {
      disposeAllDisplayBuffers()
      messages.value = state.messages
    }
  }

  // 清除回滚历史
  function clearRollbackHistory() {
    rollbackHistory.value = []
  }

  function editMessage(messageId: string, newContent: string) {
    const msg = messages.value.find((m) => m.id === messageId)
    if (msg && msg.role === 'user') {
      msg.content = newContent
      msg.timestamp = Date.now()
      // 删除该消息之后的所有消息（重新生成）
      const index = messages.value.indexOf(msg)
      if (index !== -1) {
        messages.value.slice(index + 1).forEach((message) => disposeDisplayBuffer(message.id))
        messages.value.splice(index + 1)
      }
    }
  }

  async function regenerateMessage(messageId: string) {
    const index = messages.value.findIndex((m) => m.id === messageId)
    if (index === -1) return

    const msg = messages.value[index]
    if (msg.role !== 'assistant') return

    // 找到前一条用户消息
    let userIndex = index - 1
    while (userIndex >= 0 && messages.value[userIndex].role !== 'user') {
      userIndex--
    }

    if (userIndex < 0) return

    const userMsg = messages.value[userIndex]
    
    // 删除当前 AI 消息和后续消息
    messages.value.splice(index)
    
    // 重新发送
    await sendMessage(userMsg.content, {
      attachment_ids: userMsg.attachments?.map((item) => item.attachment_id),
      attachments: userMsg.attachments,
    })
  }

  function addAssistantMessage() {
    const msg: Message = {
      id: _generateMsgID(),
      role: 'assistant',
      content: '',
      displayContent: '',
      thinking: '',
      toolSteps: [],
      isLoading: true,
    }
    messages.value.push(msg)
    return msg
  }

  function setMessageDisplayContent(messageId: string, displayContent: string) {
    const index = messages.value.findIndex((message) => message.id === messageId)
    if (index === -1) return
    messages.value[index] = {
      ...messages.value[index],
      displayContent,
    }
  }

  function getDisplayBuffer(message: Message): BufferedStreamText {
    const existing = displayBuffers.get(message.id)
    if (existing) return existing.buffer

    const entry = {} as DisplayBufferEntry
    entry.messageId = message.id
    const buffer = createBufferedStreamText({
      frameMs: 24,
      initialText: message.displayContent ?? '',
      onDisplayChange: (displayContent) => setMessageDisplayContent(entry.messageId, displayContent),
    })
    entry.buffer = buffer
    displayBuffers.set(message.id, entry)
    return buffer
  }

  function flushDisplayBuffer(messageId: string, remove = false) {
    const entry = displayBuffers.get(messageId)
    if (!entry) return
    entry.buffer.flush()
    if (remove) {
      displayBuffers.delete(messageId)
    }
  }

  function disposeDisplayBuffer(messageId: string) {
    const entry = displayBuffers.get(messageId)
    if (!entry) return
    entry.buffer.dispose()
    displayBuffers.delete(messageId)
  }

  function disposeAllDisplayBuffers() {
    for (const entry of displayBuffers.values()) {
      entry.buffer.dispose()
    }
    displayBuffers.clear()
  }

  function moveDisplayBuffer(oldMessageId: string, newMessageId: string) {
    if (!oldMessageId || !newMessageId || oldMessageId === newMessageId) return
    const entry = displayBuffers.get(oldMessageId)
    if (!entry) return
    displayBuffers.delete(oldMessageId)
    entry.messageId = newMessageId
    displayBuffers.set(newMessageId, entry)
  }

  function updateLastMessage(updates: Partial<Message>) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      const nextUpdates = { ...updates }
      if (
        nextUpdates.content !== undefined &&
        nextUpdates.displayContent === undefined &&
        nextUpdates.isLoading === false
      ) {
        disposeDisplayBuffer(last.id)
        nextUpdates.displayContent = nextUpdates.content
      }
      Object.assign(last, nextUpdates)
    }
  }

  function extractScopeTrace(value: unknown): RetrievalScopeTrace | null {
    if (!value || typeof value !== 'object') return null
    const record = value as Record<string, unknown>
    if (record.scope && typeof record.scope === 'object') {
      return record.scope as RetrievalScopeTrace
    }
    if (record.retrieval_scope && typeof record.retrieval_scope === 'object') {
      return record.retrieval_scope as RetrievalScopeTrace
    }
    if (
      'folder_id' in record ||
      'requested_folder_id' in record ||
      'document_ids' in record ||
      'requested_document_ids' in record ||
      'expanded_to_user_library' in record ||
      'retrieval_mode' in record
    ) {
      return record as RetrievalScopeTrace
    }
    return null
  }

  function collectResultMetadata(result: unknown): { scope: RetrievalScopeTrace | null; fallbacks: string[]; evidence: EvidenceItem[] } {
    const fallbacks = new Set<string>()
    const evidence: EvidenceItem[] = []
    let scope: RetrievalScopeTrace | null = extractScopeTrace(result)

    const visit = (value: unknown, depth = 0) => {
      if (!value || depth > 4) return
      if (Array.isArray(value)) {
        value.forEach((item) => visit(item, depth + 1))
        return
      }
      if (typeof value !== 'object') return
      const record = value as Record<string, unknown>
      const nestedScope = extractScopeTrace(record)
      if (!scope && nestedScope) scope = nestedScope
      const source = record.retrieval_source
      if (source === 'keyword_fallback' || source === 'visual_summary') {
        fallbacks.add(String(source))
      }
      const sourceType = typeof record.type === 'string' ? record.type : ''
      const url = typeof record.url === 'string' ? record.url : ''
      if ((sourceType === 'web' || record.source === 'anysearch' || record.provider === 'anysearch') && url) {
        let domain = typeof record.domain === 'string' ? record.domain : ''
        if (!domain) {
          try {
            domain = new URL(url).hostname.replace(/^www\./, '')
          } catch {
            domain = ''
          }
        }
        const title = String(record.title || record.display_label || record.displayLabel || domain || url)
        evidence.push({
          type: 'web',
          sourceId: typeof record.source_id === 'string'
            ? record.source_id
            : typeof record.sourceId === 'string'
              ? record.sourceId
              : undefined,
          title,
          displayLabel: typeof record.display_label === 'string'
            ? record.display_label
            : typeof record.displayLabel === 'string'
              ? record.displayLabel
              : title,
          url,
          domain,
          snippet: typeof record.snippet === 'string' ? record.snippet : undefined,
          contentPreview: typeof record.content_preview === 'string'
            ? record.content_preview
            : typeof record.contentPreview === 'string'
              ? record.contentPreview
              : undefined,
          provider: typeof record.provider === 'string'
            ? record.provider
            : typeof record.source === 'string'
              ? record.source
              : undefined,
        })
      } else if (record.display_label || record.source_anchor) {
        evidence.push({
          type: 'document',
          docId: typeof record.doc_id === 'string'
            ? record.doc_id
            : typeof record.docId === 'string'
              ? record.docId
              : typeof record.document_id === 'string'
                ? record.document_id
                : undefined,
          documentName: String(record.document_name || record.doc_name || record.documentName || record.name || ''),
          displayLabel: typeof record.display_label === 'string'
            ? record.display_label
            : typeof record.displayLabel === 'string'
              ? record.displayLabel
              : undefined,
          sourceAnchor: (record.source_anchor || null) as SourceAnchor | null,
          retrievalSource: typeof record.retrieval_source === 'string' ? record.retrieval_source : undefined,
        })
      }
      for (const nested of Object.values(record)) {
        if (typeof nested === 'object') visit(nested, depth + 1)
      }
    }

    visit(result)
    return { scope, fallbacks: Array.from(fallbacks), evidence }
  }

  function recordFromAnchor(anchor: Citation['source_anchor']): Record<string, unknown> {
    return anchor && typeof anchor === 'object' ? anchor as Record<string, unknown> : {}
  }

  function safeWebUrlFromCitation(citation: Citation): string {
    const anchor = recordFromAnchor(citation.source_anchor)
    const rawUrl = typeof anchor.url === 'string'
      ? anchor.url
      : typeof citation.document_id === 'string'
        ? citation.document_id
        : ''
    try {
      const parsed = new URL(rawUrl)
      return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : ''
    } catch {
      return ''
    }
  }

  function domainFromUrl(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '')
    } catch {
      return ''
    }
  }

  function evidenceFromCitation(citation: Citation): EvidenceItem {
    const anchor = recordFromAnchor(citation.source_anchor)
    const previewKind = String(citation.preview_kind || anchor.format || '').toLowerCase()
    const url = safeWebUrlFromCitation(citation)
    if (previewKind === 'web' || url) {
      const title = citation.document_name || citation.display_label || url
      return {
        type: 'web',
        sourceId: citation.citation_key,
        title,
        displayLabel: citation.display_label || title,
        url,
        domain: domainFromUrl(url),
        provider: 'citation',
      }
    }
    return {
      type: 'document',
      docId: citation.document_id,
      documentName: citation.document_name,
      displayLabel: citation.display_label,
      sourceAnchor: citation.source_anchor as SourceAnchor,
    }
  }

  function syncBackendConversationId(backendConversationId: string) {
    if (!backendConversationId) return
    conversationId.value = backendConversationId

    if (currentSessionId.value && currentSessionId.value !== backendConversationId) {
      const oldSessionId = currentSessionId.value
      currentSessionId.value = backendConversationId

      try {
        const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY)
        const sessionStore = parseSessionsData(sessionsData)
        const oldSession = sessionStore.sessions[oldSessionId]
        const existingSession = sessionStore.sessions[backendConversationId]
        const oldMessages = Array.isArray(oldSession?.messages) ? oldSession.messages : []
        const existingMessages = Array.isArray(existingSession?.messages) ? existingSession.messages : []
        const activeMessages = messages.value.length > 0 ? messages.value : oldMessages
        const activeDocumentContexts = documentContexts.value.length > 0
          ? documentContexts.value
          : Array.isArray(oldSession?.documentContexts)
            ? oldSession.documentContexts
            : Array.isArray(existingSession?.documentContexts)
              ? existingSession.documentContexts
              : []

        sessionStore.sessions[backendConversationId] = {
          ...existingSession,
          ...oldSession,
          messages: oldMessages.length > 0
            ? oldMessages
            : activeMessages.length > 0
              ? activeMessages
              : existingMessages,
          conversationId: backendConversationId,
          documentContexts: activeDocumentContexts,
          timestamp: Date.now(),
        }
        delete sessionStore.sessions[oldSessionId]
        sessionStore.lastActiveSessionId = backendConversationId
        writeSessionsData(sessionStore)
        console.log('Migrated session from', oldSessionId, 'to', backendConversationId)
      } catch (e) {
        console.error('Failed to migrate session:', e)
      }

      const convIndex = conversations.value.findIndex(c => c.id === oldSessionId)
      const existingIndex = conversations.value.findIndex(c => c.id === backendConversationId)
      if (convIndex !== -1) {
        const currentConversation: Conversation = {
          ...conversations.value[convIndex],
          id: backendConversationId,
          timestamp: Math.max(conversations.value[convIndex].timestamp || 0, Date.now()),
          messageCount: Math.max(conversations.value[convIndex].messageCount || 0, messages.value.length),
        }
        const existingConversation = existingIndex !== -1 ? conversations.value[existingIndex] : undefined
        const mergedConversation = mergeConversationMetadata(currentConversation, existingConversation)
        conversations.value[convIndex] = mergedConversation
        if (existingIndex !== -1 && existingIndex !== convIndex) {
          conversations.value.splice(existingIndex, 1)
        }
        saveConversationsToStorage()
      }
    } else if (!currentSessionId.value) {
      currentSessionId.value = backendConversationId
      saveCurrentSession()
    }
  }

  function handleEnvelope(envelope: StreamEnvelope) {
    let lastIndex = messages.value.length - 1
    const eventData = envelope.data as unknown as Record<string, unknown>
    const backendMessageId = typeof eventData.message_id === 'string' ? eventData.message_id : ''
    if (backendMessageId) {
      const matchingIndex = messages.value.findIndex((message) => message.id === backendMessageId)
      if (matchingIndex !== -1) {
        lastIndex = matchingIndex
      }
    }
    const last = messages.value[lastIndex]
    if (!last || last.role !== 'assistant') return

    switch (envelope.event) {
      case 'run_started': {
        const data = envelope.data as unknown as RunStarted
        if (data.conversation_id) {
          syncBackendConversationId(data.conversation_id)
        }
        const nextMessageId = data.message_id || last.id
        messages.value[lastIndex] = {
          ...last,
          id: nextMessageId,
          isLoading: true,
        }
        moveDisplayBuffer(last.id, nextMessageId)
        saveCurrentSession()
        break
      }
      case 'progress': {
        const data = envelope.data as unknown as ProgressEvent
        flushDisplayBuffer(last.id)
        const base = messages.value[lastIndex] || last
        messages.value[lastIndex] = {
          ...base,
          progressSteps: [
            ...(base.progressSteps || []),
            {
              message: data.message,
              seq: data.seq,
              ts: data.ts,
            },
          ],
        }
        break
      }
      case 'tool_started': {
        const data = envelope.data as unknown as ToolStarted
        flushDisplayBuffer(last.id)
        const base = messages.value[lastIndex] || last
        messages.value[lastIndex] = {
          ...base,
          toolSteps: [...base.toolSteps, {
            toolName: data.tool_name,
            arguments: data.arguments,
            result: null,
            status: 'calling' as const,
            seq: data.seq,
            ts: data.ts,
          }]
        }
        break
      }
      case 'tool_completed': {
        const data = envelope.data as unknown as ToolCompleted
        flushDisplayBuffer(last.id)
        const base = messages.value[lastIndex] || last
        const stepIndex = base.toolSteps.findIndex(
          (s) => s.toolName === data.tool_name && s.status === 'calling'
        )
        if (stepIndex !== -1) {
          const raw = envelope.data as unknown as Record<string, unknown>
          const updatedStep = { ...base.toolSteps[stepIndex] }
          updatedStep.result = data.result
          updatedStep.status = 'done' as const
          updatedStep.seq = updatedStep.seq ?? data.seq
          updatedStep.ts = updatedStep.ts ?? data.ts
          if (data.elapsed_ms !== undefined) {
            updatedStep.elapsedMs = Number(data.elapsed_ms)
          }
          if (raw.search_method !== undefined) {
            ;(updatedStep as any).searchMethod = String(raw.search_method)
          }
          if (raw.results_count !== undefined) {
            ;(updatedStep as any).resultsCount = Number(raw.results_count)
          }
          const newToolSteps = [...base.toolSteps]
          newToolSteps[stepIndex] = updatedStep
          const metadata = collectResultMetadata(data.result)
          messages.value[lastIndex] = {
            ...base,
            toolSteps: newToolSteps,
            retrievalScope: metadata.scope || base.retrievalScope || null,
            retrievalFallbacks: Array.from(new Set([...(base.retrievalFallbacks || []), ...metadata.fallbacks])),
            evidenceItems: dedupeEvidence([...(base.evidenceItems || []), ...metadata.evidence]),
          }
        }
        break
      }
      case 'answer_delta': {
        const data = envelope.data as unknown as AnswerDelta
        const base = messages.value[lastIndex] || last
        const buffer = getDisplayBuffer(base)
        buffer.push(data.content)
        messages.value[lastIndex] = {
          ...base,
          content: base.content + data.content,
          displayContent: buffer.current(),
        }
        break
      }
      case 'citation_added': {
        const data = envelope.data as unknown as CitationAdded
        flushDisplayBuffer(last.id)
        const base = messages.value[lastIndex] || last
        const citations = dedupeCitations([...(base.citations || []), data.citation])
        messages.value[lastIndex] = {
          ...base,
          citations,
          evidenceItems: dedupeEvidence([
            ...(base.evidenceItems || []),
            evidenceFromCitation(data.citation),
          ]),
        }
        break
      }
      case 'run_completed': {
        const data = envelope.data as unknown as RunCompleted
        if (data.conversation_id) {
          syncBackendConversationId(data.conversation_id)
        }
        const base = messages.value[lastIndex] || last
        flushDisplayBuffer(base.id, true)
        messages.value[lastIndex] = {
          ...base,
          displayContent: base.content,
          isLoading: false,
        }
        const currentConv = conversations.value.find(c => c.id === currentSessionId.value)
        if (currentConv) {
          currentConv.messageCount = messages.value.length
          currentConv.timestamp = Date.now()
          saveConversationsToStorage()
        }
        break
      }
      case 'run_failed': {
        const data = envelope.data as unknown as RunFailed
        const base = messages.value[lastIndex] || last
        flushDisplayBuffer(base.id, true)
        messages.value[lastIndex] = {
          ...base,
          content: base.content || data.error || '抱歉，处理请求时发生错误。',
          displayContent: base.content || data.error || '抱歉，处理请求时发生错误。',
          isLoading: false,
        }
        break
      }
      case 'run_cancelled': {
        const base = messages.value[lastIndex] || last
        flushDisplayBuffer(base.id, true)
        messages.value[lastIndex] = {
          ...base,
          isLoading: false,
        }
        break
      }
    }
  }

  function dedupeCitations(items: Citation[]): Citation[] {
    const seen = new Set<string>()
    const result: Citation[] = []
    for (const item of items) {
      const key = item.citation_key || `${item.document_id || ''}:${item.display_label}`
      if (!key || seen.has(key)) continue
      seen.add(key)
      result.push(item)
    }
    return result
  }

  function dedupeEvidence(items: EvidenceItem[]): EvidenceItem[] {
    const seen = new Set<string>()
    const result: EvidenceItem[] = []
    for (const item of items) {
      const key = item.type === 'web'
        ? item.url || item.sourceId || item.displayLabel || ''
        : item.displayLabel || `${item.documentName || ''}:${JSON.stringify(item.sourceAnchor || {})}`
      if (!key || seen.has(key)) continue
      seen.add(key)
      result.push(item)
      if (result.length >= 8) break
    }
    return result
  }

  function clearMessages() {
    disposeAllDisplayBuffers()
    messages.value = []
    conversationId.value = null
    currentSessionId.value = null
    rollbackHistory.value = []
    documentContexts.value = []
    clearPersistedDraftDocumentContexts()
    clearDraftComposerText()
    // 不调用 saveCurrentSession，因为清空意味着要新建对话
  }

  function setDocumentContexts(contexts: DocumentChatContext[]) {
    replaceContextsByType('document', contexts)
  }

  function setFolderContexts(contexts: DocumentChatContext[]) {
    replaceContextsByType('folder', contexts)
  }

  function clearDocumentContexts() {
    replaceContextsByType('document', [])
  }

  function clearFolderContexts() {
    replaceContextsByType('folder', [])
  }

  function startDraftWithDocumentContexts(contexts: DocumentChatContext[]) {
    if (currentSessionId.value && messages.value.length > 0) {
      saveCurrentSession()
    }
    messages.value = []
    conversationId.value = null
    currentSessionId.value = null
    rollbackHistory.value = []
    documentContexts.value = normalizeDocumentContexts(contexts)
    persistDraftDocumentContexts()
  }

  // 加载指定对话
  function attachDocumentContextsToCurrentChat(contexts: DocumentChatContext[]) {
    setDocumentContexts(contexts)
  }

  function startEmptyDraft() {
    if (currentSessionId.value && messages.value.length > 0) {
      saveCurrentSession()
    }
    messages.value = []
    conversationId.value = null
    currentSessionId.value = null
    rollbackHistory.value = []
    documentContexts.value = []
    clearPersistedDraftDocumentContexts()
    clearDraftComposerText()
  }

  function openDraftChat() {
    if (currentSessionId.value && messages.value.length > 0) {
      saveCurrentSession()
    }
    messages.value = []
    conversationId.value = null
    currentSessionId.value = null
    rollbackHistory.value = []
    documentContexts.value = loadDraftDocumentContexts()
    draftComposerText.value = loadDraftComposerText()
  }

  async function loadConversation(sessionId: string): Promise<boolean> {
    const conversation = conversations.value.find(c => c.id === sessionId)
    if (!conversation) return false

    // 如果是当前对话，不做任何事
    if (currentSessionId.value === sessionId) {
      try {
        const session = loadStoredSession(sessionId)
        if (session) {
          conversationId.value = session.conversationId || null
        }
      } catch (e) {
        console.error('Failed to restore current conversation id:', e)
      }
      return true
    }

    // 保存当前会话（如果有）
    if (messages.value.length > 0) {
      saveCurrentSession()
    }

    // 加载新对话
    currentSessionId.value = sessionId

    // 尝试从新的存储结构中恢复该对话的完整消息
    try {
      const session = loadStoredSession(sessionId)
      if (session && Array.isArray(session.messages) && session.messages.length > 0) {
          messages.value = session.messages
          conversationId.value = session.conversationId || null
          documentContexts.value = Array.isArray(session.documentContexts)
            ? normalizeDocumentContexts(session.documentContexts)
            : []
          saveCurrentSession()
          console.log('Loaded conversation:', sessionId, 'with', messages.value.length, 'messages')
          return true
      }
    } catch (e) {
      console.error('Failed to load conversation:', e)
    }

    try {
      const response = await chatApi.getMessages(sessionId)
      const backendMessages = Array.isArray(response.data)
        ? response.data.map(normalizeBackendMessage)
        : []
      if (backendMessages.length > 0) {
        messages.value = backendMessages
        conversationId.value = sessionId
        documentContexts.value = []
        saveCurrentSession()
        console.log('Hydrated backend conversation:', sessionId, 'with', messages.value.length, 'messages')
        return true
      }
    } catch (e) {
      console.error('Failed to hydrate backend conversation:', e)
    }

    // 如果没有存储的完整消息，从第一条消息开始
    messages.value = [{
      id: _generateMsgID(),
      role: 'user',
      content: conversation.firstMessage,
      thinking: '',
      toolSteps: [],
      isLoading: false,
      timestamp: conversation.timestamp,
    }]
    conversationId.value = null
    documentContexts.value = []

    saveCurrentSession()
    console.log('Created new conversation from first message:', sessionId)
    return true
  }

  function messagesForConversationExport(conversationId: string): Message[] {
    if (currentSessionId.value === conversationId) {
      return messages.value
    }
    try {
      const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY) || localStorage.getItem(LEGACY_SESSIONS_DATA_KEY)
      if (!sessionsData) return []
      const data = JSON.parse(sessionsData)
      const sessionMessages = data.sessions?.[conversationId]?.messages
      return Array.isArray(sessionMessages) ? sessionMessages : []
    } catch (e) {
      console.error('Failed to load conversation export:', e)
      return []
    }
  }

  function exportConversationMarkdown(conversationId: string, exportedAt = new Date().toISOString()) {
    const conversation = conversations.value.find(c => c.id === conversationId)
    return buildConversationExportMarkdown({
      title: conversation?.title || 'PageChat Conversation',
      exportedAt,
      messages: messagesForConversationExport(conversationId).map((message) => ({
        role: message.role,
        content: message.content,
        toolSteps: message.toolSteps,
      })),
    })
  }

  // 删除对话记录
  function deleteConversation(conversationId: string) {
    const index = conversations.value.findIndex(c => c.id === conversationId)
    if (index !== -1) {
      conversations.value.splice(index, 1)
      saveConversationsToStorage()

      // 如果删除的是当前对话，清空当前会话
      if (currentSessionId.value === conversationId) {
        clearMessages()
      }
    }
  }

  async function sendMessage(question: string, scope?: ChatSendOptions) {
    if (isLoading.value) return
    
    isLoading.value = true
    const controller = new AbortController()
    activeStreamController.value = controller
    const safeAttachments = sanitizeAttachmentMetadata(scope?.attachments)
    addUserMessage(question, safeAttachments)
    addAssistantMessage()

    try {
      const { attachments, ...streamScope } = scope || {}
      const response = await chatApi.stream({
        question,
        ...streamScope,
        conversation_id: conversationId.value || undefined,
      }, {
        signal: controller.signal,
      })

      if (!response.body) throw new Error('No response body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
            continue
          }
          if (!line.startsWith('data: ')) continue

          try {
            const payload = JSON.parse(line.slice(6))
            const envelope: StreamEnvelope = {
              event: currentEvent as any,
              data: payload,
            }
            handleEnvelope(envelope)
          } catch (e) {
            // ignore parse errors for partial SSE chunks
          }
        }
      }

      const last = messages.value[messages.value.length - 1]
      if (last?.role === 'assistant') flushDisplayBuffer(last.id, true)
      updateLastMessage({ isLoading: false })
      
      // 保存当前会话状态
      saveCurrentSession()
      
      // 更新对话的消息数
      const currentConv = conversations.value.find(c => c.id === currentSessionId.value)
      if (currentConv) {
        currentConv.messageCount = messages.value.length
        currentConv.timestamp = Date.now()
        saveConversationsToStorage()
      }
    } catch (error: any) {
      const last = messages.value[messages.value.length - 1]
      if (last?.role === 'assistant') flushDisplayBuffer(last.id, true)
      if (error?.name === 'AbortError') {
        updateLastMessage({ isLoading: false })
      } else {
        console.error('Chat error:', error)
        updateLastMessage({
          content: '抱歉，发生了错误。请稍后重试。',
          isLoading: false,
        })
      }
    } finally {
      if (activeStreamController.value === controller) {
        activeStreamController.value = null
      }
      isLoading.value = false
    }
  }

  function stopGeneration() {
    const last = messages.value[messages.value.length - 1]
    if (last?.role === 'assistant') flushDisplayBuffer(last.id, true)
    activeStreamController.value?.abort()
    activeStreamController.value = null
    isLoading.value = false
    updateLastMessage({ isLoading: false })
    saveCurrentSession()
  }

  return {
    messages,
    conversationId,
    isLoading,
    rollbackHistory,
    documentContexts,
    draftComposerText,
    conversations,
    currentSessionId,
    addUserMessage,
    addAssistantMessage,
    updateLastMessage,
    sendMessage,
    stopGeneration,
    clearMessages,
    setDocumentContexts,
    setFolderContexts,
    clearDocumentContexts,
    clearFolderContexts,
    startDraftWithDocumentContexts,
    attachDocumentContextsToCurrentChat,
    startEmptyDraft,
    openDraftChat,
    setDraftComposerText,
    clearDraftComposerText,
    handleEnvelope,
    deleteMessage,
    editMessage,
    regenerateMessage,
    rollbackToMessage,
    restoreRollback,
    clearRollbackHistory,
    loadConversationsFromStorage,
    loadConversation,
    exportConversationMarkdown,
    deleteConversation,
    saveCurrentSession,
    saveConversationsToStorage,
  }
})
