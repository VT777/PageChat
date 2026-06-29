export interface BufferedStreamText {
  push(delta: string): void
  flush(): void
  dispose(): void
  reset(text?: string): void
  current(): string
}

export interface BufferedStreamTextOptions {
  frameMs?: number
  initialText?: string
  onDisplayChange: (text: string) => void
}

const IMMEDIATE_FLUSH_RE = /[\n\r.!?;:,，。！？；：、]/

export function createBufferedStreamText(options: BufferedStreamTextOptions): BufferedStreamText {
  const frameMs = options.frameMs ?? 24
  let displayed = options.initialText ?? ''
  let pending = ''
  let timer: ReturnType<typeof setTimeout> | null = null

  const clearTimer = () => {
    if (timer === null) return
    clearTimeout(timer)
    timer = null
  }

  const flush = () => {
    if (!pending) return
    clearTimer()
    displayed += pending
    pending = ''
    options.onDisplayChange(displayed)
  }

  const schedule = () => {
    if (timer !== null) return
    timer = setTimeout(() => {
      timer = null
      flush()
    }, frameMs)
  }

  return {
    push(delta: string) {
      if (!delta) return
      pending += delta
      if (IMMEDIATE_FLUSH_RE.test(delta)) {
        flush()
        return
      }
      schedule()
    },
    flush,
    dispose() {
      clearTimer()
      pending = ''
    },
    reset(text = '') {
      clearTimer()
      displayed = text
      pending = ''
      options.onDisplayChange(displayed)
    },
    current() {
      return displayed
    },
  }
}
