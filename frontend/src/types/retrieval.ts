export interface QualityReport {
  status?: 'completed' | 'needs_review' | 'failed:indexing' | string
  score?: number
  warnings?: string[]
  node_count?: number
  page_range_coverage?: number
}

export interface RetrievalScopeTrace {
  folder_id?: string
  requested_folder_id?: string
  folder_path?: string
  include_subfolders?: boolean
  document_ids?: string[]
  requested_document_ids?: string[]
  strict_scope?: boolean
  expanded_to_user_library?: boolean
  retrieval_mode?: string
  recommended_next_action?: string
}

export interface ChatScopeRequest {
  folder_id?: string
  include_subfolders?: boolean
  document_ids?: string[]
  strict_scope?: boolean
}
