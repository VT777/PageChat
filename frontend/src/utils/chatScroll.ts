export interface ScrollMetrics {
  scrollTop: number
  scrollHeight: number
  clientHeight: number
}

export function isNearBottom(metrics: ScrollMetrics, threshold = 80): boolean {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold
}

export function answerStartScrollTop(metrics: ScrollMetrics, answerOffsetTop: number, topPadding = 24): number {
  const maxScrollTop = Math.max(0, metrics.scrollHeight - metrics.clientHeight)
  return Math.min(maxScrollTop, Math.max(0, answerOffsetTop - topPadding))
}
