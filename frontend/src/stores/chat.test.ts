import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { chatApi } from '@/api'
import chatViewSource from '@/views/ChatView.vue?raw'
import { useChatStore, type Message } from './chat'

vi.mock('@/api', () => ({
  chatApi: {
    stream: vi.fn(),
  },
}))

function message(id: string, role: Message['role'], content: string): Message {
  return {
    id,
    role,
    content,
    thinking: '',
    toolSteps: [],
    isLoading: false,
  }
}

function installLocalStorage() {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
    removeItem: (key: string) => storage.delete(key),
    clear: () => storage.clear(),
  })
}

function streamResponse(events = 'event: done\ndata: {}\n\n') {
  const encoder = new TextEncoder()
  return {
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(events))
        controller.close()
      },
    }),
  } as Response
}

describe('chat rollback', () => {
  beforeEach(() => {
    installLocalStorage()
    setActivePinia(createPinia())
    vi.mocked(chatApi.stream).mockReset()
    vi.mocked(chatApi.stream).mockResolvedValue(streamResponse())
  })

  it('keeps a rollback snapshot that can restore removed messages', () => {
    const store = useChatStore()
    store.messages.push(
      message('u1', 'user', '第一轮问题'),
      message('a1', 'assistant', '第一轮回答'),
      message('u2', 'user', '统计下各地区销售表现'),
      message('a2', 'assistant', '各地区表现差异明显'),
    )

    const result = store.rollbackToMessage('u2')

    expect(result).toMatchObject({
      deletedCount: 2,
      targetRole: 'user',
    })
    expect(store.messages.map((item) => item.id)).toEqual(['u1', 'a1'])

    store.restoreRollback()

    expect(store.messages.map((item) => item.id)).toEqual(['u1', 'a1', 'u2', 'a2'])
    expect(store.messages[2].content).toBe('统计下各地区销售表现')
  })

  it('persists selected document context with the active chat session', () => {
    const store = useChatStore()
    store.currentSessionId = 'session-docs'
    store.messages.push(message('u1', 'user', 'Ask selected files'))
    store.setDocumentContexts([
      { id: 'doc-a', label: 'sales-a.pdf' },
      { id: 'doc-b', label: 'sales-b.xlsx' },
    ])

    store.saveCurrentSession()

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage()

    expect(restored.documentContexts).toEqual([
      { id: 'doc-a', label: 'sales-a.pdf' },
      { id: 'doc-b', label: 'sales-b.xlsx' },
    ])
  })

  it('persists selected document context before the first message creates a session', () => {
    const store = useChatStore()
    store.setDocumentContexts([{ id: 'doc-draft', label: 'draft.pdf' }])

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage()

    expect(restored.documentContexts).toEqual([{ id: 'doc-draft', label: 'draft.pdf' }])
  })

  it('persists selected folder context before the first message creates a session', () => {
    const store = useChatStore()
    store.setFolderContexts([{ id: 'folder-draft', label: '销售分析', type: 'folder' }])

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage()

    expect(restored.documentContexts).toEqual([
      { id: 'folder-draft', label: '销售分析', type: 'folder' },
    ])
  })

  it('replaces stale untyped document context when the same item is selected as a folder', () => {
    const store = useChatStore()
    store.setDocumentContexts([{ id: 'folder-sales', label: '销售分析' }])

    store.setFolderContexts([{ id: 'folder-sales', label: '销售分析', type: 'folder' }])

    expect(store.documentContexts).toEqual([
      { id: 'folder-sales', label: '销售分析', type: 'folder' },
    ])
    expect(localStorage.getItem('pagechat_document_contexts')).toBe(
      JSON.stringify([{ id: 'folder-sales', label: '销售分析', type: 'folder' }]),
    )
  })

  it('deduplicates persisted same-id folder and stale document contexts when loading', () => {
    localStorage.setItem('pagechat_document_contexts', JSON.stringify([
      { id: 'folder-sales', label: '销售分析' },
      { id: 'folder-sales', label: '销售分析', type: 'folder' },
    ]))

    const store = useChatStore()
    store.loadConversationsFromStorage()

    expect(store.documentContexts).toEqual([
      { id: 'folder-sales', label: '销售分析', type: 'folder' },
    ])
  })

  it('persists selected folder context with the active chat session', () => {
    const store = useChatStore()
    store.currentSessionId = 'session-folder'
    store.messages.push(message('u1', 'user', 'Ask selected folder'))
    store.setFolderContexts([{ id: 'folder-sales', label: '销售分析', type: 'folder' }])

    store.saveCurrentSession()

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage()

    expect(restored.documentContexts).toEqual([
      { id: 'folder-sales', label: '销售分析', type: 'folder' },
    ])
  })

  it('persists the folder replacement when a stale same-id context exists in an active session', () => {
    const store = useChatStore()
    store.currentSessionId = 'session-folder-replace'
    store.messages.push(message('u1', 'user', 'Ask selected folder'))
    store.setDocumentContexts([{ id: 'folder-sales', label: '销售分析' }])

    store.setFolderContexts([{ id: 'folder-sales', label: '销售分析', type: 'folder' }])

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage()

    expect(restored.documentContexts).toEqual([
      { id: 'folder-sales', label: '销售分析', type: 'folder' },
    ])
  })

  it('does not apply draft document context to an existing session without its own documents', () => {
    localStorage.setItem('pagechat_document_contexts', JSON.stringify([
      { id: 'doc-draft', label: 'draft.pdf' },
    ]))
    localStorage.setItem('pagechat_chat_sessions', JSON.stringify([
      {
        id: 'session-empty',
        title: 'Existing chat',
        firstMessage: 'Existing question',
        timestamp: 1,
        messageCount: 1,
      },
    ]))
    localStorage.setItem('pagechat_sessions_data', JSON.stringify({
      lastActiveSessionId: 'session-empty',
      sessions: {
        'session-empty': {
          messages: [message('u1', 'user', 'Existing question')],
          conversationId: null,
          documentContexts: [],
          timestamp: 1,
        },
      },
    }))

    const store = useChatStore()
    store.loadConversationsFromStorage()

    expect(store.currentSessionId).toBe('session-empty')
    expect(store.documentContexts).toEqual([])
  })

  it('starts document chat from a draft without mutating the previously active session', () => {
    const store = useChatStore()
    store.conversations.push({
      id: 'session-existing',
      title: 'Existing chat',
      firstMessage: 'Existing question',
      timestamp: 1,
      messageCount: 1,
    })
    store.currentSessionId = 'session-existing'
    store.messages.push(message('u1', 'user', 'Existing question'))
    store.saveCurrentSession()

    store.startDraftWithDocumentContexts([{ id: 'doc-cn', label: '中文报告.pdf' }])

    expect(store.currentSessionId).toBeNull()
    expect(store.messages).toEqual([])
    expect(store.documentContexts).toEqual([{ id: 'doc-cn', label: '中文报告.pdf' }])

    store.loadConversation('session-existing')

    expect(store.currentSessionId).toBe('session-existing')
    expect(store.documentContexts).toEqual([])
  })

  it('starts a blank draft without keeping the active session or draft documents', () => {
    const store = useChatStore()
    store.currentSessionId = 'session-existing'
    store.messages.push(message('u1', 'user', 'Existing question'))
    store.setDocumentContexts([{ id: 'doc-cn', label: '中文报告.pdf' }])

    store.startEmptyDraft()

    expect(store.currentSessionId).toBeNull()
    expect(store.messages).toEqual([])
    expect(store.documentContexts).toEqual([])
    expect(localStorage.getItem('pagechat_document_contexts')).toBeNull()
  })

  it('attaches document context to the active session without starting a new chat', () => {
    const store = useChatStore()
    store.conversations.push({
      id: 'session-existing',
      title: 'Existing chat',
      firstMessage: 'Existing question',
      timestamp: 1,
      messageCount: 1,
    })
    store.currentSessionId = 'session-existing'
    store.messages.push(message('u1', 'user', 'Existing question'))

    store.attachDocumentContextsToCurrentChat([{ id: 'doc-a', label: 'report.pdf' }])

    expect(store.currentSessionId).toBe('session-existing')
    expect(store.messages.map((item) => item.id)).toEqual(['u1'])
    expect(store.documentContexts).toEqual([{ id: 'doc-a', label: 'report.pdf' }])

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage()

    expect(restored.currentSessionId).toBe('session-existing')
    expect(restored.messages.map((item) => item.id)).toEqual(['u1'])
    expect(restored.documentContexts).toEqual([{ id: 'doc-a', label: 'report.pdf' }])
  })

  it('attaches document context to a blank draft and keeps it as a draft', () => {
    const store = useChatStore()
    store.startEmptyDraft()

    store.attachDocumentContextsToCurrentChat([{ id: 'doc-draft', label: 'draft.pdf' }])

    expect(store.currentSessionId).toBeNull()
    expect(store.messages).toEqual([])
    expect(store.documentContexts).toEqual([{ id: 'doc-draft', label: 'draft.pdf' }])
    expect(localStorage.getItem('pagechat_document_contexts')).toBe(
      JSON.stringify([{ id: 'doc-draft', label: 'draft.pdf' }]),
    )
  })

  it('opens the existing draft instead of clearing loaded draft documents', () => {
    const store = useChatStore()
    store.startEmptyDraft()
    store.attachDocumentContextsToCurrentChat([{ id: 'doc-draft', label: 'draft.pdf' }])

    store.openDraftChat()

    expect(store.currentSessionId).toBeNull()
    expect(store.messages).toEqual([])
    expect(store.documentContexts).toEqual([{ id: 'doc-draft', label: 'draft.pdf' }])
  })

  it('persists draft composer text until a blank draft is explicitly started', () => {
    const store = useChatStore()
    store.startEmptyDraft()

    store.setDraftComposerText('compare these files')

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.openDraftChat()

    expect(restored.currentSessionId).toBeNull()
    expect(restored.draftComposerText).toBe('compare these files')

    restored.startEmptyDraft()

    expect(restored.draftComposerText).toBe('')
    expect(localStorage.getItem('pagechat_draft_composer_text')).toBeNull()
  })

  it('builds markdown export for a stored conversation without switching sessions', () => {
    localStorage.setItem('pagechat_chat_sessions', JSON.stringify([
      {
        id: 'session-export',
        title: 'Export me',
        firstMessage: 'Existing question',
        timestamp: 1,
        messageCount: 2,
      },
    ]))
    localStorage.setItem('pagechat_sessions_data', JSON.stringify({
      lastActiveSessionId: 'session-current',
      sessions: {
        'session-export': {
          messages: [
            message('u1', 'user', 'Existing question'),
            message('a1', 'assistant', 'Existing answer'),
          ],
          conversationId: null,
          documentContexts: [],
          timestamp: 1,
        },
      },
    }))

    const store = useChatStore()
    store.currentSessionId = 'session-current'
    store.loadConversationsFromStorage({ restoreLastActive: false, restoreDraft: false })

    const markdown = store.exportConversationMarkdown('session-export', '2026-06-25T10:00:00+08:00')

    expect(store.currentSessionId).toBe('session-current')
    expect(markdown).toContain('# Export me')
    expect(markdown).toContain('Existing question')
    expect(markdown).toContain('Existing answer')
  })

  it('restores the stored backend conversation id when switching conversations', () => {
    localStorage.setItem('pagechat_chat_sessions', JSON.stringify([
      {
        id: 'session-a',
        title: 'First chat',
        firstMessage: 'First question',
        timestamp: 1,
        messageCount: 1,
      },
      {
        id: 'session-b',
        title: 'Second chat',
        firstMessage: 'Second question',
        timestamp: 2,
        messageCount: 1,
      },
    ]))
    localStorage.setItem('pagechat_sessions_data', JSON.stringify({
      lastActiveSessionId: 'session-a',
      sessions: {
        'session-a': {
          messages: [message('u1', 'user', 'First question')],
          conversationId: 'backend-a',
          documentContexts: [],
          timestamp: 1,
        },
        'session-b': {
          messages: [message('u2', 'user', 'Second question')],
          conversationId: 'backend-b',
          documentContexts: [],
          timestamp: 2,
        },
      },
    }))

    const store = useChatStore()
    store.loadConversationsFromStorage({ restoreLastActive: false, restoreDraft: false })

    expect(store.loadConversation('session-a')).toBe(true)
    expect(store.conversationId).toBe('backend-a')

    expect(store.loadConversation('session-b')).toBe(true)
    expect(store.conversationId).toBe('backend-b')
  })

  it('deduplicates history rows when a backend conversation id already exists', () => {
    const store = useChatStore()
    store.conversations.push(
      {
        id: 'backend-existing',
        title: 'Old backend row',
        firstMessage: 'Old question',
        timestamp: 1,
        messageCount: 2,
      },
      {
        id: 'session-temp',
        title: '现在有哪些文件夹',
        firstMessage: '现在有哪些文件夹',
        timestamp: 2,
        messageCount: 2,
      },
    )
    store.currentSessionId = 'session-temp'
    store.messages.push(
      message('u-current', 'user', '现在有哪些文件夹'),
      message('a-current', 'assistant', ''),
    )
    store.saveCurrentSession()

    store.handleEnvelope({
      event: 'conversation',
      data: { conversation_id: 'backend-existing' },
    })

    const matchingRows = store.conversations.filter((conversation) => conversation.id === 'backend-existing')
    expect(store.currentSessionId).toBe('backend-existing')
    expect(matchingRows).toHaveLength(1)
    expect(matchingRows[0]).toMatchObject({
      title: '现在有哪些文件夹',
      firstMessage: '现在有哪些文件夹',
      messageCount: 2,
    })
  })

  it('sends web search as structured chat state', async () => {
    const store = useChatStore()

    await store.sendMessage('查一下最新资料', { web_search: true })

    const payload = vi.mocked(chatApi.stream).mock.calls[0][0]
    expect(payload).toMatchObject({
      question: '查一下最新资料',
      web_search: true,
    })
    expect(payload.question).not.toContain('[Context:')
  })

  it('does not encode web search as a prompt hint in ChatView', () => {
    expect(chatViewSource).not.toContain('Web Search enabled')
  })
})
