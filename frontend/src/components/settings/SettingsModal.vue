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
import { useI18n } from '@/i18n/messages'
import type { ModelProviderConfig, ModelProviderModel, ModelProviderPreset, ModelRouteMapping } from '@/types/modelSettings'
import {
  buildOcrModelOptions,
  buildParsingModelOptions,
  buildQaModelGroups,
  inferModelCapabilities,
  legacyModelSelectOption,
  modelCapabilityBadges,
  modelOptionValue,
  providerCapabilityBadges,
  type ModelSelectOption,
} from '@/utils/modelProviderModels'
import { buildModelProviderRows, filterModelProviderRows, type ModelProviderRow } from '@/utils/modelProviderRows'
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

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
}>()

const router = useRouter()
const userStore = useUserStore()
const { t, settingsNavLabel, language, languageOptions, setLanguage } = useI18n()
const isChinese = computed(() => language.value === 'zh-CN')
const activeSection = ref<SectionId>('providers')
const providers = ref<ModelProviderConfig[]>([])
const presets = ref<ModelProviderPreset[]>([])
const loadingProviders = ref(false)
const savingProvider = ref(false)
const loadingModelProviderId = ref<string | null>(null)
const providerSearchQuery = ref('')
const providerMessage = ref('')
const providerError = ref('')
const providerCredentialDialogOpen = ref(false)
const compatibleModelDialogOpen = ref(false)
const selectedProviderRow = ref<ModelProviderRow | null>(null)
const collapsedProviderModels = ref<Set<string>>(new Set())
const disabledProviderModelKeys = ref<Set<string>>(new Set())
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
const providerForm = ref({
  providerId: '',
  credentialName: 'Default credential',
  provider: 'openai_compatible',
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
})

const compatibleModelForm = ref({
  modelName: '',
  modelType: 'LLM',
  displayName: '',
  endpointModelName: '',
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
})

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
    buildOcrModelOptions(providers.value, providerModels.value, providerLabel, disabledProviderModelKeys.value),
    ocrSettings.value.model,
    !isModelValueDisabled(ocrSettings.value.model),
  ),
)

const parsingModelOptions = computed(() =>
  ensureModelOptions(
    buildParsingModelOptions(providers.value, providerModels.value, providerLabel, disabledProviderModelKeys.value),
    parsingSettings.value.model,
    !isModelValueDisabled(parsingSettings.value.model),
  ),
)

const qaModelGroups = computed(() =>
  buildQaModelGroups(providers.value, providerModels.value, providerLabel, disabledProviderModelKeys.value),
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
  includeSelected = true,
): ModelSelectOption[] {
  const unique = uniqueModelOptions(options.filter((option) => Boolean(option.value)))
  if (includeSelected && selected && !unique.some((option) => option.value === selected)) {
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

function formatTokenWindow(value: number | null | undefined): string {
  if (!value || value <= 0) return ''
  if (value >= 1000) {
    const rounded = value % 1000 === 0 ? value / 1000 : Math.round(value / 1000)
    return `${rounded}K`
  }
  return String(value)
}

function modelMetaBadges(model: ModelProviderModel): string[] {
  const badges: string[] = []
  const contextWindow = formatTokenWindow(model.context_window)
  const outputWindow = formatTokenWindow(model.max_output_tokens)
  if (contextWindow) badges.push(`Context ${contextWindow}`)
  if (outputWindow) badges.push(`Output ${outputWindow}`)
  if (!contextWindow && !outputWindow) badges.push('Context unknown')
  return badges
}

function modelMetaBadgesForOption(model: ModelSelectOption): string[] {
  const providerModelsForOption = providerModels.value[model.providerId] || []
  const source = providerModelsForOption.find((item) => item.id === model.modelId)
  return source ? modelMetaBadges(source) : []
}

function providerRowForModelOption(model: ModelSelectOption): ModelProviderRow | null {
  return providerRows.value.find((provider) =>
    provider.providerId === model.providerId ||
    provider.credentials.some((credential) => credential.providerId === model.providerId),
  ) || null
}

function providerIconForModelOption(model: ModelSelectOption): string {
  return providerRowForModelOption(model)?.iconUrl || `/provider-logos/${model.providerId}.svg`
}

function providerInitialForModelOption(model: ModelSelectOption): string {
  return providerInitial(providerRowForModelOption(model)?.label || model.providerLabel)
}

function selectQaModel(model: ModelSelectOption) {
  qaSettings.value.model = model.value
}

function qaModelSelected(model: ModelSelectOption): boolean {
  return qaSettings.value.model === model.value
}

function providerModelBadges(provider: ModelProviderRow): string[] {
  return providerCapabilityBadges(modelsForProviderRow(provider))
}

function compatibleModelCapabilities() {
  const type = compatibleModelForm.value.modelType.toLowerCase()
  if (type === 'vision') return ['llm', 'vision', 'tool_calling'] as const
  if (type === 'embedding') return ['embedding'] as const
  if (type === 'ocr') return ['llm', 'vision', 'ocr'] as const
  return ['llm', 'tool_calling'] as const
}

function providerKeyMask(providerId: string): string {
  for (const provider of providerRows.value) {
    const credential = provider.credentials.find((item) => item.providerId === providerId)
    if (credential) return credential.keyMask
    if (provider.providerId === providerId) return provider.keyMask
  }
  return ''
}

function apiKeyPlaceholder(providerId: string): string {
  const mask = providerKeyMask(providerId)
  return mask ? `Saved key ${mask}` : 'Paste API key'
}

function providerKeyHint(providerId: string): string {
  const mask = providerKeyMask(providerId)
  if (mask) {
    return isChinese.value
      ? `已保存密钥：${mask}。留空将保留当前密钥。`
      : `Saved key: ${mask}. Leave empty to keep it.`
  }
  return isChinese.value
    ? 'API Key 会加密保存。保存后会尝试读取供应商模型列表。'
    : 'The API key is encrypted after saving. Saving attempts to load the provider model list.'
}

const providerSecurityNote = computed(() =>
  isChinese.value
    ? 'API Key 会使用服务端配置的密钥加密保存。保存后会尝试读取供应商模型列表，并根据结果更新连接状态。'
    : 'API keys are encrypted with the server-side settings secret. After saving, PageChat attempts to load the provider model list and updates the connection status from that result.',
)

const newProviderKeyHint = computed(() =>
  isChinese.value
    ? '新凭据保存后会显示加密后的密钥状态。'
    : 'A saved credential will show its masked key status here.',
)

function testingStateForProvider(providerId: string): string {
  return providerTestMessages.value[providerId] || ''
}

function isOpenAICompatibleProvider(provider: string): boolean {
  const normalized = provider.toLowerCase()
  return normalized.includes('openai') && normalized.includes('compatible')
}

function providerCredentialTitle(provider: ModelProviderRow): string {
  return provider.configured ? provider.keyMask || 'API KEY 1' : '未配置'
}

function providerCredentialList(provider: ModelProviderRow | null): ModelProviderRow['credentials'] {
  return provider?.credentials || []
}

function credentialStatusLabel(validation: string): string {
  if (validation === 'valid') return 'Connected'
  if (validation === 'invalid') return 'Connection failed'
  return 'untested'
}

function refreshSelectedProviderRow(providerKey: string) {
  selectedProviderRow.value = providerRows.value.find((provider) => provider.provider === providerKey) || null
}

function modelsForProviderRow(provider: ModelProviderRow): ModelProviderModel[] {
  const seen = new Set<string>()
  return provider.credentials.flatMap((credential) => modelsForProvider(credential.providerId))
    .filter((model) => {
      if (!model.id || seen.has(model.id)) return false
      seen.add(model.id)
      return true
    })
}

function modelRowsForProviderRow(provider: ModelProviderRow) {
  const seen = new Set<string>()
  return provider.credentials.flatMap((credential) =>
    modelsForProvider(credential.providerId).map((model) => ({
      key: modelOptionValue(credential.providerId, model.id || ''),
      providerId: credential.providerId,
      model,
    })),
  ).filter((entry) => {
    if (!entry.model.id || seen.has(entry.key)) return false
    seen.add(entry.key)
    return true
  })
}

function isModelValueDisabled(value: string): boolean {
  return Boolean(value) && disabledProviderModelKeys.value.has(value)
}

function isProviderModelEnabled(providerId: string, modelId: string): boolean {
  return !disabledProviderModelKeys.value.has(modelOptionValue(providerId, modelId))
}

function toggleProviderModelEnabled(providerId: string, modelId: string) {
  const key = modelOptionValue(providerId, modelId)
  const next = new Set(disabledProviderModelKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
    if (ocrSettings.value.model === key) ocrSettings.value.model = ''
    if (parsingSettings.value.model === key) parsingSettings.value.model = ''
    if (qaSettings.value.model === key) qaSettings.value.model = ''
  }
  disabledProviderModelKeys.value = next
}

function providerRowLoading(provider: ModelProviderRow): boolean {
  return provider.credentials.some((credential) => loadingModelProviderId.value === credential.providerId)
}

function providerRowError(provider: ModelProviderRow): string {
  return provider.credentials.map((credential) => providerModelErrors.value[credential.providerId]).find(Boolean) || ''
}

function isProviderModelsCollapsed(provider: ModelProviderRow): boolean {
  return collapsedProviderModels.value.has(provider.id)
}

function toggleProviderModels(provider: ModelProviderRow) {
  const next = new Set(collapsedProviderModels.value)
  if (next.has(provider.id)) next.delete(provider.id)
  else next.add(provider.id)
  collapsedProviderModels.value = next
}

function collapseAllProviderModels() {
  collapsedProviderModels.value = new Set(
    providerRows.value.filter((provider) => provider.configured).map((provider) => provider.id),
  )
}

function fillProviderForm(provider: ModelProviderRow) {
  providerForm.value = {
    providerId: provider.configured ? provider.providerId : '',
    credentialName: provider.configured ? 'API KEY 1' : `${provider.label} credential`,
    provider: provider.provider,
    baseUrl: provider.baseUrl,
    apiKey: '',
  }
  selectedProviderRow.value = provider
}

function selectProviderCredential(credential: ModelProviderRow['credentials'][number]) {
  providerForm.value = {
    providerId: credential.providerId,
    credentialName: 'API KEY 1',
    provider: credential.provider,
    baseUrl: credential.baseUrl,
    apiKey: '',
  }
}

function startAddingProviderCredential() {
  const provider = selectedProviderRow.value
  if (!provider) return
  providerForm.value = {
    providerId: '',
    credentialName: `${provider.label} credential`,
    provider: provider.provider,
    baseUrl: provider.baseUrl,
    apiKey: '',
  }
}

async function deleteProviderCredential(credential: ModelProviderRow['credentials'][number]) {
  if (!credential.providerId) return
  providerError.value = ''
  providerMessage.value = ''
  try {
    await settingsApi.deleteModelProvider(credential.providerId)
    providerMessage.value = 'API Key 已删除。'
    if (providerForm.value.providerId === credential.providerId) startAddingProviderCredential()
    await loadProviders()
    refreshSelectedProviderRow(credential.provider)
    await fetchAllConfiguredProviderModels()
  } catch (error: any) {
    providerError.value = error?.response?.data?.detail || '删除 API Key 失败。'
  }
}

function openProviderCredentialDialog(provider: ModelProviderRow) {
  fillProviderForm(provider)
  compatibleModelDialogOpen.value = false
  providerCredentialDialogOpen.value = true
}

function openCompatibleModelDialog(provider: ModelProviderRow) {
  fillProviderForm(provider)
  compatibleModelForm.value = {
    modelName: '',
    modelType: 'LLM',
    displayName: '',
    endpointModelName: '',
  }
  providerCredentialDialogOpen.value = false
  compatibleModelDialogOpen.value = true
}

function closeProviderConfigDialogs() {
  providerCredentialDialogOpen.value = false
  compatibleModelDialogOpen.value = false
  selectedProviderRow.value = null
  providerForm.value.apiKey = ''
}

function providerSaveDisabled(): boolean {
  return savingProvider.value || !providerForm.value.baseUrl.trim() || (!providerForm.value.providerId && !providerForm.value.apiKey.trim())
}

async function saveProviderAndClose() {
  const savedProviderId = await saveProvider()
  if (!savedProviderId) return
  if (compatibleModelDialogOpen.value && compatibleModelForm.value.modelName.trim()) {
    try {
      await settingsApi.saveModelProviderCustomModel(savedProviderId, {
        model: compatibleModelForm.value.modelName.trim(),
        display_name: compatibleModelForm.value.displayName.trim() || undefined,
        model_type: compatibleModelForm.value.modelType.toLowerCase(),
        endpoint_model_name: compatibleModelForm.value.endpointModelName.trim() || undefined,
        capabilities: [...compatibleModelCapabilities()],
      })
      await fetchProviderModels(savedProviderId, { silent: true })
    } catch (error: any) {
      providerError.value = error?.response?.data?.detail || '保存自定义模型失败。'
      return
    }
  }
  closeProviderConfigDialogs()
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
    collapseAllProviderModels()
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
    providerTestMessages.value = {
      ...providerTestMessages.value,
      [providerId]: models.length > 0 ? `Connected. ${models.length} models loaded.` : 'Connected. No remote models returned.',
    }
  } catch (error: any) {
    const message = error?.response?.data?.detail || 'Failed to fetch models.'
    providerModelErrors.value = {
      ...providerModelErrors.value,
      [providerId]: message,
    }
    providerTestMessages.value = {
      ...providerTestMessages.value,
      [providerId]: message,
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

async function fetchProviderRowModels(provider: ModelProviderRow) {
  await Promise.allSettled(
    provider.credentials.map((credential) =>
      fetchProviderModels(credential.providerId),
    ),
  )
}

async function saveProvider(): Promise<string | null> {
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
    providerMessage.value = 'Provider saved. Loading available models...'
    providerForm.value.apiKey = ''
    await loadProviders()
    if (savedProviderId) {
      await fetchProviderModels(savedProviderId, { silent: true })
      await loadProviders()
    }
    return savedProviderId
  } catch (error: any) {
    providerError.value = error?.response?.data?.detail || '保存模型供应商失败。'
    return null
  } finally {
    savingProvider.value = false
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
  await Promise.all([loadProviders(), loadWebSearchSettings()])
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
            <h2>{{ t('settings.title') }}</h2>
            <p>配置 PageChat 的模型、OCR、解析和问答行为</p>
          </div>
          <button type="button" @click="close" :aria-label="t('settings.close')">
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
            <span>{{ settingsNavLabel(section.id) }}</span>
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
            <span>{{ settingsNavLabel(section.id) }}</span>
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
            <article
              v-for="provider in filteredProviderRows"
              :key="provider.id"
              :class="['provider-row', provider.configured ? 'provider-card-configured' : 'provider-card-unconfigured']"
            >
              <div class="provider-card-top">
                <div class="provider-main">
                  <div class="provider-logo">
                    <img :src="provider.iconUrl" :alt="provider.label" @error="hideBrokenLogo" />
                    <span>{{ providerInitial(provider.label) }}</span>
                  </div>
                  <div class="provider-title">
                    <div>
                      <strong>{{ provider.label }}</strong>
                      <i v-if="provider.configured && provider.validation === 'valid'" class="provider-ready-dot" aria-label="Provider available" />
                      <span>{{ isOpenAICompatibleProvider(provider.provider) ? 'OpenAI-API-compatible' : 'Provider' }}</span>
                    </div>
                    <p>{{ provider.baseUrl }}</p>
                  </div>
                </div>

                <div v-if="provider.configured" class="provider-config-summary">
                  <div class="provider-config-status">
                    <i class="provider-ready-dot" aria-label="Provider available" />
                    <strong>{{ providerCredentialTitle(provider) }}</strong>
                    <span>{{ testingStateForProvider(provider.providerId) || credentialStatusLabel(provider.validation) }}</span>
                  </div>
                  <button class="provider-config-button" type="button" @click="openProviderCredentialDialog(provider)">
                    <SlidersHorizontal />
                    配置
                  </button>
                </div>
              </div>

              <div v-if="provider.configured && providerModelBadges(provider).length" class="provider-service-tags" aria-label="Provider capabilities">
                <span v-for="badge in providerModelBadges(provider)" :key="badge">{{ badge }}</span>
              </div>

              <div v-if="!provider.configured" class="provider-card-notice">
                <span>请配置 API 密钥，添加模型。</span>
                <button
                  type="button"
                  @click="isOpenAICompatibleProvider(provider.provider) ? openCompatibleModelDialog(provider) : openProviderCredentialDialog(provider)"
                >
                  <KeyRound />
                  {{ isOpenAICompatibleProvider(provider.provider) ? '添加模型' : '添加 API 密钥' }}
                </button>
              </div>

              <div v-else class="provider-configured-body">
                <div class="model-list">
                  <div class="model-list-header">
                    <button class="model-count-line" type="button" @click="toggleProviderModels(provider)">
                      {{ modelsForProviderRow(provider).length }} 个模型
                      <ChevronDown />
                    </button>
                    <div class="model-list-actions">
                      <button
                        v-if="isOpenAICompatibleProvider(provider.provider)"
                        type="button"
                        @click="openCompatibleModelDialog(provider)"
                      >
                        添加模型
                      </button>
                      <button
                        type="button"
                        :disabled="providerRowLoading(provider)"
                        @click="fetchProviderRowModels(provider)"
                      >
                        <Loader2 v-if="providerRowLoading(provider)" class="spin" />
                        <RefreshCw v-else />
                        刷新
                      </button>
                    </div>
                  </div>
                  <div v-if="!isProviderModelsCollapsed(provider)" class="model-list-body">
                    <div v-if="providerRowLoading(provider)" class="model-empty">
                      正在获取可用模型...
                    </div>
                    <div v-else-if="providerRowError(provider)" class="model-empty error">
                      {{ providerRowError(provider) }}
                    </div>
                    <div v-else-if="modelsForProviderRow(provider).length === 0" class="model-empty">
                      暂未返回模型。请检查 API Key 或 endpoint 后刷新。
                    </div>
                    <div
                      v-for="entry in modelRowsForProviderRow(provider)"
                      :key="entry.key"
                      class="model-row model-compact-row"
                      :class="{ disabled: !isProviderModelEnabled(entry.providerId, entry.model.id || '') }"
                    >
                      <span class="model-provider-logo">
                        <img :src="provider.iconUrl" :alt="provider.label" @error="hideBrokenLogo" />
                        <small>{{ providerInitial(provider.label) }}</small>
                      </span>
                      <div class="model-inline-main">
                        <strong>{{ entry.model.id }}</strong>
                        <span
                          v-for="capability in modelCapabilityBadges(entry.model)"
                          :key="capability"
                          class="model-capabilities"
                        >
                          {{ capability }}
                        </span>
                        <span
                          v-for="badge in modelMetaBadges(entry.model)"
                          :key="badge"
                          class="model-meta-badge"
                        >
                          {{ badge }}
                        </span>
                      </div>
                      <button
                        class="model-enabled-toggle"
                        :class="{ off: !isProviderModelEnabled(entry.providerId, entry.model.id || '') }"
                        type="button"
                        :aria-pressed="isProviderModelEnabled(entry.providerId, entry.model.id || '')"
                        aria-label="Toggle model availability"
                        @click.stop="toggleProviderModelEnabled(entry.providerId, entry.model.id || '')"
                      />
                    </div>
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
            <div class="wide">
              <div class="field-label">问答模型</div>
              <div v-if="qaModelGroups.length === 0" class="model-empty">
                请先配置模型供应商，并刷新可用模型。
              </div>
              <div v-else class="qa-model-groups">
                <section v-for="group in qaModelGroups" :key="group.providerId" class="qa-model-group">
                  <header>{{ group.providerLabel }}</header>
                  <button
                    v-for="model in group.models"
                    :key="model.value"
                    :class="{ active: qaModelSelected(model) }"
                    class="model-row qa-model-row"
                    type="button"
                    @click="selectQaModel(model)"
                  >
                    <span class="model-provider-logo">
                      <img :src="providerIconForModelOption(model)" :alt="model.providerLabel" @error="hideBrokenLogo" />
                      <small>{{ providerInitialForModelOption(model) }}</small>
                    </span>
                    <span class="model-inline-main">
                      <strong>{{ model.modelId }}</strong>
                      <span
                        v-for="capability in modelCapabilityBadges(model)"
                        :key="capability"
                        class="model-capabilities"
                      >
                        {{ capability }}
                      </span>
                      <span
                        v-for="badge in modelMetaBadgesForOption(model)"
                        :key="badge"
                        class="model-meta-badge"
                      >
                        {{ badge }}
                      </span>
                    </span>
                    <small v-if="!model.capabilities.includes('vision')" class="qa-model-note">
                      图片页将使用 OCR 文本证据
                    </small>
                  </button>
                </section>
              </div>
            </div>
            <div class="wide settings-actions">
              <span>{{ functionalRouteMessage || 'Document Q&A uses the selected answer model route.' }}</span>
              <button type="button" :disabled="savingFunctionalRoutes" @click="saveFunctionalRoutes">
                <Loader2 v-if="savingFunctionalRoutes" class="spin" />
                <CheckCircle2 v-else />
                Save model routing
              </button>
            </div>
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
              <h2>{{ t('settings.languageTitle') }}</h2>
              <p>{{ t('settings.languageDescription') }}</p>
            </div>
          </div>
          <div class="form-grid">
            <label class="wide">
              {{ t('settings.interfaceLanguage') }}
              <select v-model="language" @change="setLanguage(language)">
                <option v-for="option in languageOptions" :key="option.id" :value="option.id">
                  {{ option.label }}
                </option>
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
          <div
            v-if="providerCredentialDialogOpen || compatibleModelDialogOpen"
            class="provider-dialog-backdrop"
            @click.self="closeProviderConfigDialogs"
          >
            <section class="provider-config-dialog" @click.stop>
              <header class="provider-config-header">
                <div>
                  <h3>{{ compatibleModelDialogOpen ? '添加模型' : 'API 密钥授权配置' }}</h3>
                  <p>{{ selectedProviderRow?.label }}</p>
                </div>
                <button type="button" aria-label="Close provider dialog" @click="closeProviderConfigDialogs">
                  <X />
                </button>
              </header>

              <div class="provider-config-body">
                <template v-if="compatibleModelDialogOpen">
                  <label>
                    供应商名称
                    <input :value="selectedProviderRow?.label || providerLabel(providerForm.provider)" disabled />
                  </label>
                  <label>
                    模型名称
                    <input v-model="compatibleModelForm.modelName" placeholder="例如 gpt-4o 或 qwen-vl-max" />
                  </label>
                  <label>
                    模型类型
                    <select v-model="compatibleModelForm.modelType">
                      <option>LLM</option>
                      <option>Vision</option>
                      <option>Embedding</option>
                      <option>OCR</option>
                    </select>
                  </label>
                  <label>
                    凭据名称
                    <input v-model="providerForm.credentialName" />
                  </label>
                  <label>
                    显示名称
                    <input v-model="compatibleModelForm.displayName" placeholder="可选，用于设置页展示" />
                  </label>
                  <label>
                    API Key
                    <input
                      v-model="providerForm.apiKey"
                      type="password"
                      :placeholder="apiKeyPlaceholder(providerForm.providerId)"
                      autocomplete="new-password"
                    />
                  </label>
                  <label class="wide">
                    API endpoint URL
                    <input v-model="providerForm.baseUrl" placeholder="https://api.example.com/v1" />
                  </label>
                  <label class="wide">
                    Endpoint model name
                    <input v-model="compatibleModelForm.endpointModelName" placeholder="留空时使用模型名称" />
                  </label>
                </template>

                <template v-else>
                  <div class="wide provider-credential-list">
                    <div class="field-label">API 密钥</div>
                    <div
                      v-for="credential in providerCredentialList(selectedProviderRow)"
                      :key="credential.providerId"
                      :class="['provider-credential-item', { active: providerForm.providerId === credential.providerId }]"
                      @click="selectProviderCredential(credential)"
                    >
                      <span class="provider-credential-check">{{ providerForm.providerId === credential.providerId ? '✓' : '' }}</span>
                      <span class="provider-credential-dot" />
                      <strong>{{ credential.keyMask }}</strong>
                      <small>{{ credentialStatusLabel(credential.validation) }}</small>
                      <button class="provider-credential-delete" type="button" @click.stop="deleteProviderCredential(credential)">
                        删除
                      </button>
                    </div>
                    <button class="provider-add-credential-button" type="button" @click="startAddingProviderCredential">
                      添加 API 密钥
                    </button>
                  </div>
                  <label class="wide">
                    凭据名称
                    <input v-model="providerForm.credentialName" />
                  </label>
                  <label class="wide">
                    API Key
                    <input
                      v-model="providerForm.apiKey"
                      type="password"
                      :placeholder="apiKeyPlaceholder(providerForm.providerId)"
                      autocomplete="new-password"
                    />
                  </label>
                  <label class="wide">
                    API endpoint URL
                    <input v-model="providerForm.baseUrl" />
                  </label>
                </template>
              </div>

              <p class="provider-security-note">
                {{ providerSecurityNote }}
              </p>

              <footer class="provider-dialog-footer">
                <span>{{ providerForm.providerId ? providerKeyHint(providerForm.providerId) : newProviderKeyHint }}</span>
                <button type="button" @click="closeProviderConfigDialogs">取消</button>
                <button type="button" :disabled="providerSaveDisabled()" @click="saveProviderAndClose">
                  <Loader2 v-if="savingProvider" class="spin" />
                  <CheckCircle2 v-else />
                  保存
                </button>
              </footer>
            </section>
          </div>
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
  position: relative;
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
  box-sizing: border-box;
  min-width: 220px;
  align-items: center;
  gap: 8px;
  width: min(320px, 100%);
  height: 36px;
  flex: 1 1 260px;
  overflow: hidden;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 10px;
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

.provider-search:focus-within {
  border-color: rgba(47, 128, 237, 0.45);
  box-shadow: 0 0 0 3px rgba(47, 128, 237, 0.12);
}

.provider-search input {
  width: 100%;
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  box-shadow: none;
  padding: 0;
  outline: none;
  font-size: 13px;
}

.provider-search input:focus {
  border: 0;
  box-shadow: none;
}

.provider-list {
  display: grid;
  gap: 12px;
}

.provider-row {
  display: grid;
  gap: 12px;
  border: 1px solid var(--kc-border);
  border-radius: 10px;
  background: #fff;
  padding: 14px;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.035);
}

.provider-card-top,
.provider-main,
.provider-card-notice,
.model-list-header,
.model-list-actions {
  display: flex;
  align-items: center;
}

.provider-card-top {
  justify-content: space-between;
  gap: 12px;
}

.provider-main {
  min-width: 0;
  gap: 12px;
}

.provider-logo {
  position: relative;
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  place-items: center;
  border: 1px solid var(--kc-border);
  border-radius: 9px;
  background: linear-gradient(180deg, #fff, #f5f7fb);
  color: var(--kc-text);
  font-size: 11px;
  font-weight: 680;
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
  font-size: 10.5px;
  font-weight: 760;
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
  color: var(--kc-text);
  font-size: 14.5px;
  font-weight: 650;
}

.provider-ready-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12);
}

.provider-title div:first-child span {
  border-radius: 999px;
  background: var(--kc-surface-muted);
  padding: 3px 7px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.provider-title p {
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--kc-text-tertiary);
  font-size: 12.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-config-button,
.provider-card-notice button,
.model-list-header button,
.provider-dialog-footer button,
.settings-actions button,
.account-card button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 32px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 10px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  font-weight: 560;
}

.provider-config-summary {
  display: grid;
  gap: 6px;
  min-width: 160px;
  border: 1px solid var(--kc-border-soft);
  border-radius: 9px;
  background: #fff;
  padding: 8px;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.045);
}

.provider-config-status {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--kc-text);
  font-size: 12.5px;
}

.provider-config-status .provider-ready-dot {
  width: 8px;
  height: 8px;
  box-shadow: none;
}

.provider-config-status strong {
  overflow: hidden;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-config-status span {
  margin-left: auto;
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.provider-config-button {
  width: 100%;
  min-height: 30px;
  justify-content: flex-start;
  border-radius: 8px;
  padding: 0 9px;
  color: var(--kc-text-secondary);
}

.provider-card-notice button,
.provider-dialog-footer button:last-child {
  border-color: rgba(47, 128, 237, 0.28);
  background: #2563eb;
  color: #fff;
}

.provider-card-notice button {
  min-height: 30px;
  padding: 0 12px;
  border-radius: 9px;
  font-size: 12px;
}

.provider-card-notice button svg {
  width: 15px;
  height: 15px;
}

.provider-card-notice button:hover,
.provider-dialog-footer button:last-child:hover {
  background: #1d4ed8;
}

.provider-config-button:hover,
.model-list-header button:hover,
.settings-actions button:hover,
.account-card button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.provider-service-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.provider-service-tags span,
.model-row .model-capabilities,
.model-row .model-meta-badge {
  border: 1px solid var(--kc-border-soft);
  border-radius: 999px;
  background: #f8fafc;
  padding: 3px 7px;
  color: var(--kc-text-secondary);
  font-size: 11px;
}

.provider-card-notice {
  justify-content: space-between;
  gap: 12px;
  border-radius: var(--kc-radius-md);
  background: #f8fafc;
  padding: 10px 12px;
  color: var(--kc-text-tertiary);
  font-size: 12.5px;
}

.provider-configured-body {
  display: grid;
  gap: 12px;
}

.model-list {
  display: grid;
  align-content: start;
  gap: 8px;
  min-height: 0;
}

.model-list-header {
  justify-content: space-between;
  gap: 8px;
}

.model-list-actions {
  gap: 6px;
}

.model-list-header .model-count-line {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  font-weight: 620;
}

.model-list-header button:disabled,
.provider-dialog-footer button:disabled {
  cursor: default;
  opacity: 0.55;
}

.model-list-header svg,
.provider-config-button svg {
  width: 13px;
  height: 13px;
}

.model-list-body {
  display: grid;
  max-height: 260px;
  gap: 0;
  overflow: auto;
  padding-right: 4px;
  scrollbar-width: thin;
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
  gap: 8px;
  min-height: 34px;
  border-bottom: 1px solid var(--kc-border-soft);
  border-radius: 0;
  background: transparent;
  padding: 7px 2px;
}

.model-row:last-child {
  border-bottom: 0;
}

.model-provider-logo {
  position: relative;
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  border: 1px solid var(--kc-border);
  border-radius: 6px;
  background: linear-gradient(180deg, #fff, #f5f7fb);
  color: var(--kc-text-tertiary);
  font-size: 9.5px;
  font-weight: 750;
}

.model-provider-logo img {
  position: relative;
  z-index: 1;
  width: 16px;
  height: 16px;
  object-fit: contain;
}

.model-provider-logo small {
  position: absolute;
  color: var(--kc-text-tertiary);
  font-size: 8.5px;
  font-weight: 750;
}

.model-inline-main {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
}

.model-inline-main strong {
  margin-right: 2px;
  overflow-wrap: anywhere;
  color: var(--kc-text);
  font-size: 12.5px;
  font-weight: 560;
}

.model-row .model-capabilities {
  border-color: rgba(47, 128, 237, 0.18);
  background: #edf6ff;
  color: #145eb8;
}

.model-row .model-meta-badge {
  border-color: rgba(100, 116, 139, 0.18);
  background: #f8fafc;
  color: var(--kc-text-tertiary);
}

.model-row.disabled {
  opacity: 0.52;
}

.model-row.disabled .model-inline-main strong,
.model-row.disabled .model-capabilities,
.model-row.disabled .model-meta-badge {
  color: var(--kc-text-tertiary);
}

.qa-model-groups {
  display: grid;
  max-height: 320px;
  gap: 10px;
  overflow: auto;
  padding-right: 4px;
  scrollbar-width: thin;
}

.qa-model-group {
  display: grid;
  gap: 6px;
}

.qa-model-group header {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  font-weight: 650;
}

.qa-model-row {
  width: 100%;
  min-height: 38px;
  justify-content: space-between;
  border: 0;
  border-bottom: 1px solid var(--kc-border-soft);
  padding: 7px 2px;
  color: var(--kc-text-secondary);
  text-align: left;
}

.qa-model-row.active {
  background: #f4f8ff;
  color: #145eb8;
}

.qa-model-note {
  flex: 0 0 auto;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
}

.model-enabled-toggle {
  position: relative;
  width: 30px;
  height: 18px;
  flex: 0 0 30px;
  border: 0;
  border-radius: 999px;
  background: #2563eb;
  cursor: pointer;
  transition: background 0.16s ease;
}

.model-enabled-toggle::after {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: #fff;
  content: '';
  transition: transform 0.16s ease;
}

.model-enabled-toggle.off {
  background: #cbd5e1;
}

.model-enabled-toggle.off::after {
  right: auto;
  left: 3px;
}

.form-grid,
.account-card {
  border: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-md);
  background: #fbfcfd;
  padding: 12px;
}

.form-grid {
  display: grid;
  gap: 12px;
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

.provider-dialog-backdrop {
  position: absolute;
  inset: 0;
  z-index: 4;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.2);
  backdrop-filter: blur(4px);
}

.provider-config-dialog {
  display: grid;
  width: min(640px, calc(100vw - 72px));
  max-height: min(760px, calc(100vh - 120px));
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  overflow: hidden;
  border: 1px solid rgba(226, 232, 240, 0.9);
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.22);
}

.provider-config-header,
.provider-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
}

.provider-config-header {
  border-bottom: 1px solid var(--kc-border-soft);
}

.provider-config-header h3,
.provider-config-header p,
.provider-security-note {
  margin: 0;
}

.provider-config-header h3 {
  color: var(--kc-text);
  font-size: 17px;
  font-weight: 680;
}

.provider-config-header p {
  margin-top: 3px;
  color: var(--kc-text-tertiary);
  font-size: 12.5px;
}

.provider-config-header button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--kc-text-tertiary);
}

.provider-config-header button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.provider-config-header svg {
  width: 16px;
  height: 16px;
}

.provider-config-body {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  overflow: auto;
  padding: 16px 18px;
}

.provider-config-body .wide {
  grid-column: 1 / -1;
}

.provider-config-body input:disabled {
  background: #f8fafc;
  color: var(--kc-text-tertiary);
}

.provider-credential-list {
  display: grid;
  gap: 8px;
}

.provider-credential-item {
  display: grid;
  grid-template-columns: 20px 8px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  border-radius: var(--kc-radius-md);
  background: #f8fafc;
  padding: 0 10px;
  cursor: pointer;
}

.provider-credential-item.active {
  background: #f1f5f9;
}

.provider-credential-check {
  color: #2563eb;
  font-size: 14px;
  font-weight: 700;
}

.provider-credential-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #22c55e;
}

.provider-credential-item strong {
  overflow: hidden;
  color: var(--kc-text);
  font-size: 13px;
  font-weight: 620;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-credential-item small {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
}

.provider-credential-delete,
.provider-add-credential-button {
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  color: var(--kc-text-secondary);
  font-size: 12px;
}

.provider-credential-delete {
  height: 28px;
  padding: 0 9px;
}

.provider-add-credential-button {
  height: 36px;
}

.provider-security-note {
  border-top: 1px solid var(--kc-border-soft);
  background: #fbfcfd;
  padding: 10px 18px;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  line-height: 17px;
}

.provider-dialog-footer {
  border-top: 1px solid var(--kc-border-soft);
  background: #fff;
}

.provider-dialog-footer span {
  min-width: 0;
  flex: 1;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  line-height: 17px;
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

  .provider-config-body {
    grid-template-columns: 1fr;
  }
}
</style>
