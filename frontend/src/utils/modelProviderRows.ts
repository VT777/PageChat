import type { ModelProviderConfig, ModelProviderPreset } from '@/types/modelSettings'

export interface ModelProviderRow {
  id: string
  providerId: string
  provider: string
  label: string
  iconUrl: string
  baseUrl: string
  configured: boolean
  keyMask: string
  validation: string
  credentials: ModelProviderCredential[]
}

export interface ModelProviderCredential {
  providerId: string
  provider: string
  baseUrl: string
  keyMask: string
  validation: string
}

export function buildModelProviderRows(
  providers: ModelProviderConfig[],
  presets: ModelProviderPreset[],
  labelProvider: (provider: string) => string,
): ModelProviderRow[] {
  const configuredByProvider = groupProvidersByProvider(providers)

  const rows = presets.map((preset) => {
    const credentials = configuredByProvider.get(preset.provider.toLowerCase()) || []
    const primary = primaryCredential(credentials)
    if (primary) {
      return {
        id: preset.provider,
        providerId: primary.providerId,
        provider: preset.provider,
        label: preset.label || labelProvider(preset.provider),
        iconUrl: preset.icon_url || `/provider-logos/${preset.provider}.svg`,
        baseUrl: primary.baseUrl,
        configured: true,
        keyMask: primary.keyMask,
        validation: primary.validation,
        credentials,
      }
    }

    return {
      id: preset.provider,
      providerId: '',
      provider: preset.provider,
      label: preset.label,
      iconUrl: preset.icon_url || `/provider-logos/${preset.provider}.svg`,
      baseUrl: preset.base_url,
      configured: false,
      keyMask: '',
      validation: 'Not configured',
      credentials: [],
    }
  })

  const presetKeys = new Set(presets.map((preset) => preset.provider.toLowerCase()))
  const customProviders = Array.from(configuredByProvider.entries())
    .filter(([provider]) => !presetKeys.has(provider))
    .map(([provider, credentials]) => {
      const primary = primaryCredential(credentials) || credentials[0]
      return {
        id: provider,
        providerId: primary.providerId,
        provider: primary.provider,
        label: labelProvider(primary.provider),
        iconUrl: `/provider-logos/${primary.provider}.svg`,
        baseUrl: primary.baseUrl,
        configured: true,
        keyMask: primary.keyMask,
        validation: primary.validation,
        credentials,
      }
    })

  return [...rows, ...customProviders]
}

export function filterModelProviderRows(
  rows: ModelProviderRow[],
  query: string,
): ModelProviderRow[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return rows
  return rows.filter((row) =>
    [row.label, row.provider, row.baseUrl, ...row.credentials.map((credential) => credential.keyMask)]
      .some((value) => value.toLowerCase().includes(normalized)),
  )
}

function groupProvidersByProvider(providers: ModelProviderConfig[]): Map<string, ModelProviderCredential[]> {
  const groups = new Map<string, ModelProviderCredential[]>()
  for (const provider of providers) {
    const key = provider.provider.toLowerCase()
    const credentials = groups.get(key) || []
    credentials.push({
      providerId: provider.provider_id,
      provider: provider.provider,
      baseUrl: provider.base_url,
      keyMask: provider.api_key_mask || 'stored',
      validation: provider.validation_status || 'Configured',
    })
    groups.set(key, credentials)
  }
  return groups
}

function primaryCredential(credentials: ModelProviderCredential[]): ModelProviderCredential | undefined {
  return credentials.find((credential) => credential.validation === 'valid') || credentials[0]
}
