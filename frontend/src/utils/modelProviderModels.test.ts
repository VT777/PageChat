import { describe, expect, it } from 'vitest'
import {
  buildAvailableModelOptions,
  buildOcrModelOptions,
  buildParsingModelOptions,
  buildQaModelOptions,
  inferModelCapabilities,
  modelCapabilityBadges,
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

  it('infers model capabilities from model metadata and ids', () => {
    expect(inferModelCapabilities({ id: 'qwen-vl-ocr-2025' })).toEqual([
      'llm',
      'vision',
      'ocr',
    ])
    expect(inferModelCapabilities({ id: 'text-embedding-v3' })).toEqual(['embedding'])
    expect(inferModelCapabilities({ id: 'gpt-4o' })).toEqual(['llm', 'vision', 'tool_calling'])
    expect(
      inferModelCapabilities({ id: 'custom-model', capabilities: ['vision', 'embedding'] }),
    ).toEqual(['vision', 'embedding'])
  })

  it('renders concise capability badges for model rows', () => {
    expect(modelCapabilityBadges({ id: 'qwen-vl-ocr' })).toEqual(['Vision', 'OCR'])
    expect(modelCapabilityBadges({ id: 'text-embedding-v3' })).toEqual(['Embedding'])
  })

  it('filters task model options by capability', () => {
    const providers = [
      { provider_id: 'dashscope-1', provider: 'dashscope' },
      { provider_id: 'deepseek-1', provider: 'deepseek' },
    ]
    const models = {
      'dashscope-1': [
        { id: 'qwen-plus' },
        { id: 'qwen-vl-ocr-2025' },
        { id: 'text-embedding-v3' },
      ],
      'deepseek-1': [{ id: 'deepseek-chat' }],
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
})
