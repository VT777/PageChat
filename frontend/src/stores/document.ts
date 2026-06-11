import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { documentApi } from '@/api'
import type { ProcessingStep } from '@/api'
import type { QualityReport } from '@/types/retrieval'

export interface Document {
  id: string
  name: string
  original_name: string
  file_path: string
  index_path?: string
  file_size: number
  file_type: string
  status: string
  page_count?: number
  processed_pages?: number
  error_message?: string
  description?: string
  parse_requested_mode?: 'smart' | 'fast' | 'balanced' | null
  parse_execution_mode?: 'smart' | 'fast' | 'balanced' | null
  parse_reasons?: string[]
  parse_completion?: 'completed' | 'failed' | 'processing' | null
  parse_error_code?: string | null
  quality_report?: QualityReport | null
  processing_duration?: number
  created_at: string
  updated_at: string
  folder_id?: string | null
}

export const useDocumentStore = defineStore('document', () => {
  const documents = ref<Document[]>([])
  const loading = ref(false)
  const total = ref(0)
  const currentPage = ref(1)
  const searchQuery = ref('')
  const currentFolderId = ref<string | null>(null)

  // View & selection state
  const viewMode = ref<'grid' | 'list'>('grid')
  const selectedIds = ref<Set<string>>(new Set())
  const isBatchMode = ref(false)

  // Polling state
  const pollingInterval = ref<ReturnType<typeof setInterval> | null>(null)
  const processingDocIds = ref<Set<string>>(new Set())

  const indexedDocuments = computed(() =>
    documents.value.filter((d) => d.status === 'completed')
  )

  const selectedDocuments = computed(() =>
    documents.value.filter((d) => selectedIds.value.has(d.id))
  )

  const hasSelection = computed(() => selectedIds.value.size > 0)

  // Selection helpers
  function toggleSelect(id: string) {
    if (selectedIds.value.has(id)) {
      selectedIds.value.delete(id)
    } else {
      selectedIds.value.add(id)
    }
  }

  function selectAll() {
    documents.value.forEach((d) => selectedIds.value.add(d.id))
  }

  function deselectAll() {
    selectedIds.value.clear()
  }

  function clearSelection() {
    selectedIds.value.clear()
    isBatchMode.value = false
  }

  function toggleBatchMode() {
    isBatchMode.value = !isBatchMode.value
    if (!isBatchMode.value) {
      selectedIds.value.clear()
    }
  }

  async function fetchDocuments(page = 1, search?: string, folder_id?: string | null, include_subfolders = false) {
    loading.value = true
    try {
      const { data } = await documentApi.list({
        page,
        page_size: 20,
        search,
        folder_id: folder_id ?? currentFolderId.value,
        include_subfolders,
      })
      documents.value = data.items
      total.value = data.total
      currentPage.value = page
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    } finally {
      loading.value = false
    }
  }

  async function uploadDocument(file: File, folder_id?: string | null, parse_mode?: string | null) {
    try {
      const { data } = await documentApi.upload(file, folder_id, parse_mode)
      documents.value.unshift(data)
      total.value++
      // Start polling if document is processing or pending
      if (data.status && (data.status.startsWith('processing') || data.status === 'pending')) {
        processingDocIds.value.add(data.id)
        ensurePolling()
      }
      return data
    } catch (error) {
      console.error('Failed to upload document:', error)
      throw error
    }
  }

  async function uploadDocuments(
    files: File[],
    folder_id?: string | null,
    parse_mode?: string | null,
    onProgress?: (current: number, fileName: string) => void
  ) {
    const results = []
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      if (onProgress) {
        onProgress(i + 1, file.name)
      }
      try {
        const data = await uploadDocument(file, folder_id, parse_mode)
        results.push(data)
      } catch (error) {
        console.error(`Failed to upload ${file.name}:`, error)
        // Continue uploading remaining files
      }
    }
    return results
  }

  async function deleteDocument(id: string) {
    try {
      await documentApi.delete(id)
      documents.value = documents.value.filter((d) => d.id !== id)
      selectedIds.value.delete(id)
      total.value--
    } catch (error) {
      console.error('Failed to delete document:', error)
      throw error
    }
  }

  async function reindexDocument(id: string, mode: 'smart' | 'fast' | 'balanced' = 'smart') {
    try {
      await documentApi.reindex(id, { mode })
      const doc = documents.value.find((d) => d.id === id)
      if (doc) {
        doc.status = 'processing'
        processingDocIds.value.add(id)
        ensurePolling()
      }
    } catch (error) {
      console.error('Failed to reindex document:', error)
      throw error
    }
  }

  async function moveDocument(id: string, folder_id: string | null) {
    try {
      await documentApi.move(id, folder_id)
      // Remove document from current list since it was moved
      documents.value = documents.value.filter((d) => d.id !== id)
      selectedIds.value.delete(id)
      total.value--
    } catch (error) {
      console.error('Failed to move document:', error)
      throw error
    }
  }

  async function renameDocument(id: string, name: string) {
    try {
      await documentApi.rename(id, name)
      const doc = documents.value.find((d) => d.id === id)
      if (doc) {
        doc.original_name = name
      }
    } catch (error) {
      console.error('Failed to rename document:', error)
      throw error
    }
  }

  function updateDocumentStatus(id: string, status: Document['status'], extra?: Partial<Document>) {
    const doc = documents.value.find((d) => d.id === id)
    if (doc) {
      doc.status = status
      if (extra) {
        Object.assign(doc, extra)
      }
    }
  }

  // Polling logic
  function ensurePolling() {
    if (pollingInterval.value) return
    pollingInterval.value = setInterval(async () => {
      if (processingDocIds.value.size === 0) {
        stopPolling()
        return
      }
      // Refresh current page to get updated statuses
      try {
        const { data } = await documentApi.list({
          page: currentPage.value,
          page_size: 20,
          search: searchQuery.value || undefined,
          folder_id: currentFolderId.value,
          include_subfolders: true,
        })
        // Update documents while preserving selection state
        const selected = new Set(selectedIds.value)
        documents.value = data.items
        selectedIds.value = selected

        // Check which docs are still processing or pending
        const stillProcessing = new Set<string>()
        for (const doc of data.items) {
          if (doc.status && (doc.status.startsWith('processing') || doc.status === 'pending')) {
            stillProcessing.add(doc.id)
          }
        }
        processingDocIds.value = stillProcessing
        if (stillProcessing.size === 0) {
          stopPolling()
        }
      } catch (e) {
        console.error('Polling error:', e)
      }
    }, 3000)
  }

  function stopPolling() {
    if (pollingInterval.value) {
      clearInterval(pollingInterval.value)
      pollingInterval.value = null
    }
  }

  // Fetch processing steps for a document
  async function fetchDocumentSteps(id: string): Promise<ProcessingStep[]> {
    try {
      const { data } = await documentApi.getProcessingSteps(id)
      return data.steps || []
    } catch (error) {
      console.error('Failed to fetch processing steps:', error)
      return []
    }
  }

  // Batch download
  async function batchDownload(docIds: string[]) {
    try {
      const response = await documentApi.batchDownload(docIds)
      const blob = new Blob([response.data], { type: 'application/zip' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `batch_download_${docIds.length}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to batch download:', error)
      throw error
    }
  }

  // 批量操作
  async function batchMove(docIds: string[], folder_id: string | null) {
    for (const id of docIds) {
      try {
        await moveDocument(id, folder_id)
      } catch (error) {
        console.error(`Failed to move document ${id}:`, error)
      }
    }
  }

  async function batchDelete(docIds: string[]) {
    for (const id of docIds) {
      try {
        await deleteDocument(id)
      } catch (error) {
        console.error(`Failed to delete document ${id}:`, error)
      }
    }
  }

  async function batchReindex(docIds: string[]) {
    for (const id of docIds) {
      try {
        await reindexDocument(id)
      } catch (error) {
        console.error(`Failed to reindex document ${id}:`, error)
      }
    }
  }

  return {
    documents,
    loading,
    total,
    currentPage,
    searchQuery,
    currentFolderId,
    viewMode,
    selectedIds,
    isBatchMode,
    selectedDocuments,
    hasSelection,
    indexedDocuments,
    toggleSelect,
    selectAll,
    deselectAll,
    clearSelection,
    toggleBatchMode,
    fetchDocuments,
    uploadDocument,
    uploadDocuments,
    deleteDocument,
    reindexDocument,
    moveDocument,
    renameDocument,
    updateDocumentStatus,
    fetchDocumentSteps,
    batchDownload,
    batchMove,
    batchDelete,
    batchReindex,
    stopPolling,
  }
})
