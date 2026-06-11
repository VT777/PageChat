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
  supports_custom_base_url: boolean
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
