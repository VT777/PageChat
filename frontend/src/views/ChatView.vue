<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { useDocumentStore } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'
import { documentApi, chatApi } from '@/api'
import type { EvidenceItem, Message } from '@/stores/chat'
import { 
  Send, 
  FileText,
  Loader2,
  Plus,
  Sparkles,
  MessageSquare,
  BookOpen,
  X,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Settings,
  Copy,
  Undo,
  Brain,
  Wrench,
  CheckCircle,
  PanelLeft,
  PanelRight,
  Highlighter,
  RotateCcw,
  Trash2
} from 'lucide-vue-next'
import { marked } from 'marked'
import PdfReferenceViewer from '@/components/PdfReferenceViewer.vue'
import UniversalPreview from '@/components/preview/UniversalPreview.vue'
import type { SourceAnchor } from '@/types/preview'
import type { ChatScopeRequest } from '@/types/retrieval'
import { anchorFromCitation, isPreviewSupported, unsupportedPreviewMessage } from '@/utils/documentWorkbench'
import { formatEvidenceLabel } from '@/utils/evidence'
import { describeScopeTrace } from '@/utils/retrievalScope'

const chatStore = useChatStore()
const documentStore = useDocumentStore()
const folderStore = useFolderStore()
const router = useRouter()

// UI State
const activeTab = ref('chat')
const inputText = ref('')
const showLeftPanel = ref(true)
const showRightPanel = ref(false)
const showRollbackPanel = ref(false) // 撤回历史面板展开状态

// 折叠状态管理
const collapsedThinking = ref<Set<string>>(new Set())
const collapsedTools = ref<Set<string>>(new Set())
// 管理每个工具项的展开状态（格式：messageId-toolIndex）
const expandedToolItems = ref<Set<string>>(new Set())

// 引用预览状态
const previewDocId = ref<string>('')
const previewDocName = ref<string>('')
const previewDocType = ref<string>('')
const previewAnchor = ref<SourceAnchor | null>(null)
const previewUnsupportedMessage = ref<string>('')

// 右侧引用预览窗口状态
const showRightPdfViewer = ref(false)
const showRightUniversalPreview = ref(false)
const scopeMode = ref<'all' | 'folder' | 'folder_subtree' | 'selected'>('all')

let resumeFromBackgroundNeeded = false
let scrollListenerAttached = false
const userPinnedToBottom = ref(true)

// Stats
const stats = ref({
  documents: 0,
  conversations: 0,
  todayChats: 0
})

const examplePrompts = ref([
  '帮我分析这份市场调研报告的关键数据',
  '总结这份合同的重点条款',
  '从这份财报中提取核心财务指标',
  '分析用户画像和目标受众',
])

// Functions
function handleNewChat() {
  chatStore.clearMessages()
  inputText.value = ''
}

async function handleSend() {
  if (!inputText.value.trim() || chatStore.isLoading) return
  
  const question = inputText.value.trim()
  inputText.value = ''
  showRightPanel.value = false
  userPinnedToBottom.value = true
  
  // 先触发发送（会同步插入用户消息与助手占位）
  const sending = chatStore.sendMessage(question, buildChatScope())

  // 等待渲染后滚动，确保用户问题可见
  await nextTick()
  scrollToBottom()

  await sending
  
  // 再次滚动到底部
  await nextTick()
  if (userPinnedToBottom.value) {
    scrollToBottom()
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function buildChatScope(): ChatScopeRequest | undefined {
  if (scopeMode.value === 'selected' && documentStore.selectedIds.size > 0) {
    return { document_ids: Array.from(documentStore.selectedIds), strict_scope: true }
  }
  if ((scopeMode.value === 'folder' || scopeMode.value === 'folder_subtree') && folderStore.currentFolderId) {
    return {
      folder_id: folderStore.currentFolderId,
      include_subfolders: scopeMode.value === 'folder_subtree',
      strict_scope: true,
    }
  }
  return undefined
}

const currentScopeLabel = computed(() => {
  if (scopeMode.value === 'selected') {
    const count = documentStore.selectedIds.size
    return count > 0 ? `Selected documents (${count})` : 'Selected documents'
  }
  if (scopeMode.value === 'folder' && folderStore.currentFolder) {
    return `Folder: ${folderStore.currentFolder.name}`
  }
  if (scopeMode.value === 'folder_subtree' && folderStore.currentFolder) {
    return `Folder + subfolders: ${folderStore.currentFolder.name}`
  }
  return 'All documents'
})

function fallbackDisclosure(message: Message): string {
  const labels = new Set((message.retrievalFallbacks || []).map((item) =>
    item === 'keyword_fallback' ? 'keyword fallback' : item === 'visual_summary' ? 'visual summary' : item
  ))
  return Array.from(labels).join(', ')
}

function evidenceLabel(item: EvidenceItem): string {
  return formatEvidenceLabel({
    documentName: item.documentName,
    displayLabel: item.displayLabel,
    sourceAnchor: item.sourceAnchor,
  })
}

const previewAnchorLabel = computed(() =>
  formatEvidenceLabel({
    documentName: previewDocName.value,
    sourceAnchor: previewAnchor.value,
  })
)

// 切换思考过程的折叠状态
function toggleThinking(msgId: string) {
  if (collapsedThinking.value.has(msgId)) {
    collapsedThinking.value.delete(msgId)
  } else {
    collapsedThinking.value.add(msgId)
  }
  collapsedThinking.value = new Set(collapsedThinking.value)
}

// 切换工具调用的折叠状态
function toggleTools(msgId: string) {
  if (collapsedTools.value.has(msgId)) {
    collapsedTools.value.delete(msgId)
  } else {
    collapsedTools.value.add(msgId)
  }
  collapsedTools.value = new Set(collapsedTools.value)
}

// 切换单个工具项的展开状态
function toggleToolItem(msgId: string, toolIndex: number) {
  const key = `${msgId}-${toolIndex}`
  if (expandedToolItems.value.has(key)) {
    expandedToolItems.value.delete(key)
  } else {
    expandedToolItems.value.add(key)
  }
  expandedToolItems.value = new Set(expandedToolItems.value)
}

// 格式化 JSON 显示
function formatJSON(obj: any): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

// 处理引用点击 - 支持多格式
async function handleCitationClick(
  docName: string, 
  position: string,
  positionType: string = 'page'
) {
  console.log('点击引用:', docName, positionType, position)
  
  // 如果文档列表为空，尝试重新获取
  if (documentStore.documents.length === 0) {
    await documentStore.fetchDocuments(1, undefined, undefined, true)
  }
  
  // 规范化文档名 - 去除所有空格用于比较
  const normalizedDocName = docName.trim()
  const normalizedDocNameNoSpaces = normalizedDocName.replace(/\s+/g, '')
  console.log('规范化后的文档名:', normalizedDocName)
  console.log('无空格版本:', normalizedDocNameNoSpaces)
  
  // 查找文档 ID - 支持有空格和无空格两种匹配方式
  let doc = documentStore.documents.find(d => {
    const originalNoSpaces = d.original_name.replace(/\s+/g, '')
    const nameNoSpaces = d.name.replace(/\s+/g, '')
    
    return d.original_name === normalizedDocName || 
           d.name === normalizedDocName ||
           originalNoSpaces === normalizedDocNameNoSpaces ||
           nameNoSpaces === normalizedDocNameNoSpaces
  })
  
  if (!doc) {
    console.log('精确匹配失败，尝试模糊匹配...')
    // 尝试模糊匹配 - 使用无空格版本进行包含匹配
    doc = documentStore.documents.find(d => {
      const originalNoSpaces = d.original_name.toLowerCase().replace(/\s+/g, '')
      const nameNoSpaces = d.name.toLowerCase().replace(/\s+/g, '')
      const searchNoSpaces = normalizedDocNameNoSpaces.toLowerCase()
      
      return originalNoSpaces.includes(searchNoSpaces) || 
             nameNoSpaces.includes(searchNoSpaces) ||
             searchNoSpaces.includes(originalNoSpaces) ||
             searchNoSpaces.includes(nameNoSpaces)
    })
  }
  
  // 如果本地缓存中找不到，通过搜索API查找所有文档
  if (!doc) {
    console.log('本地缓存未找到，尝试通过搜索API查找...')
    try {
      // 使用文档名作为搜索关键词，获取所有匹配的文档（不限制页数）
      const searchResults = await documentApi.searchByName(normalizedDocName)
      if (searchResults && searchResults.length > 0) {
        const foundDoc = searchResults[0]
        if (foundDoc) {
          doc = foundDoc
          console.log('通过搜索API找到文档:', foundDoc.original_name, 'ID:', foundDoc.id)
        }
      }
    } catch (e) {
      console.error('搜索API调用失败:', e)
    }
  }
  
  if (!doc) {
    console.error('未找到匹配文档, 可用文档数:', documentStore.documents.length)
    return
  }
  
  console.log('找到文档:', doc.original_name, 'ID:', doc.id, '类型:', doc.file_type)

  // 构建锚点信息
  const fileType = (doc.file_type || '').toLowerCase()
  const anchor: SourceAnchor = { format: fileType.replace('.', '') }
  previewUnsupportedMessage.value = ''
  
  // 解析位置
  const posValue = parseInt(position, 10)
  
  if (fileType === '.pdf') {
    // PDF 使用页码
    anchor.start_page = posValue
    anchor.end_page = posValue
    showRightPdfViewer.value = true
    showRightUniversalPreview.value = false
  } else if (!isPreviewSupported(fileType)) {
    previewUnsupportedMessage.value = unsupportedPreviewMessage(fileType)
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = false
  } else if (fileType === '.txt' || fileType === '.md' || fileType === '.markdown') {
    // 文本文件使用行号或段落号
    if (positionType === 'line') {
      anchor.start_line = posValue
      anchor.end_line = posValue
    } else {
      // 非 PDF 的 p.x 代表内容单元序号，不做“40行/页”换算
      anchor.start_line = posValue
      anchor.end_line = posValue
    }
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = true
  } else if (fileType === '.csv' || fileType === '.tsv') {
    // CSV/TSV 使用行号
    anchor.start_row = posValue
    anchor.end_row = posValue
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = true
  } else if (fileType === '.xlsx') {
    // Excel 使用行号，支持 sheet 指定
    anchor.start_row = posValue
    anchor.end_row = posValue
    // TODO: 从 position 中解析 sheet 名称
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = true
  } else if (fileType === '.docx') {
    // Word 使用段落号
    anchor.start_paragraph = posValue
    anchor.end_paragraph = posValue
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = true
  } else if (fileType === '.pptx') {
    // PPT 使用幻灯片号
    anchor.unit_type = 'slide'
    anchor.slide = posValue
    anchor.start_slide = posValue
    anchor.end_slide = posValue
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = true
  } else {
    // 不支持的格式，仍然尝试 PDF 预览
    console.warn('Unsupported citation preview file type:', fileType)
    previewUnsupportedMessage.value = unsupportedPreviewMessage(fileType)
    showRightPdfViewer.value = false
    showRightUniversalPreview.value = false
  }
  
  // 设置预览状态
  previewDocId.value = doc.id
  previewDocName.value = doc.original_name
  previewDocType.value = fileType
  previewAnchor.value = anchor
  showRightPanel.value = true
}

// Markdown 渲染 - 处理引用格式
async function openEvidencePreview(item: EvidenceItem) {
  if (documentStore.documents.length === 0) {
    await documentStore.fetchDocuments(1, undefined, undefined, true)
  }

  let doc = item.docId
    ? documentStore.documents.find((candidate) => candidate.id === item.docId)
    : null

  if (!doc && item.documentName) {
    const normalizedName = item.documentName.trim().replace(/\s+/g, '')
    doc = documentStore.documents.find((candidate) => {
      return candidate.original_name.replace(/\s+/g, '') === normalizedName
        || candidate.name.replace(/\s+/g, '') === normalizedName
    }) || null
  }

  if (!doc && item.documentName) {
    try {
      const searchResults = await documentApi.searchByName(item.documentName)
      doc = searchResults?.[0] || null
    } catch (error) {
      console.error('Failed to search evidence document:', error)
    }
  }

  if (!doc) return

  const fileType = (doc.file_type || '').toLowerCase()
  previewDocId.value = doc.id
  previewDocName.value = doc.original_name
  previewDocType.value = fileType
  previewAnchor.value = anchorFromCitation({
    fileType,
    sourceAnchor: item.sourceAnchor as Record<string, unknown> | null | undefined,
  }) as SourceAnchor
  previewUnsupportedMessage.value = ''
  showRightPdfViewer.value = fileType === '.pdf'
  showRightUniversalPreview.value = fileType !== '.pdf' && isPreviewSupported(fileType)
  if (!showRightPdfViewer.value && !showRightUniversalPreview.value) {
    previewUnsupportedMessage.value = unsupportedPreviewMessage(fileType)
  }
  showRightPanel.value = true
}

function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    let processedContent = content
    
    // 1. 标准格式：[[doc_name type.position]]
    // 支持：p.页码, line.行号, row.行号, para.段落号, slide.幻灯片号
    const standardCitationRegex = /\[\[(.+?)\s+(p|line|row|para|slide)\.(\d+)(?:[-~](\d+))?\]\]/gi
    
    processedContent = processedContent.replace(
      standardCitationRegex,
      (_match, docName, positionType, startPos, endPos) => {
        const positionTypeMap: Record<string, string> = {
          'p': 'page',
          'line': 'line',
          'row': 'row',
          'para': 'para',
          'slide': 'slide'
        }
        const fullPositionType = positionTypeMap[positionType.toLowerCase()] || 'page'
        const displayName = docName.trim().replace(/\.(pdf|txt|md|csv|tsv|xlsx|docx|pptx)$/i, '')
        const positionDisplay = endPos 
          ? `${positionType}.${startPos}-${endPos}` 
          : `${positionType}.${startPos}`
        
        return `<a href="#" class="citation-link" data-doc-name="${docName.trim()}" data-position-type="${fullPositionType}" data-position="${startPos}" onclick="event.preventDefault(); window.handleCitationClick && window.handleCitationClick('${docName.trim()}', '${startPos}', '${fullPositionType}');">${displayName} ${positionDisplay}</a>`
      }
    )
    
    // 2. 向后兼容：[[doc_name p.page_num]] 格式（用于 PDF）
    const legacyCitationRegex = /\[\[(.+?)\s+p\.(\d+)(?:[-~](\d+))?\]\]/g
    processedContent = processedContent.replace(
      legacyCitationRegex,
      (_match, docName, startPage, endPage) => {
        const displayName = docName.trim().replace(/\.pdf$/i, '')
        const pageDisplay = endPage ? `p.${startPage}-${endPage}` : `p.${startPage}`
        return `<a href="#" class="citation-link" data-doc-name="${docName.trim()}" data-position-type="page" data-position="${startPage}" onclick="event.preventDefault(); window.handleCitationClick && window.handleCitationClick('${docName.trim()}', '${startPage}', 'page');">${displayName} ${pageDisplay}</a>`
      }
    )
    
    return marked.parse(processedContent, {
      breaks: true,
      gfm: true
    }) as string
  } catch (e) {
    console.error('Markdown parsing error:', e)
    return content
  }
}

// 将 handleCitationClick 暴露到 window，供 onclick 使用
(window as any).handleCitationClick = handleCitationClick

// 导航到文档页面
function navigateToDocuments() {
  router.push('/documents')
}

const markdownCache = new Map<string, { source: string; html: string }>()
function renderMessageContent(message: Message): string {
  const cacheKey = message.id
  const cached = markdownCache.get(cacheKey)
  if (cached && cached.source === message.content) {
    return cached.html
  }
  const html = renderMarkdown(message.content)
  markdownCache.set(cacheKey, { source: message.content, html })
  return html
}

// 处理示例提示点击
function handlePromptClick(prompt: string) {
  inputText.value = prompt
}

// 加载指定对话
async function loadConversation(conversationId: string) {
  const loaded = chatStore.loadConversation(conversationId)
  if (!loaded) return
  userPinnedToBottom.value = true
  await nextTick()
  scrollToBottom()
}

function scrollToBottom() {
  const scrollContainer = document.querySelector('.messages-scroll')
  if (scrollContainer) {
    scrollContainer.scrollTop = scrollContainer.scrollHeight
  }
}

function getScrollContainer(): HTMLElement | null {
  return document.querySelector('.messages-scroll') as HTMLElement | null
}

function handleMessagesScroll() {
  userPinnedToBottom.value = isScrollNearBottom(96)
}

function ensureScrollListenerAttached() {
  if (scrollListenerAttached) return
  const container = getScrollContainer()
  if (!container) return
  container.addEventListener('scroll', handleMessagesScroll, { passive: true })
  scrollListenerAttached = true
  handleMessagesScroll()
}

function detachScrollListener() {
  if (!scrollListenerAttached) return
  const container = getScrollContainer()
  if (container) {
    container.removeEventListener('scroll', handleMessagesScroll)
  }
  scrollListenerAttached = false
}

function isScrollNearBottom(threshold = 80): boolean {
  const scrollContainer = document.querySelector('.messages-scroll') as HTMLElement | null
  if (!scrollContainer) return true
  const distance = scrollContainer.scrollHeight - scrollContainer.scrollTop - scrollContainer.clientHeight
  return distance <= threshold
}

function mergeMessagesIncrementally(incomingMessages: Message[]): { changed: boolean } {
  const existing = chatStore.messages
  const incomingIds = new Set(incomingMessages.map((m) => m.id))
  const indexById = new Map(existing.map((m, i) => [m.id, i]))
  const usedIndices = new Set<number>()
  let changed = false

  console.log(`[merge] START: existing=${existing.length}, incoming=${incomingMessages.length}`)

  const toolStepsEqual = (a: Message['toolSteps'], b: Message['toolSteps']) =>
    JSON.stringify(a || []) === JSON.stringify(b || [])

  function findDuplicateUserIndex(content: string): number {
    for (let i = existing.length - 1; i >= 0; i--) {
      if (usedIndices.has(i)) continue
      const msg = existing[i]
      if (!msg || msg.role !== 'user') continue
      if (msg.content !== content) continue
      if (incomingIds.has(msg.id)) continue
      return i
    }
    return -1
  }

  function findDuplicateAssistantIndex(incoming: Message): number {
    for (let i = existing.length - 1; i >= 0; i--) {
      if (usedIndices.has(i)) continue
      const msg = existing[i]
      if (!msg || msg.role !== 'assistant') continue
      if (incomingIds.has(msg.id)) continue
      if (msg.isLoading) continue
      // 仅合并非加载态的完整回复，避免误伤占位消息
      if (incoming.isLoading) continue

      // 精确匹配
      if (
        msg.content === incoming.content &&
        msg.thinking === incoming.thinking &&
        toolStepsEqual(msg.toolSteps, incoming.toolSteps)
      ) {
        return i
      }

      // 宽松匹配：前端 stream 结束时的内容可能与后端保存的有细微差异（如最后几个字符）
      // 只要前 90% 相同 + role 相同 + thinking 非空时也宽松匹配，就视为同一条
      const contentMatchLen = Math.min(msg.content.length, incoming.content.length)
      if (contentMatchLen >= 10) {
        const matchThreshold = Math.floor(contentMatchLen * 0.9)
        const prefixMatch =
          msg.content.slice(0, matchThreshold) === incoming.content.slice(0, matchThreshold)
        if (prefixMatch) {
          // thinking 宽松匹配：至少一侧为空或前 80% 相同
          let thinkingOk = false
          if (!msg.thinking && !incoming.thinking) {
            thinkingOk = true
          } else {
            const tLen = Math.min((msg.thinking || '').length, (incoming.thinking || '').length)
            if (tLen === 0) {
              thinkingOk = true
            } else {
              const tThreshold = Math.floor(tLen * 0.8)
              thinkingOk = (msg.thinking || '').slice(0, tThreshold) === (incoming.thinking || '').slice(0, tThreshold)
            }
          }
          if (thinkingOk) {
            return i
          }
        }
      }
    }
    return -1
  }

  for (const incoming of incomingMessages) {
    const existingIndex = indexById.get(incoming.id)
    if (existingIndex !== undefined) {
      usedIndices.add(existingIndex)
      const current = existing[existingIndex]
      if (
        current.content !== incoming.content ||
        current.thinking !== incoming.thinking ||
        current.isLoading !== incoming.isLoading ||
        !toolStepsEqual(current.toolSteps, incoming.toolSteps)
      ) {
        existing[existingIndex] = {
          ...current,
          content: incoming.content,
          thinking: incoming.thinking,
          toolSteps: incoming.toolSteps,
          isLoading: incoming.isLoading,
          timestamp: incoming.timestamp,
        }
        changed = true
      }
      continue
    }

    if (incoming.role === 'user') {
      const dupUserIndex = findDuplicateUserIndex(incoming.content)
      if (dupUserIndex !== -1) {
        const current = existing[dupUserIndex]
        existing[dupUserIndex] = {
          ...current,
          id: incoming.id,
          timestamp: incoming.timestamp,
        }
        indexById.set(incoming.id, dupUserIndex)
        usedIndices.add(dupUserIndex)
        changed = true
        continue
      }
    }

    if (incoming.role === 'assistant') {
      const dupAssistantIndex = findDuplicateAssistantIndex(incoming)
      if (dupAssistantIndex !== -1) {
        const current = existing[dupAssistantIndex]
        existing[dupAssistantIndex] = {
          ...current,
          id: incoming.id,
          content: incoming.content,
          thinking: incoming.thinking,
          toolSteps: incoming.toolSteps,
          isLoading: incoming.isLoading,
          timestamp: incoming.timestamp,
        }
        indexById.set(incoming.id, dupAssistantIndex)
        usedIndices.add(dupAssistantIndex)
        changed = true
        continue
      }
    }

    const placeholderIndex = existing.findIndex(
      (m, i) =>
        !usedIndices.has(i) &&
        m.role === 'assistant' &&
        m.isLoading &&
        !incomingIds.has(m.id)
    )

    if (placeholderIndex !== -1) {
      existing[placeholderIndex] = incoming
      indexById.set(incoming.id, placeholderIndex)
      usedIndices.add(placeholderIndex)
      changed = true
    } else {
      existing.push(incoming)
      indexById.set(incoming.id, existing.length - 1)
      usedIndices.add(existing.length - 1)
      changed = true
    }
  }

  // 清理本地残留的临时 assistant 占位（避免返回页面后出现悬空加载动画）
  for (let i = existing.length - 1; i >= 0; i--) {
    const m = existing[i]
    if (!m) continue
    const isStalePlaceholder =
      m.role === 'assistant' &&
      m.isLoading &&
      !incomingIds.has(m.id) &&
      (m.content || '') === '' &&
      (m.thinking || '') === '' &&
      (!m.toolSteps || m.toolSteps.length === 0)
    if (isStalePlaceholder) {
      existing.splice(i, 1)
      changed = true
    }
  }

  // 按时间戳排序，确保消息顺序（防止 ID 冲突导致顺序错乱）
  existing.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0))

  if (changed) {
    console.log(`[merge] END: existing=${existing.length}, changed=true`)
  }
  return { changed }
}

function copyMessage(content: string) {
  navigator.clipboard.writeText(content)
}

function regenerateMessage(messageId: string) {
  chatStore.regenerateMessage(messageId)
}

// 撤回到指定消息（包含该消息）
function rollbackToMessage(messageId: string) {
  const result = chatStore.rollbackToMessage(messageId)
  if (result.content) {
    inputText.value = result.content
  }
  if (result.deletedCount > 0) {
    showRollbackPanel.value = true
  }
}

// 恢复上一次撤回
function restoreLastRollback() {
  chatStore.restoreRollback()
  showRollbackPanel.value = false
}

// 清除撤回历史
function clearRollbackHistory() {
  chatStore.clearRollbackHistory()
  showRollbackPanel.value = false
}

// 获取最近撤回的内容预览
function getLastRollbackPreview(): string {
  const history = chatStore.rollbackHistory
  if (history.length === 0) return ''
  const lastState = history[history.length - 1]
  const lastMessage = lastState.messages[lastState.messages.length - 1]
  return lastMessage ? lastMessage.content.slice(0, 50) : ''
}

function getToolStatusText(toolName: string): string {
  const toolNames: Record<string, string> = {
    'get_document_structure': '获取文档结构',
    'get_page_content': '获取页面内容',
    'get_section_content': '获取章节内容',
    'search_documents': '搜索文档',
    'find_related_documents': '搜索相关文档',
    'list_documents': '列出文档',
    'chat': '智能问答',
  }
  return toolNames[toolName] || toolName
}

// 监听消息数量变化，避免深度监听导致流式渲染卡顿
watch(() => chatStore.messages.length, (newLen, oldLen) => {
  if (newLen <= 0) return
  ensureScrollListenerAttached()

  // 初始加载不自动折叠，保持用户离开前状态
  if (!oldLen || oldLen === 0) return

  // 仅处理新增消息
  if (newLen > oldLen) {
    const newMsg = chatStore.messages[newLen - 1]
    if (!newMsg || newMsg.role !== 'assistant') return
    if (newMsg.thinking) collapsedThinking.value.add(newMsg.id)
    if (newMsg.toolSteps && newMsg.toolSteps.length > 0) collapsedTools.value.add(newMsg.id)
    collapsedThinking.value = new Set(collapsedThinking.value)
    collapsedTools.value = new Set(collapsedTools.value)
  }
}, { immediate: true })

const streamRenderSignal = computed(() => {
  const last = chatStore.messages[chatStore.messages.length - 1]
  if (!last || last.role !== 'assistant') return ''
  return `${last.id}|${last.isLoading ? 1 : 0}|${last.content.length}|${last.thinking.length}|${last.toolSteps.length}`
})

watch(streamRenderSignal, async () => {
  const last = chatStore.messages[chatStore.messages.length - 1]
  if (!last || last.role !== 'assistant' || !last.isLoading) return
  if (!userPinnedToBottom.value) return
  await nextTick()
  requestAnimationFrame(() => scrollToBottom())
}, { flush: 'post' })

onMounted(async () => {
  console.log('ChatView onMounted - 开始加载')
  
  // 仅在内存中没有会话时才从 localStorage 恢复，避免覆盖正在流式更新的状态
  if (chatStore.messages.length === 0 && chatStore.conversations.length === 0) {
    chatStore.loadConversationsFromStorage()
  }
  
  // 等待 Vue 响应式更新完成
  await nextTick()
  ensureScrollListenerAttached()
  
  // 检查是否有未完成的对话需要恢复
  await resumeConversationIfNeeded()
  
  // 获取文档列表（包含所有文件夹）
  console.log('开始获取文档列表...')
  await documentStore.fetchDocuments(1, undefined, undefined, true)
  console.log('文档列表获取完成，数量:', documentStore.documents.length)
  console.log('文档详情:', documentStore.documents.map(d => d.original_name))
  stats.value.documents = documentStore.total
  
  console.log('ChatView onMounted - 加载完成')
  
  // 添加 beforeunload 事件监听器，防止页面刷新时丢失对话
  window.addEventListener('beforeunload', handleBeforeUnload)
  
  // 添加 visibilitychange 事件监听器，处理页面切换
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  console.log('ChatView onBeforeUnmount - 保存当前会话')
  // 组件销毁前保存当前会话
  chatStore.saveCurrentSession()
  
  // 移除 beforeunload 事件监听器
  window.removeEventListener('beforeunload', handleBeforeUnload)
  
  // 移除 visibilitychange 事件监听器
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  detachScrollListener()
})

// beforeunload 事件处理函数
function handleBeforeUnload() {
  console.log('beforeunload - 保存当前会话')
  chatStore.saveCurrentSession()
}

// visibilitychange 事件处理函数 - 处理页面切换
async function handleVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    resumeFromBackgroundNeeded = true
    return
  }

  if (document.visibilityState === 'visible') {
    console.log('页面重新可见 - 检查是否需要恢复对话')
    if (resumeFromBackgroundNeeded) {
      await resumeConversationIfNeeded()
      resumeFromBackgroundNeeded = false
    }
  }
}

// 恢复未完成的对话
async function resumeConversationIfNeeded() {
  // 检查是否有当前会话
  if (!chatStore.currentSessionId) {
    return
  }
  
  // 检查是否有后端的 conversation_id（区分本地草稿和已同步的会话）
  if (!chatStore.conversationId) {
    return
  }
  
  // 检查最后一条消息是否还在加载中
  const lastMessage = chatStore.messages[chatStore.messages.length - 1]
  if (!lastMessage) {
    return
  }
  
  // 无论最后一条状态如何，都尝试与后端对齐一次
  
  
  try {
    // 使用 conversationId（后端ID）调用 API，而不是 currentSessionId（本地ID）
    const backendConversationId = chatStore.conversationId || chatStore.currentSessionId
    const shouldKeepBottom = isScrollNearBottom()
    
    // 调用 API 获取该会话的所有消息
    let messages: any[] = []
    try {
      const response = await chatApi.getMessages(backendConversationId)
      messages = response.data
    } catch (error: any) {
      if (error.response?.status === 404) {
        // 新建会话或尚未同步到后端时静默返回
        return
      }
      throw error // 其他错误继续抛出
    }
    
    if (!messages || messages.length === 0) {
      console.log('后端没有该会话的消息')
      chatStore.isLoading = false
      return
    }
    
    // 转换后端消息格式为前端格式
    const convertedMessages: Message[] = messages.map((msg: any) => ({
      id: msg.id,
      role: msg.role,
      content: msg.content || '',
      thinking: msg.thinking || '',
      toolSteps: msg.agent_steps || [],
      isLoading: msg.role === 'assistant' && msg.status === 'streaming',
      timestamp: new Date(msg.created_at).getTime(),
    }))

    // 增量合并，避免整段替换造成页面闪动
    const { changed } = mergeMessagesIncrementally(convertedMessages)
    
    // 更新 loading 状态
    const lastMsg = convertedMessages[convertedMessages.length - 1]
    if (lastMsg && lastMsg.role === 'assistant') {
      chatStore.isLoading = lastMsg.isLoading
    } else {
      chatStore.isLoading = false
    }
    
    // 保存到本地存储
    chatStore.saveCurrentSession()
    
    // 滚动到底部
    if (changed && shouldKeepBottom) {
      await nextTick()
      scrollToBottom()
    }
    
  } catch (error) {
    console.error('恢复对话失败:', error)
  } finally {
    // 如果最后一条消息已完成，确保 isLoading 为 false
    const lastMsg = chatStore.messages[chatStore.messages.length - 1]
    if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.isLoading) {
      chatStore.isLoading = false
    }
  }
}
</script>

<template>
  <div class="app-container">
    <!-- Left Sidebar - Navigation & History -->
    <aside :class="['sidebar-left', { collapsed: !showLeftPanel }]">
      <div class="sidebar-content">
        <!-- Header -->
        <div class="sidebar-header">
          <div class="logo">
            <div class="logo-icon">
              <Sparkles class="w-5 h-5" />
            </div>
            <span class="logo-text">KnowClaw</span>
          </div>
        </div>

        <!-- New Chat Button -->
        <button class="new-chat-btn" @click="handleNewChat">
          <Plus class="w-4 h-4" />
          <span>新建对话</span>
        </button>

        <!-- Navigation -->
        <nav class="nav-menu">
          <button :class="['nav-item', { active: activeTab === 'chat' }]">
            <MessageSquare class="w-4 h-4" />
            <span>对话</span>
          </button>
          <button :class="['nav-item', { active: activeTab === 'documents' }]" @click="navigateToDocuments">
            <FileText class="w-4 h-4" />
            <span>文档</span>
            <span class="nav-badge">{{ stats.documents }}</span>
          </button>
          <button :class="['nav-item', { active: activeTab === 'library' }]">
            <BookOpen class="w-4 h-4" />
            <span>知识库</span>
          </button>
        </nav>

        <!-- Recent Chats -->
        <div class="chat-history">
          <div class="section-header">
            <span class="section-title">对话记录</span>
          </div>
          
          <div class="chat-list">
            <div v-if="chatStore.conversations.length === 0" class="empty-chat-hint">
              暂无历史对话
            </div>
            <div
              v-for="conv in chatStore.conversations" 
              :key="conv.id"
              :class="['chat-item', { active: chatStore.currentSessionId === conv.id }]"
              @click="loadConversation(conv.id)"
            >
              <MessageSquare class="w-3.5 h-3.5 chat-icon" />
              <span class="chat-title">{{ conv.title }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="sidebar-footer">
        <button class="footer-item" @click="router.push('/settings')">
          <Settings class="w-4 h-4" />
          <span>设置</span>
        </button>
      </div>
    </aside>

    <!-- Toggle Left Panel -->
    <button 
      v-if="showLeftPanel"
      class="panel-toggle left"
      @click="showLeftPanel = false"
      title="收起侧边栏"
    >
      <PanelLeft class="w-4 h-4" />
    </button>

    <!-- Expand Left Panel Button (when collapsed) -->
    <button 
      v-if="!showLeftPanel"
      class="panel-toggle-expand left"
      @click="showLeftPanel = true"
      title="展开侧边栏"
    >
      <PanelRight class="w-4 h-4" />
    </button>

    <!-- Main Chat Area -->
    <main class="main-area">
      <!-- Empty State -->
      <template v-if="chatStore.messages.length === 0">
        <div class="empty-state">
          <div class="empty-content">
            <div class="welcome-center">
              <div class="welcome-logo">
                <div class="logo-glow"></div>
                <Sparkles class="w-8 h-8 welcome-icon" />
              </div>
              
              <h1 class="welcome-title">
                你好，我是 <span class="gradient-text">KnowClaw</span>
              </h1>
              
              <p class="welcome-desc">
                你的智能文档助手。上传文档，开始探索知识的无限可能。
              </p>

              <div class="quick-prompts">
                <button 
                  v-for="(prompt, i) in examplePrompts" 
                  :key="i"
                  class="prompt-chip"
                  @click="handlePromptClick(prompt)"
                >
                  <Highlighter class="w-3.5 h-3.5" />
                  <span>{{ prompt }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Chat Content -->
      <template v-else>
        <div class="chat-container">
          <div class="messages-scroll">
            <div class="messages-list">
              <!-- Messages -->
              <div
                v-for="message in chatStore.messages"
                :key="message.id"
                :class="['message-item', message.role]"
              >
                <!-- Avatar -->
                <div class="message-avatar">
                  <div v-if="message.role === 'user'" class="avatar user-avatar">U</div>
                  <div v-else class="avatar ai-avatar">
                    <Sparkles class="w-4 h-4" />
                  </div>
                </div>

                <div class="message-body">
                  <!-- Header -->
                  <div class="message-header">
                    <span class="message-author">{{ message.role === 'user' ? '你' : 'KnowClaw' }}</span>
                  </div>

                  <!-- Thinking Section -->
                  <div v-if="message.thinking" class="thinking-section">
                    <button class="thinking-toggle" @click="toggleThinking(message.id)">
                      <Brain class="w-3.5 h-3.5 thinking-icon" />
                      <span>思考过程</span>
                      <ChevronDown 
                        v-if="!collapsedThinking.has(message.id)" 
                        class="w-3.5 h-3.5 toggle-arrow" 
                      />
                      <ChevronRight 
                        v-else 
                        class="w-3.5 h-3.5 toggle-arrow" 
                      />
                    </button>
                    <div v-if="!collapsedThinking.has(message.id)" class="thinking-content">
                      <pre>{{ message.thinking }}</pre>
                    </div>
                  </div>

                  <!-- Tools Section -->
                  <div v-if="message.toolSteps && message.toolSteps.length > 0" class="tools-section">
                    <button class="tools-toggle" @click="toggleTools(message.id)">
                      <div class="tools-info">
                        <Wrench class="w-3.5 h-3.5 tools-icon" />
                        <span>工具调用 ({{ message.toolSteps.length }})</span>
                      </div>
                      <ChevronDown 
                        v-if="!collapsedTools.has(message.id)" 
                        class="w-3.5 h-3.5 toggle-arrow" 
                      />
                      <ChevronRight 
                        v-else 
                        class="w-3.5 h-3.5 toggle-arrow" 
                      />
                    </button>
                    
                    <div v-if="!collapsedTools.has(message.id)" class="tools-list">
                      <div 
                        v-for="(tool, tIdx) in message.toolSteps" 
                        :key="tIdx"
                        class="tool-item"
                        :class="{ expanded: expandedToolItems.has(`${message.id}-${tIdx}`) }"
                        @click="toggleToolItem(message.id, tIdx)"
                      >
                        <div class="tool-header">
                          <div class="tool-status">
                            <CheckCircle class="w-3 h-3" />
                          </div>
                          <span class="tool-name">{{ getToolStatusText(tool.toolName) }}</span>
                          <span v-if="tool.elapsedMs" class="tool-time">{{ tool.elapsedMs }}ms</span>
                          <ChevronDown 
                            v-if="expandedToolItems.has(`${message.id}-${tIdx}`)" 
                            class="w-3 h-3 tool-expand-icon" 
                          />
                          <ChevronRight 
                            v-else 
                            class="w-3 h-3 tool-expand-icon" 
                          />
                        </div>
                        
                        <!-- 工具详情 -->
                        <div v-if="expandedToolItems.has(`${message.id}-${tIdx}`)" class="tool-details">
                          <div class="tool-detail-section">
                            <div class="tool-detail-label">请求参数</div>
                            <pre class="tool-detail-content">{{ formatJSON(tool.arguments) }}</pre>
                          </div>
                          <div v-if="tool.result" class="tool-detail-section">
                            <div class="tool-detail-label">执行结果</div>
                            <pre class="tool-detail-content">{{ formatJSON(tool.result) }}</pre>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- Content -->
                  <div v-if="message.content" class="message-text">
                    <template v-if="message.role === 'user'">
                      <div class="user-message-content">{{ message.content }}</div>
                    </template>
                    <template v-else>
                      <div class="markdown-body" v-html="renderMessageContent(message)"></div>
                      <div v-if="!message.isLoading" class="evidence-meta">
                        <span>{{ describeScopeTrace(message.retrievalScope) }}</span>
                        <span v-if="message.retrievalScope?.expanded_to_user_library" class="evidence-warning">
                          Scope expanded
                        </span>
                        <span v-if="fallbackDisclosure(message)" class="evidence-warning">
                          Used {{ fallbackDisclosure(message) }}
                        </span>
                      </div>
                      <div v-if="message.evidenceItems?.length" class="evidence-chip-row">
                        <button
                          v-for="item in message.evidenceItems"
                          :key="evidenceLabel(item)"
                          class="evidence-chip"
                          :class="{ fallback: item.retrievalSource === 'keyword_fallback' || item.retrievalSource === 'visual_summary' }"
                          type="button"
                          @click="openEvidencePreview(item)"
                        >
                          {{ evidenceLabel(item) }}
                        </button>
                      </div>
                    </template>
                  </div>

                  <!-- Message Actions (below content) -->
                  <div class="message-actions-bar">
                    <!-- 用户消息操作 -->
                    <template v-if="message.role === 'user'">
                      <button class="action-btn" title="复制" @click="copyMessage(message.content)">
                        <Copy class="w-3.5 h-3.5" />
                        <span>复制</span>
                      </button>
                      <button class="action-btn" title="撤回到此处" @click="rollbackToMessage(message.id)">
                        <Undo class="w-3.5 h-3.5" />
                        <span>撤回到此处</span>
                      </button>
                    </template>
                    <!-- AI消息操作 -->
                    <template v-else>
                      <button class="action-btn" title="复制" @click="copyMessage(message.content)">
                        <Copy class="w-3.5 h-3.5" />
                        <span>复制</span>
                      </button>
                      <button 
                        v-if="!message.isLoading" 
                        class="action-btn" 
                        title="重新生成"
                        @click="regenerateMessage(message.id)"
                      >
                        <RefreshCw class="w-3.5 h-3.5" />
                        <span>重新生成</span>
                      </button>
                    </template>
                  </div>

                  <!-- Loading -->
                  <div v-if="message.isLoading" class="message-loading">
                    <div class="loading-dots">
                      <span></span>
                      <span></span>
                      <span></span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Input Area -->
      <div class="input-container">
        <!-- 撤回历史折叠面板 -->
        <div v-if="chatStore.rollbackHistory.length > 0" class="rollback-panel">
          <button 
            class="rollback-toggle"
            @click="showRollbackPanel = !showRollbackPanel"
          >
            <div class="rollback-info">
              <RotateCcw class="w-3.5 h-3.5 rollback-icon" />
              <span>已撤回 {{ chatStore.rollbackHistory.length }} 条消息</span>
              <span v-if="!showRollbackPanel" class="rollback-preview">
                {{ getLastRollbackPreview() }}{{ getLastRollbackPreview().length >= 50 ? '...' : '' }}
              </span>
            </div>
            <ChevronDown 
              v-if="showRollbackPanel" 
              class="w-4 h-4 toggle-arrow" 
            />
            <ChevronRight 
              v-else 
              class="w-4 h-4 toggle-arrow" 
            />
          </button>
          
          <div v-if="showRollbackPanel" class="rollback-content">
            <div class="rollback-actions">
              <button class="rollback-action-btn restore" @click="restoreLastRollback">
                <Undo class="w-3.5 h-3.5" />
                <span>恢复对话</span>
              </button>
              <button class="rollback-action-btn clear" @click="clearRollbackHistory">
                <Trash2 class="w-3.5 h-3.5" />
                <span>清空历史</span>
              </button>
            </div>
          </div>
        </div>

        <div class="input-wrapper">
          <div class="input-row">
            <textarea
              v-model="inputText"
              @keydown="handleKeydown"
              placeholder="问我点难的，让我多思考思考"
              class="message-input"
              rows="1"
            ></textarea>
            
            <button 
              class="send-button"
              :disabled="!inputText.trim() || chatStore.isLoading"
              @click="handleSend"
            >
              <Loader2 v-if="chatStore.isLoading" class="w-5 h-5 animate-spin" />
              <Send v-else class="w-5 h-5" />
            </button>
          </div>
          
          <div class="input-toolbar">
            <div class="toolbar-left">
              <button class="toolbar-btn" @click="navigateToDocuments">
                <Plus class="w-4 h-4" />
                <span>添加文档</span>
              </button>
              <label class="scope-select">
                <span>{{ currentScopeLabel }}</span>
                <select v-model="scopeMode">
                  <option value="all">All documents</option>
                  <option value="folder" :disabled="!folderStore.currentFolderId">Current folder</option>
                  <option value="folder_subtree" :disabled="!folderStore.currentFolderId">Folder + subfolders</option>
                  <option value="selected" :disabled="documentStore.selectedIds.size === 0">Selected documents</option>
                </select>
              </label>
            </div>
            
            <div class="toolbar-hint">
              <span>Enter 发送 · Shift + Enter 换行</span>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- Toggle Right Panel -->
    <button 
      v-if="showRightPanel"
      class="panel-toggle right"
      @click="showRightPanel = false"
      title="收起预览"
    >
      <PanelRight class="w-4 h-4" />
    </button>

    <!-- Expand Right Panel Button (when collapsed) -->
    <button 
      v-if="!showRightPanel"
      class="panel-toggle-expand right"
      @click="showRightPanel = true"
      title="展开预览"
    >
      <PanelLeft class="w-4 h-4" />
    </button>

    <!-- Right Sidebar - Citation Preview -->
    <aside :class="['sidebar-right', { collapsed: !showRightPanel }]">
      <div class="sidebar-content">
        <!-- Header -->
        <div class="preview-panel-header">
          <div class="header-doc-info">
            <div class="doc-type-icon">
              <FileText class="w-5 h-5" />
            </div>
            <div class="doc-title-group">
              <span class="doc-title">{{ previewDocName || '文档预览' }}</span>
              <span class="doc-subtitle">
                {{ previewDocId ? previewAnchorLabel : '选择引用以查看详情' }}
              </span>
            </div>
          </div>
          <button class="btn-icon" @click="showRightPanel = false" title="关闭预览">
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Preview Content Area -->
        <div class="preview-scroll-area" :class="{ 'has-pdf': showRightPdfViewer || showRightUniversalPreview }">
          <!-- 空状态 -->
          <div v-if="!showRightPdfViewer && !showRightUniversalPreview" class="simple-page-preview">
            <div class="page-card">
              <div class="page-placeholder">
                <FileText class="w-12 h-12" />
                <p class="page-hint">
                  {{ previewUnsupportedMessage || 'Click a citation to preview the source' }}
                </p>
                <p class="page-subhint">
                  Supported formats: PDF, TXT, Markdown, CSV, TSV, XLSX, DOCX, PPTX<br>
                  Example: [[report.pdf p.3]] or [[table.xlsx row.50]]
                </p>
              </div>
            </div>
          </div>
          
          <!-- PDF 预览 -->
          <div v-else-if="showRightPdfViewer" class="pdf-viewer-container">
            <PdfReferenceViewer
              :visible="showRightPdfViewer"
              :file-url="`/api/documents/${previewDocId}/file`"
              :file-name="previewDocName"
              :initial-page="previewAnchor?.start_page || 1"
              :embedded="true"
              @close="showRightPdfViewer = false; showRightPanel = false"
              @page-change="(page) => { if (previewAnchor) previewAnchor.start_page = page }"
            />
          </div>
          
          <!-- 多格式通用预览 -->
          <div v-else-if="showRightUniversalPreview" class="universal-preview-container">
            <UniversalPreview
              :doc-id="previewDocId"
              :doc-name="previewDocName"
              :file-type="previewDocType"
              :initial-anchor="previewAnchor"
              @anchor-click="(anchor) => previewAnchor = anchor"
              @error="(msg) => console.error('预览错误:', msg)"
            />
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<style>
/* Design System */
:root {
  /* Colors */
  --bg-canvas: #f8fafc;
  --bg-surface: #ffffff;
  --bg-surface-hover: #f1f5f9;
  --bg-subtle: #f8fafc;
  --bg-muted: #f1f5f9;
  
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-tertiary: #94a3b8;
  --text-muted: #cbd5e1;
  
  --border-default: #e2e8f0;
  --border-subtle: #f1f5f9;
  
  --accent-primary: #3b82f6;
  --accent-primary-soft: rgba(59, 130, 246, 0.1);
  --accent-success: #10b981;
  --accent-warning: #f59e0b;
  
  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.02);
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.03);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.03);
  --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.03);
  --shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.03);
  
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 9999px;
  
  --sidebar-width: 260px;
  --sidebar-right-width: 50%;
}

/* Reset & Base */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.app-container {
  display: flex;
  height: 100vh;
  background: var(--bg-canvas);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  overflow: hidden;
  color: var(--text-primary);
}

/* Left Sidebar */
.sidebar-left {
  width: var(--sidebar-width);
  background: var(--bg-surface);
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
}

.sidebar-left.collapsed {
  width: 0;
  opacity: 0;
  overflow: hidden;
}

.sidebar-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 16px;
  gap: 16px;
  overflow-y: auto;
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}

.logo-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.btn-icon {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-icon:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
}

.btn-icon-sm {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-icon-sm:hover {
  background: var(--bg-muted);
  color: var(--text-secondary);
}

/* New Chat Button */
.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 10px 16px;
  background: var(--text-primary);
  color: white;
  border: none;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  box-shadow: var(--shadow-sm);
}

.new-chat-btn:hover {
  background: #1e293b;
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

.new-chat-btn:active {
  transform: translateY(0);
}

/* Navigation */
.nav-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
}

.nav-item:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--accent-primary-soft);
  color: var(--accent-primary);
}

.nav-badge {
  margin-left: auto;
  padding: 2px 6px;
  background: var(--bg-muted);
  border-radius: var(--radius-full);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
}

.nav-item.active .nav-badge {
  background: rgba(59, 130, 246, 0.15);
  color: var(--accent-primary);
}

/* Chat History */
.chat-history {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.section-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.empty-chat-hint {
  padding: 12px;
  text-align: center;
  font-size: 13px;
  color: var(--text-tertiary);
}

.chat-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chat-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
}

.chat-item:hover {
  background: var(--bg-muted);
}

.chat-item.active {
  background: var(--bg-muted);
}

.chat-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.chat-item.active .chat-icon {
  color: var(--accent-primary);
}

.chat-title {
  flex: 1;
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-item.active .chat-title {
  color: var(--text-primary);
  font-weight: 500;
}

/* Sidebar Footer */
.sidebar-footer {
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.footer-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
}

.footer-item:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
}

/* Panel Toggles */
.panel-toggle {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 20px;
  height: 40px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.15s ease;
  z-index: 10;
}

.panel-toggle:hover {
  color: var(--text-secondary);
  background: var(--bg-surface-hover);
}

.panel-toggle.left {
  left: var(--sidebar-width);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  border-left: none;
}

.panel-toggle.left.collapsed {
  left: 0;
}

.panel-toggle.right {
  right: var(--sidebar-right-width);
  border-radius: var(--radius-md) 0 0 var(--radius-md);
  border-right: none;
}

.panel-toggle.right.collapsed {
  right: 0;
}

/* Panel Toggle Expand Buttons (when panels are collapsed) */
.panel-toggle-expand {
  position: fixed;
  top: 20px;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.15s ease;
  z-index: 100;
  box-shadow: var(--shadow-md);
  border-radius: var(--radius-md);
}

.panel-toggle-expand:hover {
  color: var(--text-secondary);
  background: var(--bg-surface-hover);
  transform: scale(1.05);
}

.panel-toggle-expand.left {
  left: 16px;
}

.panel-toggle-expand.right {
  right: 16px;
}

/* Main Area */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  margin: 0 20px;
}

/* Empty State */
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
}

.empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 48px;
  max-width: 560px;
  width: 100%;
}

.welcome-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 24px;
}

.welcome-logo {
  position: relative;
  width: 72px;
  height: 72px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo-glow {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.3), rgba(139, 92, 246, 0.3));
  border-radius: var(--radius-xl);
  filter: blur(20px);
  opacity: 0.6;
}

.welcome-icon {
  position: relative;
  color: var(--accent-primary);
}

.welcome-title {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.5px;
}

.gradient-text {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.welcome-desc {
  font-size: 16px;
  color: var(--text-secondary);
  line-height: 1.6;
  max-width: 400px;
}

.quick-prompts {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.prompt-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  text-align: left;
  box-shadow: var(--shadow-xs);
}

.prompt-chip:hover {
  border-color: var(--accent-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.prompt-chip svg {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

/* Chat Container */
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 32px 0;
}

.messages-list {
  max-width: 720px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 32px;
  padding: 0 20px;
}

/* Message Item */
.message-item {
  display: flex;
  gap: 14px;
}

.message-item.user {
  flex-direction: row-reverse;
}

.message-avatar {
  flex-shrink: 0;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}

.user-avatar {
  background: var(--text-primary);
  color: white;
}

.ai-avatar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.message-body {
  flex: 1;
  max-width: calc(100% - 46px);
}

.message-item.user .message-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.message-item.user .message-header {
  flex-direction: row-reverse;
  margin-bottom: 4px;
}

.message-author {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

/* Message Actions Bar (below content) */
.message-actions-bar {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 8px;
  opacity: 0;
  transition: opacity 0.2s ease;
}

.message-item:hover .message-actions-bar {
  opacity: 1;
}

.message-actions-bar .action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  width: auto;
  height: auto;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--text-tertiary);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s ease;
}

.message-actions-bar .action-btn:hover {
  color: var(--text-secondary);
  background: var(--bg-muted);
}

/* Thinking Section */
.thinking-section {
  margin-bottom: 12px;
}

.thinking-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(59, 130, 246, 0.06);
  border: 1px solid rgba(59, 130, 246, 0.15);
  border-radius: var(--radius-md);
  font-size: 12px;
  font-weight: 500;
  color: var(--accent-primary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.thinking-toggle:hover {
  background: rgba(59, 130, 246, 0.1);
}

.thinking-icon {
  opacity: 0.8;
}

.toggle-arrow {
  margin-left: auto;
  opacity: 0.6;
  transition: transform 0.2s ease;
}

.thinking-toggle:hover .toggle-arrow {
  opacity: 1;
}

.thinking-content {
  margin-top: 8px;
  padding: 12px;
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.thinking-content pre {
  font-family: 'SF Mono', Monaco, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Tools Section */
.tools-section {
  margin-bottom: 12px;
}

.tools-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-muted);
  border: none;
  border-radius: var(--radius-md);
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.tools-toggle:hover {
  background: var(--border-subtle);
}

.tools-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tools-icon {
  color: var(--accent-primary);
}

.tools-list {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-item {
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-item:hover {
  border-color: var(--border-subtle);
  background: var(--bg-muted);
}

.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-status {
  color: var(--accent-success);
}

.tool-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  font-family: 'SF Mono', Monaco, monospace;
}

.tool-time {
  font-size: 11px;
  color: var(--text-tertiary);
}

.tool-expand-icon {
  color: var(--text-tertiary);
  transition: transform 0.2s ease;
}

.tool-item:hover .tool-expand-icon {
  color: var(--text-secondary);
}

.tool-item.expanded {
  border-color: var(--accent-primary);
  background: var(--bg-subtle);
}

.tool-details {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}

.tool-detail-section {
  margin-bottom: 10px;
}

.tool-detail-section:last-child {
  margin-bottom: 0;
}

.tool-detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.tool-detail-content {
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary);
  background: var(--bg-muted);
  padding: 8px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

/* Message Text */
.message-text {
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-word;
}

.message-item.user .message-text {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  padding: 8px 16px;
  border-radius: 8px;
  display: inline-block;
  max-width: 80%;
  font-size: 14px;
  line-height: 1.35;
  box-shadow: 0 1px 4px rgba(59, 130, 246, 0.2);
  word-break: break-word;
  text-align: center;
}

.user-message-content {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.35;
}

/* 删除重复的样式定义 */

.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4,
.markdown-body h5,
.markdown-body h6 {
  font-weight: 600;
  color: var(--text-primary);
  margin: 20px 0 12px;
  line-height: 1.4;
}

.markdown-body h1 {
  font-size: 20px;
  border-bottom: 2px solid var(--border-default);
  padding-bottom: 8px;
}

.markdown-body h2 {
  font-size: 18px;
}

.markdown-body h3 {
  font-size: 16px;
}

.markdown-body h4 {
  font-size: 15px;
}

.markdown-body p {
  margin-bottom: 12px;
  line-height: 1.7;
}

.markdown-body strong {
  font-weight: 600;
  color: var(--text-primary);
}

.markdown-body ul,
.markdown-body ol {
  margin: 12px 0;
  padding-left: 24px;
}

.markdown-body li {
  margin-bottom: 6px;
  line-height: 1.6;
}

.markdown-body code {
  background: rgba(0, 0, 0, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  font-size: 0.9em;
  color: #e83e8c;
}

.markdown-body pre {
  background: #f6f8fa;
  padding: 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
}

.markdown-body pre code {
  background: transparent;
  padding: 0;
  color: inherit;
  font-size: 13px;
}

.markdown-body blockquote {
  border-left: 4px solid var(--accent-primary);
  padding-left: 16px;
  margin: 12px 0;
  color: var(--text-secondary);
  font-style: italic;
}

.markdown-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid var(--border-default);
  padding: 8px 12px;
  text-align: left;
}

.markdown-body th {
  background: var(--bg-muted);
  font-weight: 600;
}

.markdown-body tr:nth-child(even) {
  background: var(--bg-subtle);
}

.markdown-body a {
  color: var(--accent-primary);
  text-decoration: none;
}

.markdown-body a:hover {
  text-decoration: underline;
}

.markdown-body hr {
  border: none;
  border-top: 1px solid var(--border-default);
  margin: 20px 0;
}

.markdown-body img {
  max-width: 100%;
  border-radius: 8px;
  margin: 12px 0;
}

/* 用户消息的 Markdown 样式调整 */
.message-item.user .markdown-body {
  color: white;
  text-align: center;
}

.message-item.user .markdown-body p {
  margin: 0;
  line-height: inherit;
}

.message-item.user .markdown-body h1,
.message-item.user .markdown-body h2,
.message-item.user .markdown-body h3,
.message-item.user .markdown-body h4,
.message-item.user .markdown-body h5,
.message-item.user .markdown-body h6 {
  color: white;
  border-color: rgba(255, 255, 255, 0.3);
}

.message-item.user .markdown-body strong {
  color: white;
}

.message-item.user .markdown-body code {
  background: rgba(255, 255, 255, 0.2);
  color: white;
}

.message-item.user .markdown-body pre {
  background: rgba(0, 0, 0, 0.2);
}

.message-item.user .markdown-body blockquote {
  border-color: rgba(255, 255, 255, 0.5);
  color: rgba(255, 255, 255, 0.9);
}

.message-item.user .markdown-body a {
  color: #93c5fd;
}

/* Loading */
.message-loading {
  padding: 12px 0;
}

.loading-dots {
  display: flex;
  gap: 4px;
}

.loading-dots span {
  width: 6px;
  height: 6px;
  background: var(--text-muted);
  border-radius: var(--radius-full);
  animation: loading-dot 1.4s ease-in-out infinite;
}

.loading-dots span:nth-child(2) {
  animation-delay: 0.2s;
}

.loading-dots span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes loading-dot {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.4;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

/* Rollback Panel */
.rollback-panel {
  max-width: 720px;
  margin: 0 auto 12px;
  background: var(--bg-muted);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.rollback-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}

.rollback-toggle:hover {
  background: var(--bg-surface-hover);
}

.rollback-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.rollback-icon {
  color: var(--accent-warning);
  flex-shrink: 0;
}

.rollback-info span {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.rollback-preview {
  color: var(--text-tertiary) !important;
  font-weight: 400 !important;
  margin-left: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rollback-content {
  padding: 0 14px 12px;
  border-top: 1px solid var(--border-subtle);
}

.rollback-actions {
  display: flex;
  gap: 10px;
  padding-top: 12px;
}

.rollback-action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  border: none;
}

.rollback-action-btn.restore {
  background: var(--accent-primary-soft);
  color: var(--accent-primary);
}

.rollback-action-btn.restore:hover {
  background: rgba(59, 130, 246, 0.15);
}

.rollback-action-btn.clear {
  background: var(--bg-surface);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
}

.rollback-action-btn.clear:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
}

/* Confirm Modal */
.confirm-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
  animation: fadeIn 0.2s ease;
}

.confirm-modal {
  background: var(--bg-surface);
  border-radius: var(--radius-xl);
  padding: 24px;
  max-width: 400px;
  width: 90%;
  box-shadow: var(--shadow-xl);
  animation: scaleIn 0.2s ease;
}

@keyframes scaleIn {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.confirm-modal-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.confirm-icon {
  color: var(--accent-warning);
}

.confirm-modal-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.confirm-modal-text {
  font-size: 14px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 20px;
}

.confirm-modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.confirm-btn {
  padding: 8px 16px;
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  border: none;
}

.confirm-btn.cancel {
  background: var(--bg-muted);
  color: var(--text-secondary);
}

.confirm-btn.cancel:hover {
  background: var(--border-default);
  color: var(--text-primary);
}

.confirm-btn.confirm {
  background: var(--accent-primary);
  color: white;
}

.confirm-btn.confirm:hover {
  background: #2563eb;
}

/* Input Container */
.input-container {
  padding: 16px 24px;
  background: var(--bg-surface);
  border-top: 1px solid var(--border-subtle);
  flex-shrink: 0;
  max-height: 280px;
  box-sizing: border-box;
  overflow-y: auto;
}

.input-wrapper {
  max-width: 720px;
  margin: 0 auto;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-xl);
  transition: all 0.2s ease;
  overflow: hidden;
  box-shadow: var(--shadow-md);
}

.empty-state + .input-container .input-wrapper {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  box-shadow: var(--shadow-lg);
}

.input-wrapper:focus-within {
  border-color: var(--accent-primary);
  background: var(--bg-surface);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1), var(--shadow-sm);
}

.input-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  min-height: 48px;
}

.message-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 15px;
  line-height: 1.5;
  color: var(--text-primary);
  outline: none;
  resize: none;
  min-height: 24px;
  max-height: 100px;
  font-family: inherit;
  padding: 0;
}

.message-input::placeholder {
  color: var(--text-tertiary);
  font-size: 14px;
}

.send-button {
  width: 36px;
  height: 36px;
  border: none;
  background: var(--text-primary);
  color: white;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
}

.send-button:hover:not(:disabled) {
  background: #1e293b;
  transform: scale(1.05);
}

.send-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-top: 1px solid var(--border-subtle);
}

.toolbar-left {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.toolbar-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
}

.toolbar-btn:hover {
  background: var(--bg-muted);
  color: var(--text-primary);
}

.toolbar-hint {
  font-size: 12px;
  color: var(--text-tertiary);
}

.scope-select {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 280px;
  color: var(--text-secondary);
  font-size: 12px;
}

.scope-select span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.scope-select select {
  max-width: 150px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 6px;
}

.evidence-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-tertiary);
}

.evidence-warning {
  color: var(--accent-warning);
}

.evidence-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.evidence-chip {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-sm);
  background: var(--bg-muted);
  color: var(--text-secondary);
  font-size: 11px;
  padding: 3px 7px;
}

.evidence-chip.fallback {
  border-color: rgba(245, 158, 11, 0.35);
  color: var(--accent-warning);
}

/* Right Sidebar - Citation Preview */
.sidebar-right {
  width: var(--sidebar-right-width);
  background: var(--bg-surface);
  border-left: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  flex-shrink: 0;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.04);
}

.sidebar-right.collapsed {
  width: 0;
  opacity: 0;
  overflow: hidden;
}

.sidebar-right .sidebar-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Preview Panel Header */
.preview-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-surface);
}

.header-doc-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.doc-type-icon {
  width: 40px;
  height: 40px;
  background: var(--accent-primary-soft);
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent-primary);
  flex-shrink: 0;
}

.doc-title-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.doc-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-subtitle {
  font-size: 12px;
  color: var(--text-tertiary);
}

/* Preview Scroll Area */
.preview-scroll-area {
  flex: 1;
  overflow-y: auto;
  background: var(--bg-canvas);
  padding: 16px;
}

.preview-scroll-area.has-pdf {
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.pdf-viewer-container {
  flex: 1;
  overflow: hidden;
}

.universal-preview-container {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* Simple Page Preview */
.simple-page-preview {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.page-card {
  width: 100%;
  background: white;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  padding: 32px 24px;
  text-align: center;
}

.page-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-tertiary);
}

.page-placeholder svg {
  color: var(--accent-primary);
  opacity: 0.5;
}

.page-hint {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.page-subhint {
  font-size: 12px;
  color: var(--text-tertiary);
}

/* Citation Link Styles - 协调的灰色系样式 */
.markdown-body .citation-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-muted);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  vertical-align: baseline;
  margin: 0 2px;
}

.markdown-body .citation-link:hover {
  background: var(--bg-surface-hover);
  border-color: var(--accent-primary);
  color: var(--accent-primary);
}

/* Citation Preview Content */
.preview-loading-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-tertiary);
}

.preview-loading-state .loading-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.citation-preview-content {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-image-container {
  background: white;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.page-image {
  width: 100%;
  height: auto;
  display: block;
}

.page-text-container {
  background: white;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 16px;
}

.page-text-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-subtle);
}

.page-text-content {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}

/* Scrollbar */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: var(--radius-full);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--text-muted);
}

/* Animations */
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-item {
  animation: fadeIn 0.3s ease;
}

/* Responsive */
@media (max-width: 1200px) {
  .sidebar-right {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    box-shadow: -10px 0 40px rgba(0, 0, 0, 0.1);
  }
  
  .sidebar-right.collapsed {
    transform: translateX(100%);
  }
  
  .panel-toggle.right {
    right: 0;
  }
}

@media (max-width: 768px) {
  .sidebar-left {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    z-index: 50;
    box-shadow: 10px 0 40px rgba(0, 0, 0, 0.1);
  }
  
  .sidebar-left.collapsed {
    transform: translateX(-100%);
  }
  
  .panel-toggle.left {
    left: 0;
  }
  
  .main-area {
    margin: 0 12px;
  }
  
  .messages-list {
    padding: 0 12px;
  }
  
  .message-body {
    max-width: calc(100% - 50px);
  }
}
</style>
