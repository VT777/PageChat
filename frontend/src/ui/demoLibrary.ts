import type { Folder } from '@/api/folders'
import type { Document } from '@/stores/document'
import type { BreadcrumbItem } from './pagechatContracts'

export const DEMO_FOLDER_ID = 'demo-sales-analysis-folder'
export const DEMO_DOCUMENT_ID = 'demo-sales-performance'

export const DEMO_LIBRARY_FOLDERS: Folder[] = [
  {
    id: DEMO_FOLDER_ID,
    name: '销售分析',
    parent_id: null,
    path: 'root / 销售分析',
    created_at: '2026-06-18T09:30:00+08:00',
    updated_at: '2026-06-23T16:42:00+08:00',
  },
]

export const DEMO_LIBRARY_DOCUMENTS: Document[] = [
  {
    id: DEMO_DOCUMENT_ID,
    name: '区域销售表现样例.xlsx',
    original_name: '区域销售表现样例.xlsx',
    file_path: 'root / 销售分析 / 区域销售表现样例.xlsx',
    file_size: 184320,
    file_type: '.xlsx',
    status: 'completed',
    page_count: 4,
    processed_pages: 4,
    parse_requested_mode: 'smart',
    parse_execution_mode: 'smart',
    parse_reasons: ['表格结构清晰', '包含地区维度和销售额字段'],
    parse_completion: 'completed',
    quality_report: { status: 'completed' } as any,
    processing_duration: 17.4,
    created_at: '2026-06-18T10:16:00+08:00',
    updated_at: '2026-06-23T16:42:00+08:00',
    folder_id: DEMO_FOLDER_ID,
    folder_path: 'root / 销售分析',
    last_reindex_at: '2026-06-23T16:42:00+08:00',
  },
]

export function demoFoldersForParent(parentId: string | null): Folder[] {
  return parentId ? [] : DEMO_LIBRARY_FOLDERS
}

export function demoDocumentsForFolder(folderId: string | null): Document[] {
  return folderId === DEMO_FOLDER_ID ? DEMO_LIBRARY_DOCUMENTS : []
}

export function demoBreadcrumbForFolder(folderId: string | null): BreadcrumbItem[] {
  const root = { id: null, label: 'root', isRoot: true }
  const folder = DEMO_LIBRARY_FOLDERS.find((item) => item.id === folderId)
  return folder ? [root, { id: folder.id, label: folder.name, isRoot: false }] : [root]
}

export function shouldShowDemoLibrary(input: {
  loading: boolean
  folderCount: number
  documentCount: number
  searchQuery: string
}): boolean {
  void input
  return false
}

export function buildLibrarySelectionSummary(input: {
  documentCount: number
  folderCount: number
}): string {
  const parts: string[] = []
  if (input.documentCount > 0) parts.push(`${input.documentCount} 个文件`)
  if (input.folderCount > 0) parts.push(`${input.folderCount} 个文件夹`)
  return `已选择 ${parts.join('、') || '0 个项目'}`
}
