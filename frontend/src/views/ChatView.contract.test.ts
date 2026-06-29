import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('ChatView citation rendering contract', () => {
  it('does not append structured citations when the answer has no inline citation marker', () => {
    const source = readFileSync(new URL('./ChatView.vue', import.meta.url), 'utf8')

    expect(source).not.toContain('appendStructuredCitationButtons(')
    expect(source).not.toContain('data-structured-citation-index')
  })

  it('opens web citations in the browser instead of the preview drawer', () => {
    const source = readFileSync(new URL('./ChatView.vue', import.meta.url), 'utf8')

    expect(source).toContain('window.open(source.url')
    expect(source).not.toContain('activeCitation.value = webPreviewFromSource(source)')
  })
})
