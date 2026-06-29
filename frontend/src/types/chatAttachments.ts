export interface ChatAttachmentMetadata {
  attachment_id: string
  original_name: string
  mime_type: string
  size_bytes: number
  width?: number | null
  height?: number | null
  content_url?: string
}

export interface ComposerImageAttachment {
  localId: string
  name: string
  file: File
  previewUrl: string
  status: 'local' | 'uploading' | 'uploaded' | 'failed'
  error?: string
  remote?: ChatAttachmentMetadata
}

export interface ChatAttachmentPreview extends ChatAttachmentMetadata {
  preview_url?: string
  preview_status?: 'idle' | 'loading' | 'ready' | 'failed'
}
