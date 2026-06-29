import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('AssistantMarkdownRenderer contract', () => {
  it('owns assistant Markdown rendering and emits source click events', () => {
    const source = readFileSync(new URL('./AssistantMarkdownRenderer.vue', import.meta.url), 'utf-8')

    expect(source).toContain('class="assistant-markdown"')
    expect(source).toContain('renderAssistantMarkdown')
    expect(source).toContain('bindInlineCitations')
    expect(source).toContain('assignInlineSourceNumbers')
    expect(source).toContain('citation-click')
    expect(source).toContain('web-source-click')
    expect(source).toContain('data-citation-index')
    expect(source).toContain('data-web-source-index')
  })

  it('keeps ChatView free of inline Markdown parser and citation HTML construction', () => {
    const source = readFileSync(new URL('../../views/ChatView.vue', import.meta.url), 'utf-8')

    expect(source).toContain('AssistantMarkdownRenderer')
    expect(source).not.toContain("import { marked } from 'marked'")
    expect(source).not.toContain('function renderMarkdown')
    expect(source).not.toContain('function renderMessageMarkdown')
    expect(source).not.toContain('contentWithCitationPlaceholders')
    expect(source).not.toContain('decorateWebSourceLinks')
  })

  it('defines Dify-lite answer prose styles in the renderer boundary', () => {
    const source = readFileSync(new URL('./AssistantMarkdownRenderer.vue', import.meta.url), 'utf-8')

    expect(source).toContain('.assistant-markdown')
    expect(source).toContain(':deep(.answer-table-wrap)')
    expect(source).toContain(':deep(table)')
    expect(source).toContain(':deep(th)')
    expect(source).toContain(':deep(td)')
    expect(source).toContain(':deep(blockquote)')
    expect(source).toContain(':deep(pre)')
    expect(source).toContain(':deep(.answer-code-block)')
    expect(source).toContain(':deep(.answer-code-header)')
    expect(source).toContain(':deep(img)')
    expect(source).toContain(':deep(.inline-citation)')
  })
})
