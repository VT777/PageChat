import type { SourceAnchor } from './preview'

export type StreamEventName =
  | 'run_started'
  | 'progress'
  | 'tool_started'
  | 'tool_completed'
  | 'answer_delta'
  | 'citation_added'
  | 'run_completed'
  | 'run_failed'
  | 'run_cancelled'

export interface StreamEnvelope<TData = PageChatStreamData> {
  event: StreamEventName
  data: TData
}

export interface PageChatEventMeta {
  run_id: string
  conversation_id: string
  message_id: string
  seq: number
  ts: string
}

export interface RunStarted extends PageChatEventMeta {
  status: 'running'
}

export interface ProgressEvent extends PageChatEventMeta {
  kind?: string
  message: string
  step?: number
  status?: string
  target_kind?: string
}

export interface ToolStarted extends PageChatEventMeta {
  tool_name: string
  arguments: Record<string, unknown>
}

export interface ToolCompleted extends PageChatEventMeta {
  tool_name: string
  result: Record<string, unknown>
  elapsed_ms?: number
  search_method?: string
  results_count?: number
}

export interface AnswerDelta extends PageChatEventMeta {
  content: string
}

export interface Citation {
  citation_key: string
  document_id?: string
  document_name: string
  source_anchor: SourceAnchor | Record<string, unknown>
  display_label: string
  preview_kind: string
}

export interface CitationAdded extends PageChatEventMeta {
  citation: Citation
}

export interface RunCompleted extends PageChatEventMeta {
  status: 'completed'
}

export interface RunFailed extends PageChatEventMeta {
  status: 'failed'
  error: string
}

export interface RunCancelled extends PageChatEventMeta {
  status: 'cancelled'
}

export type PageChatStreamData =
  | RunStarted
  | ProgressEvent
  | ToolStarted
  | ToolCompleted
  | AnswerDelta
  | CitationAdded
  | RunCompleted
  | RunFailed
  | RunCancelled
