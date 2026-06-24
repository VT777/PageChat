export interface PopoverAnchorRect {
  top: number
  right: number
  bottom: number
}

export interface PopoverSize {
  width: number
  height: number
}

export interface ViewportSize {
  width: number
  height: number
}

export interface CalculatePopoverPositionInput {
  anchorRect: PopoverAnchorRect
  popoverSize: PopoverSize
  viewportSize: ViewportSize
  gutter?: number
}

export interface PopoverPosition {
  top: number
  left: number
  maxHeight: number
}

export function calculatePopoverPosition({
  anchorRect,
  popoverSize,
  viewportSize,
  gutter = 8,
}: CalculatePopoverPositionInput): PopoverPosition {
  const maxHeight = Math.max(0, viewportSize.height - gutter * 2)
  const height = Math.min(popoverSize.height, maxHeight)
  const left = Math.max(
    gutter,
    Math.min(viewportSize.width - popoverSize.width - gutter, anchorRect.right - popoverSize.width),
  )
  const belowTop = anchorRect.bottom + gutter
  const aboveTop = anchorRect.top - height - gutter
  const top = belowTop + height <= viewportSize.height - gutter
    ? belowTop
    : Math.max(gutter, aboveTop)

  return {
    top,
    left,
    maxHeight,
  }
}
