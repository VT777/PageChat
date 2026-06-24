import { formatDocumentDate, formatDocumentSize } from '@/utils/documentWorkbench'

export function formatFileSize(bytes?: number): string {
  return formatDocumentSize(bytes)
}

export function formatDate(date?: string): string {
  return formatDocumentDate(date)
}
