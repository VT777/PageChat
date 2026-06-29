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

  it('shows saved API key mask state and treats loaded models as provider connection', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('apiKeyPlaceholder')
    expect(source).toContain('providerKeyMask')
    expect(source).toContain('fetchProviderModels(savedProviderId')
    expect(source).toContain('testingStateForProvider')
    expect(source).not.toContain('autoTestSavedProvider')
  })

  it('renders model capabilities inside a scrollable available-models panel', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('model-list-body')
    expect(source).toContain('modelCapabilityBadges')
    expect(source).toContain('model-capabilities')
  })

  it('renders Dify-like model metadata for context, output and thinking capability', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')
    const modelProviderModelsSource = readFileSync(
      new URL('../../utils/modelProviderModels.ts', import.meta.url),
      'utf-8',
    )

    expect(source).toContain('modelMetaBadges')
    expect(source).toContain('model-meta-badge')
    expect(source).toContain('model-compact-row')
    expect(source).toContain('model-count-line')
    expect(source).toContain('formatTokenWindow')
    expect(modelProviderModelsSource).toContain("reasoning: 'Thinking'")
  })

  it('uses Dify-like provider cards and modal configuration flows instead of inline credential panels', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('provider-card-unconfigured')
    expect(source).toContain('provider-card-configured')
    expect(source).toContain('provider-config-summary')
    expect(source).toContain('openProviderCredentialDialog')
    expect(source).toContain('openCompatibleModelDialog')
    expect(source).toContain('provider-config-dialog')
    expect(source).toContain('providerModelBadges')
    expect(source).toContain('provider-ready-dot')
    expect(source).toContain('settingsApi.saveModelProviderCustomModel')
    expect(source).toContain('collapsedProviderModels')
    expect(source).toContain('toggleProviderModels')
    expect(source).toContain('deleteProviderCredential')
    expect(source).toContain('providerCredentialList')
    expect(source).toContain('API 密钥授权配置')
    expect(source).toContain('添加模型')
    expect(source).not.toContain('class="credential-panel"')
    expect(source).not.toContain('<span>Chat</span>')
  })

  it('uses an actionable provider configuration area instead of an inert chevron button', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('provider-config-summary')
    expect(source).toContain('provider-config-button')
    expect(source).toContain('openProviderCredentialDialog(provider)')
    expect(source).not.toContain('provider-more-button')
  })

  it('aligns model row icons to the same provider logo system', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('model-provider-logo')
    expect(source).toContain(':src="provider.iconUrl"')
  })

  it('uses task-specific model option lists and persists route settings', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('ocrModelOptions')
    expect(source).toContain('parsingModelOptions')
    expect(source).toContain('qaModelGroups')
    expect(source).toContain('loadFunctionalRoutes')
    expect(source).toContain('saveFunctionalRoutes')
    expect(source).toContain('settingsApi.listModelRoutes')
    expect(source).toContain('settingsApi.saveModelRoutes')
  })

  it('renders QA model selector grouped by provider with backend capability tags', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('v-for="group in qaModelGroups"')
    expect(source).toContain('v-for="model in group.models"')
    expect(source).toContain('qa-model-groups')
    expect(source).toContain('qa-model-row')
    expect(source).toContain('modelCapabilityBadges(model)')
    expect(source).toContain('图片页将使用 OCR 文本证据')
    expect(source).not.toContain('v-for="model in qaModelOptions"')
  })

  it('lets provider model rows disable models and hides disabled models from task selectors', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('disabledProviderModelKeys')
    expect(source).toContain('toggleProviderModelEnabled')
    expect(source).toContain('isProviderModelEnabled')
    expect(source).toContain('@click.stop="toggleProviderModelEnabled')
    expect(source).toContain('disabled: !isProviderModelEnabled')
    expect(source).toContain('disabledProviderModelKeys.value')
  })

  it('renders QA model options with the same compact model row structure as provider models', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('providerIconForModelOption')
    expect(source).toContain('providerInitialForModelOption')
    expect(source).toContain('class="model-row qa-model-row"')
    expect(source).toContain('model-provider-logo')
    expect(source).toContain('model-inline-main')
    expect(source).not.toContain('qa-model-main')
  })

  it('does not expose hard-coded example models as selectable route options', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).not.toContain("model: 'OpenAI Compatible: gpt-4.1'")
    expect(source).not.toContain("fallbackModelOptions(['OpenAI Compatible: gpt-4.1'")
    expect(source).not.toContain("fallbackModelOptions(['OpenAI Compatible: gpt-4o'")
    expect(source).not.toContain('function fallbackModelOptions')
  })

  it('wires the language selector to the global interface language preference', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain("import { useI18n }")
    expect(source).toContain('languageOptions')
    expect(source).toContain('v-model="language"')
    expect(source).toContain('@change="setLanguage(language)"')
    expect(source).toContain("settingsNavLabel(section.id)")
  })

  it('keeps the provider search input visually contained in its rounded parent', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).toContain('.provider-search:focus-within')
    expect(source).toContain('box-sizing: border-box;')
    expect(source).toContain('overflow: hidden;')
    expect(source).toContain('background: transparent;')
    expect(source).toContain('box-shadow: none;')
    expect(source).toContain('width: 100%;')
  })

  it('does not render QA thinking controls in settings', () => {
    const source = readFileSync(new URL('./SettingsModal.vue', import.meta.url), 'utf-8')

    expect(source).not.toContain('qaThinkingOptions')
    expect(source).not.toContain('qaSettings.thinkingMode')
    expect(source).not.toContain('settingsApi.getQaSettings')
    expect(source).not.toContain('settingsApi.updateQaSettings')
  })
})
