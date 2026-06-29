import { describe, expect, it } from 'vitest'
import {
  buildAvailableModelOptions,
  buildOcrModelOptions,
  buildParsingModelOptions,
  buildQaModelOptions,
  buildQaModelGroups,
  formatModelContextBadge,
  inferModelCapabilities,
  modelCapabilityBadges,
  modelOptionValue,
  providerCapabilityBadges,
  resolveProviderTestModel,
} from './modelProviderModels'

describe('model provider model helpers', () => {
  it('does not send the placeholder default model to provider tests', () => {
    expect(resolveProviderTestModel('default', [])).toBe('')
  })

  it('uses the first fetched remote model when the explicit model is empty or default', () => {
    const remoteModels = [{ id: 'qwen-plus' }, { id: 'qwen-max' }]

    expect(resolveProviderTestModel('', remoteModels)).toBe('qwen-plus')
    expect(resolveProviderTestModel(' default ', remoteModels)).toBe('qwen-plus')
  })

  it('builds task model options from fetched provider models', () => {
    const options = buildAvailableModelOptions(
      [
        { provider_id: 'dashscope-1', provider: 'dashscope' },
        { provider_id: 'deepseek-1', provider: 'deepseek' },
      ],
      {
        'dashscope-1': [{ id: 'qwen-plus' }],
        'deepseek-1': [{ id: 'deepseek-chat' }],
      },
      (provider) => provider,
    )

    expect(options.map((option) => option.label)).toEqual([
      'dashscope: qwen-plus',
      'deepseek: deepseek-chat',
    ])
  })

  it('keeps provider identity when two providers share a display label', () => {
    const options = buildAvailableModelOptions(
      [
        { provider_id: 'dash-a', provider: 'dashscope' },
        { provider_id: 'dash-b', provider: 'dashscope' },
      ],
      {
        'dash-a': [{ id: 'qwen-plus' }],
        'dash-b': [{ id: 'qwen3.7-max-2026-06-08' }],
      },
      () => 'Alibaba Cloud Bailian / Tongyi',
    )

    expect(options).toContainEqual(
      expect.objectContaining({
        value: 'dash-b::qwen3.7-max-2026-06-08',
        label: 'Alibaba Cloud Bailian / Tongyi: qwen3.7-max-2026-06-08',
        providerId: 'dash-b',
        providerLabel: 'Alibaba Cloud Bailian / Tongyi',
        modelId: 'qwen3.7-max-2026-06-08',
      }),
    )
  })

  it('uses backend capabilities only and does not infer from model ids', () => {
    expect(inferModelCapabilities({ id: 'qwen-vl-ocr-2025' })).toEqual([])
    expect(inferModelCapabilities({ id: 'text-embedding-v3' })).toEqual([])
    expect(inferModelCapabilities({ id: 'gpt-4o' })).toEqual([])
    expect(
      inferModelCapabilities({ id: 'custom-model', capabilities: ['vision', 'embedding'] }),
    ).toEqual(['vision', 'embedding'])
  })

  it('renders concise capability badges for model rows', () => {
    expect(modelCapabilityBadges({ id: 'qwen-vl-ocr' })).toEqual([])
    expect(modelCapabilityBadges({ id: 'text-embedding-v3' })).toEqual([])
    expect(modelCapabilityBadges({ id: 'plain-model', capabilities: ['llm', 'vision'] })).toEqual(['LLM', 'VISION'])
    expect(modelCapabilityBadges({ id: 'tool-model', capabilities: ['llm', 'tool_calling'] })).toEqual(['LLM', 'TOOLS'])
    expect(modelCapabilityBadges({ id: 'plain-chat', capabilities: ['llm'] })).toEqual(['LLM'])
    expect(formatModelContextBadge({ id: 'long-context', context_window: 128000 })).toBe('Context 128K')
    expect(formatModelContextBadge({ id: 'schema-context', model_properties: { context_size: 200000 } })).toBe('Context 200K')
  })

  it('derives provider capability badges from configured provider models only', () => {
    expect(providerCapabilityBadges([])).toEqual([])
    expect(providerCapabilityBadges([
      { id: 'qwen-plus', capabilities: ['llm', 'tool_calling'], context_window: 32768 },
      { id: 'qwen-vl-max', capabilities: ['llm', 'vision', 'tool_calling'], context_window: 128000 },
      { id: 'text-embedding-v3', capabilities: ['embedding'] },
    ])).toEqual(['LLM', 'VISION', 'TOOLS', 'EMBEDDING', '128K Context'])
  })

  it('filters task model options by capability', () => {
    const providers = [
      { provider_id: 'dashscope-1', provider: 'dashscope' },
      { provider_id: 'deepseek-1', provider: 'deepseek' },
    ]
    const models = {
      'dashscope-1': [
        { id: 'qwen-plus', capabilities: ['llm', 'tool_calling'] },
        { id: 'qwen-vl-ocr-2025', capabilities: ['llm', 'vision', 'ocr'] },
        { id: 'text-embedding-v3', capabilities: ['embedding'] },
      ],
      'deepseek-1': [{ id: 'deepseek-chat', capabilities: ['llm'] }],
    }
    const labelProvider = (provider: string) => provider

    expect(buildOcrModelOptions(providers, models, labelProvider).map((option) => option.label)).toEqual([
      'dashscope: qwen-vl-ocr-2025',
    ])
    expect(buildParsingModelOptions(providers, models, labelProvider).map((option) => option.label)).toEqual([
      'dashscope: qwen-plus',
      'dashscope: qwen-vl-ocr-2025',
      'deepseek: deepseek-chat',
    ])
    expect(buildQaModelOptions(providers, models, labelProvider).map((option) => option.label)).toEqual([
      'dashscope: qwen-vl-ocr-2025',
      'dashscope: qwen-plus',
      'deepseek: deepseek-chat',
    ])
  })

  it('filters disabled provider models out of task selectors', () => {
    const providers = [
      { provider_id: 'dashscope-1', provider: 'dashscope' },
      { provider_id: 'deepseek-1', provider: 'deepseek' },
    ]
    const models = {
      'dashscope-1': [
        { id: 'qwen-plus', capabilities: ['llm', 'tool_calling'] },
        { id: 'qwen-vl-ocr-2025', capabilities: ['llm', 'vision', 'ocr'] },
      ],
      'deepseek-1': [{ id: 'deepseek-chat', capabilities: ['llm'] }],
    }
    const disabled = new Set([
      modelOptionValue('dashscope-1', 'qwen-vl-ocr-2025'),
      modelOptionValue('deepseek-1', 'deepseek-chat'),
    ])
    const labelProvider = (provider: string) => provider

    expect(buildOcrModelOptions(providers, models, labelProvider, disabled)).toEqual([])
    expect(buildParsingModelOptions(providers, models, labelProvider, disabled).map((option) => option.value)).toEqual([
      modelOptionValue('dashscope-1', 'qwen-plus'),
    ])
    expect(buildQaModelGroups(providers, models, labelProvider, disabled)).toEqual([
      expect.objectContaining({
        providerId: 'dashscope-1',
        models: [expect.objectContaining({ modelId: 'qwen-plus' })],
      }),
    ])
  })

  it('builds qa model groups by provider with backend capability metadata', () => {
    const groups = buildQaModelGroups(
      [
        { provider_id: 'dashscope-1', provider: 'dashscope' },
        { provider_id: 'deepseek-1', provider: 'deepseek' },
      ],
      {
        'dashscope-1': [
          { id: 'qwen-vl-max', capabilities: ['llm', 'vision'], context_window: 128000 },
          { id: 'qwen-plus', capabilities: ['llm'], context_window: 32768 },
        ],
        'deepseek-1': [{ id: 'deepseek-chat', capabilities: ['llm'] }],
      },
      (provider) => provider === 'dashscope' ? 'Alibaba Cloud Bailian / Tongyi' : provider,
    )

    expect(groups[0].providerLabel).toBe('Alibaba Cloud Bailian / Tongyi')
    expect(groups[0].models[0].capabilities).toContain('vision')
    expect(groups[1].models[0].modelId).toBe('deepseek-chat')
  })
})
