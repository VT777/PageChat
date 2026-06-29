import { describe, expect, it } from 'vitest'
import { buildModelProviderRows, filterModelProviderRows } from './modelProviderRows'
import type { ModelProviderConfig, ModelProviderPreset } from '@/types/modelSettings'

const presets: ModelProviderPreset[] = [
  {
    provider: 'openai',
    label: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    supports_custom_base_url: false,
  },
  {
    provider: 'dashscope',
    label: 'Alibaba Cloud Bailian / Tongyi',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    supports_custom_base_url: false,
  },
  {
    provider: 'deepseek',
    label: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    supports_custom_base_url: true,
  },
]

describe('model provider rows', () => {
  it('keeps unconfigured presets visible after one provider is configured', () => {
    const configured: ModelProviderConfig[] = [
      {
        provider_id: 'provider-openai',
        provider: 'openai',
        base_url: 'https://api.openai.com/v1',
        api_key_mask: 'sk-...abcd',
        validation_status: 'untested',
      },
    ]

    const rows = buildModelProviderRows(configured, presets, (provider) => provider)

    expect(rows.map((row) => row.provider)).toEqual(['openai', 'dashscope', 'deepseek'])
    expect(rows.find((row) => row.provider === 'openai')).toMatchObject({
      id: 'openai',
      providerId: 'provider-openai',
      configured: true,
      keyMask: 'sk-...abcd',
    })
    expect(rows.find((row) => row.provider === 'dashscope')).toMatchObject({
      id: 'dashscope',
      iconUrl: '/provider-logos/dashscope.svg',
      configured: false,
      validation: 'Not configured',
    })
  })

  it('groups multiple API keys under one provider row', () => {
    const configured: ModelProviderConfig[] = [
      {
        provider_id: 'deepseek-key-1',
        provider: 'deepseek',
        base_url: 'https://api.deepseek.com',
        api_key_mask: 'sk-...1111',
        validation_status: 'valid',
      },
      {
        provider_id: 'deepseek-key-2',
        provider: 'deepseek',
        base_url: 'https://api.deepseek.com',
        api_key_mask: 'sk-...2222',
        validation_status: 'untested',
      },
    ]

    const rows = buildModelProviderRows(configured, presets, (provider) => provider)
    const deepseek = rows.find((row) => row.provider === 'deepseek')

    expect(rows.map((row) => row.provider)).toEqual(['openai', 'dashscope', 'deepseek'])
    expect(deepseek).toMatchObject({
      id: 'deepseek',
      configured: true,
      providerId: 'deepseek-key-1',
      keyMask: 'sk-...1111',
      validation: 'valid',
    })
    expect(deepseek?.credentials).toEqual([
      expect.objectContaining({ providerId: 'deepseek-key-1', keyMask: 'sk-...1111' }),
      expect.objectContaining({ providerId: 'deepseek-key-2', keyMask: 'sk-...2222' }),
    ])
  })

  it('filters providers by label, provider id, and base URL', () => {
    const rows = buildModelProviderRows([], presets, (provider) => provider)

    expect(filterModelProviderRows(rows, 'ali').map((row) => row.provider)).toEqual(['dashscope'])
    expect(filterModelProviderRows(rows, 'deepseek').map((row) => row.provider)).toEqual(['deepseek'])
    expect(filterModelProviderRows(rows, 'dashscope.aliyuncs').map((row) => row.provider)).toEqual([
      'dashscope',
    ])
    expect(filterModelProviderRows(rows, '').map((row) => row.provider)).toEqual([
      'openai',
      'dashscope',
      'deepseek',
    ])
  })
})
