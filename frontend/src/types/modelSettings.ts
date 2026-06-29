export type ModelRouteSlot =
  | 'general_chat'
  | 'document_qa'
  | 'query_expansion'
  | 'indexing'
  | 'vision'

export interface ModelProviderPreset {
  provider: string
  label: string
  base_url: string
  icon_url?: string
  supports_custom_base_url: boolean
  supports_responses_api?: boolean
  supports_reasoning_effort?: boolean
  supports_reasoning_summary?: boolean
}

export interface ModelProviderConfig {
  provider_id: string
  provider: string
  base_url: string
  api_key_mask?: string
  validation_status?: string
  supports_responses_api?: boolean
  supports_reasoning_effort?: boolean
  supports_reasoning_summary?: boolean
  created_at?: string
  updated_at?: string
}

export interface ModelProviderModel {
  id: string
  owned_by?: string
  created?: number
  object?: string
  capabilities?: ModelCapability[]
  capability_source?: 'provider_metadata' | 'dify_schema' | 'litellm_catalog' | 'custom' | 'known_catalog' | 'inferred' | 'unknown' | string
  features?: ModelCapability[]
  model_type?: string
  model_properties?: {
    mode?: string
    context_size?: number
    max_output_tokens?: number
    [key: string]: unknown
  }
  supports_vision?: boolean
  supports_tool_calling?: boolean
  supports_reasoning?: boolean
  supports_embedding?: boolean
  supports_ocr?: boolean
  context_window?: number | null
  max_output_tokens?: number | null
}

export type ModelCapability = 'llm' | 'vision' | 'embedding' | 'tool_calling' | 'reasoning' | 'ocr'

export interface ModelProviderModelsResponse {
  provider_id: string
  provider: string
  base_url: string
  models: ModelProviderModel[]
  source: 'remote' | string
}

export interface ModelProviderInput {
  provider: string
  base_url: string
  api_key: string
}

export interface ModelProviderUpdateInput {
  provider: string
  base_url: string
  api_key?: string
}

export interface ModelProviderCustomModelInput {
  model: string
  display_name?: string
  model_type?: string
  endpoint_model_name?: string
  capabilities?: ModelCapability[]
  context_window?: number | null
  max_output_tokens?: number | null
}

export interface ModelRouteMapping {
  route_slot: ModelRouteSlot | string
  provider_id: string
  model: string
  supports_streaming?: boolean
  supports_tool_calling?: boolean
  supports_vision?: boolean
  supports_structured_output?: boolean
  supports_responses_api?: boolean
  route_version?: string
}
