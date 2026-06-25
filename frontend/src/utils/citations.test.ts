import { describe, expect, it } from 'vitest'
import {
  bindInlineCitations,
  citationFileType,
  extractInlineCitations,
} from './citations'

describe('inline citation helpers', () => {
  it('extracts document citation markers without moving them out of the answer text', () => {
    const citations = extractInlineCitations('重庆的工业投资增长来自制造业升级 [[重庆统计年鉴.pdf p.12]]，同时服务业恢复。')

    expect(citations).toHaveLength(1)
    expect(citations[0]).toEqual(expect.objectContaining({
      marker: '[[重庆统计年鉴.pdf p.12]]',
      label: '重庆统计年鉴.pdf p.12',
      documentName: '重庆统计年鉴.pdf',
      positionType: 'p',
      position: '12',
    }))
  })

  it('binds citation markers to tool evidence with doc id and source anchor', () => {
    const [binding] = bindInlineCitations(
      '结论来自对应页面 [[重庆统计年鉴.pdf p.12]]。',
      [
        {
          docId: 'doc-chongqing',
          documentName: '重庆统计年鉴.pdf',
          displayLabel: '重庆统计年鉴.pdf p.12',
          sourceAnchor: { format: 'pdf', unit_type: 'page', start_page: 12, end_page: 12 },
        },
      ],
      [],
    )

    expect(binding).toEqual(expect.objectContaining({
      docId: 'doc-chongqing',
      documentName: '重庆统计年鉴.pdf',
      displayLabel: '重庆统计年鉴.pdf p.12',
      fileType: '.pdf',
      sourceAnchor: expect.objectContaining({ start_page: 12 }),
    }))
  })

  it('falls back to document metadata when direct tool evidence is unavailable', () => {
    const [binding] = bindInlineCitations(
      '明细在表格行里 [[sales_orders.xlsx row 4]]。',
      [],
      [
        {
          id: 'doc-orders',
          name: 'sales_orders.xlsx',
          original_name: 'sales_orders.xlsx',
          file_type: '.xlsx',
        },
      ],
    )

    expect(binding).toEqual(expect.objectContaining({
      docId: 'doc-orders',
      documentName: 'sales_orders.xlsx',
      fileType: '.xlsx',
      sourceAnchor: expect.objectContaining({
        format: 'xlsx',
        unit_type: 'row_range',
        start_row: 4,
      }),
    }))
  })

  it('infers supported file type from labels and anchors', () => {
    expect(citationFileType('report.pdf')).toBe('.pdf')
    expect(citationFileType('slides.pptx')).toBe('.pptx')
    expect(citationFileType('unknown', { format: 'docx' })).toBe('.docx')
  })
})
