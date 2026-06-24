export type WebSearchProvider = 'anysearch'
export type WebSearchMode = 'on-demand' | 'auto'
export type WebSearchZone = 'cn' | 'intl'
export type WebSearchLanguage = 'zh-CN' | 'en'
export type WebSearchContentType = 'web' | 'news'

export interface WebSearchSettings {
  provider: WebSearchProvider
  mode: WebSearchMode
  zone: WebSearchZone
  language: WebSearchLanguage
  max_results: number
  content_types: WebSearchContentType[]
  api_key_mask: string
  updated_at?: string
}

export interface WebSearchSettingsUpdate {
  provider: WebSearchProvider
  mode: WebSearchMode
  api_key?: string
  zone: WebSearchZone
  language: WebSearchLanguage
  max_results: number
  content_types: WebSearchContentType[]
}

export function defaultWebSearchSettings(): WebSearchSettings {
  return {
    provider: 'anysearch',
    mode: 'on-demand',
    zone: 'cn',
    language: 'zh-CN',
    max_results: 5,
    content_types: ['web', 'news'],
    api_key_mask: '',
  }
}
