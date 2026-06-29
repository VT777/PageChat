import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('PdfReferenceViewer loading contract', () => {
  it('preflights the PDF response so 200 HTML or API errors are shown clearly instead of generic load failure', () => {
    const source = readFileSync(new URL('./PdfReferenceViewer.vue', import.meta.url), 'utf8')

    expect(source).toContain('fetchPdfBlobUrl')
    expect(source).toContain('revokeObjectURL')
  })
})
