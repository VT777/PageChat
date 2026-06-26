import { describe, expect, it } from 'vitest'
import { buildModelProviderRows } from './modelProviderRows'
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
      id: 'provider-openai',
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
})
