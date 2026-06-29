export interface PdfRenderDimensionsInput {
  cssWidth: number
  cssHeight: number
  devicePixelRatio?: number
  maxOutputScale?: number
}

export interface PdfRenderDimensions {
  cssWidth: number
  cssHeight: number
  backingWidth: number
  backingHeight: number
  outputScale: number
}

export function computePdfRenderDimensions(input: PdfRenderDimensionsInput): PdfRenderDimensions {
  const cssWidth = Math.max(1, Number(input.cssWidth) || 1)
  const cssHeight = Math.max(1, Number(input.cssHeight) || 1)
  const maxOutputScale = Math.max(1, Number(input.maxOutputScale) || 2.5)
  const rawRatio = Number(input.devicePixelRatio)
  const outputScale = Math.min(
    maxOutputScale,
    Math.max(1, Number.isFinite(rawRatio) ? rawRatio : 1),
  )

  return {
    cssWidth,
    cssHeight,
    backingWidth: Math.max(1, Math.round(cssWidth * outputScale)),
    backingHeight: Math.max(1, Math.round(cssHeight * outputScale)),
    outputScale,
  }
}

export function currentPdfRenderDimensions(cssWidth: number, cssHeight: number): PdfRenderDimensions {
  return computePdfRenderDimensions({
    cssWidth,
    cssHeight,
    devicePixelRatio: typeof window === 'undefined' ? 1 : window.devicePixelRatio,
  })
}
