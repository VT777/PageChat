import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

describe('SettingsModal model provider contract', () => {
  it('does not send the placeholder default model when testing a provider', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).not.toContain("providerForm.value.testModel || 'default'")
  })
})
