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
    isChinese: computed(() => currentLanguage.value === 'zh-CN'),
  }
}

export function resetI18nForTests() {
  currentLanguage.value = readStoredLanguage()
}