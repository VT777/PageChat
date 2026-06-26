import type { SourceAnchor } from '@/types/preview'
import { anchorFromCitation } from './documentWorkbench'

export interface InlineCitation {
  index: number
  marker: string
  label: string
  documentName: string
  positionType: string
  position: string
  start: number
  end: number
}

export interface CitationEvidenceLike {
  docId?: string
  documentName?: string
  displayLabel?: string
  sourceAnchor?: SourceAnchor | null
  fileType?: string
  highlightedSnippet?: string
}

export interface CitationDocumentLike {
  id: string
  name?: string
  original_name?: string
  file_type?: string
}

export interface BoundInlineCitation extends InlineCitation {
  docId?: string
  documentName: string
  displayLabel: string
  sourceNumber: number
  compactLabel: string
  fileType: string
  sourceAnchor: SourceAnchor
  highlightedSnippet?: string
  resolved: boolean
}

export interface SourceNumberMaps {
  documentNumbers: Map<number, number>
  webNumbers: Map<number, number>
}

const CITATION_RE = /\[\[([^\[\]]+)\]\]/g
const POSITION_RE = /^(.*?)\s+(p|page|pages|页|line|lines|row|rows|para|paragraph|paragraphs|slide|slides)\.?\s*(\d+(?:\s*-\s*\d+)?)$/i

export function extractInlineCitations(content: string): InlineCitation[] {
  const citations: InlineCitation[] = []
  let match: RegExpExecArray | null
  CITATION_RE.lastIndex = 0

  while ((match = CITATION_RE.exec(content)) !== null) {
    const label = match[1].trim().replace(/\s+/g, ' ')
    const parsed = parseCitationLabel(label)
    citations.push({
      index: citations.length,
      marker: match[0],
      label,
      documentName: parsed.documentName,
      positionType: parsed.positionType,
      position: parsed.position,
      start: match.index,
      end: match.index + match[0].length,
    })
  }

  return citations
}

export function citationFileType(documentName: string, anchor?: Partial<SourceAnchor> | null): string {
  const fromAnchor = anchor?.format ? normalizeExtension(String(anchor.format)) : ''
  if (fromAnchor) return fromAnchor

  const match = documentName.match(/\.(pdf|docx|xlsx|csv|tsv|pptx|md|markdown|txt)\b/i)
  if (!match) return '.pdf'
  const ext = match[1].toLowerCase()
  return ext === 'markdown' ? '.md' : `.${ext}`
}

export function bindInlineCitations(
  content: string,
  evidenceItems: CitationEvidenceLike[] = [],
  documents: CitationDocumentLike[] = [],
): BoundInlineCitation[] {
  return extractInlineCitations(content).map((citation) => {
    const evidence = bestEvidence(citation, evidenceItems)
    const document = evidence?.docId
      ? documents.find((item) => item.id === evidence.docId)
      : findDocument(citation.documentName, documents)
    const documentName = evidence?.documentName || document?.original_name || document?.name || citation.documentName
    const sourceAnchor = evidence?.sourceAnchor || null
    const fileType = normalizeExtension(evidence?.fileType || document?.file_type || citationFileType(documentName, sourceAnchor))
    return {
      ...citation,
      docId: evidence?.docId || document?.id,
      documentName,
      displayLabel: evidence?.displayLabel || citation.label,
      sourceNumber: citation.index + 1,
      compactLabel: `[${citation.index + 1}]`,
      fileType,
      sourceAnchor: anchorFromCitation({
        fileType,
        sourceAnchor: sourceAnchor ? { ...sourceAnchor } : null,
        positionType: citation.positionType,
        position: citation.position,
      }),
      highlightedSnippet: evidence?.highlightedSnippet,
      resolved: Boolean(evidence?.docId || document?.id),
    }
  })
}

export function assignInlineSourceNumbers(content: string, webSourceUrls: string[] = []): SourceNumberMaps {
  const entries: Array<{ kind: 'document' | 'web'; index: number; start: number; key: string }> = []
  extractInlineCitations(content).forEach((citation) => {
    entries.push({
      kind: 'document',
      index: citation.index,
      start: citation.start,
      key: `document:${normalizeComparable(citation.label)}`,
    })
  })
  webSourceUrls.forEach((url, index) => {
    const start = url ? content.indexOf(url) : -1
    entries.push({
      kind: 'web',
      index,
      start: start >= 0 ? start : Number.MAX_SAFE_INTEGER - index,
      key: `web:${url}`,
    })
  })

  entries.sort((a, b) => a.start - b.start || a.index - b.index)
  const documentNumbers = new Map<number, number>()
  const webNumbers = new Map<number, number>()
  const numberByKey = new Map<string, number>()
  let nextNumber = 1
  entries.forEach((entry) => {
    let number = numberByKey.get(entry.key)
    if (!number) {
      number = nextNumber
      numberByKey.set(entry.key, number)
      nextNumber += 1
    }
    if (entry.kind === 'document') {
      documentNumbers.set(entry.index, number)
    } else {
      webNumbers.set(entry.index, number)
    }
  })
  return { documentNumbers, webNumbers }
}

function parseCitationLabel(label: string): Pick<InlineCitation, 'documentName' | 'positionType' | 'position'> {
  const match = label.match(POSITION_RE)
  if (!match) {
    return {
      documentName: label,
      positionType: '',
      position: '1',
    }
  }

  return {
    documentName: match[1].trim(),
    positionType: normalizePositionType(match[2]),
    position: match[3].replace(/\s+/g, ''),
  }
}

function normalizePositionType(value: string): string {
  const type = value.toLowerCase()
  if (type === 'page' || type === 'pages' || type === '页') return 'p'
  if (type === 'lines') return 'line'
  if (type === 'rows') return 'row'
  if (type === 'paragraph' || type === 'paragraphs') return 'para'
  if (type === 'slides') return 'slide'
  return type
}

function normalizeExtension(value?: string): string {
  const raw = String(value || '').trim().toLowerCase()
  if (!raw) return ''
  if (raw === 'markdown') return '.md'
  return raw.startsWith('.') ? raw : `.${raw}`
}

function normalizeComparable(value?: string): string {
  return String(value || '')
    .toLowerCase()
    .replace(/[\[\]（）()'"“”‘’]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function stripExtension(value: string): string {
  return normalizeComparable(value).replace(/\.(pdf|docx|xlsx|csv|tsv|pptx|md|markdown|txt)\b/g, '')
}

function sameDocumentName(a?: string, b?: string): boolean {
  const left = normalizeComparable(a)
  const right = normalizeComparable(b)
  if (!left || !right) return false
  return left === right || stripExtension(left) === stripExtension(right)
}

function citationPositionNumber(citation: InlineCitation): number {
  const match = citation.position.match(/\d+/)
  return match ? Number(match[0]) : 1
}

function anchorPositionNumber(anchor?: Partial<SourceAnchor> | null): number | null {
  if (!anchor) return null
  const values = [
    anchor.start_page,
    anchor.start_line,
    anchor.start_row,
    anchor.start_paragraph,
    anchor.start_slide,
    anchor.slide,
  ]
  const found = values.find((value) => Number.isFinite(Number(value)))
  return found === undefined ? null : Number(found)
}

function bestEvidence(citation: InlineCitation, evidenceItems: CitationEvidenceLike[]): CitationEvidenceLike | null {
  let best: { item: CitationEvidenceLike; score: number } | null = null
  for (const item of evidenceItems) {
    const label = normalizeComparable(item.displayLabel)
    const citationLabel = normalizeComparable(citation.label)
    const itemName = item.documentName || item.displayLabel || ''
    const nameMatches = sameDocumentName(itemName, citation.documentName)
    const labelMatches = label.length > 0 && label === citationLabel
    const positionMatches = anchorPositionNumber(item.sourceAnchor) === citationPositionNumber(citation)
    if (!labelMatches && !nameMatches) continue

    let score = 0
    if (labelMatches) score += 100
    if (nameMatches) score += 60
    if (positionMatches) score += 30
    if (item.docId) score += 10
    if (score > (best?.score || 0)) best = { item, score }
  }
  return best?.item || null
}

function findDocument(documentName: string, documents: CitationDocumentLike[]): CitationDocumentLike | undefined {
  return documents.find((item) =>
    sameDocumentName(item.original_name || item.name || item.id, documentName),
  )
}
