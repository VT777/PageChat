<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loader2, Save } from 'lucide-vue-next'
import { settingsApi } from '@/api'
import type { ModelProviderConfig, ModelRouteMapping, ModelRouteSlot } from '@/types/modelSettings'

const routeLabels: Array<{ slot: ModelRouteSlot; label: string; hint: string; vision?: boolean }> = [
  { slot: 'general_chat', label: 'General chat', hint: 'Everyday conversation and non-document answers.' },
  { slot: 'document_qa', label: 'Document Q&A', hint: 'Grounded answers over selected documents.' },
  { slot: 'query_expansion', label: 'Query expansion', hint: 'Search planning and alternate query generation.' },
  { slot: 'indexing', label: 'Index generation', hint: 'Production-backed by Phase 5.1 indexing route verification.' },
  { slot: 'vision', label: 'Vision/OCR enrichment', hint: 'Use a vision-capable provider when available.', vision: true },
]

const providers = ref<ModelProviderConfig[]>([])
const routes = ref<Record<string, ModelRouteMapping>>({})
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const error = ref('')

const providerOptions = computed(() => providers.value)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [providerResponse, routeResponse] = await Promise.all([
      settingsApi.listModelProviders(),
      settingsApi.listModelRoutes(),
    ])
    providers.value = providerResponse.data || []
    routes.value = Object.fromEntries((routeResponse.data || []).map((route: ModelRouteMapping) => [route.route_slot, route]))
  } catch (err: any) {
    error.value = err?.response?.data?.detail || 'Failed to load model routes'
  } finally {
    loading.value = false
  }
}

function routeFor(slot: ModelRouteSlot): ModelRouteMapping {
  if (!routes.value[slot]) {
    routes.value[slot] = { route_slot: slot, provider_id: '', model: '', supports_vision: slot === 'vision' }
  }
  return routes.value[slot]
}

async function saveRoutes() {
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    const payload = routeLabels
      .map(({ slot }) => routeFor(slot))
      .filter((route) => route.provider_id && route.model)
    await settingsApi.saveModelRoutes(payload)
    message.value = 'Routes saved. Empty routes continue to use server defaults.'
    await load()
  } catch (err: any) {
    error.value = err?.response?.data?.detail || 'Failed to save routes'
  } finally {
    saving.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section class="space-y-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <h3 class="font-medium">Route mapping</h3>
        <p class="text-sm text-muted-foreground">Map user-facing tasks to saved providers or leave them on server defaults.</p>
      </div>
      <Loader2 v-if="loading" class="w-4 h-4 animate-spin text-muted-foreground" />
    </div>

    <div class="space-y-3">
      <div v-for="route in routeLabels" :key="route.slot" class="rounded-lg border p-3">
        <div class="mb-3 flex items-start justify-between gap-3">
          <div>
            <p class="font-medium">{{ route.label }}</p>
            <p class="text-xs text-muted-foreground">{{ route.hint }}</p>
          </div>
          <span v-if="!routeFor(route.slot).provider_id" class="rounded-full bg-muted px-2 py-1 text-xs text-muted-foreground">
            Server default
          </span>
        </div>
        <div class="grid gap-2 md:grid-cols-[1fr_1fr_auto]">
          <select v-model="routeFor(route.slot).provider_id" class="rounded-lg border bg-background px-3 py-2 text-sm">
            <option value="">Server default</option>
            <option v-for="provider in providerOptions" :key="provider.provider_id" :value="provider.provider_id">
              {{ provider.provider }} · {{ provider.api_key_mask || 'saved key' }}
            </option>
          </select>
          <input v-model="routeFor(route.slot).model" placeholder="Model ID" class="rounded-lg border bg-background px-3 py-2 text-sm" />
          <label class="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <input v-model="routeFor(route.slot).supports_vision" type="checkbox" :disabled="!route.vision" />
            Vision
          </label>
        </div>
      </div>
    </div>

    <button
      class="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
      :disabled="saving"
      @click="saveRoutes"
    >
      <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
      <Save v-else class="w-4 h-4" />
      Save routes
    </button>
    <p v-if="message" class="text-sm text-emerald-600">{{ message }}</p>
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
  </section>
</template>
