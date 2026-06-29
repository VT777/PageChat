import { marked } from 'marked'
import type { BoundInlineCitation } from './citations'
import { extractInlineCitations } from './citations'

export interface WebSourceLike {
  url?: string
  title?: string
}

export interface RenderAssistantMarkdownInput {
  content: string
  citationBindings: BoundInlineCitation[]
  documentNumbers: Map<number, number>
  webSources: WebSourceLike[]
  webNumbers: Map<number, number>
}

export function renderMarkdown(content: string): string {
  if (!content) return ''
  try {
    return marked.parse(content, { breaks: true, gfm: true }) as string
  } catch {
    return escapeHtml(content)
  }
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function contentWithCitationPlaceholders(content: string): string {
  const citations = extractInlineCitations(content)
  if (citations.length === 0) return content

  let cursor = 0
  const parts: string[] = []
  for (const citation of citations) {
    parts.push(content.slice(cursor, citation.start))
    parts.push(`PAGECHAT_CITATION_${citation.index}`)
    cursor = citation.end
  }
  parts.push(content.slice(cursor))
  return parts.join('')
}

export function renderAssistantMarkdown(input: RenderAssistantMarkdownInput): string {
  const { content, citationBindings, documentNumbers, webSources, webNumbers } = input
  const hasDocumentCitations = citationBindings.length > 0
  let html = renderMarkdown(hasDocumentCitations ? contentWithCitationPlaceholders(content) : content)

  for (const binding of citationBindings) {
    const placeholder = `PAGECHAT_CITATION_${binding.index}`
    const title = binding.displayLabel
    const number = documentNumbers.get(binding.index) || binding.sourceNumber
    const button = [
      '<button type="button" class="inline-citation"',
      ` data-citation-index="${binding.index}"`,
      ` title="${escapeHtml(title)}">`,
      `[${number}]`,
      '</button>',
    ].join('')
    html = html.replace(placeholder, button)
  }

  html = decorateWebSourceLinks(html, webSources, webNumbers)
  return wrapCodeBlocks(wrapMarkdownTables(html))
}

export function decorateWebSourceLinks(
  html: string,
  webSources: WebSourceLike[],
  webNumbers: Map<number, number>,
): string {
  let decorated = html
  webSources.forEach((source, index) => {
    if (!source.url) return
    const escapedUrl = escapeHtml(source.url)
    const number = webNumbers.get(index) || index + 1
    const button = [
      '<button type="button" class="inline-citation web-citation"',
      ` data-web-source-index="${index}"`,
      ` title="${escapeHtml(source.title || source.url)}">`,
      `[${number}]`,
      '</button>',
    ].join('')
    const linkPattern = new RegExp(`<a href="${escapeRegExp(escapedUrl)}"[^>]*>.*?</a>`, 'g')
    decorated = decorated.replace(linkPattern, button)
  })
  return decorated
}

export function wrapMarkdownTables(html: string): string {
  if (!html.includes('<table')) return html
  return html.replace(/<table([\s\S]*?)<\/table>/g, '<div class="answer-table-wrap"><table$1</table></div>')
}

export function wrapCodeBlocks(html: string): string {
  if (!html.includes('<pre><code')) return html
  return html.replace(
    /<pre><code(?: class="language-([^"]+)")?>([\s\S]*?)<\/code><\/pre>/g,
    (_match, language: string | undefined, code: string) => {
      const label = languageLabel(language || 'plain')
      const className = language ? ` class="language-${escapeHtml(language)}"` : ''
      return [
        '<div class="answer-code-block">',
        `<div class="answer-code-header"><span>${escapeHtml(label)}</span></div>`,
        `<pre><code${className}>${code}</code></pre>`,
        '</div>',
      ].join('')
    },
  )
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function languageLabel(language: string): string {
  const normalized = language.trim().toLowerCase()
  const labels: Record<string, string> = {
    js: 'JavaScript',
    javascript: 'JavaScript',
    ts: 'TypeScript',
    typescript: 'TypeScript',
    py: 'Python',
    python: 'Python',
    json: 'JSON',
    html: 'HTML',
    css: 'CSS',
    sql: 'SQL',
    sh: 'Shell',
    bash: 'Shell',
    shell: 'Shell',
    md: 'Markdown',
    markdown: 'Markdown',
    mermaid: 'Mermaid',
    echarts: 'ECharts',
    plain: 'Plain',
    text: 'Plain',
  }
  return labels[normalized] || normalized.charAt(0).toUpperCase() + normalized.slice(1)
}
