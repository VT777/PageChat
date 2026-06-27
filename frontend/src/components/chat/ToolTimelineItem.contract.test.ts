import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('ToolTimelineItem contract', () => {
  it('prefers backend result labels over array result counts', () => {
    const source = readFileSync(
      new URL('./ToolTimelineItem.vue', import.meta.url),
      'utf8',
    )

    expect(source).toContain('resultLabel')
    expect(source).toContain('result.result_label')
    expect(source).toContain('{{ resultLabel }}')
    expect(source).not.toContain('{{ resultCount }} results')
  })
})
