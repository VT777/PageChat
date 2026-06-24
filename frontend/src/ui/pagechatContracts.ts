export const PRODUCT_NAME = 'PageChat'

export type IconName =
  | 'ArrowUp'
  | 'BookOpen'
  | 'Download'
  | 'File'
  | 'FileCode'
  | 'FileImage'
  | 'FileSearch'
  | 'FileSpreadsheet'
  | 'FileText'
  | 'FileType'
  | 'Files'
  | 'Folder'
  | 'FolderTree'
  | 'Globe'
  | 'Image'
  | 'ImagePlus'
  | 'ListTree'
  | 'MessageSquare'
  | 'Move'
  | 'Plus'
  | 'Presentation'
  | 'RefreshCw'
  | 'Search'
  | 'Settings2'
  | 'SlidersHorizontal'
  | 'Sparkles'
  | 'Trash2'

export interface NavigationItem {
  id: string
  label: string
  icon: IconName
  route?: string
}

export const APP_NAV_ITEMS: NavigationItem[] = [
  { id: 'new-chat', label: 'New Chat', icon: 'MessageSquare', route: '/' },
  { id: 'documents', label: 'Documents', icon: 'FileText', route: '/documents' },
]

export const SETTINGS_NAV_SECTIONS = {
  primary: [
    { id: 'providers', label: '模型供应商', icon: 'SlidersHorizontal' },
    { id: 'ocr', label: 'OCR 设置', icon: 'Image' },
    { id: 'parsing', label: '解析设置', icon: 'ListTree' },
    { id: 'qa', label: '问答设置', icon: 'MessageSquare' },
  ],
  footer: [
    { id: 'language', label: '语言', icon: 'Globe' },
    { id: 'account', label: 'Account', icon: 'Settings2' },
  ],
} as const

export const PARSE_MODE_OPTIONS = [
  {
    id: 'smart',
    label: '智能',
    badge: '推荐',
    description: '自动判断文档结构，优先质量和可追溯性。',
  },
  {
    id: 'balanced',
    label: '平衡',
    badge: undefined,
    description: '在解析速度和目录质量之间保持稳定表现。',
  },
  {
    id: 'fast',
    label: '快速',
    badge: undefined,
    description: '优先处理速度，适合结构简单或临时检索文档。',
  },
] as const

export const PARSING_BATCH_CONCURRENCY_SETTING = {
  id: 'batchParseConcurrency',
  label: '批量解析并发上限',
  description: '同时进入解析流程的文档数量，过高可能增加模型和 OCR 压力。',
  defaultValue: 3,
  min: 1,
  max: 12,
} as const

export const WEB_SEARCH_MODE_OPTIONS = [
  {
    id: 'on-demand',
    label: '用户要求使用',
    description: '仅当用户明确要求联网搜索时参与回答。',
  },
  {
    id: 'auto',
    label: '自动调用',
    description: '问题需要外部新信息时允许模型自动启用网页搜索。',
  },
] as const

export const COMPOSER_ACTIONS = [
  { id: 'image', label: '添加图片', icon: 'ImagePlus' },
  { id: 'web-search', label: '网页搜索', icon: 'Globe' },
  { id: 'file', label: '选择文件', icon: 'FileText' },
  { id: 'folder', label: '选择文件夹', icon: 'Folder' },
] as const

export interface FilePresentation {
  icon: IconName
  tone: string
  label: string
}

export const DOCUMENT_FILE_PRESENTATIONS = {
  folder: { icon: 'Folder', tone: 'folder', label: 'Folder' },
  pdf: { icon: 'FileText', tone: 'pdf', label: 'PDF' },
  word: { icon: 'FileType', tone: 'word', label: 'Word' },
  sheet: { icon: 'FileSpreadsheet', tone: 'sheet', label: 'Sheet' },
  deck: { icon: 'Presentation', tone: 'deck', label: 'Slides' },
  code: { icon: 'FileCode', tone: 'code', label: 'Text' },
  image: { icon: 'FileImage', tone: 'image', label: 'Image' },
  file: { icon: 'File', tone: 'file', label: 'File' },
} satisfies Record<string, FilePresentation>

export type DocumentSelectionActionId = 'chat' | 'download' | 'reindex' | 'move' | 'delete'

export interface DocumentSelectionAction {
  id: DocumentSelectionActionId
  label: string
  icon: IconName
  tone: 'default' | 'danger'
}

export const DOCUMENT_SELECTION_ACTIONS: DocumentSelectionAction[] = [
  { id: 'chat', label: 'Chat', icon: 'MessageSquare', tone: 'default' },
  { id: 'download', label: '下载', icon: 'Download', tone: 'default' },
  { id: 'reindex', label: '重新解析', icon: 'RefreshCw', tone: 'default' },
  { id: 'move', label: '移动', icon: 'Move', tone: 'default' },
  { id: 'delete', label: '删除', icon: 'Trash2', tone: 'danger' },
]

export interface SelectableDocumentLike {
  id: string
  selectable?: boolean
}

export function documentSelectionActionIds(): DocumentSelectionActionId[] {
  return DOCUMENT_SELECTION_ACTIONS.map((action) => action.id)
}

export function buildDocumentSelectionSummary(count: number): string {
  return `已选择 ${count} 个文件`
}

export function selectableDocumentIds(documents: SelectableDocumentLike[]): string[] {
  return documents
    .filter((document) => document.selectable !== false)
    .map((document) => document.id)
}

export function hasSelectableLibraryItems(documentIds: string[], folderIds: string[]): boolean {
  return documentIds.length + folderIds.length > 0
}

function normalizeExtension(fileType?: string): string {
  const value = (fileType || '').trim().toLowerCase()
  if (!value) return ''
  return value.startsWith('.') ? value : `.${value}`
}

export function documentPresentationForType(fileType?: string): FilePresentation {
  const ext = normalizeExtension(fileType)
  if (ext === '.pdf') return DOCUMENT_FILE_PRESENTATIONS.pdf
  if (['.doc', '.docx'].includes(ext)) return DOCUMENT_FILE_PRESENTATIONS.word
  if (['.xls', '.xlsx', '.csv', '.tsv'].includes(ext)) return DOCUMENT_FILE_PRESENTATIONS.sheet
  if (['.ppt', '.pptx', '.key'].includes(ext)) return DOCUMENT_FILE_PRESENTATIONS.deck
  if (['.md', '.markdown', '.txt', '.json', '.js', '.ts', '.py', '.java', '.cpp', '.c', '.go', '.rs'].includes(ext)) {
    return DOCUMENT_FILE_PRESENTATIONS.code
  }
  if (['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.bmp'].includes(ext)) {
    return DOCUMENT_FILE_PRESENTATIONS.image
  }
  return DOCUMENT_FILE_PRESENTATIONS.file
}

export interface FolderPathItem {
  id: string
  name: string
}

export interface BreadcrumbItem {
  id: string | null
  label: string
  isRoot: boolean
}

export interface DocumentChatRouteInput {
  id: string
  name?: string
  original_name?: string
}

export interface DocumentChatContext {
  id: string
  label: string
  type?: 'document' | 'folder'
}

export interface FolderChatRouteInput {
  id: string
  name?: string
}

export interface FolderChatContext {
  id: string
  label: string
  type?: 'folder'
}

export interface DocumentChatNameLike {
  id: string
  name?: string
  original_name?: string
}

export function documentOnlyChatContexts(contexts: DocumentChatContext[]): DocumentChatContext[] {
  return contexts
    .filter((context) => context.type !== 'folder')
    .map((context) => ({
      id: context.id,
      label: context.label,
    }))
}

export function resolveDocumentChatContext(
  id: string,
  initialContexts: DocumentChatContext[],
  documents: DocumentChatNameLike[],
): DocumentChatContext {
  const initialContext = documentOnlyChatContexts(initialContexts).find((context) => context.id === id)
  const document = documents.find((item) => item.id === id)
  return {
    id,
    label: initialContext?.label || document?.original_name || document?.name || id,
  }
}

export function buildDocumentBreadcrumb(path: FolderPathItem[]): BreadcrumbItem[] {
  return [
    { id: null, label: 'root', isRoot: true },
    ...path.map((folder) => ({
      id: folder.id,
      label: folder.name,
      isRoot: false,
    })),
  ]
}

function documentLabel(document: DocumentChatRouteInput): string {
  return document.original_name || document.name || document.id
}

export function buildDocumentChatRoute(document: DocumentChatRouteInput | DocumentChatRouteInput[]) {
  if (Array.isArray(document)) {
    return {
      path: '/',
      query: {
        documentIds: JSON.stringify(document.map((item) => item.id)),
        documentNames: JSON.stringify(document.map(documentLabel)),
      },
    }
  }

  return {
    path: '/',
    query: {
      documentId: document.id,
      documentName: documentLabel(document),
    },
  }
}

export function buildFolderChatRoute(folder: FolderChatRouteInput | FolderChatRouteInput[]) {
  if (Array.isArray(folder)) {
    return {
      path: '/',
      query: {
        folderIds: JSON.stringify(folder.map((item) => item.id)),
        folderNames: JSON.stringify(folder.map((item) => item.name || item.id)),
      },
    }
  }

  return {
    path: '/',
    query: {
      folderId: folder.id,
      folderName: folder.name || folder.id,
    },
  }
}

function firstQueryValue(value: unknown): string {
  if (Array.isArray(value)) {
    return typeof value[0] === 'string' ? value[0] : ''
  }
  return typeof value === 'string' ? value : ''
}

function parseStringArray(value: unknown): string[] {
  const raw = firstQueryValue(value)
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string' && item.length > 0)
      : []
  } catch {
    return raw.split(',').map((item) => item.trim()).filter(Boolean)
  }
}

export function parseDocumentChatRouteQuery(query: Record<string, unknown>): DocumentChatContext[] {
  const ids = parseStringArray(query.documentIds)
  const names = parseStringArray(query.documentNames)
  if (ids.length > 0) {
    return ids.map((id, index) => ({
      id,
      label: names[index] || id,
    }))
  }

  const id = firstQueryValue(query.documentId)
  if (!id) return []
  const name = firstQueryValue(query.documentName)
  return [{ id, label: name || id }]
}

export function parseFolderChatRouteQuery(query: Record<string, unknown>): FolderChatContext | null {
  const contexts = parseFolderChatRouteContexts(query)
  return contexts[0] || null
}

export function parseFolderChatRouteContexts(query: Record<string, unknown>): FolderChatContext[] {
  const ids = parseStringArray(query.folderIds)
  const names = parseStringArray(query.folderNames)
  if (ids.length > 0) {
    return ids.map((id, index) => ({
      id,
      label: names[index] || id,
    }))
  }

  const id = firstQueryValue(query.folderId)
  if (!id) return []
  const name = firstQueryValue(query.folderName)
  return [{ id, label: name || id }]
}

export interface ToolStepLike {
  toolName: string
  arguments: Record<string, unknown>
  result: Record<string, unknown> | null
  status: 'calling' | 'done'
  elapsedMs?: number
  resultsCount?: number
}

export interface ConversationExportMessage {
  role: 'user' | 'assistant'
  content: string
  toolSteps?: ToolStepLike[]
}

export interface ConversationExportInput {
  title: string
  exportedAt: string
  messages: ConversationExportMessage[]
}

export interface ToolStepSummary {
  action: string
  detail: string
  icon: IconName
  tone: 'running' | 'success' | 'error'
}

function resultArrayCount(result: Record<string, unknown> | null, keys: string[]): number {
  if (!result) return 0
  for (const key of keys) {
    const value = result[key]
    if (Array.isArray(value)) return value.length
  }
  return 0
}

function toolTarget(args: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = args[key]
    if (typeof value === 'string' && value.trim()) return value
    if (typeof value === 'number') return String(value)
  }
  return ''
}

function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`
}

function quoted(value: string): string {
  return value ? `"${value}"` : ''
}

function countDetail(parts: Array<{ count: number; singular: string; plural?: string }>): string {
  return parts
    .filter((part) => part.count > 0)
    .map((part) => pluralize(part.count, part.singular, part.plural))
    .join(', ')
}

function firstPositiveNumber(args: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = Number(args[key])
    if (Number.isFinite(value) && value > 0) return value
  }
  return null
}

function pageRangeLabel(args: Record<string, unknown>): string {
  const start = firstPositiveNumber(args, ['start_page', 'startPage', 'page_start', 'from_page', 'page'])
  const end = firstPositiveNumber(args, ['end_page', 'endPage', 'page_end', 'to_page'])
  if (start && end && end !== start) return `${start}-${end}`
  if (start) return String(start)
  const rawRange = toolTarget(args, ['page_range', 'pageRange', 'pages'])
  return rawRange.replace(/^pages?\s*/i, '')
}

function resultCount(step: ToolStepLike, keys: string[]): number {
  if (typeof step.resultsCount === 'number') return step.resultsCount
  return resultArrayCount(step.result, keys)
}

export function summarizeToolStep(step: ToolStepLike): ToolStepSummary {
  const tone: ToolStepSummary['tone'] = step.status === 'calling' ? 'running' : 'success'
  const targetDoc = toolTarget(step.arguments, [
    'document_name',
    'documentName',
    'doc_name',
    'docName',
    'file_name',
    'fileName',
    'name',
    'docId',
    'document_id',
  ])
  const pages = pageRangeLabel(step.arguments)

  switch (step.toolName) {
    case 'get_folder_tree':
    case 'list_folder_tree':
    case 'browse_folder':
      return {
        action: step.status === 'calling' ? 'Viewing folder structure' : 'Viewed folder structure',
        detail: pluralize(resultArrayCount(step.result, ['folders', 'items', 'children']), 'folder'),
        icon: 'FolderTree',
        tone,
      }
    case 'list_folder_contents': {
      const folders = resultArrayCount(step.result, ['folders', 'children'])
      const documents = resultArrayCount(step.result, ['documents', 'files'])
      const items = resultArrayCount(step.result, ['items'])
      return {
        action: step.status === 'calling' ? 'Viewing folder contents' : 'Viewed folder contents',
        detail: countDetail([
          { count: folders, singular: 'folder' },
          { count: documents, singular: 'document' },
          { count: folders || documents ? 0 : items, singular: 'item' },
        ]),
        icon: 'FolderTree',
        tone,
      }
    }
    case 'find_related_documents':
    case 'search_documents':
    case 'browse_documents':
      return {
        action: step.status === 'calling' ? 'Browsing documents' : 'Browsed documents',
        detail: pluralize(resultCount(step, ['documents', 'items', 'results']), 'document'),
        icon: 'Files',
        tone,
      }
    case 'get_document_toc':
    case 'read_document_structure':
    case 'get_document_structure':
      return {
        action: step.status === 'calling' ? 'Reading the document structure' : 'Read the document structure',
        detail: targetDoc ? quoted(targetDoc) : pluralize(resultArrayCount(step.result, ['toc', 'nodes', 'items']), 'node'),
        icon: 'ListTree',
        tone,
      }
    case 'get_document_pages':
    case 'read_document_pages':
    case 'read_pages':
      return {
        action: `${step.status === 'calling' ? 'Reading' : 'Read'} ${pages && !pages.includes(',') ? (pages.includes('-') ? `pages ${pages}` : `page ${pages}`) : 'pages'}`,
        detail: quoted(targetDoc),
        icon: 'BookOpen',
        tone,
      }
    case 'get_document_image':
    case 'view_document_image':
    case 'view_figure':
      return {
        action: step.status === 'calling' ? 'Viewing page image' : 'Viewed page image',
        detail: [pages ? `page ${pages}` : '', quoted(targetDoc)].filter(Boolean).join(' from '),
        icon: 'Image',
        tone,
      }
    case 'search_within_document':
      return {
        action: step.status === 'calling' ? 'Searching within document' : 'Searched within document',
        detail: targetDoc
          ? quoted(targetDoc)
          : pluralize(resultCount(step, ['matches', 'results']), 'match', 'matches'),
        icon: 'FileSearch',
        tone,
      }
    case 'aggregate_tables':
    case 'summarize_tables':
    case 'query_tables':
      return {
        action: step.status === 'calling' ? 'Aggregating table data' : 'Aggregated table data',
        detail: pluralize(resultArrayCount(step.result, ['rows', 'items', 'results']), 'row'),
        icon: 'FileSpreadsheet',
        tone,
      }
    case 'web_search':
      return {
        action: step.status === 'calling' ? 'Searching the web' : 'Searched the web',
        detail: pluralize(resultCount(step, ['results']), 'result'),
        icon: 'Globe',
        tone,
      }
    default:
      return {
        action: step.status === 'calling' ? `Using ${step.toolName}` : `Used ${step.toolName}`,
        detail: step.elapsedMs ? `${step.elapsedMs}ms` : '',
        icon: 'Sparkles',
        tone,
      }
  }
}

export function buildConversationExportMarkdown(input: ConversationExportInput): string {
  const blocks = [
    `# ${input.title || 'PageChat Conversation'}`,
    '',
    `Exported: ${input.exportedAt}`,
  ]

  for (const message of input.messages) {
    blocks.push('', `## ${message.role === 'user' ? 'User' : 'PageChat'}`, '')
    if (message.toolSteps?.length) {
      blocks.push('Tool calls:')
      for (const step of message.toolSteps) {
        const summary = summarizeToolStep(step)
        const detail = summary.detail ? `: ${summary.detail}` : ''
        blocks.push(`- ${summary.action}${detail}`)
      }
      blocks.push('')
    }
    blocks.push(message.content || '_No content_')
  }

  return `${blocks.join('\n')}\n`
}
