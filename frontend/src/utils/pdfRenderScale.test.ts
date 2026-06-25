import { describe, expect, it } from 'vitest'
import { computePdfRenderDimensions } from './pdfRenderScale'

describe('pdf render scale helpers', () => {
  it('keeps CSS dimensions stable while increasing backing store pixels', () => {
    expect(computePdfRenderDimensions({
      cssWidth: 600,
      cssHeight: 800,
      devicePixelRatio: 2,
    })).toEqual({
      cssWidth: 600,
      cssHeight: 800,
      backingWidth: 1200,
      backingHeight: 1600,
      outputScale: 2,
    })
  })

  it('caps very high device pixel ratios to avoid excessive PDF canvas memory', () => {
    expect(computePdfRenderDimensions({
      cssWidth: 600,
      cssHeight: 800,
      devicePixelRatio: 4,
      maxOutputScale: 2.5,
    })).toEqual(expect.objectContaining({
      backingWidth: 1500,
      backingHeight: 2000,
      outputScale: 2.5,
    }))
  })

  it('falls back to a 1x backing store for invalid or low ratios', () => {
    expect(computePdfRenderDimensions({
      cssWidth: 600.4,
      cssHeight: 800.6,
      devicePixelRatio: 0.75,
    })).toEqual({
      cssWidth: 600.4,
      cssHeight: 800.6,
      backingWidth: 600,
      backingHeight: 801,
      outputScale: 1,
    })
  })
})
