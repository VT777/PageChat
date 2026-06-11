<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CheckCircle2, Loader2, Trash2, AlertCircle } from 'lucide-vue-next'
import { settingsApi } from '@/api'
import type { ModelProviderConfig, ModelProviderPreset } from '@/types/modelSettings'

const emit = defineEmits<{
  changed: []
}>()

const presets = ref<ModelProviderPreset[]>([])
const providers = ref<ModelProviderConfig[]>([])
const loading = ref(false)
const saving = ref(false)
const testingProviderId = ref<string | null>(null)
const message = ref('')
const error = ref('')

const selectedPreset = ref('openai_compatible')
const baseUrl = ref('')
const apiKey = ref('')
const testModel = ref('')
const editingProviderId = ref<string | null>(null)

const currentPreset = computed(() =>
  presets.value.find((preset) => preset.provider === selectedPreset.value)
)

function applyPreset() {
  const preset = currentPreset.value
  if (!preset) return
  if (!preset.supports_custom_base_url) baseUrl.value = preset.base_url
  if (!baseUrl.value) baseUrl.value = preset.base_url
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [presetResponse, providerResponse] = await Promise.all([
      settingsApi.getModelProviderPresets(),
      settingsApi.listModelProviders(),
    ])
    presets.value = presetResponse.data || []
    providers.value = providerResponse.data || []
    if (!baseUrl.value) applyPreset()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || 'Failed to load model providers'
  } finally {
    loading.value = false
  }
}

async function saveProvider() {
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    if (editingProviderId.value) {
      await settingsApi.updateModelProvider(editingProviderId.value, {
        provider: selectedPreset.value,
        base_url: baseUrl.value,
        ...(apiKey.value ? { api_key: apiKey.value } : {}),
      })
    } else {
      await settingsApi.saveModelProvider({
        provider: selectedPreset.value,
        base_url: baseUrl.value,
        api_key: apiKey.value,
      })
    }
    apiKey.value = ''
    editingProviderId.value = null
    message.value = 'Provider saved. Stored keys remain write-only.'
    await load()
    emit('changed')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || 'Failed to save provider'
  } finally {
    saving.value = false
  }
}

function editProvider(provider: ModelProviderConfig) {
  editingProviderId.value = provider.provider_id
  selectedPreset.value = provider.provider
  baseUrl.value = provider.base_url
  apiKey.value = ''
  message.value = 'Editing non-secret fields. Leave API key empty to preserve the saved key.'
  error.value = ''
}

async function deleteProvider(providerId: string) {
  if (!confirm('Routes using this provider will fall back to server defaults until remapped. Delete it?')) return
  error.value = ''
  message.value = ''
  try {
    await settingsApi.deleteModelProvider(providerId)
    message.value = 'Provider deleted. Affected routes will use server defaults.'
    await load()
    emit('changed')
  } catch (err: any) {
    error.value = err?.response?.data?.detail || 'Failed to delete provider'
  }
}

async function testProvider(provider: ModelProviderConfig) {
  testingProviderId.value = provider.provider_id
  error.value = ''
  message.value = ''
  try {
    await settingsApi.testModelProvider(provider.provider_id, testModel.value || 'default')
    message.value = 'Connection test passed.'
  } catch (err: any) {
    error.value = err?.response?.data?.detail || 'Connection test failed'
  } finally {
    testingProviderId.value = null
  }
}

onMounted(load)
</script>

<template>
  <section class="space-y-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h3 class="font-medium">Model providers</h3>
        <p class="text-sm text-muted-foreground">Save OpenAI-compatible providers without exposing stored keys.</p>
      </div>
      <Loader2 v-if="loading" class="w-4 h-4 animate-spin text-muted-foreground" />
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <label class="space-y-1 text-sm">
        <span class="text-muted-foreground">Provider</span>
        <select v-model="selectedPreset" @change="applyPreset" class="w-full rounded-lg border bg-background px-3 py-2">
          <option v-for="preset in presets" :key="preset.provider" :value="preset.provider">
            {{ preset.label }}
          </option>
        </select>
      </label>
      <label class="space-y-1 text-sm">
        <span class="text-muted-foreground">Base URL</span>
        <input
          v-model="baseUrl"
          :disabled="currentPreset && !currentPreset.supports_custom_base_url"
          class="w-full rounded-lg border bg-background px-3 py-2 disabled:opacity-60"
        />
      </label>
      <label class="space-y-1 text-sm md:col-span-2">
        <span class="text-muted-foreground">API key</span>
        <input
          v-model="apiKey"
          type="password"
          autocomplete="new-password"
          placeholder="Paste a key to save or replace"
          class="w-full rounded-lg border bg-background px-3 py-2"
        />
      </label>
    </div>

    <button
      class="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
      :disabled="saving || !selectedPreset || !baseUrl || (!editingProviderId && !apiKey)"
      @click="saveProvider"
    >
      <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
      <CheckCircle2 v-else class="w-4 h-4" />
      {{ editingProviderId ? (apiKey ? 'Replace key and save' : 'Save fields') : 'Save provider' }}
    </button>

    <div class="space-y-2">
      <div v-for="provider in providers" :key="provider.provider_id" class="rounded-lg border p-3">
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="font-medium truncate">{{ provider.provider }}</p>
            <p class="text-xs text-muted-foreground truncate">{{ provider.base_url }}</p>
            <p class="text-xs text-muted-foreground">Saved key {{ provider.api_key_mask || 'stored' }}</p>
          </div>
          <button class="rounded-md p-1.5 text-destructive hover:bg-destructive/10" @click="deleteProvider(provider.provider_id)">
            <Trash2 class="w-4 h-4" />
          </button>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <input v-model="testModel" placeholder="Model for test" class="min-w-0 flex-1 rounded-lg border bg-background px-3 py-1.5 text-sm" />
          <button class="rounded-lg border px-3 py-1.5 text-sm hover:bg-accent" @click="editProvider(provider)">
            Edit
          </button>
          <button class="rounded-lg border px-3 py-1.5 text-sm hover:bg-accent" @click="testProvider(provider)">
            <Loader2 v-if="testingProviderId === provider.provider_id" class="inline w-3.5 h-3.5 animate-spin" />
            Test
          </button>
        </div>
      </div>
    </div>

    <p v-if="message" class="text-sm text-emerald-600">{{ message }}</p>
    <p v-if="error" class="flex items-center gap-1 text-sm text-destructive">
      <AlertCircle class="w-4 h-4" />
      {{ error }}
    </p>
  </section>
</template>
