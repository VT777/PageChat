<script setup lang="ts">
import { computed, ref } from 'vue'
import { Brain, ChevronDown, ChevronRight, Circle } from 'lucide-vue-next'
import type { ProgressStep, ToolStep } from '@/stores/chat'
import ToolTimelineItem from './ToolTimelineItem.vue'

const props = defineProps<{
  progressSteps?: ProgressStep[]
  toolSteps?: ToolStep[]
  isLoading?: boolean
}>()

interface TimelineEntry {
  kind: 'progress' | 'tool'
  key: string
  seq: number
  order: number
  message?: string
  tool?: ToolStep
}

const UNSEQUENCED_BASE = 1_000_000_000
const expandedThought = ref(false)

const hasTools = computed(() => (props.toolSteps || []).length > 0)

const progressEntries = computed<TimelineEntry[]>(() =>
  (props.progressSteps || []).map((step, index) => ({
    kind: 'progress',
    key: `progress-${step.seq ?? index}`,
    seq: step.seq ?? UNSEQUENCED_BASE + index,
    order: index,
    message: step.message,
  })),
)

const timelineEntries = computed<TimelineEntry[]>(() => {
  const progressCount = progressEntries.value.length
  const tools = (props.toolSteps || []).map((tool, index) => ({
    kind: 'tool' as const,
    key: `tool-${tool.seq ?? index}-${tool.toolName}`,
    seq: tool.seq ?? UNSEQUENCED_BASE + progressCount + index,
    order: progressCount + index,
    tool,
  }))
  return [...progressEntries.value, ...tools].sort((a, b) => a.seq - b.seq || a.order - b.order)
})

const thoughtLabel = computed(() => (
  props.isLoading ? 'Thinking...' : 'Thought for a moment'
))

const showThoughtDetails = computed(() => props.isLoading || expandedThought.value)
</script>

<template>
  <div
    v-if="progressEntries.length || hasTools"
    class="run-timeline"
    data-testid="run-timeline"
  >
    <template v-if="hasTools">
      <div
        v-for="entry in timelineEntries"
        :key="entry.key"
        class="timeline-row"
        :data-kind="entry.kind"
      >
        <div v-if="entry.kind === 'progress'" class="progress-row">
          <Circle class="progress-dot" />
          <span>{{ entry.message }}</span>
        </div>
        <ToolTimelineItem v-else-if="entry.tool" :tool="entry.tool" />
      </div>
    </template>

    <template v-else>
      <button
        class="thought-row"
        type="button"
        :aria-expanded="showThoughtDetails"
        @click="expandedThought = !expandedThought"
      >
        <Brain class="thought-icon" />
        <span>{{ thoughtLabel }}</span>
        <ChevronDown v-if="showThoughtDetails" />
        <ChevronRight v-else />
      </button>
      <div v-if="showThoughtDetails" class="thought-details">
        <div
          v-for="entry in progressEntries"
          :key="entry.key"
          class="progress-row"
        >
          <Circle class="progress-dot" />
          <span>{{ entry.message }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.run-timeline {
  width: 100%;
  margin: 2px 0 10px;
  color: var(--kc-text-secondary);
}

.timeline-row {
  display: block;
}

.progress-row,
.thought-row {
  display: flex;
  min-height: 28px;
  align-items: center;
  gap: 8px;
  color: var(--kc-text-secondary);
  font-size: 13px;
}

.thought-row {
  border: 0;
  background: transparent;
  cursor: pointer;
  padding: 4px 0;
}

.thought-row:hover {
  color: var(--kc-text);
}

.thought-row svg,
.progress-dot {
  width: 14px;
  height: 14px;
  stroke-width: 1.9;
}

.thought-icon {
  color: var(--kc-accent);
}

.progress-dot {
  color: var(--kc-text-tertiary);
  fill: currentColor;
  opacity: 0.55;
}

.thought-details {
  margin-left: 22px;
  border-left: 1px solid var(--kc-border-soft);
  padding-left: 10px;
}
</style>
