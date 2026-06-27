import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

describe('SettingsModal model provider contract', () => {
  it('does not send the placeholder default model when testing a provider', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).not.toContain("providerForm.value.testModel || 'default'")
  })

  it('binds provider search and renders the filtered provider rows', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('providerSearchQuery')
    expect(source).toContain('v-model="providerSearchQuery"')
    expect(source).toContain('filteredProviderRows')
    expect(source).toContain('v-for="provider in filteredProviderRows"')
  })

  it('keeps provider-level capability tags and manual test model fields out of the UI', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).not.toContain('class="capability-row"')
    expect(source).not.toContain('providerForm.testModel')
    expect(source).not.toContain('testModel:')
    expect(source).not.toContain('TestTube2')
  })

  it('shows saved API key mask state and auto-tests providers after save', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('apiKeyPlaceholder')
    expect(source).toContain('providerKeyMask')
    expect(source).toContain('autoTestSavedProvider')
    expect(source).toContain('testingStateForProvider')
  })

  it('renders model capabilities inside a scrollable available-models panel', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('model-list-body')
    expect(source).toContain('modelCapabilityBadges')
    expect(source).toContain('model-capabilities')
  })

  it('uses task-specific model option lists and persists route settings', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('ocrModelOptions')
    expect(source).toContain('parsingModelOptions')
    expect(source).toContain('qaModelOptions')
    expect(source).toContain('loadFunctionalRoutes')
    expect(source).toContain('saveFunctionalRoutes')
    expect(source).toContain('settingsApi.listModelRoutes')
    expect(source).toContain('settingsApi.saveModelRoutes')
  })

  it('renders QA thinking controls and persists them through settings API', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('qaThinkingOptions')
    expect(source).toContain('qaSettings.thinkingMode')
    expect(source).toContain('settingsApi.getQaSettings')
    expect(source).toContain('settingsApi.updateQaSettings')
  })
})
