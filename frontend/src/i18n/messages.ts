import { computed, ref } from 'vue'

export type InterfaceLanguage = 'en' | 'zh-CN'

export const INTERFACE_LANGUAGE_STORAGE_KEY = 'pagechat_interface_language'

const dictionaries: Record<InterfaceLanguage, Record<string, string>> = {
  en: {
    'nav.newChat': 'New Chat',
    'nav.documents': 'Documents',
    'nav.chats': 'Chats',
    'nav.noChats': 'No chats yet',
    'nav.settings': 'Settings',
    'nav.more': 'More chat actions',
    'nav.exportConversation': 'Export conversation',
    'nav.deleteConversation': 'Delete conversation',
    'nav.deleteConfirm': 'Delete this conversation? This cannot be undone.',
    'settings.title': 'Settings',
    'settings.subtitle': 'Configure PageChat model, OCR, parsing, and answer behavior.',
    'settings.close': 'Close settings',
    'settings.providers': 'Model Providers',
    'settings.ocr': 'OCR Settings',
    'settings.parsing': 'Parsing Settings',
    'settings.qa': 'Q&A Settings',
    'settings.language': 'Language',
    'settings.account': 'Account',
    'settings.languageTitle': 'Language',
    'settings.languageDescription': 'Set the interface display language.',
    'settings.interfaceLanguage': 'Interface language',
    'composer.image': 'Add image',
    'composer.webSearch': 'Web search',
    'composer.library': 'Select files/folders',
    'composer.addContext': 'Add context',
    'composer.search': 'Search',
    'composer.thinking': 'Thinking',
    'composer.reasoningTitle': 'Toggle native model reasoning for this request',
    'composer.placeholder': 'Ask PageChat about your documents...',
    'composer.selectFile': 'Select file',
    'composer.selectFolder': 'Select folder',
    'composer.selectFileHint': 'Limit this answer to selected documents.',
    'composer.selectFolderHint': 'Limit this answer to selected folders.',
    'composer.loadingFiles': 'Loading files...',
    'composer.noFiles': 'No selectable files',
    'composer.noFolders': 'No selectable folders',
    'composer.folderLabel': 'Folder',
    'composer.uploading': 'Uploading',
    'composer.failed': 'Failed',
  },
  'zh-CN': {
    'nav.newChat': '新对话',
    'nav.documents': '文档',
    'nav.chats': '对话',
    'nav.noChats': '暂无对话',
    'nav.settings': '设置',
    'nav.more': '更多对话操作',
    'nav.exportConversation': '导出对话',
    'nav.deleteConversation': '删除对话',
    'nav.deleteConfirm': '删除这条对话历史？此操作不可撤销。',
    'settings.title': '设置',
    'settings.subtitle': '配置 PageChat 的模型、OCR、解析和问答行为。',
    'settings.close': '关闭设置',
    'settings.providers': '模型供应商',
    'settings.ocr': 'OCR 设置',
    'settings.parsing': '解析设置',
    'settings.qa': '问答设置',
    'settings.language': '语言',
    'settings.account': '账户',
    'settings.languageTitle': '语言',
    'settings.languageDescription': '设置界面显示语言。',
    'settings.interfaceLanguage': '界面语言',
    'composer.image': '添加图片',
    'composer.webSearch': '网页搜索',
    'composer.library': '选择文件/文件夹',
    'composer.addContext': '添加上下文',
    'composer.search': '搜索',
    'composer.thinking': '思考',
    'composer.reasoningTitle': '为本次请求切换模型原生 reasoning',
    'composer.placeholder': '询问 PageChat 关于你的文档...',
    'composer.selectFile': '选择文件',
    'composer.selectFolder': '选择文件夹',
    'composer.selectFileHint': '限定这次回答使用的文档。',
    'composer.selectFolderHint': '限定这次回答使用的文件夹。',
    'composer.loadingFiles': '正在加载文件...',
    'composer.noFiles': '暂无可选文件',
    'composer.noFolders': '暂无可选文件夹',
    'composer.folderLabel': '文件夹',
    'composer.uploading': '上传中',
    'composer.failed': '失败',
  },
}

function readStoredLanguage(): InterfaceLanguage {
  if (typeof localStorage === 'undefined') return 'en'
  return localStorage.getItem(INTERFACE_LANGUAGE_STORAGE_KEY) === 'zh-CN' ? 'zh-CN' : 'en'
}

export const currentLanguage = ref<InterfaceLanguage>(readStoredLanguage())

export const languageOptions = [
  { id: 'zh-CN' as const, label: '简体中文' },
  { id: 'en' as const, label: 'English' },
]

export function setLanguage(language: InterfaceLanguage) {
  currentLanguage.value = language
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(INTERFACE_LANGUAGE_STORAGE_KEY, language)
  }
}

export function t(key: string): string {
  return dictionaries[currentLanguage.value][key] || dictionaries.en[key] || key
}

const textToEnglish: Record<string, string> = {
  '根目录': 'Root',
  '打开/预览': 'Open / Preview',
  '打开': 'Open',
  '重命名': 'Rename',
  '移动到': 'Move to',
  '移动': 'Move',
  '删除': 'Delete',
  '下载': 'Download',
  '重新解析': 'Re-parse',
  '重新索引': 'Re-index',
  '新建子文件夹': 'New subfolder',
  '新建文件夹': 'New folder',
  '文件夹名称': 'Folder name',
  '请输入文件夹名称': 'Enter folder name',
  '文件夹名称不能为空': 'Folder name is required',
  '文件夹名称不能超过255个字符': 'Folder name cannot exceed 255 characters',
  '文件夹名称不能包含 / 或 \\ ': 'Folder name cannot contain / or \\',
  '创建文件夹失败': 'Failed to create folder',
  '取消': 'Cancel',
  '创建': 'Create',
  '创建中...': 'Creating...',
  '移动到文件夹': 'Move to folder',
  '选择目标文件夹：': 'Choose destination folder:',
  '暂无文件夹': 'No folders yet',
  '移动中...': 'Moving...',
  '移动失败，请重试': 'Move failed. Please try again.',
  '已选择': 'Selected',
  '全选': 'Select all',
  '请选择要操作的文档': 'Select documents to operate on',
  '处理进度': 'Processing progress',
  '查看详情': 'View details',
  '预览': 'Preview',
  '处理中': 'Processing',
  '失败': 'Failed',
  '已完成': 'Completed',
  '需复核': 'Needs review',
  '未知': 'Unknown',
  '索引中': 'Indexing',
  '处理详情': 'Processing details',
  '文档：': 'Document:',
  '加载中...': 'Loading...',
  '暂无处理步骤信息': 'No processing steps yet',
  '关闭': 'Close',
  '关闭预览': 'Close preview',
  '未找到对应文档，无法打开来源预览。': 'The source document was not found, so the preview cannot be opened.',
  '正在加载PDF...': 'Loading PDF...',
  '加载失败': 'Load failed',
  '加载失败，请刷新重试': 'Load failed. Please refresh and try again.',
  '重试': 'Retry',
  '目录': 'TOC',
  '信息': 'Info',
  '暂无目录信息': 'No TOC available',
  '基本信息': 'Basic information',
  '文件名': 'File name',
  '文件类型': 'File type',
  '文件大小': 'File size',
  '页数': 'Pages',
  '创建时间': 'Created at',
  '文档摘要': 'Document summary',
  '索引统计': 'Index statistics',
  '章节数': 'Sections',
  '摘要覆盖率': 'Summary coverage',
  '已通过': 'Passed',
  '索引已完成，可用于问答和引用定位': 'Indexing is complete and ready for Q&A and citation navigation.',
  '索引完成，但质量检查提示需要复核': 'Indexing is complete, but quality checks require review.',
  '索引失败，请重新解析': 'Indexing failed. Please re-parse.',
  '未生成': 'Not generated',
  '暂无质量报告': 'No quality report yet',
  '打开预览后统计': 'Calculated after opening preview',
  '页数 / 字数': 'Pages / words',
  'TOC 节点': 'TOC nodes',
  '摘要覆盖': 'Summary coverage',
  '文本字符': 'Text characters',
  'OCR 页': 'OCR pages',
  '未接入': 'Not connected',
  '来源预览': 'Source preview',
  '暂无可预览片段': 'No preview snippet available',
  '段落': 'paragraphs',
  '图片': 'images',
  '文档无文本内容': 'No text content in this document',
  '文档图片': 'Document images',
  '段落组': 'Paragraph group',
  '根据目录结构，核心风险集中在现金流、续约条款和附件证明三处。': 'Based on the TOC, the key risks are concentrated in cash flow, renewal terms, and attachment evidence.',
  '欢迎回来': 'Welcome back',
  '创建账号': 'Create account',
  '登录后继续管理文档和对话。': 'Sign in to continue managing documents and chats.',
  '创建 PageChat 账号，开始构建可追溯的文档问答工作区。': 'Create a PageChat account to build a traceable document Q&A workspace.',
  '登录': 'Sign in',
  '注册': 'Register',
  '电子邮箱': 'Email',
  '密码': 'Password',
  '记住我': 'Remember me',
  '忘记密码？': 'Forgot password?',
  '用户名': 'Username',
  '至少 8 位，含大小写、数字和符号': 'At least 8 characters with upper/lowercase, numbers, and symbols',
  '确认密码': 'Confirm password',
  '再次输入密码': 'Enter the password again',
  '两次输入的密码不一致': 'The two passwords do not match',
  '所选项目': 'Selected item',
  '个文件': 'files',
  '个文件夹': 'folders',
  '个项目': 'items',
  '取消选择': 'Clear selection',
  '文件夹重新解析需要后端接口支持，当前先保留入口和选择状态。': 'Folder re-parsing requires backend API support. The entry and selection state are kept for now.',
  '文件夹下载需要后端接口支持，当前先保留入口和选择状态。': 'Folder download requires backend API support. The entry and selection state are kept for now.',
  '移动项目': 'Move items',
  '目标位置': 'Destination',
  '将移动': 'Moving',
  '另有': 'plus',
  '选择目标文件夹': 'Choose destination folder',
  '移动到这里': 'Move here',
  '在聊天中使用': 'Use in chat',
  '打开预览': 'Open preview',
  '复制文件名': 'Copy file name',
  '打开文件夹': 'Open folder',
  '原始文件名': 'Original file name',
  '所在路径': 'Path',
  '解析路径': 'Parsing route',
  '解析总用时': 'Processing time',
  'TOC 节点数': 'TOC nodes',
  '文本字符数': 'Text characters',
  '质量报告': 'Quality report',
  '总结当前文件夹里的关键结论': 'Summarize the key conclusions in the current folder',
  '找出这份报告里和收入增长相关的证据': 'Find evidence related to revenue growth in this report',
  '对比两个版本的合同条款差异': 'Compare contract clause differences across two versions',
  '根据目录结构帮我定位风险章节': 'Use the TOC to locate risk-related sections',
  '复制': 'Copy',
  '撤回': 'Rollback',
  '加载中': 'Loading',
  '已撤回': 'Rolled back',
  '条消息，原提示词已放入输入框': 'messages. The original prompt has been placed in the composer.',
  '还原': 'Restore',
  '已复制': 'Copied',
  '复制内容': 'Copy content',
  '重新生成': 'Regenerate',
  '回滚到此处': 'Rollback to here',
  '确定要回滚到这条消息吗？这将删除之后的所有消息。': 'Rollback to this message? This will delete all following messages.',
  '上传失败': 'Upload failed',
  '上传中': 'Uploading',
  '搜索': 'Search',
  '网格视图': 'Grid view',
  '网格': 'Grid',
  '列表视图': 'List view',
  '列表': 'List',
  '共': 'Total',
  '项': 'items',
  '页': 'pages',
  '跳至': 'Go to',
  '模型供应商': 'Model Providers',
  'OCR 设置': 'OCR Settings',
  '解析设置': 'Parsing Settings',
  '问答设置': 'Q&A Settings',
  '语言': 'Language',
  '智能': 'Smart',
  '推荐': 'Recommended',
  '自动判断文档结构，优先质量和可追溯性。': 'Automatically detect document structure, prioritizing quality and traceability.',
  '平衡': 'Balanced',
  '在解析速度和目录质量之间保持稳定表现。': 'Keep a stable balance between parsing speed and TOC quality.',
  '快速': 'Fast',
  '优先处理速度，适合结构简单或临时检索文档。': 'Prioritize speed for simple structures or temporary retrieval.',
  '批量解析并发上限': 'Batch parsing concurrency',
  '同时进入解析流程的文档数量，过高可能增加模型和 OCR 压力。': 'Number of documents parsed concurrently. Higher values may increase model and OCR load.',
  '用户要求使用': 'User-requested only',
  '仅当用户明确要求联网搜索时参与回答。': 'Use web search only when the user explicitly asks for it.',
  '自动调用': 'Auto',
  '问题需要外部新信息时允许模型自动启用网页搜索。': 'Allow the model to use web search when external or fresh information is needed.',
  '中国区': 'China',
  '国际区': 'International',
  '简体中文': 'Simplified Chinese',
  '添加图片': 'Add image',
  '网页搜索': 'Web search',
  '选择文件/文件夹': 'Select files/folders',
  '配置 PageChat 的模型、OCR、解析和问答行为': 'Configure PageChat models, OCR, parsing, and answer behavior',
  '统一管理供应商、凭据、OpenAI-compatible endpoint 和可用模型能力。': 'Manage providers, credentials, OpenAI-compatible endpoints, and model capabilities.',
  '配置': 'Configure',
  '请配置 API 密钥，添加模型。': 'Configure an API key and add models.',
  '添加模型': 'Add model',
  '添加 API 密钥': 'Add API key',
  '刷新': 'Refresh',
  '正在获取可用模型...': 'Fetching available models...',
  '暂未返回模型。请检查 API Key 或 endpoint 后刷新。': 'No models returned yet. Check the API key or endpoint, then refresh.',
  '选择 OCR/VLM 模型、并发和视觉提示词。': 'Choose OCR/VLM model, concurrency, and visual prompt.',
  'OCR 模型': 'OCR model',
  '请先配置支持 OCR/VLM 的模型': 'Configure a model that supports OCR/VLM first',
  '并发': 'Concurrency',
  'VLM 提示词': 'VLM prompt',
  '配置 TOC 和结构解析使用的模型与默认解析模式。': 'Configure the model and default parsing mode used for TOC and structure parsing.',
  '解析模型': 'Parsing model',
  '请先配置模型供应商': 'Configure a model provider first',
  '解析模式': 'Parsing mode',
  '选择问答模型，并设置 Web Search 参与回答的方式。': 'Choose the QA model and how Web Search participates in answers.',
  '问答模型': 'QA model',
  '请先配置模型供应商，并刷新可用模型。': 'Configure a model provider first, then refresh available models.',
  '图片页将使用 OCR 文本证据': 'Image pages will use OCR text evidence',
  '搜索供应商': 'Search provider',
  '留空则使用匿名额度': 'Leave empty to use anonymous quota',
  '搜索区域': 'Search region',
  '最大结果数': 'Max results',
  '内容类型': 'Content type',
  '正在加载 Web Search 设置...': 'Loading Web Search settings...',
  'API Key 可选；留空时使用 AnySearch 匿名额度。': 'API key is optional. Leave empty to use AnySearch anonymous quota.',
  '保存 Web Search': 'Save Web Search',
  '当前登录状态和账号操作。': 'Current login status and account actions.',
  '未登录': 'Not signed in',
  '已登录': 'Signed in',
  '访客模式': 'Guest mode',
  '退出登录': 'Sign out',
  'API 密钥授权配置': 'API key authorization',
  '供应商名称': 'Provider name',
  '模型名称': 'Model name',
  '模型类型': 'Model type',
  '凭据名称': 'Credential name',
  '显示名称': 'Display name',
  '可选，用于设置页展示': 'Optional, shown in settings',
  '留空时使用模型名称': 'Leave empty to use the model name',
  'API 密钥': 'API key',
  '保存': 'Save',
  '未配置': 'Not configured',
  'API Key 已删除。': 'API key deleted.',
  '删除 API Key 失败。': 'Failed to delete API key.',
  '保存自定义模型失败。': 'Failed to save custom model.',
  '模型供应商配置暂时无法加载，已显示默认供应商。': 'Model provider settings could not be loaded. Default providers are shown.',
  'Web Search 配置暂时无法加载，已显示默认设置。': 'Web Search settings could not be loaded. Default settings are shown.',
  'Web Search 设置已保存。': 'Web Search settings saved.',
  '保存 Web Search 设置失败。': 'Failed to save Web Search settings.',
  '保存模型供应商失败。': 'Failed to save model provider.',
  '文件夹': 'Folders',
  '请输入新文件夹名称:': 'Enter new folder name:',
  '确定要删除这个文件夹吗？\n\n⚠️ 警告：文件夹内的所有子文件夹和文档将被一并删除！': 'Delete this folder?\n\nWarning: all subfolders and documents inside it will also be deleted.',
}

export function localizeText(value: string): string {
  if (currentLanguage.value !== 'en') return value
  return textToEnglish[value] || value
}

function replaceText(value: string, search: string, replacement: string): string {
  return value.split(search).join(replacement)
}

export function localizeError(value?: string | null): string {
  const text = String(value || '')
  if (!text || currentLanguage.value !== 'en') return text
  const exact = textToEnglish[text]
  if (exact) return exact
  return [
    ['未配置 OCR/VLM 模型。请先在设置页配置 OCR 设置后重新解析。', 'OCR/VLM model is not configured. Configure OCR settings, then re-parse the document.'],
    ['解析失败，请重新解析。', 'Parsing failed. Please re-parse the document.'],
    ['索引失败，请重新解析', 'Indexing failed. Please re-parse.'],
    ['请先在设置页配置问答模型。', 'Configure a QA model in Settings first.'],
    ['请先在设置页配置解析模型。', 'Configure a parsing model in Settings first.'],
    ['请先在设置页配置 OCR/VLM 模型。', 'Configure an OCR/VLM model in Settings first.'],
    ['请先在设置页配置聊天模型。', 'Configure a chat model in Settings first.'],
    ['请先在设置页配置所需模型。', 'Configure the required model in Settings first.'],
    ['抱歉，处理请求时发生错误。', 'Sorry, an error occurred while processing the request.'],
    ['抱歉，发生了错误。请稍后重试。', 'Sorry, something went wrong. Please try again later.'],
    ['登录失败', 'Login failed'],
    ['注册失败', 'Registration failed'],
  ].reduce((result, [search, replacement]) => replaceText(result, search, replacement), text)
}

export function localizeDuration(seconds: number): string {
  if (currentLanguage.value !== 'en') {
    if (seconds < 60) return `${Math.round(seconds)}秒`
    const mins = Math.floor(seconds / 60)
    const secs = Math.round(seconds % 60)
    if (mins < 60) return `${mins}分${secs}秒`
    const hours = Math.floor(mins / 60)
    const remainingMins = mins % 60
    return `${hours}小时${remainingMins}分`
  }
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return `${mins}m ${secs}s`
  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60
  return `${hours}h ${remainingMins}m`
}

export function navLabel(id: string): string {
  if (id === 'new-chat') return t('nav.newChat')
  if (id === 'documents') return t('nav.documents')
  return id
}

export function settingsNavLabel(id: string): string {
  const key = `settings.${id}`
  return t(key)
}

export function composerActionLabel(id: string): string {
  if (id === 'image') return t('composer.image')
  if (id === 'web-search') return t('composer.webSearch')
  if (id === 'library') return t('composer.library')
  if (id === 'file') return t('composer.selectFile')
  if (id === 'folder') return t('composer.selectFolder')
  return id
}

export function useI18n() {
  return {
    language: currentLanguage,
    languageOptions,
    setLanguage,
    t,
    navLabel,
    settingsNavLabel,
    composerActionLabel,
    localizeText,
    localizeError,
    localizeDuration,
    isChinese: computed(() => currentLanguage.value === 'zh-CN'),
  }
}

export function resetI18nForTests() {
  currentLanguage.value = readStoredLanguage()
}
