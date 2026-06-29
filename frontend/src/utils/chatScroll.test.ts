import { describe, expect, it } from 'vitest'
import { answerStartScrollTop, isNearBottom } from './chatScroll'

describe('chat scroll helpers', () => {
  it('detects whether the user is still following streaming output', () => {
    expect(isNearBottom({ scrollTop: 900, scrollHeight: 1200, clientHeight: 260 })).toBe(true)
    expect(isNearBottom({ scrollTop: 760, scrollHeight: 1200, clientHeight: 260 })).toBe(false)
  })

  it('calculates the final position at the start of the newest answer', () => {
    expect(answerStartScrollTop(
      { scrollTop: 0, scrollHeight: 2000, clientHeight: 700 },
      1180,
      32,
    )).toBe(1148)
    expect(answerStartScrollTop(
      { scrollTop: 0, scrollHeight: 1200, clientHeight: 700 },
      1100,
      32,
    )).toBe(500)
  })
})
