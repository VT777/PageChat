import type { ModelCapability, ModelProviderModel } from '@/types/modelSettings'

export interface ProviderModelOption {
  id?: string
  capabilities?: ModelCapability[]
}

export interface ProviderConfigOption {
  provider_id: string
  provider: string
}

const CAPABILITY_ORDER: ModelCapability[] = [
  'llm',
  'vision',
  'tool_calling',
  'ocr',
  'embedding',
]

const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  llm: 'LLM',
  vision: 'Vision',
  embedding: 'Embedding',
  tool_calling: 'Tool Calling',
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
  if (explicit.length > 0) return uniqueCapabilities(explicit)

  const id = (model.id || '').toLowerCase()
  if (!id) return ['llm']
  if (id.includes('embedding') || id.includes('embed') || id.includes('bge-')) {
    return ['embedding']
  }
  if (id.includes('ocr')) {
    return uniqueCapabilities(['llm', 'vision', 'ocr'])
  }
  if (
    id.includes('vl') ||
    id.includes('vision') ||
    id.includes('gpt-4o') ||
    id.includes('gemini') ||
    id.includes('claude-3') ||
    id.includes('qvq')
  ) {
    return uniqueCapabilities(['llm', 'vision', 'tool_calling'])
  }
  return uniqueCapabilities(['llm', 'tool_calling'])
}

export function modelCapabilityBadges(model: ProviderModelOption): string[] {
  return inferModelCapabilities(model)
    .filter((capability) => capability !== 'llm' && capability !== 'tool_calling')
    .map((capability) => CAPABILITY_LABELS[capability])
}

export function buildAvailableModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): string[] {
  const remoteOptions = modelEntries(providers, providerModels, labelProvider).map(
    (entry) => entry.option,
  )
  if (remoteOptions.length > 0) return remoteOptions
  return providers.map((provider) => `${labelProvider(provider.provider)}: models not loaded`)
}

export function buildOcrModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): string[] {
  return modelEntries(providers, providerModels, labelProvider)
    .filter(({ capabilities }) =>
      capabilities.includes('ocr') || capabilities.includes('vision'),
    )
    .map(({ option }) => option)
}

export function buildParsingModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): string[] {
  return modelEntries(providers, providerModels, labelProvider)
    .filter(({ capabilities }) =>
      capabilities.includes('llm') || capabilities.includes('vision'),
    )
    .map(({ option }) => option)
}

export function buildQaModelOptions(
  providers: ProviderConfigOption[],
  providerModels: Record<string, ProviderModelOption[]>,
  labelProvider: (provider: string) => string,
): string[] {
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
    .map(({ option }) => option)
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
      .map(({ model, modelId, capabilities }) => ({
        model: model as ModelProviderModel,
        modelId,
        capabilities,
        option: `${labelProvider(provider.provider)}: ${modelId}`,
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
