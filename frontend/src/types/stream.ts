/**
 * SSE 事件类型定义
 * 基于 PageIndex 官方流程
 */

// SSE 事件名称
export type StreamEventName =
  | 'conversation'
  | 'thinking'
  | 'content'
  | 'tool_call'
  | 'tool_result'
  | 'done'

// 通用信封
export interface StreamEnvelope<TData = Record<string, unknown>> {
  event: StreamEventName
  data: TData
}

// thinking 事件 - 模型思考过程（流式）
export interface ThinkingData {
  content: string
  step: number
}

// content 事件 - 最终答案内容（流式）
export interface ContentData {
  content: string
}

// tool_call 事件 - 工具调用
export interface ToolCallData {
  tool_name: string
  arguments: Record<string, unknown>
  step: number
}

// tool_result 事件 - 工具返回结果
export interface ToolResultData {
  tool_name: string
  result: Record<string, unknown>
  step: number
}

// done 事件 - 完成
export interface DoneData {
  conversation_id?: string
  tool_results?: Array<{
    tool_name: string
    result: Record<string, unknown>
  }>
}
