import type { RetrievalScopeTrace } from '@/types/retrieval'

export function describeScopeTrace(trace?: RetrievalScopeTrace | null): string {
  if (!trace) return 'Current scope'
  if (trace.expanded_to_user_library) return 'Expanded to all accessible documents'
  if (trace.folder_path) {
    return trace.include_subfolders ? `Used ${trace.folder_path} and subfolders` : `Used ${trace.folder_path}`
  }

  const folderId = trace.folder_id || trace.requested_folder_id
  if (folderId) return trace.include_subfolders ? 'Used selected folder and subfolders' : 'Used selected folder'

  const documentIds = trace.document_ids || trace.requested_document_ids
  if (documentIds?.length) {
    return `Used ${documentIds.length} selected document${documentIds.length === 1 ? '' : 's'}`
  }

  return trace.retrieval_mode || 'Current scope'
}
