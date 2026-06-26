import { describe, expect, it } from 'vitest'
import { buildAvailableModelOptions, resolveProviderTestModel } from './modelProviderModels'

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

    expect(options).toEqual(['dashscope: qwen-plus', 'deepseek: deepseek-chat'])
  })
})
