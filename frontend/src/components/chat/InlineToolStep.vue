<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  FileSearch,
  FileSpreadsheet,
  Files,
  FolderTree,
  Image,
  ListTree,
  Loader2,
  Sparkles,
} from 'lucide-vue-next'
import type { ToolStep } from '@/stores/chat'
import { summarizeToolStep } from '@/ui/pagechatContracts'

const props = defineProps<{
  step: ToolStep
}>()

const expanded = ref(false)

const iconMap = {
  BookOpen,
  FileSearch,
  FileSpreadsheet,
  Files,
  FolderTree,
  Image,
  ListTree,
  Sparkles,
}

const summary = computed(() => summarizeToolStep(props.step))
const SummaryIcon = computed(() => iconMap[summary.value.icon as keyof typeof iconMap] || Sparkles)

const argumentRows = computed(() => objectRows(props.step.arguments))
const resultRows = computed(() => props.step.result ? objectRows(props.step.result) : [])

function scrubLargeValues(value: unknown, depth = 0): unknown {
  if (depth > 4) return '[Collapsed]'
  if (typeof value === 'string') {
    return value.length > 600 ? `${value.slice(0, 600)}... [truncated ${value.length - 600} chars]` : value
  }
  if (Array.isArray(value)) {
    if (value.length > 8) {
      return [
        ...value.slice(0, 8).map((item) => scrubLargeValues(item, depth + 1)),
        `[${value.length - 8} more items]`,
      ]
    }
    return value.map((item) => scrubLargeValues(item, depth + 1))
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        scrubLargeValues(item, depth + 1),
      ])
    )
  }
  return value
}

function formatJSON(value: unknown): string {
  try {
    return JSON.stringify(scrubLargeValues(value), null, 2)
  } catch {
    return String(value)
  }
}

function labelForKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function compactValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'None'
  if (typeof value === 'string') return value.length > 120 ? `${value.slice(0, 120)}...` : value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    if (value.length === 0) return '0 items'
    const named = value
      .slice(0, 3)
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item)
        const record = item as Record<string, unknown>
        return record.name || record.original_name || record.title || record.id || 'item'
      })
      .join(', ')
    return value.length > 3 ? `${named} +${value.length - 3} more` : named
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const known = record.name || record.original_name || record.title || record.status || record.id
    if (known) return String(known)
    return `${Object.keys(record).length} fields`
  }
  return String(value)
}

function objectRows(value: Record<string, unknown>): Array<{ key: string; label: string; value: string }> {
  return Object.entries(value)
    .filter(([key]) => !['content', 'full_text', 'raw_text', 'ocr_text', 'markdown', 'html'].includes(key))
    .slice(0, 6)
    .map(([key, item]) => ({
      key,
      label: labelForKey(key),
      value: compactValue(item),
    }))
}
</script>

<template>
  <div class="inline-tool-step">
    <button class="tool-line" type="button" @click="expanded = !expanded">
      <span :class="['tool-status-dot', summary.tone]">
        <Loader2 v-if="summary.tone === 'running'" class="tool-spinner" />
        <component :is="SummaryIcon" v-else class="tool-icon" />
      </span>
      <span class="tool-action">{{ summary.action }}</span>
      <span v-if="summary.detail" class="tool-detail">· {{ summary.detail }}</span>
      <ChevronDown v-if="expanded" class="tool-chevron" />
      <ChevronRight v-else class="tool-chevron" />
    </button>

    <div v-if="expanded" class="tool-inspector">
      <div class="tool-inspector-section">
        <div class="tool-inspector-label">Parameters</div>
        <div v-if="argumentRows.length" class="tool-kv-list">
          <div v-for="row in argumentRows" :key="`arg-${row.key}`" class="tool-kv-row">
            <span>{{ row.label }}</span>
            <strong>{{ row.value }}</strong>
          </div>
        </div>
        <pre v-else>{{ formatJSON(step.arguments) }}</pre>
      </div>
      <div class="tool-inspector-section">
        <div class="tool-inspector-label">Result</div>
        <div v-if="resultRows.length" class="tool-kv-list">
          <div v-for="row in resultRows" :key="`result-${row.key}`" class="tool-kv-row">
            <span>{{ row.label }}</span>
            <strong>{{ row.value }}</strong>
          </div>
        </div>
        <pre v-else>{{ step.result ? formatJSON(step.result) : 'Waiting for result...' }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inline-tool-step {
  width: 100%;
}

.tool-line {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 6px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--kc-text-secondary);
  padding: 3px 5px 3px 0;
  text-align: left;
  font-size: 12.5px;
  line-height: 18px;
}

.tool-line:hover {
  color: var(--kc-text);
}

.tool-status-dot {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  place-items: center;
  border-radius: 999px;
  background: transparent;
  color: var(--kc-text-tertiary);
}

.tool-status-dot.success {
  color: #667085;
}

.tool-status-dot.running {
  color: var(--kc-accent);
}

.tool-status-dot.error {
  color: var(--kc-danger);
}

.tool-icon,
.tool-spinner,
.tool-chevron {
  width: 13px;
  height: 13px;
  stroke-width: 1.9;
}

.tool-spinner {
  animation: spin 1s linear infinite;
}

.tool-action {
  min-width: 0;
  overflow: hidden;
  color: inherit;
  font-weight: 560;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-detail {
  min-width: 0;
  overflow: hidden;
  color: var(--kc-text-tertiary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-chevron {
  flex: 0 0 auto;
  margin-left: -2px;
  color: var(--kc-text-tertiary);
}

.tool-inspector {
  display: grid;
  gap: 7px;
  margin: 3px 0 9px 24px;
  max-width: min(760px, 100%);
  border-left: 1px solid var(--kc-border-soft);
  padding-left: 12px;
}

.tool-inspector-label {
  margin-bottom: 5px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
  font-weight: 650;
}

.tool-kv-list {
  display: grid;
  gap: 4px;
}

.tool-kv-row {
  display: grid;
  grid-template-columns: minmax(88px, 132px) minmax(0, 1fr);
  gap: 10px;
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
  line-height: 17px;
}

.tool-kv-row strong {
  min-width: 0;
  overflow: hidden;
  color: var(--kc-text-secondary);
  font-weight: 540;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-inspector pre {
  max-height: 180px;
  overflow: auto;
  border: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-sm);
  background: #f8fafc;
  padding: 8px 10px;
  color: #243041;
  font-size: 11px;
  line-height: 16px;
  white-space: pre-wrap;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
