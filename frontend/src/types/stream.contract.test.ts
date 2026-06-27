import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('stream event contract', () => {
  it('declares provider processing and tool call delta events', () => {
    const source = readFileSync(new URL('./stream.ts', import.meta.url), 'utf8')

    expect(source).toContain("'processing_delta'")
    expect(source).toContain("'tool_call_delta'")
    expect(source).toContain('export interface ProcessingDelta')
    expect(source).toContain('export interface ToolCallDelta')
    expect(source).toContain('| ProcessingDelta')
    expect(source).toContain('| ToolCallDelta')
  })
})
