import { describe, expect, it } from 'vitest'
import { formatEvidenceLabel } from './evidence'

describe('formatEvidenceLabel', () => {
  it('prefers backend display labels', () => {
    expect(formatEvidenceLabel({
      documentName: 'report.pdf',
      displayLabel: 'backend label',
      sourceAnchor: { unit_type: 'page', start_page: 12 },
    })).toBe('backend label')
  })

  it('formats PDF page ranges', () => {
    expect(formatEvidenceLabel({
      documentName: 'report.pdf',
      sourceAnchor: { unit_type: 'page', start_page: 12, end_page: 15 },
    })).toBe('report.pdf p.12-15')
  })

  it('formats text line ranges', () => {
    expect(formatEvidenceLabel({
      documentName: 'notes.md',
      sourceAnchor: { unit_type: 'line', start_line: 20, end_line: 42 },
    })).toBe('notes.md lines 20-42')
  })

  it('formats DOCX paragraph ranges', () => {
    expect(formatEvidenceLabel({
      documentName: 'contract.docx',
      sourceAnchor: { unit_type: 'paragraph', start_paragraph: 10, end_paragraph: 18 },
    })).toBe('contract.docx paragraphs 10-18')
  })

  it('formats spreadsheet row ranges with sheet names', () => {
    expect(formatEvidenceLabel({
      documentName: 'sales.xlsx',
      sourceAnchor: { unit_type: 'row_range', sheet: 'Sheet1', start_row: 2, end_row: 80 },
    })).toBe('sales.xlsx Sheet1 rows 2-80')
  })

  it('formats PPTX slides', () => {
    expect(formatEvidenceLabel({
      documentName: 'deck.pptx',
      sourceAnchor: { unit_type: 'slide', start_slide: 7, end_slide: 7 },
    })).toBe('deck.pptx slide 7')
  })
})
