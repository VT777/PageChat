import { describe, expect, it } from 'vitest'
import { calculatePopoverPosition } from './popoverPosition'

describe('calculatePopoverPosition', () => {
  it('keeps a taller-than-expected row menu inside the visible viewport', () => {
    const position = calculatePopoverPosition({
      anchorRect: { top: 460, right: 1060, bottom: 488 },
      popoverSize: { width: 176, height: 360 },
      viewportSize: { width: 1100, height: 520 },
      gutter: 8,
    })

    expect(position.top).toBe(92)
    expect(position.left).toBe(884)
    expect(position.maxHeight).toBe(504)
    expect(position.top + 360).toBeLessThanOrEqual(512)
  })

  it('lets the menu itself scroll when the viewport is shorter than the menu', () => {
    const position = calculatePopoverPosition({
      anchorRect: { top: 180, right: 860, bottom: 208 },
      popoverSize: { width: 176, height: 420 },
      viewportSize: { width: 900, height: 320 },
      gutter: 8,
    })

    expect(position.top).toBe(8)
    expect(position.left).toBe(684)
    expect(position.maxHeight).toBe(304)
  })
})
