<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileSearch,
  Loader2,
} from 'lucide-vue-next'
import type { ToolStep } from '@/stores/chat'

const props = defineProps<{
  tool: ToolStep
}>()

const expanded = ref(false)

const toolLabels: Record<string, string> = {
  view_folder_structure: 'View folder structure',
  browse_documents: 'Browse documents',
  get_document_structure: 'Read document structure',
  get_page_content: 'Read page content',
  get_page_image: 'View page image',
  get_document_image: 'View document image',
  search_within_document: 'Search within document',
  aggregate_tables: 'Analyze table data',
  web_search: 'Search the web',
}

const label = computed(() => toolLabels[props.tool.toolName] || props.tool.toolName)
const panelId = computed(() => `tool-panel-${props.tool.toolName}-${props.tool.seq ?? 'unsequenced'}`)

const target = computed(() => {
  const args = props.tool.arguments || {}
  if (typeof args.doc_name === 'string') return args.doc_name
  if (typeof args.doc_id === 'string') return args.doc_id
  if (typeof args.folder_id === 'string') return `Folder ${args.folder_id}`
  if (typeof args.query === 'string') return args.query
  if (typeof args.image_path === 'string') return args.image_path
  return ''
})

const resultCount = computed(() => {
  if (typeof props.tool.resultsCount === 'number') return props.tool.resultsCount
  const result = props.tool.result || {}
  if (typeof result.result_count === 'number') return result.result_count
  for (const key of ['documents', 'matches', 'pages', 'results', 'items']) {
    const value = result[key]
    if (Array.isArray(value)) return value.length
  }
  return null
})

const resultLabel = computed(() => {
  const result = props.tool.result || {}
  if (typeof result.result_label === 'string' && result.result_label.trim()) {
    return result.result_label
  }
  return resultCount.value !== null ? `${resultCount.value} results` : ''
})

function formatJSON(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}
</script>

<template>
  <div class="tool-timeline-item" :class="{ expanded }">
    <button
      class="tool-row"
      type="button"
      :aria-expanded="expanded"
      :aria-controls="panelId"
      @click="expanded = !expanded"
    >
      <span class="tool-state" :class="tool.status">
        <Loader2 v-if="tool.status === 'calling'" class="spin" />
        <CheckCircle2 v-else />
      </span>
      <FileSearch class="tool-icon" />
      <span class="tool-title">{{ label }}</span>
      <ChevronDown v-if="expanded" class="tool-chevron" />
      <ChevronRight v-else class="tool-chevron" />
      <span v-if="target" class="tool-target">{{ target }}</span>
      <span v-if="resultLabel" class="tool-meta">{{ resultLabel }}</span>
      <span v-if="tool.elapsedMs !== undefined" class="tool-meta">
        <Clock3 />
        {{ tool.elapsedMs }}ms
      </span>
    </button>

    <div v-if="expanded" :id="panelId" class="tool-panel">
      <section v-if="tool.argumentText && !tool.result">
        <span>Partial parameters</span>
        <pre>{{ tool.argumentText }}</pre>
      </section>
      <section>
        <span>Parameters</span>
        <pre>{{ formatJSON(tool.arguments) }}</pre>
      </section>
      <section v-if="tool.result">
        <span>Result</span>
        <pre>{{ formatJSON(tool.result) }}</pre>
      </section>
    </div>
  </div>
</template>

<style scoped>
.tool-timeline-item {
  display: block;
}

.tool-row {
  display: flex;
  width: 100%;
  min-height: 28px;
  align-items: center;
  gap: 7px;
  border: 0;
  background: transparent;
  color: var(--kc-text-secondary);
  cursor: pointer;
  padding: 4px 0;
  text-align: left;
}

.tool-row:hover .tool-title {
  color: var(--kc-text);
}

.tool-state,
.tool-icon,
.tool-chevron {
  display: inline-flex;
  flex: 0 0 auto;
  color: var(--kc-text-tertiary);
}

.tool-state.done {
  color: #1f9d55;
}

.tool-state.calling {
  color: var(--kc-accent);
}

.tool-state svg,
.tool-icon,
.tool-chevron,
.tool-meta svg {
  width: 14px;
  height: 14px;
  stroke-width: 1.9;
}

.tool-title {
  color: var(--kc-text-secondary);
  font-size: 13px;
  font-weight: 550;
}

.tool-target {
  min-width: 0;
  max-width: 280px;
  overflow: hidden;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-meta {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.tool-meta + .tool-meta {
  margin-left: 6px;
}

.tool-panel {
  display: grid;
  gap: 8px;
  margin: 4px 0 8px 28px;
  border-left: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-sm);
  background: var(--kc-surface-muted);
  padding: 8px 10px;
}

.tool-panel span {
  display: block;
  margin-bottom: 4px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
  font-weight: 650;
}

.tool-panel pre {
  max-height: 180px;
  overflow: auto;
  margin: 0;
  color: var(--kc-text-secondary);
  font: 11px/1.45 "SF Mono", Monaco, Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

.spin {
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
