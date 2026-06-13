import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi } from '@/api'
import type {
  StreamEnvelope,
  ThinkingData,
  ContentData,
  ToolCallData,
  ToolResultData,
  DoneData,
} from '@/types/stream'
import type { ChatScopeRequest, RetrievalScopeTrace } from '@/types/retrieval'
import type { SourceAnchor } from '@/types/preview'

export interface EvidenceItem {
  docId?: string
  documentName?: string
  displayLabel?: string
  sourceAnchor?: SourceAnchor | null
  retrievalSource?: string
}

export interface ToolStep {
  toolName: string
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
  status: 'calling' | 'done'
  elapsedMs?: number
  searchMethod?: string
  resultsCount?: number
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  thinking: string
  toolSteps: ToolStep[]
  isLoading: boolean
  timestamp?: number
  retrievalScope?: RetrievalScopeTrace | null
  retrievalFallbacks?: string[]
  evidenceItems?: EvidenceItem[]
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

const STORAGE_KEY = 'knowclaw_chat_sessions'
const SESSIONS_DATA_KEY = 'knowclaw_sessions_data'

let _msgIDCounter = 0
function _generateMsgID(): string {
  _msgIDCounter++
  return `${Date.now()}-${_msgIDCounter}`
}

export const useChatStore = defineStore('chat', () => {
  // 当前会话的消息
  const messages = ref<Message[]>([])
  const conversationId = ref<string | null>(null)
  const isLoading = ref(false)
  const rollbackHistory = ref<RollbackState[]>([])
  
  // 对话历史记录列表
  const conversations = ref<Conversation[]>([])
  const currentSessionId = ref<string | null>(null)

  // 从localStorage加载会话历史
  function loadConversationsFromStorage() {
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        conversations.value = JSON.parse(stored)
      }
      
      // 加载所有会话的数据
      const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY)
      if (sessionsData) {
        const data = JSON.parse(sessionsData)
        // 找到最近活跃的会话并加载
        const lastActiveSessionId = data.lastActiveSessionId
        if (lastActiveSessionId && data.sessions && data.sessions[lastActiveSessionId]) {
          const session = data.sessions[lastActiveSessionId]
          messages.value = session.messages || []
          conversationId.value = session.conversationId || null
          currentSessionId.value = lastActiveSessionId
          console.log('Loaded session:', lastActiveSessionId, 'with', messages.value.length, 'messages')
        }
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
      let data: { lastActiveSessionId: string | null; sessions: Record<string, any> } = {
        lastActiveSessionId: null,
        sessions: {}
      }
      
      const existing = localStorage.getItem(SESSIONS_DATA_KEY)
      if (existing) {
        data = JSON.parse(existing)
      }
      
      // 保存当前会话
      data.sessions[currentSessionId.value] = {
        messages: messages.value,
        conversationId: conversationId.value,
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

  function addUserMessage(content: string) {
    messages.value.push({
      id: _generateMsgID(),
      role: 'user',
      content,
      thinking: '',
      toolSteps: [],
      isLoading: false,
      timestamp: Date.now(),
    })
    
    // 检查是否已有当前对话记录
    let currentConv = conversations.value.find(c => c.id === currentSessionId.value)
    
    if (!currentConv) {
      // 如果没有找到对话记录（可能是新会话或ID丢失），创建新的
      const newSessionId = `session-${Date.now()}-${++_msgIDCounter}`
      currentSessionId.value = newSessionId
      
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
  }

  function deleteMessage(messageId: string) {
    const index = messages.value.findIndex((m) => m.id === messageId)
    if (index !== -1) {
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
    await sendMessage(userMsg.content)
  }

  function addAssistantMessage() {
    const msg: Message = {
      id: _generateMsgID(),
      role: 'assistant',
      content: '',
      thinking: '',
      toolSteps: [],
      isLoading: true,
    }
    messages.value.push(msg)
    return msg
  }

  function updateLastMessage(updates: Partial<Message>) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      Object.assign(last, updates)
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
      if (record.display_label || record.source_anchor) {
        evidence.push({
          docId: typeof record.doc_id === 'string'
            ? record.doc_id
            : typeof record.docId === 'string'
              ? record.docId
              : undefined,
          documentName: String(record.document_name || record.doc_name || record.documentName || record.name || ''),
          displayLabel: typeof record.display_label === 'string' ? record.display_label : undefined,
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

  function syncBackendConversationId(backendConversationId: string) {
    if (!backendConversationId) return
    conversationId.value = backendConversationId

    if (currentSessionId.value && currentSessionId.value !== backendConversationId) {
      const oldSessionId = currentSessionId.value
      currentSessionId.value = backendConversationId

      try {
        const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY)
        if (sessionsData) {
          const sessionStore = JSON.parse(sessionsData)
          if (sessionStore.sessions && sessionStore.sessions[oldSessionId]) {
            sessionStore.sessions[backendConversationId] = sessionStore.sessions[oldSessionId]
            delete sessionStore.sessions[oldSessionId]
            sessionStore.lastActiveSessionId = backendConversationId
            localStorage.setItem(SESSIONS_DATA_KEY, JSON.stringify(sessionStore))
            console.log('Migrated session from', oldSessionId, 'to', backendConversationId)
          }
        }
      } catch (e) {
        console.error('Failed to migrate session:', e)
      }

      const convIndex = conversations.value.findIndex(c => c.id === oldSessionId)
      if (convIndex !== -1) {
        conversations.value[convIndex].id = backendConversationId
      }
    } else if (!currentSessionId.value) {
      currentSessionId.value = backendConversationId
    }
  }

  function handleEnvelope(envelope: StreamEnvelope) {
    const lastIndex = messages.value.length - 1
    const last = messages.value[lastIndex]
    if (!last || last.role !== 'assistant') return

    switch (envelope.event) {
      case 'thinking': {
        const data = envelope.data as unknown as ThinkingData
        messages.value[lastIndex] = { ...last, thinking: last.thinking + data.content }
        break
      }
      case 'content': {
        const data = envelope.data as unknown as ContentData
        messages.value[lastIndex] = { ...last, content: last.content + data.content }
        break
      }
      case 'tool_call': {
        const data = envelope.data as unknown as ToolCallData
        messages.value[lastIndex] = {
          ...last,
          toolSteps: [...last.toolSteps, {
            toolName: data.tool_name,
            arguments: data.arguments,
            result: null,
            status: 'calling' as const,
          }]
        }
        break
      }
      case 'tool_result': {
        const data = envelope.data as unknown as ToolResultData
        const stepIndex = last.toolSteps.findIndex(
          (s) => s.toolName === data.tool_name && s.status === 'calling'
        )
        if (stepIndex !== -1) {
          const raw = envelope.data as Record<string, unknown>
          const updatedStep = { ...last.toolSteps[stepIndex] }
          updatedStep.result = data.result
          updatedStep.status = 'done' as const
          if (raw.elapsed_ms !== undefined) {
            updatedStep.elapsedMs = Number(raw.elapsed_ms)
          }
          if (raw.search_method !== undefined) {
            ;(updatedStep as any).searchMethod = String(raw.search_method)
          }
          if (raw.results_count !== undefined) {
            ;(updatedStep as any).resultsCount = Number(raw.results_count)
          }
          const newToolSteps = [...last.toolSteps]
          newToolSteps[stepIndex] = updatedStep
          const metadata = collectResultMetadata(data.result)
          messages.value[lastIndex] = {
            ...last,
            toolSteps: newToolSteps,
            retrievalScope: metadata.scope || last.retrievalScope || null,
            retrievalFallbacks: Array.from(new Set([...(last.retrievalFallbacks || []), ...metadata.fallbacks])),
            evidenceItems: dedupeEvidence([...(last.evidenceItems || []), ...metadata.evidence]),
          }
        }
        break
      }
      case 'conversation': {
        const data = envelope.data as unknown as DoneData
        if (data.conversation_id) {
          syncBackendConversationId(data.conversation_id)
        }
        break
      }
      case 'done': {
        const doneData = envelope.data as unknown as DoneData
        if (doneData.conversation_id) {
          syncBackendConversationId(doneData.conversation_id)
        }
        const metadata = collectResultMetadata(doneData.tool_results || [])
        messages.value[lastIndex] = {
          ...last,
          isLoading: false,
          retrievalScope: metadata.scope || last.retrievalScope || null,
          retrievalFallbacks: Array.from(new Set([...(last.retrievalFallbacks || []), ...metadata.fallbacks])),
          evidenceItems: dedupeEvidence([...(last.evidenceItems || []), ...metadata.evidence]),
        }
        
        // 更新对话记录的消息数
        const currentConv = conversations.value.find(c => c.id === currentSessionId.value)
        if (currentConv) {
          currentConv.messageCount = messages.value.length
          currentConv.timestamp = Date.now()
          saveConversationsToStorage()
          console.log('Updated conversation after AI reply:', currentConv.id, 'now has', messages.value.length, 'messages')
        }
        break
      }
    }
  }

  function dedupeEvidence(items: EvidenceItem[]): EvidenceItem[] {
    const seen = new Set<string>()
    const result: EvidenceItem[] = []
    for (const item of items) {
      const key = item.displayLabel || `${item.documentName || ''}:${JSON.stringify(item.sourceAnchor || {})}`
      if (!key || seen.has(key)) continue
      seen.add(key)
      result.push(item)
      if (result.length >= 8) break
    }
    return result
  }

  function clearMessages() {
    messages.value = []
    conversationId.value = null
    currentSessionId.value = null
    rollbackHistory.value = []
    // 不调用 saveCurrentSession，因为清空意味着要新建对话
  }

  // 加载指定对话
  function loadConversation(conversationId: string) {
    const conversation = conversations.value.find(c => c.id === conversationId)
    if (!conversation) return false

    // 如果是当前对话，不做任何事
    if (currentSessionId.value === conversationId) return true

    // 保存当前会话（如果有）
    if (messages.value.length > 0) {
      saveCurrentSession()
    }

    // 加载新对话
    currentSessionId.value = conversationId

    // 尝试从新的存储结构中恢复该对话的完整消息
    try {
      const sessionsData = localStorage.getItem(SESSIONS_DATA_KEY)
      if (sessionsData) {
        const data = JSON.parse(sessionsData)
        if (data.sessions && data.sessions[conversationId] && data.sessions[conversationId].messages) {
          messages.value = data.sessions[conversationId].messages
          saveCurrentSession()
          console.log('Loaded conversation:', conversationId, 'with', messages.value.length, 'messages')
          return true
        }
      }
    } catch (e) {
      console.error('Failed to load conversation:', e)
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

    saveCurrentSession()
    console.log('Created new conversation from first message:', conversationId)
    return true
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

  async function sendMessage(question: string, scope?: ChatScopeRequest) {
    if (isLoading.value) return
    
    isLoading.value = true
    addUserMessage(question)
    addAssistantMessage()

    try {
      const response = await chatApi.stream({
        question,
        ...scope,
        conversation_id: conversationId.value || undefined,
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
    } catch (error) {
      console.error('Chat error:', error)
      updateLastMessage({
        content: '抱歉，发生了错误。请稍后重试。',
        isLoading: false,
      })
    } finally {
      isLoading.value = false
    }
  }

  return {
    messages,
    conversationId,
    isLoading,
    rollbackHistory,
    conversations,
    currentSessionId,
    addUserMessage,
    addAssistantMessage,
    updateLastMessage,
    sendMessage,
    clearMessages,
    handleEnvelope,
    deleteMessage,
    editMessage,
    regenerateMessage,
    rollbackToMessage,
    restoreRollback,
    clearRollbackHistory,
    loadConversationsFromStorage,
    loadConversation,
    deleteConversation,
    saveCurrentSession,
    saveConversationsToStorage,
  }
})
