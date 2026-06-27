import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { chatApi } from '@/api'
import chatViewSource from '@/views/ChatView.vue?raw'
import { useChatStore, type Message } from './chat'

vi.mock('@/api', () => ({
  chatApi: {
    stream: vi.fn(),
    getMessages: vi.fn(),
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

function streamResponse(events = [
  'event: run_completed',
  'data: {"run_id":"run-test","conversation_id":"conv-test","message_id":"msg-test","seq":1,"ts":"2026-06-26T10:00:00Z","status":"completed"}',
  '',
  '',
].join('\n')) {
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
    vi.mocked(chatApi.getMessages).mockReset()
    vi.mocked(chatApi.stream).mockResolvedValue(streamResponse())
    vi.mocked(chatApi.getMessages).mockResolvedValue({ data: [] } as any)
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

  it('restores the stored backend conversation id when switching conversations', async () => {
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

    await expect(store.loadConversation('session-a')).resolves.toBe(true)
    expect(store.conversationId).toBe('backend-a')

    await expect(store.loadConversation('session-b')).resolves.toBe(true)
    expect(store.conversationId).toBe('backend-b')
  })

  it('hydrates a backend conversation when local session data is missing', async () => {
    localStorage.setItem('pagechat_chat_sessions', JSON.stringify([{
      id: 'backend-a',
      title: 'Backend chat',
      firstMessage: 'original',
      timestamp: 1,
      messageCount: 2,
    }]))
    vi.mocked(chatApi.getMessages).mockResolvedValueOnce({
      data: [
        {
          id: 'u1',
          role: 'user',
          content: 'question',
          thinking_content: '',
          agent_steps: [],
          attachments: [],
          created_at: '2026-06-25T00:00:00Z',
        },
        {
          id: 'a1',
          role: 'assistant',
          content: 'answer',
          thinking_content: 'thinking',
          agent_steps: [],
          attachments: [],
          created_at: '2026-06-25T00:00:01Z',
        },
      ],
    } as any)

    const store = useChatStore()
    store.loadConversationsFromStorage({ restoreLastActive: false, restoreDraft: false })

    await expect(store.loadConversation('backend-a')).resolves.toBe(true)
    expect(chatApi.getMessages).toHaveBeenCalledWith('backend-a')
    expect(store.messages.map((item) => item.content)).toEqual(['question', 'answer'])
    expect(store.messages[1].thinking).toBe('thinking')
    expect(store.conversationId).toBe('backend-a')
  })

  it('saves migrated backend conversations under the backend id without dropping messages', async () => {
    const store = useChatStore()
    store.currentSessionId = 'session-temp'
    store.messages.push(message('u1', 'user', 'question'), message('a1', 'assistant', 'answer'))
    store.saveCurrentSession()

    store.handleEnvelope({
      event: 'run_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'backend-a',
        message_id: 'a1',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        status: 'running',
      },
    } as any)

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage({ restoreLastActive: true, restoreDraft: false })

    expect(restored.currentSessionId).toBe('backend-a')
    expect(restored.messages.map((item) => item.content)).toEqual(['question', 'answer'])
  })

  it('persists the assistant placeholder when run_started migrates a draft session', () => {
    const store = useChatStore()
    store.currentSessionId = 'session-temp'
    store.messages.push(message('u1', 'user', 'question'))
    store.saveCurrentSession()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'run_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'backend-a',
        message_id: 'backend-assistant-a',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        status: 'running',
      },
    } as any)

    setActivePinia(createPinia())
    const restored = useChatStore()
    restored.loadConversationsFromStorage({ restoreLastActive: true, restoreDraft: false })

    expect(restored.currentSessionId).toBe('backend-a')
    expect(restored.messages.map((item) => item.id)).toEqual(['u1', 'backend-assistant-a'])
  })

  it('can abort an in-flight chat stream', async () => {
    let signal: AbortSignal | undefined
    vi.mocked(chatApi.stream).mockImplementationOnce((_payload: any, options?: { signal?: AbortSignal }) => {
      signal = options?.signal
      return new Promise<Response>((_resolve, reject) => {
        options?.signal?.addEventListener('abort', () => {
          reject(new DOMException('Aborted', 'AbortError'))
        })
      })
    })
    const store = useChatStore()

    const pending = store.sendMessage('stop me')
    await Promise.resolve()
    store.stopGeneration()

    expect(signal?.aborted).toBe(true)
    expect(store.isLoading).toBe(false)
    expect(store.messages[store.messages.length - 1]?.isLoading).toBe(false)
    await pending
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
      event: 'run_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'backend-existing',
        message_id: 'a-current',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        status: 'running',
      },
    } as any)

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

  it('sends attachment ids without persisting image payloads', async () => {
    const store = useChatStore()

    await store.sendMessage('看截图', {
      attachment_ids: ['att-a'],
      attachments: [
        {
          attachment_id: 'att-a',
          original_name: 'screen.png',
          mime_type: 'image/png',
          size_bytes: 70,
          width: 1,
          height: 1,
          content_url: '/api/chat/attachments/att-a/content',
          preview_url: 'blob:http://local-preview',
          data: 'data:image/png;base64,AAA',
        },
      ],
    } as any)

    const payload = vi.mocked(chatApi.stream).mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload).toMatchObject({
      question: '看截图',
      attachment_ids: ['att-a'],
    })
    expect(payload).not.toHaveProperty('attachments')

    expect(store.messages[0].attachments).toEqual([
      {
        attachment_id: 'att-a',
        original_name: 'screen.png',
        mime_type: 'image/png',
        size_bytes: 70,
        width: 1,
        height: 1,
        content_url: '/api/chat/attachments/att-a/content',
      },
    ])
    const serializedStorage = JSON.stringify(localStorage)
    expect(serializedStorage).not.toContain('data:image')
    expect(serializedStorage).not.toContain('blob:')
  })

  it('does not encode web search as a prompt hint in ChatView', () => {
    expect(chatViewSource).not.toContain('Web Search enabled')
  })

  it('ignores legacy stream envelopes without changing assistant message state', () => {
    vi.useFakeTimers()
    try {
      const store = useChatStore()
      store.addAssistantMessage()

      store.handleEnvelope({ event: 'content', data: { content: 'Bei' } } as any)
      store.handleEnvelope({ event: 'content', data: { content: 'jing' } } as any)
      store.handleEnvelope({ event: 'thinking', data: { content: 'plan', step: 0 } } as any)
      store.handleEnvelope({ event: 'done', data: { conversation_id: 'legacy-conv' } } as any)

      expect(store.messages[0].content).toBe('')
      expect(store.messages[0].thinking).toBe('')
      expect(store.conversationId).toBeNull()

      vi.advanceTimersByTime(40)

      expect(store.messages[0].content).toBe('')
      expect(store.messages[0].thinking).toBe('')
    } finally {
      vi.useRealTimers()
    }
  })

  it('handles PageChat run events with buffered display text and citations', () => {
    vi.useFakeTimers()
    try {
      const store = useChatStore()
      const assistant = store.addAssistantMessage()

      store.handleEnvelope({
        event: 'run_started',
        data: {
          run_id: 'run-a',
          conversation_id: 'conv-a',
          message_id: 'backend-assistant-a',
          seq: 1,
          ts: '2026-06-26T10:00:00Z',
          status: 'running',
        },
      } as any)
      store.handleEnvelope({
        event: 'progress',
        data: {
          run_id: 'run-a',
          conversation_id: 'conv-a',
          message_id: 'backend-assistant-a',
          seq: 2,
          ts: '2026-06-26T10:00:01Z',
          message: '正在定位相关页面',
        },
      } as any)
      store.handleEnvelope({
        event: 'answer_delta',
        data: {
          run_id: 'run-a',
          conversation_id: 'conv-a',
          message_id: 'backend-assistant-a',
          seq: 3,
          ts: '2026-06-26T10:00:02Z',
          content: '重庆',
        },
      } as any)

      expect(store.conversationId).toBe('conv-a')
      expect(store.messages[0].id).toBe('backend-assistant-a')
      expect(store.messages[0].content).toBe('重庆')
      expect(store.messages[0].displayContent).toBe('')
      expect(store.messages[0].progressSteps).toEqual([
        {
          message: '正在定位相关页面',
          seq: 2,
          ts: '2026-06-26T10:00:01Z',
        },
      ])

      vi.advanceTimersByTime(24)
      expect(store.messages[0].displayContent).toBe('重庆')

      store.handleEnvelope({
        event: 'citation_added',
        data: {
          run_id: 'run-a',
          conversation_id: 'conv-a',
          message_id: 'backend-assistant-a',
          seq: 4,
          ts: '2026-06-26T10:00:03Z',
          citation: {
            citation_key: 'c1',
            document_id: 'doc-cq',
            document_name: '重庆报告.pdf',
            display_label: '重庆报告.pdf p.2',
            source_anchor: { format: 'pdf', start_page: 2 },
            preview_kind: 'pdf',
          },
        },
      } as any)
      store.handleEnvelope({
        event: 'run_completed',
        data: {
          run_id: 'run-a',
          conversation_id: 'conv-a',
          message_id: 'backend-assistant-a',
          seq: 5,
          ts: '2026-06-26T10:00:04Z',
          status: 'completed',
        },
      } as any)

      expect(store.messages[0].isLoading).toBe(false)
      expect(store.messages[0].citations).toHaveLength(1)
      expect(store.messages[0].evidenceItems?.[0]).toMatchObject({
        docId: 'doc-cq',
        documentName: '重庆报告.pdf',
        displayLabel: '重庆报告.pdf p.2',
      })
      expect(assistant.id).not.toBe(store.messages[0].id)
    } finally {
      vi.useRealTimers()
    }
  })

  it('merges processing deltas into one visible processing step', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'run_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'assistant-a',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        status: 'running',
      },
    } as any)
    store.handleEnvelope({
      event: 'processing_delta',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'assistant-a',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        step: 1,
        content: 'I will check ',
      },
    } as any)
    store.handleEnvelope({
      event: 'processing_delta',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'assistant-a',
        seq: 3,
        ts: '2026-06-26T10:00:02Z',
        step: 1,
        content: 'the selected evidence.',
      },
    } as any)

    expect(store.messages[0].progressSteps).toEqual([
      expect.objectContaining({
        kind: 'processing',
        step: 1,
        message: 'I will check the selected evidence.',
        status: 'streaming',
      }),
    ])
  })

  it('uses tool call deltas as the same pending tool row that tool_started completes', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'tool_call_delta',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        tool_call_id: 'call-read-pages',
        tool_name: 'get_page_content',
        arguments_delta: '{"doc_id":"doc-cq"',
      },
    } as any)
    store.handleEnvelope({
      event: 'tool_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 3,
        ts: '2026-06-26T10:00:02Z',
        tool_call_id: 'call-read-pages',
        tool_name: 'get_page_content',
        arguments: { doc_id: 'doc-cq', pages: '1-3,8' },
      },
    } as any)

    expect(store.messages[0].toolSteps).toHaveLength(1)
    expect(store.messages[0].toolSteps[0]).toMatchObject({
      toolCallId: 'call-read-pages',
      toolName: 'get_page_content',
      arguments: { doc_id: 'doc-cq', pages: '1-3,8' },
      argumentText: '{"doc_id":"doc-cq"',
      status: 'calling',
    })
  })

  it('removes a streamed planner thought when the backend retracts it', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'progress',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        kind: 'plan',
        step: 1,
        status: 'streaming',
        message: 'I will answer from structure only.',
      },
    } as any)
    store.handleEnvelope({
      event: 'progress',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        kind: 'plan_retract',
        step: 1,
        target_kind: 'plan',
        message: '',
      },
    } as any)
    store.handleEnvelope({
      event: 'progress',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 3,
        ts: '2026-06-26T10:00:02Z',
        kind: 'plan',
        step: 2,
        status: 'streaming',
        message: 'I will read the page evidence first.',
      },
    } as any)

    expect(store.messages[0].progressSteps).toEqual([
      {
        message: 'I will read the page evidence first.',
        kind: 'plan',
        step: 2,
        status: 'streaming',
        seq: 3,
        ts: '2026-06-26T10:00:02Z',
      },
    ])
  })

  it('collects web source bindings from tool results as preview evidence', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'tool_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        tool_name: 'web_search',
        arguments: { query: 'Beijing weather' },
      },
    } as any)
    store.handleEnvelope({
      event: 'tool_completed',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        tool_name: 'web_search',
        result: {
          source_bindings: [
            {
              type: 'web',
              source_id: 'web-1',
              title: 'Beijing weather',
              display_label: 'Beijing weather',
              url: 'https://weather.example/beijing',
              domain: 'weather.example',
              snippet: 'Sunny and warm.',
            },
          ],
        },
      },
    } as any)

    expect(store.messages[0].evidenceItems).toEqual([
      expect.objectContaining({
        type: 'web',
        sourceId: 'web-1',
        title: 'Beijing weather',
        displayLabel: 'Beijing weather',
        url: 'https://weather.example/beijing',
        domain: 'weather.example',
        snippet: 'Sunny and warm.',
      }),
    ])
  })

  it('collects citation bindings from citation events as preview evidence', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'citation_added',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        citation: {
          citation_key: 'c1',
          document_id: 'doc-cq',
          document_name: '重庆统计年鉴.pdf',
          display_label: '重庆统计年鉴.pdf p.12',
          source_anchor: {
            format: 'pdf',
            unit_type: 'page',
            start_page: 12,
            end_page: 12,
          },
          preview_kind: 'pdf',
        },
      },
    } as any)

    expect(store.messages[0].evidenceItems).toEqual([
      expect.objectContaining({
        docId: 'doc-cq',
        documentName: '重庆统计年鉴.pdf',
        displayLabel: '重庆统计年鉴.pdf p.12',
        sourceAnchor: expect.objectContaining({ start_page: 12 }),
      }),
    ])
  })

  it('dedupes document preview evidence by source identity instead of display label', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'tool_started',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 1,
        ts: '2026-06-26T10:00:00Z',
        tool_name: 'get_page_content',
        arguments: { doc_id: 'doc-cq', pages: '12' },
      },
    } as any)
    store.handleEnvelope({
      event: 'tool_completed',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        tool_name: 'get_page_content',
        result: {
          citations: [
            {
              document_id: 'doc-cq',
              document_name: '重庆统计年鉴.pdf',
              display_label: '重庆统计年鉴.pdf p.12',
              source_anchor: {
                format: 'pdf',
                unit_type: 'page',
                start_page: 12,
                end_page: 12,
              },
            },
            {
              document_id: 'doc-cq',
              document_name: '重庆统计年鉴',
              display_label: '重庆统计年鉴 page 12',
              source_anchor: {
                format: 'pdf',
                unit_type: 'page',
                start_page: 12,
                end_page: 12,
              },
            },
          ],
        },
      },
    } as any)

    expect(store.messages[0].evidenceItems).toEqual([
      expect.objectContaining({
        docId: 'doc-cq',
        documentName: '重庆统计年鉴.pdf',
        displayLabel: '重庆统计年鉴.pdf p.12',
        sourceAnchor: expect.objectContaining({ start_page: 12 }),
      }),
    ])
  })

  it('keeps web citation events as web preview evidence', () => {
    const store = useChatStore()
    store.addAssistantMessage()

    store.handleEnvelope({
      event: 'citation_added',
      data: {
        run_id: 'run-a',
        conversation_id: 'conv-a',
        message_id: 'a1',
        seq: 2,
        ts: '2026-06-26T10:00:01Z',
        citation: {
          citation_key: 'https://weather.example/beijing',
          document_id: 'https://weather.example/beijing',
          document_name: 'Beijing weather forecast',
          display_label: 'Beijing weather forecast',
          source_anchor: {
            format: 'web',
            url: 'https://weather.example/beijing',
          },
          preview_kind: 'web',
        },
      },
    } as any)

    expect(store.messages[0].evidenceItems).toEqual([
      expect.objectContaining({
        type: 'web',
        sourceId: 'https://weather.example/beijing',
        title: 'Beijing weather forecast',
        displayLabel: 'Beijing weather forecast',
        url: 'https://weather.example/beijing',
        domain: 'weather.example',
      }),
    ])
  })

  it('renders the new run timeline in ChatView instead of legacy thinking/tool blocks', () => {
    expect(chatViewSource).toContain('RunTimeline')
    expect(chatViewSource).not.toContain('ThinkingBlock')
    expect(chatViewSource).not.toContain('InlineToolStep')
    expect(chatViewSource).toContain('data-citation-index')
    expect(chatViewSource).toContain('data-web-source-index')
    expect(chatViewSource).not.toContain('data-structured-citation-index')
  })
})
