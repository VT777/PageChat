import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createBufferedStreamText } from './useBufferedStreamText'

describe('createBufferedStreamText', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('buffers tiny chunks until the frame delay elapses while preserving final text', () => {
    const updates: string[] = []
    const buffer = createBufferedStreamText({
      frameMs: 24,
      onDisplayChange: (text) => updates.push(text),
    })

    buffer.push('北')
    buffer.push('京')
    buffer.push('天')

    expect(buffer.current()).toBe('')
    expect(updates).toEqual([])

    vi.advanceTimersByTime(23)
    expect(buffer.current()).toBe('')

    vi.advanceTimersByTime(1)
    expect(buffer.current()).toBe('北京天')
    expect(updates).toEqual(['北京天'])

    buffer.push('气')
    buffer.flush()

    expect(buffer.current()).toBe('北京天气')
    expect(updates).toEqual(['北京天', '北京天气'])
  })

  it('flushes immediately when punctuation or a newline arrives', () => {
    const updates: string[] = []
    const buffer = createBufferedStreamText({
      frameMs: 32,
      onDisplayChange: (text) => updates.push(text),
    })

    buffer.push('你好')
    expect(updates).toEqual([])

    buffer.push('。')
    expect(buffer.current()).toBe('你好。')
    expect(updates).toEqual(['你好。'])

    buffer.push('下一行\n')
    expect(buffer.current()).toBe('你好。下一行\n')
    expect(updates).toEqual(['你好。', '你好。下一行\n'])
  })

  it('disposes pending timers without emitting stale buffered text', () => {
    const updates: string[] = []
    const buffer = createBufferedStreamText({
      frameMs: 24,
      onDisplayChange: (text) => updates.push(text),
    })

    buffer.push('stale')
    buffer.dispose()
    vi.advanceTimersByTime(24)

    expect(buffer.current()).toBe('')
    expect(updates).toEqual([])
  })
})
