import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('RunTimeline contract', () => {
  it('renders progress and tools inside one thought container', () => {
    const source = readFileSync(
      new URL('./RunTimeline.vue', import.meta.url),
      'utf8',
    )

    expect(source).toContain('class="thought-row"')
    expect(source).toContain('v-for="entry in timelineEntries"')
    expect(source).not.toContain('<template v-if="hasTools">')
  })

  it('renders thought text without gray progress dots and hides guardrail rows', () => {
    const source = readFileSync(
      new URL('./RunTimeline.vue', import.meta.url),
      'utf8',
    )

    expect(source).toContain('visibleProgressSteps')
    expect(source).toContain("step.kind !== 'guardrail'")
    expect(source).toContain("step.kind !== 'observation'")
    expect(source).not.toContain('progress-dot')
    expect(source).not.toContain('Circle')
  })
})
