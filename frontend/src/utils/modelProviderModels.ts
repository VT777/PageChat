export interface ProviderModelOption {
  id?: string
}

export interface ProviderConfigOption {
  provider_id: string
  provider: string
}

export function resolveProviderTestModel(
  explicitModel: string,
  remoteModels: ProviderModelOption[],
): string {
  const trimmed = explicitModel.trim()
  if (trimmed && trimmed.toLowerCase() !== 'default') return trimmed
  return remoteModels.find((model) => model.id?.trim())?.id?.trim() || ''
}

export function buildAvailableModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): string[] {
  const remoteOptions = providers.flatMap((provider) =>
    (providerModels[provider.provider_id] || [])
      .map((model) => model.id?.trim())
      .filter((model): model is string => Boolean(model))
      .map((model) => `${labelProvider(provider.provider)}: ${model}`),
  )
  if (remoteOptions.length > 0) return remoteOptions
  return providers.map((provider) => `${labelProvider(provider.provider)}: 未加载模型`)
}
