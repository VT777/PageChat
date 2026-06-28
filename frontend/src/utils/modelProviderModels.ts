import type { ModelCapability, ModelProviderModel } from '@/types/modelSettings'

export interface ProviderModelOption {
  id?: string
  capabilities?: ModelCapability[]
}

export interface ProviderConfigOption {
  provider_id: string
  provider: string
}

export interface ModelSelectOption {
  value: string
  label: string
  providerId: string
  providerLabel: string
  modelId: string
  capabilities: ModelCapability[]
}

const CAPABILITY_ORDER: ModelCapability[] = [
  'llm',
  'vision',
  'tool_calling',
  'reasoning',
  'ocr',
  'embedding',
]

const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  llm: 'LLM',
  vision: 'VISION',
  embedding: 'Embedding',
  tool_calling: 'CHAT',
  reasoning: 'Thinking',
  ocr: 'OCR',
}

export function resolveProviderTestModel(
  explicitModel: string,
  remoteModels: ProviderModelOption[],
): string {
  const trimmed = explicitModel.trim()
  if (trimmed && trimmed.toLowerCase() !== 'default') return trimmed
  return remoteModels.find((model) => model.id?.trim())?.id?.trim() || ''
}

export function inferModelCapabilities(model: ProviderModelOption): ModelCapability[] {
  const explicit = (model.capabilities || []).filter(isModelCapability)

  const id = (model.id || '').toLowerCase()
  if (!id) return explicit.length > 0 ? uniqueCapabilities(explicit) : ['llm']
  if (id.includes('embedding') || id.includes('embed') || id.includes('bge-')) {
    return ['embedding']
  }
  const inferred: ModelCapability[] = []
  const isOcrModel = id.includes('ocr')
  if (isOcrModel) {
    inferred.push('llm', 'vision', 'ocr')
  }
  if (!isOcrModel && (
    id.includes('vl') ||
    id.includes('vision') ||
    id.includes('gpt-4o') ||
    id.includes('gemini') ||
    id.includes('claude-3') ||
    id.includes('qvq')
  )) {
    inferred.push('llm', 'vision', 'tool_calling')
  }
  if (
    id.includes('qwen3') ||
    id.includes('qwen-3') ||
    id.includes('qvq') ||
    id.includes('qwq') ||
    id.includes('r1') ||
    id.includes('reason') ||
    id.includes('thinking') ||
    id.includes('o1') ||
    id.includes('o3')
  ) {
    inferred.push('llm', 'tool_calling', 'reasoning')
  }
  if (explicit.length > 0 || inferred.length > 0) return uniqueCapabilities([...explicit, ...inferred])
  return uniqueCapabilities(['llm', 'tool_calling'])
}

export function modelCapabilityBadges(model: ProviderModelOption): string[] {
  return inferModelCapabilities(model)
    .filter((capability) => capability !== 'reasoning')
    .map((capability) => CAPABILITY_LABELS[capability].toUpperCase())
}

export function formatModelContextBadge(model: ProviderModelOption): string {
  const contextWindow = typeof (model as any).context_window === 'number'
    ? (model as any).context_window
    : 0
  if (!contextWindow || contextWindow <= 0) return ''
  const rounded = contextWindow >= 1000
    ? `${contextWindow % 1000 === 0 ? contextWindow / 1000 : Math.round(contextWindow / 1000)}K`
    : String(contextWindow)
  return `Context ${rounded}`
}

export function providerCapabilityBadges(models: ProviderModelOption[]): string[] {
  if (!models.length) return []
  const capabilities = new Set<ModelCapability>()
  let largestContextWindow = 0
  for (const model of models) {
    inferModelCapabilities(model).forEach((capability) => capabilities.add(capability))
    const contextWindow = typeof (model as any).context_window === 'number'
      ? (model as any).context_window
      : 0
    largestContextWindow = Math.max(largestContextWindow, contextWindow)
  }
  const badges = CAPABILITY_ORDER
    .filter((capability) => capabilities.has(capability))
    .filter((capability) => capability !== 'reasoning' && capability !== 'ocr')
    .map((capability) => CAPABILITY_LABELS[capability].toUpperCase())
  if (largestContextWindow > 0) {
    const value = largestContextWindow >= 1000
      ? `${largestContextWindow % 1000 === 0 ? largestContextWindow / 1000 : Math.round(largestContextWindow / 1000)}K`
      : String(largestContextWindow)
    badges.push(`${value} Context`)
  }
  return badges
}

export function buildAvailableModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): ModelSelectOption[] {
  const remoteOptions = modelEntries(providers, providerModels, labelProvider)
  if (remoteOptions.length > 0) return remoteOptions
  return providers.map((provider) => {
    const providerLabel = labelProvider(provider.provider)
    return {
      value: modelOptionValue(provider.provider_id, ''),
      label: `${providerLabel}: models not loaded`,
      providerId: provider.provider_id,
      providerLabel,
      modelId: '',
      capabilities: [],
    }
  })
}

export function buildOcrModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): ModelSelectOption[] {
  return modelEntries(providers, providerModels, labelProvider)
    .filter(({ capabilities }) =>
      capabilities.includes('ocr') || capabilities.includes('vision'),
    )
}

export function buildParsingModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): ModelSelectOption[] {
  return modelEntries(providers, providerModels, labelProvider)
    .filter(({ capabilities }) =>
      capabilities.includes('llm') || capabilities.includes('vision'),
    )
}

export function buildQaModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): ModelSelectOption[] {
  return modelEntries(providers, providerModels, labelProvider)
    .filter(({ capabilities }) =>
      capabilities.includes('llm') || capabilities.includes('vision'),
    )
    .map((entry, index) => ({ ...entry, index }))
    .sort((a, b) => {
      const priorityA = a.capabilities.includes('vision') ? 0 : 1
      const priorityB = b.capabilities.includes('vision') ? 0 : 1
      return priorityA - priorityB || a.index - b.index
    })
}

export function modelOptionValue(providerId: string, modelId: string): string {
  return `${providerId}::${modelId}`
}

export function legacyModelSelectOption(label: string): ModelSelectOption {
  const separator = label.indexOf(': ')
  return {
    value: label,
    label,
    providerId: '',
    providerLabel: separator >= 0 ? label.slice(0, separator) : '',
    modelId: separator >= 0 ? label.slice(separator + 2).trim() : label.trim(),
    capabilities: [],
  }
}

function modelEntries(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
) {
  return providers.flatMap((provider) =>
    (providerModels[provider.provider_id] || [])
      .map((model) => ({
        model,
        modelId: model.id?.trim() || '',
        capabilities: inferModelCapabilities(model),
      }))
      .filter(({ modelId }) => Boolean(modelId))
      .map(({ model, modelId, capabilities }) => {
        const providerLabel = labelProvider(provider.provider)
        return {
          model: model as ModelProviderModel,
          providerId: provider.provider_id,
          providerLabel,
          modelId,
          capabilities,
          value: modelOptionValue(provider.provider_id, modelId),
          label: `${providerLabel}: ${modelId}`,
        }
      })
      .map(({ model, providerId, providerLabel, modelId, capabilities, value, label }) => ({
        model,
        providerId,
        providerLabel,
        modelId,
        capabilities,
        value,
        label,
      })),
  )
}

function uniqueCapabilities(capabilities: ModelCapability[]): ModelCapability[] {
  const set = new Set(capabilities)
  return CAPABILITY_ORDER.filter((capability) => set.has(capability))
}

function isModelCapability(value: string): value is ModelCapability {
  return CAPABILITY_ORDER.includes(value as ModelCapability)
}
