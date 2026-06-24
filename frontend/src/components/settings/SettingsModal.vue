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
  Search,
  Settings2,
  SlidersHorizontal,
  TestTube2,
  User,
  X,
} from 'lucide-vue-next'
import { settingsApi } from '@/api'
import { useUserStore } from '@/stores/user'
import type { ModelProviderConfig, ModelProviderPreset } from '@/types/modelSettings'
import {
  PARSING_BATCH_CONCURRENCY_SETTING,
  PARSE_MODE_OPTIONS,
  SETTINGS_NAV_SECTIONS,
  WEB_SEARCH_MODE_OPTIONS,
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
const activeSection = ref<SectionId>('providers')
const providers = ref<ModelProviderConfig[]>([])
const presets = ref<ModelProviderPreset[]>([])
const loadingProviders = ref(false)
const savingProvider = ref(false)
const testingProviderId = ref<string | null>(null)
const providerMessage = ref('')
const providerError = ref('')
const expandedProviderId = ref<string | null>(null)

const providerForm = ref({
  providerId: '',
  credentialName: 'Default credential',
  provider: 'openai_compatible',
  baseUrl: 'https://api.openai.com/v1',
  apiKey: '',
  testModel: 'gpt-4.1',
})

const ocrSettings = ref({
  model: 'OpenAI Compatible: gpt-4.1',
  concurrency: 3,
  vlmPrompt: '请只根据页面图像识别版面结构、表格和图片语义，不要编造不可见内容。',
})

const parsingSettings = ref({
  model: 'OpenAI Compatible: gpt-4.1',
  mode: 'smart',
  batchParseConcurrency: PARSING_BATCH_CONCURRENCY_SETTING.defaultValue,
})

const qaSettings = ref({
  model: 'OpenAI Compatible: gpt-4.1',
  webSearchMode: 'on-demand',
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
  if (providers.value.length > 0) {
    return providers.value.map((provider) => ({
      id: provider.provider_id,
      provider: provider.provider,
      label: providerLabel(provider.provider),
      baseUrl: provider.base_url,
      configured: true,
      keyMask: provider.api_key_mask || 'stored',
      validation: provider.validation_status || 'Configured',
    }))
  }
  return defaultProviders().map((provider) => ({
    id: provider.provider,
    provider: provider.provider,
    label: provider.label,
    baseUrl: provider.base_url,
    configured: false,
    keyMask: '',
    validation: 'Not configured',
  }))
})

const availableModels = computed(() => {
  const base = providers.value.length > 0
    ? providers.value.map((provider) => `${provider.provider}: ${providerForm.value.testModel || 'default'}`)
    : ['OpenAI Compatible: gpt-4.1', 'OpenAI Compatible: gpt-4.1-mini', 'Local: qwen2.5-vl']
  return Array.from(new Set(base))
})

function navIcon(icon: string) {
  return iconMap[icon as keyof typeof iconMap] || Settings2
}

function providerLabel(provider: string) {
  const normalized = provider.toLowerCase()
  if (normalized.includes('openai') && normalized.includes('compatible')) return 'OpenAI Compatible'
  if (normalized.includes('openai')) return 'OpenAI'
  if (normalized.includes('anthropic')) return 'Anthropic'
  if (normalized.includes('gemini') || normalized.includes('google')) return 'Google Gemini'
  if (normalized.includes('azure')) return 'Azure OpenAI'
  if (normalized.includes('ollama')) return 'Ollama'
  return provider
}

function providerInitial(label: string) {
  if (label === 'OpenAI') return '◎'
  if (label === 'Anthropic') return 'A'
  if (label === 'Google Gemini') return 'G'
  if (label === 'Azure OpenAI') return 'Az'
  if (label === 'Ollama') return 'Ol'
  return 'OC'
}

function defaultProviders(): ModelProviderPreset[] {
  return [
    { provider: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', supports_custom_base_url: false },
    { provider: 'anthropic', label: 'Anthropic', base_url: 'https://api.anthropic.com', supports_custom_base_url: false },
    { provider: 'google_gemini', label: 'Google Gemini', base_url: 'https://generativelanguage.googleapis.com/v1beta', supports_custom_base_url: false },
    { provider: 'azure_openai', label: 'Azure OpenAI', base_url: 'https://{resource}.openai.azure.com', supports_custom_base_url: true },
    { provider: 'ollama', label: 'Ollama', base_url: 'http://localhost:11434/v1', supports_custom_base_url: true },
    { provider: 'openai_compatible', label: 'OpenAI Compatible', base_url: 'https://api.openai.com/v1', supports_custom_base_url: true },
  ]
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

function startConfigure(provider: string, baseUrl: string, providerId = '') {
  providerForm.value = {
    providerId,
    credentialName: `${providerLabel(provider)} credential`,
    provider,
    baseUrl,
    apiKey: '',
    testModel: providerForm.value.testModel || 'gpt-4.1',
  }
  expandedProviderId.value = providerId || provider
}

async function saveProvider() {
  savingProvider.value = true
  providerError.value = ''
  providerMessage.value = ''
  try {
    if (providerForm.value.providerId) {
      await settingsApi.updateModelProvider(providerForm.value.providerId, {
        provider: providerForm.value.provider,
        base_url: providerForm.value.baseUrl,
        ...(providerForm.value.apiKey ? { api_key: providerForm.value.apiKey } : {}),
      })
    } else {
      await settingsApi.saveModelProvider({
        provider: providerForm.value.provider,
        base_url: providerForm.value.baseUrl,
        api_key: providerForm.value.apiKey,
      })
    }
    providerMessage.value = '模型供应商已保存。'
    providerForm.value.apiKey = ''
    await loadProviders()
  } catch (error: any) {
    providerError.value = error?.response?.data?.detail || '保存模型供应商失败。'
  } finally {
    savingProvider.value = false
  }
}

async function testProvider(providerId: string) {
  testingProviderId.value = providerId
  providerError.value = ''
  providerMessage.value = ''
  try {
    await settingsApi.testModelProvider(providerId, providerForm.value.testModel || 'default')
    providerMessage.value = '连接测试通过。'
  } catch (error: any) {
    providerError.value = error?.response?.data?.detail || '连接测试失败。'
  } finally {
    testingProviderId.value = null
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

onMounted(loadProviders)
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
              <input placeholder="Search providers" />
            </div>
          </div>

          <div class="provider-list">
            <article v-for="provider in providerRows" :key="provider.id" class="provider-row">
              <div class="provider-main">
                <div class="provider-logo">{{ providerInitial(provider.label) }}</div>
                <div class="provider-title">
                  <div>
                    <strong>{{ provider.label }}</strong>
                    <span>{{ provider.configured ? 'Configured' : 'Not configured' }}</span>
                  </div>
                  <p>{{ provider.baseUrl }}</p>
                  <div class="capability-row">
                    <span>LLM</span>
                    <span>Vision</span>
                    <span>Embedding</span>
                    <span>Tool Calling</span>
                  </div>
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
                  @click="expandedProviderId = expandedProviderId === provider.id ? null : provider.id"
                >
                  <ChevronDown />
                </button>
              </div>

              <div v-if="expandedProviderId === provider.id" class="provider-expanded">
                <div class="model-list">
                  <div v-for="model in availableModels.slice(0, 3)" :key="model" class="model-row">
                    <span>{{ model }}</span>
                    <div>
                      <small>128k context</small>
                      <span>Vision</span>
                      <span>Tools</span>
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
                    <input v-model="providerForm.apiKey" type="password" placeholder="sk-..." autocomplete="new-password" />
                  </label>
                  <label>
                    自定义 API endpoint 地址
                    <input v-model="providerForm.baseUrl" />
                  </label>
                  <label>
                    测试模型
                    <input v-model="providerForm.testModel" />
                  </label>
                  <div class="credential-actions">
                    <span>密钥会以加密形式存储，保存后仅显示脱敏值。</span>
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
                      <TestTube2 v-else />
                      Test
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
                <option v-for="model in availableModels" :key="model" :value="model">{{ model }}</option>
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
                <option v-for="model in availableModels" :key="model" :value="model">{{ model }}</option>
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
                <option v-for="model in availableModels" :key="model" :value="model">{{ model }}</option>
              </select>
            </label>
            <div class="wide">
              <div class="field-label">Web Search</div>
              <div class="mode-options two">
                <button
                  v-for="mode in WEB_SEARCH_MODE_OPTIONS"
                  :key="mode.id"
                  :class="{ active: qaSettings.webSearchMode === mode.id }"
                  type="button"
                  @click="qaSettings.webSearchMode = mode.id"
                >
                  <strong>{{ mode.label }}</strong>
                  <small>{{ mode.description }}</small>
                </button>
              </div>
            </div>
          </div>
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
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
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
  align-items: center;
  gap: 8px;
  width: 260px;
  height: 34px;
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
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  border: 1px solid var(--kc-border);
  border-radius: 10px;
  background: linear-gradient(180deg, #fff, #f3f6fb);
  color: var(--kc-text);
  font-size: 13px;
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

.capability-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.capability-row span,
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
  gap: 5px;
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
