import { describe, expect, it } from 'vitest'
import {
  DOCUMENT_WORKBENCH_PAGE_SIZE,
  buildDocumentListParams,
  documentProgress,
  formatPreviewKind,
  formatDocumentTypeLabel,
  formatDocumentDuration,
  isLegacyOfficeFile,
  isPreviewSupported,
  metadataValue,
  anchorFromCitation,
  documentDetailMetrics,
  normalizePreviewBlocks,
  previewContentMetrics,
  qualityDisplay,
  localizedStatusLabel,
  statusLabel,
  workbenchIncludeSubfolders,
  unsupportedPreviewMessage,
} from './documentWorkbench'

describe('document workbench helpers', () => {
  it('uses the Phase 8 dense-list page size', () => {
    expect(DOCUMENT_WORKBENCH_PAGE_SIZE).toBe(6)
  })

  it('maps indexing statuses to stable progress values', () => {
    expect(documentProgress('completed')).toBe(100)
    expect(documentProgress('processing:indexing')).toBe(40)
    expect(documentProgress('processing:writing_index')).toBe(70)
    expect(documentProgress('failed:indexing_timeout')).toBe(0)
  })

  it('returns neutral placeholders for unavailable metadata', () => {
    expect(metadataValue(undefined)).toBe('Not available')
    expect(metadataValue(null)).toBe('Not available')
    expect(metadataValue('')).toBe('Not available')
    expect(metadataValue('balanced')).toBe('balanced')
  })

  it('formats processing durations without inventing unavailable values', () => {
    expect(formatDocumentDuration(undefined)).toBe('Not available')
    expect(formatDocumentDuration(45)).toBe('45s')
    expect(formatDocumentDuration(125)).toBe('2m 5s')
  })

  it('labels statuses for the workbench UI', () => {
    expect(statusLabel('completed')).toBe('Completed')
    expect(statusLabel('processing:queued')).toBe('Indexing')
    expect(statusLabel('failed:parse_error')).toBe('Failed')
    expect(statusLabel('needs_review')).toBe('Needs review')
  })

  it('preserves active document list filters for polling refreshes', () => {
    expect(buildDocumentListParams({
      currentPage: 3,
      currentPageSize: 6,
      searchQuery: 'risk',
      currentFolderId: 'folder-a',
      currentIncludeSubfolders: false,
    })).toEqual({
      page: 3,
      page_size: 6,
      search: 'risk',
      folder_id: 'folder-a',
      include_subfolders: false,
    })
  })

  it('includes subfolders only for the all-documents workbench view', () => {
    expect(workbenchIncludeSubfolders(null)).toBe(true)
    expect(workbenchIncludeSubfolders('folder-a')).toBe(false)
  })

  it('keeps legacy office formats outside preview support', () => {
    expect(isPreviewSupported('.docx')).toBe(true)
    expect(isPreviewSupported('.xlsx')).toBe(true)
    expect(isPreviewSupported('.pptx')).toBe(true)
    expect(isPreviewSupported('.doc')).toBe(false)
    expect(isPreviewSupported('.xls')).toBe(false)
    expect(isPreviewSupported('.ppt')).toBe(false)
    expect(isLegacyOfficeFile('.doc')).toBe(true)
    expect(unsupportedPreviewMessage('.doc')).toContain('.docx')
  })

  it('maps supported non-pdf formats to preview kinds', () => {
    expect(formatPreviewKind('.txt')).toBe('text')
    expect(formatPreviewKind('.md')).toBe('markdown')
    expect(formatPreviewKind('.csv')).toBe('table')
    expect(formatPreviewKind('.xlsx')).toBe('table')
    expect(formatPreviewKind('.docx')).toBe('docx')
    expect(formatPreviewKind('.pptx')).toBe('pptx')
    expect(formatPreviewKind('.ppt')).toBe('unknown')
  })

  it('formats document workbench display labels', () => {
    expect(formatDocumentTypeLabel('.pdf')).toBe('PDF')
    expect(formatDocumentTypeLabel('xlsx')).toBe('XLSX')
    expect(formatDocumentTypeLabel('')).toBe('FILE')
    expect(localizedStatusLabel('completed')).toBe('已完成')
    expect(localizedStatusLabel('processing:indexing')).toBe('索引中')
    expect(localizedStatusLabel('failed:indexing_timeout')).toBe('失败')
  })

  it('normalizes canonical table row blocks for frontend rendering', () => {
    const blocks = normalizePreviewBlocks({
      format: 'csv',
      blocks: [
        {
          id: 'row_1',
          type: 'table_row',
          content: ['city', 'amount'],
          metadata: { row_number: 1 },
        },
      ],
      metadata: { row_count: 1 },
    })

    expect(blocks[0].cells).toEqual([
      { col: 'Column 1', value: 'city' },
      { col: 'Column 2', value: 'amount' },
    ])
  })

  it('normalizes canonical slide anchors for frontend rendering', () => {
    const blocks = normalizePreviewBlocks({
      format: 'pptx',
      blocks: [
        {
          id: 'slide_1',
          type: 'slide',
          content: { slide_number: 1, title: 'Intro', text: 'Hello' },
          source_anchor: { format: 'pptx', unit_type: 'slide', start_slide: 1, end_slide: 1 },
          metadata: {},
        },
      ],
      metadata: { slide_count: 1 },
    })

    expect(blocks[0].slideNumber).toBe(1)
    expect(blocks[0].title).toBe('Intro')
  })

  it('expands canonical xlsx sheet blocks into renderable table rows', () => {
    const blocks = normalizePreviewBlocks({
      format: 'xlsx',
      blocks: [
        {
          id: 'sheet_1',
          type: 'sheet',
          content: {
            name: 'Orders',
            rows: [
              { row_number: 1, cells: [{ col: 1, value: 'order_id' }] },
              { row_number: 2, cells: [{ col: 1, value: 'SO-10001' }] },
            ],
          },
          source_anchor: {
            format: 'xlsx',
            unit_type: 'row_range',
            sheet: 'Orders',
            start_row: 1,
            end_row: 2,
          },
          metadata: { sheet_name: 'Orders' },
        },
      ],
      metadata: {},
    })

    expect(blocks).toEqual([
      expect.objectContaining({
        type: 'table_row',
        rowNumber: 1,
        sheet: 'Orders',
        cells: [{ col: '1', value: 'order_id' }],
      }),
      expect.objectContaining({
        type: 'table_row',
        rowNumber: 2,
        sheet: 'Orders',
        cells: [{ col: '1', value: 'SO-10001' }],
      }),
    ])
    expect(blocks[1].source_anchor).toEqual(expect.objectContaining({
      sheet: 'Orders',
      start_row: 2,
      end_row: 2,
    }))
  })

  it('preserves docx heading and table blocks for visible document rendering', () => {
    const blocks = normalizePreviewBlocks({
      format: 'docx',
      blocks: [
        {
          id: 'h1',
          type: 'heading',
          content: 'Section one',
          source_anchor: { format: 'docx', unit_type: 'paragraph', start_paragraph: 1 },
          metadata: { level: 1, paragraph_number: 1 },
        },
        {
          id: 'p2',
          type: 'paragraph',
          content: 'Body text',
          source_anchor: { format: 'docx', unit_type: 'paragraph', start_paragraph: 2 },
          metadata: { paragraph_number: 2 },
        },
        {
          id: 't3',
          type: 'table',
          content: { rows: [['A', 'B'], ['1', '2']] },
          source_anchor: { format: 'docx', unit_type: 'paragraph', start_paragraph: 3 },
          metadata: { paragraph_number: 3 },
        },
      ],
      metadata: {},
    })

    expect(blocks.map((block) => block.type)).toEqual(['heading', 'paragraph', 'table'])
    expect(blocks[0]).toEqual(expect.objectContaining({ paraNumber: 1, text: 'Section one', level: 1 }))
    expect(blocks[2]).toEqual(expect.objectContaining({ paraNumber: 3, rows: [['A', 'B'], ['1', '2']] }))
  })

  it('summarizes preview metrics across canonical block shapes', () => {
    const metrics = previewContentMetrics({
      format: 'pptx',
      blocks: [
        { type: 'text', content: 'abc' },
        { type: 'slide', content: { text: 'slide text' } },
        { type: 'sheet', content: { rows: [{ row_number: 1, cells: [] }] } },
      ],
      metadata: { node_count: 4, summary_coverage: 0.75 },
    })

    expect(metrics).toEqual(expect.objectContaining({
      rowCount: 1,
      slideCount: 1,
      textChars: 13,
      tocNodes: 4,
      summaryCoverage: 0.75,
    }))
  })

  it('uses truthful quality wording for needs-review index reports', () => {
    expect(qualityDisplay({ status: 'needs_review', warning_count: 2 }).message).toContain('复核')
    expect(qualityDisplay({ status: 'needs_review' }).message).not.toContain('可用于问答和引用定位')
    expect(qualityDisplay({ status: 'completed' }).message).toContain('可用于问答和引用定位')
  })

  it('uses pending or missing labels instead of Not available for unloaded detail metrics', () => {
    const metrics = documentDetailMetrics({
      doc: { page_count: 12 },
      qualityReport: { status: 'needs_review', node_count: 5 },
    })

    expect(metrics.find((item) => item.label === '页数 / 字数')?.value).toBe('12 页 / 打开预览后统计')
    expect(metrics.find((item) => item.label === 'TOC 节点')?.value).toBe('5')
    expect(metrics.find((item) => item.label === 'OCR 页')?.value).toBe('未接入')
    expect(metrics.some((item) => item.value === 'Not available')).toBe(false)
  })

  it('prefers structured source anchors for chat citation preview', () => {
    expect(anchorFromCitation({
      fileType: '.xlsx',
      sourceAnchor: { format: 'xlsx', unit_type: 'row_range', sheet: 'Orders', start_row: 4, end_row: 4 },
      positionType: 'p',
      position: 9,
    })).toEqual(expect.objectContaining({ format: 'xlsx', sheet: 'Orders', start_row: 4 }))

    expect(anchorFromCitation({ fileType: '.docx', positionType: 'para', position: '7' })).toEqual(
      expect.objectContaining({ format: 'docx', unit_type: 'paragraph', start_paragraph: 7 }),
    )
    expect(anchorFromCitation({ fileType: '.pptx', positionType: 'slide', position: '2' })).toEqual(
      expect.objectContaining({ format: 'pptx', unit_type: 'slide', start_slide: 2 }),
    )
    expect(anchorFromCitation({ fileType: '.md', positionType: 'p', position: '5' })).toEqual(
      expect.objectContaining({ format: 'md', unit_type: 'line_range', start_line: 5 }),
    )
  })
})
