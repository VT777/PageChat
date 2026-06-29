import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('PdfViewer loading contract', () => {
  it('uses the same PDF response preflight as citation previews', () => {
    const source = readFileSync(new URL('./PdfViewer.vue', import.meta.url), 'utf8')

    expect(source).toContain('fetchPdfBlobUrl')
    expect(source).toContain('revokeObjectURL')
  })
})
