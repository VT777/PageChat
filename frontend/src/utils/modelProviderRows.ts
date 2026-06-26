import type { ModelProviderConfig, ModelProviderPreset } from '@/types/modelSettings'

export interface ModelProviderRow {
  id: string
  provider: string
  label: string
  iconUrl: string
  baseUrl: string
  configured: boolean
  keyMask: string
  validation: string
}

export function buildModelProviderRows(
  providers: ModelProviderConfig[],
  presets: ModelProviderPreset[],
  labelProvider: (provider: string) => string,
): ModelProviderRow[] {
  const configuredByProvider = new Map(
    providers.map((provider) => [provider.provider.toLowerCase(), provider]),
  )

  const rows = presets.map((preset) => {
    const configured = configuredByProvider.get(preset.provider.toLowerCase())
    if (configured) {
      return {
        id: configured.provider_id,
        provider: configured.provider,
        label: preset.label || labelProvider(configured.provider),
        iconUrl: preset.icon_url || `/provider-logos/${preset.provider}.svg`,
        baseUrl: configured.base_url,
        configured: true,
        keyMask: configured.api_key_mask || 'stored',
        validation: configured.validation_status || 'Configured',
      }
    }

    return {
      id: preset.provider,
      provider: preset.provider,
      label: preset.label,
      iconUrl: preset.icon_url || `/provider-logos/${preset.provider}.svg`,
      baseUrl: preset.base_url,
      configured: false,
      keyMask: '',
      validation: 'Not configured',
    }
  })

  const presetKeys = new Set(presets.map((preset) => preset.provider.toLowerCase()))
  const customProviders = providers
    .filter((provider) => !presetKeys.has(provider.provider.toLowerCase()))
    .map((provider) => ({
      id: provider.provider_id,
      provider: provider.provider,
      label: labelProvider(provider.provider),
      iconUrl: `/provider-logos/${provider.provider}.svg`,
      baseUrl: provider.base_url,
      configured: true,
      keyMask: provider.api_key_mask || 'stored',
      validation: provider.validation_status || 'Configured',
    }))

  return [...rows, ...customProviders]
}
