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
  created_at?: string
  updated_at?: string
}

export interface ModelProviderModel {
  id: string
  owned_by?: string
  created?: number
  object?: string
}

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

export interface ModelRouteMapping {
  route_slot: ModelRouteSlot | string
  provider_id: string
  model: string
  supports_vision?: boolean
  route_version?: string
}
