import type { SourceAnchor } from '@/types/preview'

export interface EvidenceLabelInput {
  documentName?: string
  displayLabel?: string | null
  sourceAnchor?: Partial<SourceAnchor> | null
  fallbackLabel?: string | null
}

export function formatEvidenceLabel(input: EvidenceLabelInput): string {
  if (input.displayLabel) return input.displayLabel
  const name = input.documentName || 'Source'
  const anchor = input.sourceAnchor
  if (!anchor) return input.fallbackLabel || name

  const range = (start?: number, end?: number) => {
    if (start === undefined || start === null) return ''
    if (end !== undefined && end !== null && end !== start) return `${start}-${end}`
    return String(start)
  }

  const unitType = anchor.unit_type || inferUnitType(anchor)
  if (unitType === 'page') {
    const pages = range(anchor.start_page, anchor.end_page)
    if (pages) return `${name} p.${pages}`
  }
  if (unitType === 'line') {
    const lines = range(anchor.start_line, anchor.end_line)
    if (lines) return `${name} ${lines.includes('-') ? 'lines' : 'line'} ${lines}`
  }
  if (unitType === 'paragraph') {
    const paragraphs = range(anchor.start_paragraph, anchor.end_paragraph)
    if (paragraphs) return `${name} ${paragraphs.includes('-') ? 'paragraphs' : 'paragraph'} ${paragraphs}`
  }
  if (unitType === 'row' || unitType === 'row_range') {
    const rows = range(anchor.start_row, anchor.end_row)
    if (rows) {
      const sheet = anchor.sheet ? ` ${anchor.sheet}` : ''
      return `${name}${sheet} ${rows.includes('-') ? 'rows' : 'row'} ${rows}`
    }
  }
  if (unitType === 'slide') {
    const start = anchor.start_slide ?? anchor.slide
    const slides = range(start, anchor.end_slide)
    if (slides) return `${name} ${slides.includes('-') ? 'slides' : 'slide'} ${slides}`
  }

  return input.fallbackLabel || name
}

function inferUnitType(anchor: Partial<SourceAnchor>): string | undefined {
  if (anchor.start_page !== undefined) return 'page'
  if (anchor.start_line !== undefined) return 'line'
  if (anchor.start_paragraph !== undefined) return 'paragraph'
  if (anchor.start_row !== undefined) return 'row_range'
  if (anchor.start_slide !== undefined || anchor.slide !== undefined) return 'slide'
  return undefined
}
