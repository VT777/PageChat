export const DOCUMENT_WORKBENCH_PAGE_SIZE = 6

export type PreviewKind = 'text' | 'markdown' | 'table' | 'docx' | 'pptx' | 'unknown'

export type NormalizedPreviewBlock = Record<string, unknown>

export type PreviewStats = {
  rowCount: number
  lineCount: number
  paragraphCount: number
  slideCount: number
  textChars: number
  tocNodes?: number
  summaryCoverage?: number
}

export type QualityDisplay = {
  label: string
  tone: 'ok' | 'warning' | 'error' | 'muted'
  message: string
}

export type DetailMetric = {
  label: string
  value: string
  state: 'ready' | 'pending' | 'missing'
}

export type DocumentListParamState = {
  currentPage: number
  currentPageSize: number
  searchQuery: string
  currentFolderId: string | null
  currentIncludeSubfolders: boolean
}

const SUPPORTED_PREVIEW_EXTENSIONS = new Set([
  '.txt',
  '.md',
  '.markdown',
  '.csv',
  '.tsv',
  '.xlsx',
  '.docx',
  '.pptx',
])

const LEGACY_OFFICE_EXTENSIONS = new Set(['.doc', '.xls', '.ppt'])

export function documentProgress(status?: string): number {
  if (!status) return 0
  if (status === 'completed') return 100
  if (status.startsWith('processing:analyze')) return 10
  if (status.startsWith('processing:indexing')) return 40
  if (status.startsWith('processing:writing_index')) return 70
  if (status.startsWith('processing:generating_summaries')) return 90
  if (status.startsWith('processing')) return 5
  return 0
}

export function isProcessingStatus(status?: string): boolean {
  return Boolean(status?.startsWith('processing') || status === 'pending')
}

export function isCompletedStatus(status?: string): boolean {
  return status === 'completed'
}

export function isFailedStatus(status?: string): boolean {
  return Boolean(status?.startsWith('failed'))
}

export function statusLabel(status?: string): string {
  if (!status) return 'Unknown'
  if (status === 'completed') return 'Completed'
  if (status === 'needs_review') return 'Needs review'
  if (status.startsWith('processing') || status === 'pending') return 'Indexing'
  if (status.startsWith('failed')) return 'Failed'
  return status
}

export function localizedStatusLabel(status?: string): string {
  if (!status) return '未知'
  if (status === 'completed') return '已完成'
  if (status === 'needs_review') return '需复核'
  if (status.startsWith('processing') || status === 'pending') return '索引中'
  if (status.startsWith('failed')) return '失败'
  return status
}

export function metadataValue(value: unknown, fallback = 'Not available'): string {
  if (value === null || value === undefined || value === '') return fallback
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString() : fallback
  return String(value)
}

export function formatDocumentSize(bytes?: number): string {
  if (!bytes || bytes < 0) return 'Not available'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDocumentDate(dateStr?: string): string {
  if (!dateStr) return 'Not available'
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return 'Not available'
  return date.toLocaleString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDocumentDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return 'Not available'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return `${mins}m ${secs}s`
  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60
  return `${hours}h ${remainingMins}m`
}

export function statusTone(status?: string): string {
  if (isFailedStatus(status)) return 'border-red-200 bg-red-50 text-red-700'
  if (status === 'needs_review') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (isProcessingStatus(status)) return 'border-blue-200 bg-blue-50 text-blue-700'
  if (isCompletedStatus(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-border bg-muted/40 text-muted-foreground'
}

export function buildDocumentListParams(state: DocumentListParamState) {
  return {
    page: state.currentPage,
    page_size: state.currentPageSize,
    search: state.searchQuery || undefined,
    folder_id: state.currentFolderId,
    include_subfolders: state.currentIncludeSubfolders,
  }
}

export function workbenchIncludeSubfolders(_folderId: string | null): boolean {
  return false
}

export function normalizeExtension(fileType?: string): string {
  const value = (fileType || '').trim().toLowerCase()
  if (!value) return ''
  return value.startsWith('.') ? value : `.${value}`
}

export function formatDocumentTypeLabel(fileType?: string): string {
  const ext = normalizeExtension(fileType)
  return ext ? ext.slice(1).toUpperCase() : 'FILE'
}

export function isLegacyOfficeFile(fileType?: string): boolean {
  return LEGACY_OFFICE_EXTENSIONS.has(normalizeExtension(fileType))
}

export function isPreviewSupported(fileType?: string): boolean {
  return SUPPORTED_PREVIEW_EXTENSIONS.has(normalizeExtension(fileType))
}

export function unsupportedPreviewMessage(fileType?: string): string {
  if (isLegacyOfficeFile(fileType)) {
    return 'Legacy Office files are not supported yet. Save the file as .docx, .xlsx, or .pptx and upload it again.'
  }
  return `Preview is not supported for this file type: ${fileType || 'unknown'}`
}

export function formatPreviewKind(fileType?: string): PreviewKind {
  const ext = normalizeExtension(fileType)
  if (ext === '.txt') return 'text'
  if (ext === '.md' || ext === '.markdown') return 'markdown'
  if (ext === '.csv' || ext === '.tsv' || ext === '.xlsx') return 'table'
  if (ext === '.docx') return 'docx'
  if (ext === '.pptx') return 'pptx'
  return 'unknown'
}

type RawPreviewBlock = {
  id?: string
  type?: string
  content?: unknown
  source_anchor?: unknown
  metadata?: unknown
}

type RawPreviewContent = {
  format?: string
  blocks?: RawPreviewBlock[]
  metadata?: unknown
}

type QualityReportLike = Record<string, unknown> | null | undefined

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function numberValue(value: unknown, fallback = 0): number {
  const num = Number(value)
  return Number.isFinite(num) && num > 0 ? num : fallback
}

function stringValue(value: unknown, fallback = ''): string {
  if (value === null || value === undefined) return fallback
  return String(value)
}

function normalizeCells(rawCells: unknown): Array<{ col: string; value: string }> {
  if (!Array.isArray(rawCells)) return []
  return rawCells.map((cell, cellIndex) => {
    if (cell && typeof cell === 'object' && 'value' in cell) {
      const item = cell as { col?: unknown; value?: unknown }
      return {
        col: stringValue(item.col, `Column ${cellIndex + 1}`),
        value: stringValue(item.value),
      }
    }
    return {
      col: `Column ${cellIndex + 1}`,
      value: stringValue(cell),
    }
  })
}

function normalizeDocxTableRows(content: unknown): unknown[][] {
  if (Array.isArray(content)) return content as unknown[][]
  const obj = objectValue(content)
  if (Array.isArray(obj.rows)) return obj.rows as unknown[][]
  return []
}

export function normalizePreviewBlocks(content: RawPreviewContent): NormalizedPreviewBlock[] {
  const format = content.format || ''
  return (content.blocks || []).flatMap<NormalizedPreviewBlock>((block, index): NormalizedPreviewBlock[] => {
    const metadata = objectValue(block.metadata)
    const anchor = objectValue(block.source_anchor)

    if (block.type === 'table_row') {
      const rawCells = Array.isArray(block.content) ? block.content : []
      return [{
        id: block.id || `row_${index + 1}`,
        type: block.type,
        rowNumber: Number(metadata.row_number || anchor.start_row || index + 1),
        sheet: anchor.sheet || metadata.sheet_name,
        cells: normalizeCells(rawCells),
        source_anchor: anchor,
      }]
    }

    if (block.type === 'sheet') {
      const sheet = objectValue(block.content)
      const sheetName = stringValue(sheet.name || metadata.sheet_name || anchor.sheet, 'Sheet 1')
      const rows = Array.isArray(sheet.rows) ? sheet.rows : []
      return rows.map((row, rowIndex) => {
        const rowObj = objectValue(row)
        const rowNumber = numberValue(rowObj.row_number, numberValue(anchor.start_row, rowIndex + 1) + rowIndex)
        return {
          id: `${block.id || `sheet_${index + 1}`}_row_${rowNumber}`,
          type: 'table_row',
          rowNumber,
          sheet: sheetName,
          cells: normalizeCells(rowObj.cells),
          source_anchor: {
            ...anchor,
            format: anchor.format || format,
            unit_type: 'row_range',
            sheet: sheetName,
            start_row: rowNumber,
            end_row: rowNumber,
          },
        }
      })
    }

    if (block.type === 'slide') {
      const slide = objectValue(block.content)
      return [{
        id: block.id || `slide_${index + 1}`,
        type: block.type,
        slideNumber: Number(slide.slide_number || anchor.start_slide || anchor.slide || index + 1),
        title: String(slide.title || `Slide ${index + 1}`),
        text: String(slide.text || ''),
        notes: Array.isArray(slide.notes) ? slide.notes : [],
        source_anchor: anchor,
      }]
    }

    if (block.type === 'heading' || block.type === 'paragraph') {
      const paraNumber = numberValue(metadata.paragraph_number, numberValue(anchor.start_paragraph, index + 1))
      return [{
        id: block.id || `${block.type}_${paraNumber}`,
        type: block.type,
        paraNumber,
        text: stringValue(block.content),
        level: numberValue(metadata.level, block.type === 'heading' ? 1 : 0),
        hasImages: Array.isArray(metadata.images) && metadata.images.length > 0,
        content: block.content,
        source_anchor: anchor,
        metadata,
      }]
    }

    if (block.type === 'table') {
      const paraNumber = numberValue(metadata.paragraph_number, numberValue(anchor.start_paragraph, index + 1))
      return [{
        id: block.id || `table_${paraNumber}`,
        type: 'table',
        paraNumber,
        rows: normalizeDocxTableRows(block.content),
        content: block.content,
        source_anchor: anchor,
        metadata,
      }]
    }

    return [{
      id: block.id || `${format || 'block'}_${index + 1}`,
      type: block.type || 'text',
      content: block.content,
      source_anchor: anchor,
      metadata,
    }]
  })
}

export function previewContentMetrics(content: RawPreviewContent): PreviewStats {
  const metadata = objectValue(content.metadata)
  const blocks = normalizePreviewBlocks(content)

  const textChars = blocks.reduce((total, block) => {
    if (typeof block.text === 'string') return total + block.text.length
    if (typeof block.content === 'string') return total + block.content.length
    return total
  }, 0)

  return {
    rowCount: blocks.filter((block) => block.type === 'table_row').length,
    lineCount: Number(metadata.total_lines || metadata.line_count || blocks.filter((block) => block.type === 'text').length || 0),
    paragraphCount: Number(metadata.paragraph_count || blocks.filter((block) => block.type === 'paragraph' || block.type === 'heading' || block.type === 'table').length || 0),
    slideCount: Number(metadata.slide_count || blocks.filter((block) => block.type === 'slide').length || 0),
    textChars: Number(metadata.char_count || metadata.text_chars || textChars || 0),
    tocNodes: metadata.node_count !== undefined ? Number(metadata.node_count) : undefined,
    summaryCoverage: metadata.summary_coverage !== undefined ? Number(metadata.summary_coverage) : undefined,
  }
}

export function qualityDisplay(report?: QualityReportLike): QualityDisplay {
  const status = stringValue(report?.status)
  if (status === 'completed') {
    return {
      label: '已通过',
      tone: 'ok',
      message: '索引已完成，可用于问答和引用定位',
    }
  }
  if (status === 'needs_review') {
    const warnings = numberValue(report?.warning_count)
    return {
      label: '需复核',
      tone: 'warning',
      message: warnings > 0
        ? `索引完成，但质量检查提示 ${warnings} 项需要复核`
        : '索引完成，但质量检查提示需要复核',
    }
  }
  if (status.startsWith('failed')) {
    return {
      label: '失败',
      tone: 'error',
      message: stringValue(report?.error_message, '索引失败，请重新解析'),
    }
  }
  return {
    label: '未生成',
    tone: 'muted',
    message: '暂无质量报告',
  }
}

export function documentDetailMetrics(input: {
  doc: Record<string, unknown>
  previewStats?: Partial<PreviewStats> | null
  qualityReport?: QualityReportLike
}): DetailMetric[] {
  const previewStats = input.previewStats || {}
  const report = input.qualityReport || {}
  const pending = '打开预览后统计'
  const pageCount = numberValue(input.doc.page_count || input.doc.pages)
  const textChars = numberValue(previewStats.textChars)
  const tocNodes = numberValue(previewStats.tocNodes, numberValue(report.node_count))
  const summaryCoverage = typeof previewStats.summaryCoverage === 'number'
    ? `${Math.round(previewStats.summaryCoverage * 100)}%`
    : report.empty_summary_ratio !== undefined
      ? `${Math.round((1 - Number(report.empty_summary_ratio)) * 100)}%`
      : pending
  const ocrPages = input.doc.ocr_pages ?? report.ocr_pages

  return [
    {
      label: '页数 / 字数',
      value: `${pageCount > 0 ? `${pageCount} 页` : pending} / ${textChars > 0 ? textChars.toLocaleString() : pending}`,
      state: textChars > 0 ? 'ready' : 'pending',
    },
    {
      label: 'TOC 节点',
      value: tocNodes > 0 ? String(tocNodes) : pending,
      state: tocNodes > 0 ? 'ready' : 'pending',
    },
    {
      label: '摘要覆盖',
      value: summaryCoverage,
      state: summaryCoverage === pending ? 'pending' : 'ready',
    },
    {
      label: '文本字符',
      value: textChars > 0 ? textChars.toLocaleString() : pending,
      state: textChars > 0 ? 'ready' : 'pending',
    },
    {
      label: 'OCR 页',
      value: ocrPages !== undefined && ocrPages !== null ? String(ocrPages) : '未接入',
      state: ocrPages !== undefined && ocrPages !== null ? 'ready' : 'missing',
    },
  ]
}

function formatFromFileType(fileType?: string): string {
  const ext = normalizeExtension(fileType).slice(1)
  if (ext === 'markdown') return 'md'
  return ext || 'pdf'
}

function parsePosition(position?: string | number): number {
  const match = String(position ?? '').match(/\d+/)
  return match ? Math.max(1, Number(match[0])) : 1
}

export function anchorFromCitation(input: {
  fileType: string
  sourceAnchor?: Record<string, unknown> | null
  positionType?: string
  position?: string | number
}): import('@/types/preview').SourceAnchor {
  const format = formatFromFileType(input.fileType)
  if (input.sourceAnchor && typeof input.sourceAnchor === 'object') {
    return {
      format,
      ...input.sourceAnchor,
    }
  }

  const position = parsePosition(input.position)
  const positionType = String(input.positionType || '').toLowerCase()

  if (format === 'pdf') {
    return { format, unit_type: 'page', start_page: position, end_page: position }
  }
  if (format === 'txt' || format === 'md') {
    return { format, unit_type: 'line_range', start_line: position, end_line: position }
  }
  if (format === 'csv' || format === 'tsv' || format === 'xlsx' || positionType === 'row') {
    return { format, unit_type: 'row_range', start_row: position, end_row: position }
  }
  if (format === 'docx' || positionType === 'para' || positionType === 'paragraph') {
    return { format, unit_type: 'paragraph', start_paragraph: position, end_paragraph: position }
  }
  if (format === 'pptx' || positionType === 'slide') {
    return { format, unit_type: 'slide', start_slide: position, end_slide: position, slide: position }
  }

  return { format, unit_type: 'line_range', start_line: position, end_line: position }
}
