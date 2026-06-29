import { describe, expect, it } from 'vitest'
import type { BoundInlineCitation } from './citations'
import {
  contentWithCitationPlaceholders,
  escapeHtml,
  renderAssistantMarkdown,
  renderMarkdown,
  wrapCodeBlocks,
  wrapMarkdownTables,
} from './answerMarkdown'

const citation = {
  index: 0,
  displayLabel: 'report.pdf p.2',
  sourceNumber: 1,
} as BoundInlineCitation

describe('answer markdown helpers', () => {
  it('renders GitHub-flavored Markdown', () => {
    expect(renderMarkdown('**Hello**\n\n- A')).toContain('<strong>Hello</strong>')
    expect(renderMarkdown('**Hello**\n\n- A')).toContain('<li>A</li>')
  })

  it('escapes citation titles before injecting inline citation buttons', () => {
    const html = renderAssistantMarkdown({
      content: 'Result [[report.pdf p.2]]',
      citationBindings: [{ ...citation, displayLabel: 'report "A" <unsafe>' }],
      documentNumbers: new Map([[0, 3]]),
      webSources: [],
      webNumbers: new Map(),
    })

    expect(html).toContain('class="inline-citation"')
    expect(html).toContain('data-citation-index="0"')
    expect(html).toContain('[3]')
    expect(html).toContain('title="report &quot;A&quot; &lt;unsafe&gt;"')
  })

  it('decorates matching web source links as inline citation buttons', () => {
    const html = renderAssistantMarkdown({
      content: 'See https://example.com/weather for details.',
      citationBindings: [],
      documentNumbers: new Map(),
      webSources: [{ url: 'https://example.com/weather', title: 'Weather' }],
      webNumbers: new Map([[0, 2]]),
    })

    expect(html).toContain('class="inline-citation web-citation"')
    expect(html).toContain('data-web-source-index="0"')
    expect(html).toContain('[2]')
  })

  it('replaces citation markers with stable placeholders before Markdown parsing', () => {
    expect(contentWithCitationPlaceholders('A [[doc.pdf p.1]] B')).toBe('A PAGECHAT_CITATION_0 B')
  })

  it('wraps tables so wide answer tables can scroll inside the chat column', () => {
    const wrapped = wrapMarkdownTables('<p>A</p><table><thead></thead></table>')

    expect(wrapped).toContain('<div class="answer-table-wrap"><table>')
  })

  it('wraps fenced code blocks with a lightweight language header', () => {
    const html = renderAssistantMarkdown({
      content: '```ts\nconst answer = 42\n```',
      citationBindings: [],
      documentNumbers: new Map(),
      webSources: [],
      webNumbers: new Map(),
    })

    expect(html).toContain('class="answer-code-block"')
    expect(html).toContain('class="answer-code-header"')
    expect(html).toContain('TypeScript')
    expect(wrapCodeBlocks('<pre><code>plain</code></pre>')).toContain('Plain')
  })

  it('escapes raw HTML text for injected attributes', () => {
    expect(escapeHtml(`"x" <y> & 'z'`)).toBe('&quot;x&quot; &lt;y&gt; &amp; &#39;z&#39;')
  })
})
