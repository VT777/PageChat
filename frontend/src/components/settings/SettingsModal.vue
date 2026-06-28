<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Globe,
  Image,
  KeyRound,
  ListTree,
  Loader2,
  MessageSquare,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  User,
  X,
} from 'lucide-vue-next'
import { settingsApi } from '@/api'
import { useUserStore } from '@/stores/user'
import type { ModelProviderConfig, ModelProviderModel, ModelProviderPreset, ModelRouteMapping } from '@/types/modelSettings'
import {
  buildOcrModelOptions,
  buildParsingModelOptions,
  buildQaModelOptions,
  inferModelCapabilities,
  legacyModelSelectOption,
  modelCapabilityBadges,
  modelOptionValue,
  type ModelSelectOption,
} from '@/utils/modelProviderModels'
import { buildModelProviderRows, filterModelProviderRows } from '@/utils/modelProviderRows'
import {
  defaultWebSearchSettings,
  type WebSearchContentType,
  type WebSearchSettings,
} from '@/types/webSearchSettings'
import {
  PARSING_BATCH_CONCURRENCY_SETTING,
  PARSE_MODE_OPTIONS,
  SETTINGS_NAV_SECTIONS,
  WEB_SEARCH_CONTENT_TYPE_OPTIONS,
  WEB_SEARCH_LANGUAGE_OPTIONS,
  WEB_SEARCH_MODE_OPTIONS,
  WEB_SEARCH_PROVIDER_OPTIONS,
  WEB_SEARCH_ZONE_OPTIONS,
} from '@/ui/pagechatContracts'

type SectionId = typeof SETTINGS_NAV_SECTIONS.primary[number]['id'] | typeof SETTINGS_NAV_SECTIONS.footer[number]['id']
type QaThinkingMode = 'off' | 'auto' | 'on'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const router = useRouter()
const userStore = useUserStore()
const activeSection = ref<SectionId>('providers')
const providers = ref<ModelProviderConfig[]>([])
const presets = ref<ModelProviderPreset[]>([])
const loadingProviders = ref(false)
const savingProvider = ref(false)
const testingProviderId = ref<string | null>(null)
const loadingModelProviderId = ref<string | null>(null)
const providerSearchQuery = ref('')
const providerMessage = ref('')
const providerError = ref('')
const expandedProviderId = ref<string | null>(null)
const providerModels = ref<Record<string, ModelProviderModel[]>>({})
const providerModelErrors = ref<Record<string, string>>({})
const providerTestMessages = ref<Record<string, string>>({})
const functionalRoutes = ref<Record<string, ModelRouteMapping>>({})
const loadingFunctionalRoutes = ref(false)
const savingFunctionalRoutes = ref(false)
const functionalRouteMessage = ref('')
const functionalRouteError = ref('')
const webSearchSettings = ref<WebSearchSettings>(defaultWebSearchSettings())
const webSearchApiKey = ref('')
const loadingWebSearchSettings = ref(false)
const savingWebSearchSettings = ref(false)
const webSearchMessage = ref('')
const webSearchError = ref('')
const loadingQaSettings = ref(false)
const savingQaSettings = ref(false)
const qaSettingsMessage = ref('')
const qaSettingsError = ref('')

const providerForm = ref({
  providerId: '',
  credentialName: 'Default credential',
  provider: 'openai_compatible',
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
})

const ocrSettings = ref({
  model: '',
  concurrency: 3,
  vlmPrompt: '请只根据页面图像识别版面结构、表格和图片语义，不要编造不可见内容。',
})

const parsingSettings = ref({
  model: '',
  mode: 'smart',
  batchParseConcurrency: PARSING_BATCH_CONCURRENCY_SETTING.defaultValue,
})

const qaSettings = ref({
  model: '',
  thinkingMode: 'off' as QaThinkingMode,
})

const qaThinkingOptions: Array<{ id: QaThinkingMode; label: string; description: string }> = [
  {
    id: 'off',
    label: '关闭',
    description: '默认关闭模型原生 thinking，优先保持响应轻快、输出干净。',
  },
  {
    id: 'auto',
    label: '自动',
    description: '允许支持的供应商自行启用 thinking，适合复杂文档推理。',
  },
  {
    id: 'on',
    label: '开启',
    description: '明确允许原生 thinking；不支持的模型会按供应商兼容行为处理。',
  },
]

const iconMap = {
  Globe,
  Image,
  ListTree,
  MessageSquare,
  Settings2,
  SlidersHorizontal,
  User,
}

const providerRows = computed(() => {
  return buildModelProviderRows(
    providers.value,
    presets.value.length > 0 ? presets.value : defaultProviders(),
    providerLabel,
  )
})

const filteredProviderRows = computed(() =>
  filterModelProviderRows(providerRows.value, providerSearchQuery.value),
)

const ocrModelOptions = computed(() =>
  ensureModelOptions(
    buildOcrModelOptions(providers.value, providerModels.value, providerLabel),
    ocrSettings.value.model,
  ),
)

const parsingModelOptions = computed(() =>
  ensureModelOptions(
    buildParsingModelOptions(providers.value, providerModels.value, providerLabel),
    parsingSettings.value.model,
  ),
)

const qaModelOptions = computed(() =>
  ensureModelOptions(
    buildQaModelOptions(providers.value, providerModels.value, providerLabel),
    qaSettings.value.model,
  ),
)

function navIcon(icon: string) {
  return iconMap[icon as keyof typeof iconMap] || Settings2
}

function providerLabel(provider: string) {
  const normalized = provider.toLowerCase()
  if (normalized.includes('openai') && normalized.includes('compatible')) return 'OpenAI Compatible'
  if (normalized.includes('dashscope') || normalized.includes('tongyi') || normalized.includes('aliyun')) return 'Alibaba Cloud Bailian / Tongyi'
  if (normalized.includes('deepseek')) return 'DeepSeek'
  if (normalized.includes('moonshot') || normalized.includes('kimi')) return 'Moonshot AI / Kimi'
  if (normalized.includes('zhipu')) return 'Zhipu AI'
  if (normalized.includes('siliconflow')) return 'SiliconFlow'
  if (normalized.includes('volcengine') || normalized.includes('ark')) return 'Volcengine Ark'
  if (normalized.includes('openrouter')) return 'OpenRouter'
  if (normalized.includes('openai')) return 'OpenAI'
  if (normalized.includes('anthropic')) return 'Anthropic'
  if (normalized.includes('gemini') || normalized.includes('google')) return 'Google Gemini'
  if (normalized.includes('azure')) return 'Azure OpenAI'
  if (normalized.includes('ollama')) return 'Ollama'
  return provider
}

function providerInitial(label: string) {
  if (label === 'OpenAI') return '◎'
  if (label.includes('Alibaba')) return 'Ali'
  if (label === 'DeepSeek') return 'DS'
  if (label.includes('Kimi')) return 'Ki'
  if (label === 'Zhipu AI') return 'Z'
  if (label === 'SiliconFlow') return 'SF'
  if (label === 'Volcengine Ark') return 'Ark'
  if (label === 'OpenRouter') return 'OR'
  if (label === 'Anthropic') return 'A'
  if (label === 'Google Gemini') return 'G'
  if (label === 'Azure OpenAI') return 'Az'
  if (label === 'Ollama') return 'Ol'
  return 'OC'
}

function hideBrokenLogo(event: Event) {
  const target = event.currentTarget
  if (target instanceof HTMLImageElement) {
    target.hidden = true
  }
}

function defaultProviders(): ModelProviderPreset[] {
  return [
    { provider: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', icon_url: '/provider-logos/openai.svg', supports_custom_base_url: false },
    { provider: 'dashscope', label: 'Alibaba Cloud Bailian / Tongyi', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', icon_url: '/provider-logos/dashscope.svg', supports_custom_base_url: false },
    { provider: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com', icon_url: '/provider-logos/deepseek.svg', supports_custom_base_url: true },
    { provider: 'moonshot', label: 'Moonshot AI / Kimi', base_url: 'https://api.moonshot.cn/v1', icon_url: '/provider-logos/moonshot.svg', supports_custom_base_url: true },
    { provider: 'zhipuai', label: 'Zhipu AI', base_url: 'https://open.bigmodel.cn/api/paas/v4', icon_url: '/provider-logos/zhipuai.svg', supports_custom_base_url: true },
    { provider: 'siliconflow', label: 'SiliconFlow', base_url: 'https://api.siliconflow.cn/v1', icon_url: '/provider-logos/siliconflow.svg', supports_custom_base_url: true },
    { provider: 'volcengine_ark', label: 'Volcengine Ark', base_url: 'https://ark.cn-beijing.volces.com/api/v3', icon_url: '/provider-logos/volcengine_ark.svg', supports_custom_base_url: true },
    { provider: 'openrouter', label: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1', icon_url: '/provider-logos/openrouter.svg', supports_custom_base_url: true },
    { provider: 'google_gemini', label: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', icon_url: '/provider-logos/google_gemini.svg', supports_custom_base_url: true },
    { provider: 'anthropic', label: 'Anthropic', base_url: 'https://api.anthropic.com/v1', icon_url: '/provider-logos/anthropic.svg', supports_custom_base_url: true },
    { provider: 'azure_openai', label: 'Azure OpenAI', base_url: 'https://{resource}.openai.azure.com/openai/deployments/{deployment}', icon_url: '/provider-logos/azure_openai.svg', supports_custom_base_url: true },
    { provider: 'ollama', label: 'Ollama', base_url: 'http://localhost:11434/v1', icon_url: '/provider-logos/ollama.svg', supports_custom_base_url: true },
    { provider: 'openai_compatible', label: 'OpenAI Compatible', base_url: 'https://api.openai.com/v1', icon_url: '/provider-logos/openai_compatible.svg', supports_custom_base_url: true },
  ]
}

function ensureModelOptions(
  options: ModelSelectOption[],
  selected: string,
): ModelSelectOption[] {
  const unique = uniqueModelOptions(options.filter((option) => Boolean(option.value)))
  if (selected && !unique.some((option) => option.value === selected)) {
    return [modelOptionForSelectedValue(selected), ...unique]
  }
  return unique
}

function uniqueModelOptions(options: ModelSelectOption[]): ModelSelectOption[] {
  const seen = new Set<string>()
  return options.filter((option) => {
    if (!option.value || seen.has(option.value)) return false
    seen.add(option.value)
    return true
  })
}

function modelOptionForSelectedValue(value: string): ModelSelectOption {
  const stable = parseStableModelOptionValue(value)
  if (!stable) return legacyModelSelectOption(value)
  const provider = providers.value.find((item) => item.provider_id === stable.providerId)
  const providerText = provider ? providerLabel(provider.provider) : stable.providerId
  return {
    value,
    label: `${providerText}: ${stable.modelId}`,
    providerId: stable.providerId,
    providerLabel: providerText,
    modelId: stable.modelId,
    capabilities: [],
  }
}

function providerKeyMask(providerId: string): string {
  return providerRows.value.find((provider) => provider.id === providerId)?.keyMask || ''
}

function apiKeyPlaceholder(providerId: string): string {
  const mask = providerKeyMask(providerId)
  return mask ? `Saved key ${mask}` : 'Paste API key'
}

function providerKeyHint(providerId: string): string {
  const mask = providerKeyMask(providerId)
  return mask
    ? `Saved key: ${mask}. Leave empty to keep it.`
    : 'Key is encrypted after saving. Saving also runs a connection test.'
}

function testingStateForProvider(providerId: string): string {
  if (testingProviderId.value === providerId) return 'Testing connection...'
  return providerTestMessages.value[providerId] || ''
}

async function loadProviders() {
  loadingProviders.value = true
  providerError.value = ''
  try {
    const [presetResponse, providerResponse] = await Promise.all([
      settingsApi.getModelProviderPresets(),
      settingsApi.listModelProviders(),
    ])
    presets.value = presetResponse.data?.length ? presetResponse.data : defaultProviders()
    providers.value = providerResponse.data || []
  } catch (error: any) {
    presets.value = defaultProviders()
    providerError.value = error?.response?.data?.detail || '模型供应商配置暂时无法加载，已显示默认供应商。'
  } finally {
    loadingProviders.value = false
  }
}

function normalizeWebSearchSettings(raw: Partial<WebSearchSettings> | null | undefined): WebSearchSettings {
  const defaults = defaultWebSearchSettings()
  const contentTypes = Array.isArray(raw?.content_types)
    ? raw.content_types.filter((item): item is WebSearchContentType =>
      WEB_SEARCH_CONTENT_TYPE_OPTIONS.some((option) => option.id === item),
    )
    : defaults.content_types

  return {
    provider: raw?.provider === 'anysearch' ? raw.provider : defaults.provider,
    mode: raw?.mode === 'auto' ? 'auto' : defaults.mode,
    zone: raw?.zone === 'intl' ? 'intl' : defaults.zone,
    language: raw?.language === 'en' ? 'en' : defaults.language,
    max_results: Math.min(10, Math.max(1, Number(raw?.max_results || defaults.max_results))),
    content_types: contentTypes.length > 0 ? contentTypes : defaults.content_types,
    api_key_mask: raw?.api_key_mask || '',
    updated_at: raw?.updated_at,
  }
}

async function loadWebSearchSettings() {
  loadingWebSearchSettings.value = true
  webSearchError.value = ''
  try {
    const response = await settingsApi.getWebSearchSettings()
    webSearchSettings.value = normalizeWebSearchSettings(response.data)
  } catch (error: any) {
    webSearchSettings.value = defaultWebSearchSettings()
    webSearchError.value = error?.response?.data?.detail || 'Web Search 配置暂时无法加载，已显示默认设置。'
  } finally {
    loadingWebSearchSettings.value = false
  }
}

function normalizeQaThinkingMode(value: unknown): QaThinkingMode {
  return value === 'auto' || value === 'on' ? value : 'off'
}

async function loadQaSettings() {
  loadingQaSettings.value = true
  qaSettingsError.value = ''
  try {
    const response = await settingsApi.getQaSettings()
    qaSettings.value.thinkingMode = normalizeQaThinkingMode(response.data?.qa_thinking_mode)
  } catch (error: any) {
    qaSettings.value.thinkingMode = 'off'
    qaSettingsError.value = error?.response?.data?.detail || '问答设置暂时无法加载，已使用默认值。'
  } finally {
    loadingQaSettings.value = false
  }
}

async function saveQaSettings() {
  savingQaSettings.value = true
  qaSettingsMessage.value = ''
  qaSettingsError.value = ''
  try {
    const response = await settingsApi.updateQaSettings({
      qa_thinking_mode: qaSettings.value.thinkingMode,
    })
    qaSettings.value.thinkingMode = normalizeQaThinkingMode(response.data?.qa_thinking_mode)
    qaSettingsMessage.value = '问答设置已保存。'
  } catch (error: any) {
    qaSettingsError.value = error?.response?.data?.detail || '保存问答设置失败。'
  } finally {
    savingQaSettings.value = false
  }
}

function toggleWebSearchContentType(type: WebSearchContentType) {
  const current = webSearchSettings.value.content_types
  if (current.includes(type)) {
    if (current.length === 1) return
    webSearchSettings.value.content_types = current.filter((item) => item !== type)
    return
  }
  webSearchSettings.value.content_types = [...current, type]
}

async function saveWebSearchSettings() {
  savingWebSearchSettings.value = true
  webSearchMessage.value = ''
  webSearchError.value = ''
  try {
    const response = await settingsApi.updateWebSearchSettings({
      provider: webSearchSettings.value.provider,
      mode: webSearchSettings.value.mode,
      zone: webSearchSettings.value.zone,
      language: webSearchSettings.value.language,
      max_results: webSearchSettings.value.max_results,
      content_types: webSearchSettings.value.content_types,
      ...(webSearchApiKey.value.trim() ? { api_key: webSearchApiKey.value.trim() } : {}),
    })
    webSearchSettings.value = normalizeWebSearchSettings(response.data)
    webSearchApiKey.value = ''
    webSearchMessage.value = 'Web Search 设置已保存。'
  } catch (error: any) {
    webSearchError.value = error?.response?.data?.detail || '保存 Web Search 设置失败。'
  } finally {
    savingWebSearchSettings.value = false
  }
}

function startConfigure(provider: string, baseUrl: string, providerId = '') {
  providerForm.value = {
    providerId,
    credentialName: `${providerLabel(provider)} credential`,
    provider,
    baseUrl,
    apiKey: '',
  }
  expandedProviderId.value = providerId || provider
}

function modelsForProvider(providerId: string): ModelProviderModel[] {
  return providerModels.value[providerId] || []
}

async function fetchProviderModels(providerId: string, options: { silent?: boolean } = {}) {
  if (!providerId) return
  if (!options.silent) loadingModelProviderId.value = providerId
  providerModelErrors.value = {
    ...providerModelErrors.value,
    [providerId]: '',
  }
  try {
    const response = await settingsApi.listModelProviderModels(providerId)
    const models = response.data?.models || []
    providerModels.value = {
      ...providerModels.value,
      [providerId]: models,
    }
  } catch (error: any) {
    providerModelErrors.value = {
      ...providerModelErrors.value,
      [providerId]: error?.response?.data?.detail || 'Failed to fetch models.',
    }
  } finally {
    if (!options.silent) loadingModelProviderId.value = null
  }
}

async function fetchAllConfiguredProviderModels() {
  await Promise.allSettled(
    providers.value.map((provider) =>
      fetchProviderModels(provider.provider_id, { silent: true }),
    ),
  )
}

async function toggleProvider(provider: { id: string; configured: boolean }) {
  const nextId = expandedProviderId.value === provider.id ? null : provider.id
  expandedProviderId.value = nextId
  if (nextId && provider.configured && !providerModels.value[provider.id]?.length) {
    await fetchProviderModels(provider.id)
  }
}

async function saveProvider() {
  savingProvider.value = true
  providerError.value = ''
  providerMessage.value = ''
  try {
    let savedProviderId = providerForm.value.providerId
    if (providerForm.value.providerId) {
      const response = await settingsApi.updateModelProvider(providerForm.value.providerId, {
        provider: providerForm.value.provider,
        base_url: providerForm.value.baseUrl,
        ...(providerForm.value.apiKey ? { api_key: providerForm.value.apiKey } : {}),
      })
      savedProviderId = response.data?.provider_id || savedProviderId
    } else {
      const response = await settingsApi.saveModelProvider({
        provider: providerForm.value.provider,
        base_url: providerForm.value.baseUrl,
        api_key: providerForm.value.apiKey,
      })
      savedProviderId = response.data?.provider_id || ''
      providerForm.value.providerId = savedProviderId
    }
    providerMessage.value = 'Provider saved. Testing connection...'
    providerForm.value.apiKey = ''
    await loadProviders()
    if (savedProviderId) {
      expandedProviderId.value = savedProviderId
      await fetchProviderModels(savedProviderId, { silent: true })
      await autoTestSavedProvider(savedProviderId)
      await loadProviders()
    }
  } catch (error: any) {
    providerError.value = error?.response?.data?.detail || '保存模型供应商失败。'
  } finally {
    savingProvider.value = false
  }
}

async function autoTestSavedProvider(providerId: string) {
  providerTestMessages.value = {
    ...providerTestMessages.value,
    [providerId]: 'Testing connection...',
  }
  await testProvider(providerId)
}

async function testProvider(providerId: string) {
  testingProviderId.value = providerId
  providerError.value = ''
  providerMessage.value = ''
  try {
    const response = await settingsApi.testModelProvider(providerId)
    const testedModel = response.data?.tested_model
    const message = testedModel
      ? `Connection test passed with ${testedModel}.`
      : 'Connection test passed.'
    providerMessage.value = message
    providerTestMessages.value = {
      ...providerTestMessages.value,
      [providerId]: message,
    }
    await loadProviders()
  } catch (error: any) {
    const message = error?.response?.data?.detail || 'Connection test failed.'
    providerError.value = message
    providerTestMessages.value = {
      ...providerTestMessages.value,
      [providerId]: message,
    }
  } finally {
    testingProviderId.value = null
  }
}

async function loadFunctionalRoutes() {
  loadingFunctionalRoutes.value = true
  functionalRouteError.value = ''
  try {
    const [routeResponse] = await Promise.all([
      settingsApi.listModelRoutes(),
      settingsApi.listOcrRoutes().catch(() => ({ data: [] })),
    ])
    functionalRoutes.value = Object.fromEntries(
      (routeResponse.data || []).map((route: ModelRouteMapping) => [route.route_slot, route]),
    )
    applySavedRoute('indexing', (value) => {
      parsingSettings.value.model = value
    })
    applySavedRoute('document_qa', (value) => {
      qaSettings.value.model = value
    })
    applySavedRoute('vision', (value) => {
      ocrSettings.value.model = value
    })
  } catch (error: any) {
    functionalRouteError.value = error?.response?.data?.detail || 'Failed to load model routes.'
  } finally {
    loadingFunctionalRoutes.value = false
  }
}

async function saveFunctionalRoutes() {
  savingFunctionalRoutes.value = true
  functionalRouteMessage.value = ''
  functionalRouteError.value = ''
  try {
    const routes = [
      buildRoutePayload('indexing', parsingSettings.value.model),
      buildRoutePayload('document_qa', qaSettings.value.model),
      buildRoutePayload('vision', ocrSettings.value.model, true),
    ].filter((route): route is ModelRouteMapping => Boolean(route))
    await settingsApi.saveModelRoutes(routes)
    functionalRouteMessage.value = 'Model routing saved.'
    await loadFunctionalRoutes()
  } catch (error: any) {
    functionalRouteError.value = error?.response?.data?.detail || 'Failed to save model routing.'
  } finally {
    savingFunctionalRoutes.value = false
  }
}

function applySavedRoute(slot: string, setter: (value: string) => void) {
  const route = functionalRoutes.value[slot]
  const option = route ? modelOptionForRoute(route) : ''
  if (option) setter(option)
}

function modelOptionForRoute(route: ModelRouteMapping): string {
  return modelOptionValue(route.provider_id, route.model)
}

function buildRoutePayload(
  routeSlot: string,
  modelOption: string,
  forceVision = false,
): ModelRouteMapping | null {
  const resolved = resolveModelOption(modelOption)
  if (!resolved) return null
  return {
    route_slot: routeSlot,
    provider_id: resolved.provider.provider_id,
    model: resolved.modelId,
    supports_streaming: true,
    supports_tool_calling: resolved.capabilities.includes('tool_calling'),
    supports_vision: forceVision || resolved.capabilities.includes('vision'),
    supports_structured_output: false,
    supports_responses_api: Boolean(resolved.provider.supports_responses_api),
  }
}

function resolveModelOption(modelOption: string) {
  const stable = resolveStableModelOption(modelOption)
  if (stable) return stable

  const separator = modelOption.indexOf(': ')
  if (separator < 0) return null
  const label = modelOption.slice(0, separator)
  const modelId = modelOption.slice(separator + 2).trim()
  const provider = providers.value.find((item) => providerLabel(item.provider) === label)
  if (!provider || !modelId || modelId === 'models not loaded') return null
  const model = modelsForProvider(provider.provider_id).find((item) => item.id === modelId)
  return {
    provider,
    modelId,
    capabilities: inferModelCapabilities(model || { id: modelId }),
  }
}

function resolveStableModelOption(modelOption: string) {
  const parsed = parseStableModelOptionValue(modelOption)
  if (!parsed || !parsed.modelId || parsed.modelId === 'models not loaded') return null
  const provider = providers.value.find((item) => item.provider_id === parsed.providerId)
  if (!provider) return null
  const model = modelsForProvider(provider.provider_id).find((item) => item.id === parsed.modelId)
  return {
    provider,
    modelId: parsed.modelId,
    capabilities: inferModelCapabilities(model || { id: parsed.modelId }),
  }
}

function parseStableModelOptionValue(value: string) {
  const separator = value.indexOf('::')
  if (separator < 0) return null
  return {
    providerId: value.slice(0, separator),
    modelId: value.slice(separator + 2).trim(),
  }
}

function logout() {
  userStore.logout()
  router.push('/login')
  close()
}

function close() {
  emit('update:open', false)
}

onMounted(async () => {
  await Promise.all([loadProviders(), loadWebSearchSettings(), loadQaSettings()])
  await fetchAllConfiguredProviderModels()
  await loadFunctionalRoutes()
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="settings-overlay" @click="close">
      <section class="settings-dialog" @click.stop>
        <header class="settings-dialog-header">
          <div>
            <h2>Settings</h2>
            <p>配置 PageChat 的模型、OCR、解析和问答行为</p>
          </div>
          <button type="button" @click="close" aria-label="Close settings">
            <X />
          </button>
        </header>

        <div class="settings-page">
      <aside class="settings-nav">
        <div class="settings-nav-group">
          <button
            v-for="section in SETTINGS_NAV_SECTIONS.primary"
            :key="section.id"
            :class="{ active: activeSection === section.id }"
            type="button"
            @click="activeSection = section.id"
          >
            <component :is="navIcon(section.icon)" />
            <span>{{ section.label }}</span>
          </button>
        </div>
        <div class="settings-nav-footer">
          <button
            v-for="section in SETTINGS_NAV_SECTIONS.footer"
            :key="section.id"
            :class="{ active: activeSection === section.id }"
            type="button"
            @click="activeSection = section.id"
          >
            <component :is="navIcon(section.icon)" />
            <span>{{ section.label }}</span>
          </button>
        </div>
      </aside>

      <main class="settings-content">
        <section v-if="activeSection === 'providers'" class="settings-section">
          <div class="section-header">
            <div>
              <h2>模型供应商</h2>
              <p>统一管理供应商、凭据、OpenAI-compatible endpoint 和可用模型能力。</p>
            </div>
            <div class="provider-search">
              <Search />
              <input v-model="providerSearchQuery" placeholder="Search providers" />
            </div>
          </div>

          <div class="provider-list">
            <article v-for="provider in filteredProviderRows" :key="provider.id" class="provider-row">
              <div class="provider-main">
                <div class="provider-logo">
                  <img :src="provider.iconUrl" :alt="provider.label" @error="hideBrokenLogo" />
                  <span>{{ providerInitial(provider.label) }}</span>
                </div>
                <div class="provider-title">
                  <div>
                    <strong>{{ provider.label }}</strong>
                    <span>{{ provider.configured ? 'Configured' : 'Not configured' }}</span>
                  </div>
                  <p>{{ provider.baseUrl }}</p>
                </div>
              </div>

              <div class="provider-actions">
                <span :class="['provider-status', { configured: provider.configured }]">
                  {{ provider.validation }}
                </span>
                <button
                  type="button"
                  @click="startConfigure(provider.provider, provider.baseUrl, provider.configured ? provider.id : '')"
                >
                  <KeyRound />
                  {{ provider.configured ? 'Edit' : 'Configure' }}
                </button>
                <button
                  class="icon-button"
                  type="button"
                  @click="toggleProvider(provider)"
                >
                  <ChevronDown />
                </button>
              </div>

              <div v-if="expandedProviderId === provider.id" class="provider-expanded">
                <div class="model-list">
                  <div class="model-list-header">
                    <strong>Available models · {{ modelsForProvider(provider.id).length }}</strong>
                    <button
                      v-if="provider.configured"
                      type="button"
                      :disabled="loadingModelProviderId === provider.id"
                      @click="fetchProviderModels(provider.id)"
                    >
                      <Loader2 v-if="loadingModelProviderId === provider.id" class="spin" />
                      <RefreshCw v-else />
                      Refresh
                    </button>
                  </div>
                  <div class="model-list-body">
                    <div v-if="!provider.configured" class="model-empty">
                      Configure this provider to fetch available models.
                    </div>
                    <div v-else-if="loadingModelProviderId === provider.id" class="model-empty">
                      Fetching models...
                    </div>
                    <div v-else-if="providerModelErrors[provider.id]" class="model-empty error">
                      {{ providerModelErrors[provider.id] }}
                    </div>
                    <div v-else-if="modelsForProvider(provider.id).length === 0" class="model-empty">
                      No models returned yet.
                    </div>
                    <div v-for="model in modelsForProvider(provider.id)" :key="model.id" class="model-row">
                      <span>{{ model.id }}</span>
                      <div>
                        <small>{{ model.owned_by || provider.label }}</small>
                        <span>Remote</span>
                        <span
                          v-for="capability in modelCapabilityBadges(model)"
                          :key="capability"
                          class="model-capabilities"
                        >
                          {{ capability }}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="credential-panel">
                  <h3>API 密钥授权配置</h3>
                  <label>
                    凭据名称
                    <input v-model="providerForm.credentialName" />
                  </label>
                  <label>
                    API Key
                    <input
                      v-model="providerForm.apiKey"
                      type="password"
                      :placeholder="apiKeyPlaceholder(provider.id)"
                      autocomplete="new-password"
                    />
                  </label>
                  <label>
                    自定义 API endpoint 地址
                    <input v-model="providerForm.baseUrl" />
                  </label>
                  <div class="credential-actions">
                    <span>{{ testingStateForProvider(provider.id) || providerKeyHint(provider.id) }}</span>
                    <button type="button" :disabled="savingProvider || !providerForm.baseUrl" @click="saveProvider">
                      <Loader2 v-if="savingProvider" class="spin" />
                      <CheckCircle2 v-else />
                      保存
                    </button>
                    <button
                      v-if="provider.configured"
                      type="button"
                      :disabled="testingProviderId === provider.id"
                      @click="testProvider(provider.id)"
                    >
                      <Loader2 v-if="testingProviderId === provider.id" class="spin" />
                      <RefreshCw v-else />
                      Retest
                    </button>
                  </div>
                </div>
              </div>
            </article>
          </div>

          <p v-if="providerMessage" class="success-message">{{ providerMessage }}</p>
          <p v-if="providerError" class="error-message">
            <AlertCircle />
            {{ providerError }}
          </p>
        </section>

        <section v-else-if="activeSection === 'ocr'" class="settings-section narrow">
          <div class="section-header">
            <div>
              <h2>OCR 设置</h2>
              <p>选择 OCR/VLM 模型、并发和视觉提示词。</p>
            </div>
          </div>
          <div class="form-grid">
            <label>
              OCR 模型
              <select v-model="ocrSettings.model">
                <option v-if="ocrModelOptions.length === 0" value="" disabled>
                  请先配置支持 OCR/VLM 的模型
                </option>
                <option v-for="model in ocrModelOptions" :key="model.value" :value="model.value">
                  {{ model.label }}
                </option>
              </select>
            </label>
            <label>
              并发
              <input v-model.number="ocrSettings.concurrency" type="number" min="1" max="12" />
            </label>
            <label class="wide">
              VLM 提示词
              <textarea v-model="ocrSettings.vlmPrompt" rows="6" />
            </label>
            <div class="wide settings-actions">
              <span>
                <template v-if="loadingFunctionalRoutes">Loading model routes...</template>
                <template v-else>{{ functionalRouteMessage || 'OCR/VLM uses the selected vision-capable model route.' }}</template>
              </span>
              <button type="button" :disabled="savingFunctionalRoutes" @click="saveFunctionalRoutes">
                <Loader2 v-if="savingFunctionalRoutes" class="spin" />
                <CheckCircle2 v-else />
                Save model routing
              </button>
            </div>
          </div>
        </section>

        <section v-else-if="activeSection === 'parsing'" class="settings-section narrow">
          <div class="section-header">
            <div>
              <h2>解析设置</h2>
              <p>配置 TOC 和结构解析使用的模型与默认解析模式。</p>
            </div>
          </div>
          <div class="form-grid">
            <label class="wide">
              解析模型
              <select v-model="parsingSettings.model">
                <option v-if="parsingModelOptions.length === 0" value="" disabled>
                  请先配置模型供应商
                </option>
                <option v-for="model in parsingModelOptions" :key="model.value" :value="model.value">
                  {{ model.label }}
                </option>
              </select>
            </label>
            <label class="wide">
              {{ PARSING_BATCH_CONCURRENCY_SETTING.label }}
              <input
                v-model.number="parsingSettings.batchParseConcurrency"
                type="number"
                :min="PARSING_BATCH_CONCURRENCY_SETTING.min"
                :max="PARSING_BATCH_CONCURRENCY_SETTING.max"
              />
              <small class="field-hint">{{ PARSING_BATCH_CONCURRENCY_SETTING.description }}</small>
            </label>
            <div class="wide">
              <div class="field-label">解析模式</div>
              <div class="mode-options">
                <button
                  v-for="mode in PARSE_MODE_OPTIONS"
                  :key="mode.id"
                  :class="{ active: parsingSettings.mode === mode.id }"
                  type="button"
                  @click="parsingSettings.mode = mode.id"
                >
                  <strong>{{ mode.label }} <span v-if="mode.badge">{{ mode.badge }}</span></strong>
                  <small>{{ mode.description }}</small>
                </button>
              </div>
            </div>
            <div class="wide settings-actions">
              <span>{{ functionalRouteMessage || 'Parsing uses the indexing route.' }}</span>
              <button type="button" :disabled="savingFunctionalRoutes" @click="saveFunctionalRoutes">
                <Loader2 v-if="savingFunctionalRoutes" class="spin" />
                <CheckCircle2 v-else />
                Save model routing
              </button>
            </div>
          </div>
        </section>

        <section v-else-if="activeSection === 'qa'" class="settings-section narrow">
          <div class="section-header">
            <div>
              <h2>问答设置</h2>
              <p>选择问答模型，并设置 Web Search 参与回答的方式。</p>
            </div>
          </div>
          <div class="form-grid">
            <label class="wide">
              问答模型
              <select v-model="qaSettings.model">
                <option v-if="qaModelOptions.length === 0" value="" disabled>
                  请先配置模型供应商
                </option>
                <option v-for="model in qaModelOptions" :key="model.value" :value="model.value">
                  {{ model.label }}
                </option>
              </select>
            </label>
            <div class="wide settings-actions">
              <span>{{ functionalRouteMessage || 'Document Q&A uses the selected answer model route.' }}</span>
              <button type="button" :disabled="savingFunctionalRoutes" @click="saveFunctionalRoutes">
                <Loader2 v-if="savingFunctionalRoutes" class="spin" />
                <CheckCircle2 v-else />
                Save model routing
              </button>
            </div>
            <div class="wide">
              <div class="field-label">模型 Thinking</div>
              <div class="mode-options three">
                <button
                  v-for="option in qaThinkingOptions"
                  :key="option.id"
                  :class="{ active: qaSettings.thinkingMode === option.id }"
                  type="button"
                  @click="qaSettings.thinkingMode = option.id"
                >
                  <strong>{{ option.label }}</strong>
                  <small>{{ option.description }}</small>
                </button>
              </div>
            </div>
            <div class="wide settings-actions">
              <span>
                <template v-if="loadingQaSettings">正在加载问答设置...</template>
                <template v-else>{{ qaSettingsMessage || 'Thinking 默认关闭；复杂推理时可切换为自动或开启。' }}</template>
              </span>
              <button
                type="button"
                :disabled="savingQaSettings || loadingQaSettings"
                @click="saveQaSettings"
              >
                <Loader2 v-if="savingQaSettings" class="spin" />
                <CheckCircle2 v-else />
                保存问答设置
              </button>
            </div>
            <p v-if="qaSettingsError" class="wide error-message">
              <AlertCircle />
              {{ qaSettingsError }}
            </p>
            <div class="wide">
              <div class="field-label">Web Search</div>
              <div class="mode-options two">
                <button
                  v-for="mode in WEB_SEARCH_MODE_OPTIONS"
                  :key="mode.id"
                  :class="{ active: webSearchSettings.mode === mode.id }"
                  type="button"
                  @click="webSearchSettings.mode = mode.id"
                >
                  <strong>{{ mode.label }}</strong>
                  <small>{{ mode.description }}</small>
                </button>
              </div>
            </div>

            <label>
              搜索供应商
              <select v-model="webSearchSettings.provider">
                <option
                  v-for="provider in WEB_SEARCH_PROVIDER_OPTIONS"
                  :key="provider.id"
                  :value="provider.id"
                >
                  {{ provider.label }}
                </option>
              </select>
            </label>
            <label>
              API Key
              <input
                v-model="webSearchApiKey"
                type="password"
                autocomplete="new-password"
                :placeholder="webSearchSettings.api_key_mask || '留空则使用匿名额度'"
              />
            </label>
            <label>
              搜索区域
              <select v-model="webSearchSettings.zone">
                <option v-for="zone in WEB_SEARCH_ZONE_OPTIONS" :key="zone.id" :value="zone.id">
                  {{ zone.label }}
                </option>
              </select>
            </label>
            <label>
              语言
              <select v-model="webSearchSettings.language">
                <option v-for="language in WEB_SEARCH_LANGUAGE_OPTIONS" :key="language.id" :value="language.id">
                  {{ language.label }}
                </option>
              </select>
            </label>
            <label>
              最大结果数
              <input v-model.number="webSearchSettings.max_results" type="number" min="1" max="10" />
            </label>
            <div>
              <div class="field-label">内容类型</div>
              <div class="checkbox-row">
                <button
                  v-for="contentType in WEB_SEARCH_CONTENT_TYPE_OPTIONS"
                  :key="contentType.id"
                  :class="{ active: webSearchSettings.content_types.includes(contentType.id) }"
                  type="button"
                  @click="toggleWebSearchContentType(contentType.id)"
                >
                  <CheckCircle2 v-if="webSearchSettings.content_types.includes(contentType.id)" />
                  <span v-else />
                  {{ contentType.label }}
                </button>
              </div>
            </div>

            <div class="wide settings-actions">
              <span>
                <template v-if="loadingWebSearchSettings">正在加载 Web Search 设置...</template>
                <template v-else-if="webSearchSettings.api_key_mask">已保存密钥：{{ webSearchSettings.api_key_mask }}</template>
                <template v-else>API Key 可选；留空时使用 AnySearch 匿名额度。</template>
              </span>
              <button
                type="button"
                :disabled="savingWebSearchSettings || loadingWebSearchSettings"
                @click="saveWebSearchSettings"
              >
                <Loader2 v-if="savingWebSearchSettings" class="spin" />
                <CheckCircle2 v-else />
                保存 Web Search
              </button>
            </div>
          </div>
          <p v-if="webSearchMessage" class="success-message">{{ webSearchMessage }}</p>
          <p v-if="webSearchError" class="error-message">
            <AlertCircle />
            {{ webSearchError }}
          </p>
        </section>

        <section v-else-if="activeSection === 'language'" class="settings-section narrow">
          <div class="section-header">
            <div>
              <h2>语言</h2>
              <p>设置界面显示语言。</p>
            </div>
          </div>
          <div class="form-grid">
            <label class="wide">
              Interface language
              <select>
                <option>简体中文</option>
                <option>English</option>
              </select>
            </label>
          </div>
        </section>

        <section v-else class="settings-section narrow">
          <div class="section-header">
            <div>
              <h2>Account</h2>
              <p>当前登录状态和账号操作。</p>
            </div>
          </div>
          <div class="account-card">
            <div class="account-avatar">{{ (userStore.username || 'P').slice(0, 1).toUpperCase() }}</div>
            <div>
              <strong>{{ userStore.username || '未登录' }}</strong>
              <span>{{ userStore.isLoggedIn ? '已登录' : '访客模式' }}</span>
            </div>
            <button type="button" @click="logout">退出登录</button>
          </div>
        </section>
      </main>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.settings-overlay {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.22);
  backdrop-filter: blur(8px);
}

.settings-dialog {
  display: grid;
  width: min(1280px, calc(100vw - 96px));
  height: calc(100vh - 80px);
  min-height: 0;
  grid-template-rows: 58px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: var(--kc-radius-lg);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: var(--kc-shadow-modal);
}

.settings-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--kc-border);
  padding: 0 16px 0 22px;
}

.settings-dialog-header h2,
.settings-dialog-header p {
  margin: 0;
}

.settings-dialog-header h2 {
  font-size: 17px;
  font-weight: 680;
  line-height: 24px;
}

.settings-dialog-header p {
  margin-top: 2px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.settings-dialog-header button {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--kc-text-secondary);
}

.settings-dialog-header button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.settings-dialog-header svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}

.settings-page {
  display: grid;
  width: 100%;
  height: 100%;
  min-height: 0;
  grid-template-columns: 248px minmax(0, 1fr);
  overflow: hidden;
  background: transparent;
}

.settings-nav {
  display: flex;
  min-height: 0;
  flex-direction: column;
  justify-content: space-between;
  border-right: 1px solid var(--kc-border);
  background: #f8fafc;
  padding: 14px;
}

.settings-nav-group,
.settings-nav-footer {
  display: grid;
  gap: 4px;
}

.settings-nav button {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 36px;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  padding: 0 10px;
  color: var(--kc-text-secondary);
  font-size: 13px;
  text-align: left;
}

.settings-nav button:hover,
.settings-nav button.active {
  background: #eaf3ff;
  color: #145eb8;
}

.settings-nav svg,
.section-header svg,
.provider-search svg,
.provider-actions svg,
.error-message svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}

.settings-content {
  min-height: 0;
  overflow: auto;
  padding: 24px;
}

.settings-section {
  display: grid;
  gap: 18px;
}

.settings-section.narrow {
  max-width: 820px;
}

.section-header {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.section-header > div:first-child {
  min-width: 0;
}

.section-header h2,
.section-header p {
  margin: 0;
}

.section-header h2 {
  font-size: 19px;
  font-weight: 680;
  line-height: 27px;
}

.section-header p {
  margin-top: 3px;
  color: var(--kc-text-tertiary);
  font-size: 12.5px;
  line-height: 19px;
}

.provider-search {
  display: flex;
  min-width: 180px;
  align-items: center;
  gap: 8px;
  width: min(260px, 36%);
  height: 34px;
  flex: 0 1 260px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 10px;
}

.provider-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: none;
  font-size: 12.5px;
}

.provider-list {
  display: grid;
  gap: 10px;
}

.provider-row {
  display: grid;
  gap: 12px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 14px;
}

.provider-main {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 12px;
}

.provider-row {
  grid-template-columns: minmax(0, 1fr) auto;
}

.provider-expanded {
  grid-column: 1 / -1;
}

.provider-logo {
  position: relative;
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  border: 1px solid var(--kc-border);
  border-radius: 10px;
  background: linear-gradient(180deg, #fff, #f3f6fb);
  color: var(--kc-text);
  font-size: 12px;
  font-weight: 650;
}

.provider-logo img {
  position: relative;
  z-index: 1;
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.provider-logo span {
  position: absolute;
  color: var(--kc-text-tertiary);
  font-size: 11px;
  font-weight: 750;
}

.provider-title {
  min-width: 0;
}

.provider-title div:first-child {
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider-title strong {
  font-size: 14px;
}

.provider-title div:first-child span,
.provider-status {
  border-radius: 999px;
  background: var(--kc-surface-muted);
  padding: 3px 7px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.provider-status.configured {
  background: #ecfdf3;
  color: #15803d;
}

.provider-title p {
  margin: 4px 0 8px;
  overflow: hidden;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-row span {
  border: 1px solid var(--kc-border-soft);
  border-radius: 999px;
  background: #f8fafc;
  padding: 3px 7px;
  color: var(--kc-text-secondary);
  font-size: 11px;
}

.provider-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider-actions button,
.credential-actions button,
.settings-actions button,
.account-card button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 10px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  font-weight: 560;
}

.provider-actions button:hover,
.credential-actions button:hover,
.settings-actions button:hover,
.account-card button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.provider-actions .icon-button {
  width: 32px;
  justify-content: center;
  padding: 0;
}

.provider-expanded {
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(420px, 1.2fr);
  gap: 14px;
  border-top: 1px solid var(--kc-border-soft);
  padding-top: 12px;
}

.model-list,
.credential-panel,
.form-grid,
.account-card {
  border: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-md);
  background: #fbfcfd;
  padding: 12px;
}

.model-list {
  display: grid;
  align-content: start;
  gap: 8px;
  min-height: 0;
}

.model-list-body {
  display: grid;
  max-height: 280px;
  gap: 8px;
  overflow: auto;
  padding-right: 4px;
  scrollbar-width: thin;
}

.model-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.model-list-header strong {
  color: var(--kc-text);
  font-size: 12.5px;
}

.model-list-header button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-sm);
  background: #fff;
  padding: 0 9px;
  color: var(--kc-text-secondary);
  font-size: 11.5px;
}

.model-list-header button:disabled {
  opacity: 0.62;
}

.model-list-header svg {
  width: 13px;
  height: 13px;
}

.model-empty {
  border: 1px dashed var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 14px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  line-height: 18px;
}

.model-empty.error {
  border-color: rgba(220, 38, 38, 0.22);
  background: #fff7f7;
  color: #b42318;
}

.model-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 10px;
}

.model-row > span {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--kc-text);
  font-size: 12.5px;
  font-weight: 600;
}

.model-row div {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}

.model-row .model-capabilities {
  border-color: rgba(47, 128, 237, 0.18);
  background: #edf6ff;
  color: #145eb8;
}

.model-row small {
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.credential-panel,
.form-grid {
  display: grid;
  gap: 12px;
}

.credential-panel h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 650;
}

label,
.field-label {
  display: grid;
  gap: 6px;
  color: var(--kc-text-secondary);
  font-size: 12px;
  font-weight: 560;
}

.field-hint {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  font-weight: 450;
  line-height: 17px;
}

input,
select,
textarea {
  width: 100%;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 8px 10px;
  color: var(--kc-text);
  font-size: 13px;
  outline: none;
}

textarea {
  resize: vertical;
  line-height: 20px;
}

input:focus,
select:focus,
textarea:focus {
  border-color: rgba(47, 128, 237, 0.45);
  box-shadow: 0 0 0 3px rgba(47, 128, 237, 0.12);
}

.credential-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  border-radius: var(--kc-radius-md);
  background: #f3f6fb;
  padding: 10px;
}

.credential-actions span {
  min-width: 220px;
  flex: 1;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
}

.settings-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  border-radius: var(--kc-radius-md);
  background: #f3f6fb;
  padding: 10px;
}

.settings-actions span {
  min-width: 220px;
  flex: 1;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  line-height: 17px;
}

.form-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.wide {
  grid-column: 1 / -1;
}

.mode-options {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.mode-options.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.mode-options button {
  display: grid;
  gap: 5px;
  min-height: 92px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 12px;
  color: var(--kc-text-secondary);
  text-align: left;
}

.mode-options button.active {
  border-color: rgba(47, 128, 237, 0.36);
  background: #eaf3ff;
  color: #145eb8;
}

.mode-options strong {
  color: var(--kc-text);
  font-size: 13px;
}

.mode-options strong span {
  color: var(--kc-accent);
  font-size: 11px;
}

.mode-options small {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  line-height: 17px;
}

.checkbox-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.checkbox-row button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 10px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  font-weight: 560;
}

.checkbox-row button.active {
  border-color: rgba(47, 128, 237, 0.32);
  background: #eaf3ff;
  color: #145eb8;
}

.checkbox-row button span,
.checkbox-row button svg {
  display: grid;
  width: 15px;
  height: 15px;
  place-items: center;
  border: 1px solid currentColor;
  border-radius: 4px;
}

.checkbox-row button svg {
  border-color: transparent;
  stroke-width: 2;
}

.account-card {
  display: flex;
  align-items: center;
  gap: 12px;
}

.account-avatar {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 999px;
  background: #eaf3ff;
  color: var(--kc-accent);
  font-weight: 750;
}

.account-card div:nth-child(2) {
  display: grid;
  flex: 1;
  gap: 2px;
}

.account-card strong {
  font-size: 14px;
}

.account-card span {
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.success-message,
.error-message {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 0;
  font-size: 12.5px;
}

.success-message {
  color: #15803d;
}

.error-message {
  color: var(--kc-danger);
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1050px) {
  .settings-dialog {
    width: calc(100vw - 28px);
    height: calc(100vh - 40px);
  }

  .settings-page {
    grid-template-columns: 210px minmax(0, 1fr);
  }

  .provider-expanded {
    grid-template-columns: 1fr;
  }
}
</style>
