<script setup lang="ts">
import { computed, ref } from 'vue'
import { Brain, ChevronDown, ChevronRight } from 'lucide-vue-next'
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

const visibleProgressSteps = computed(() =>
  (props.progressSteps || []).filter((step) => (
    step.kind !== 'guardrail' && step.kind !== 'observation'
  )),
)

const progressEntries = computed<TimelineEntry[]>(() =>
  visibleProgressSteps.value.map((step, index) => ({
    kind: 'progress',
    key: `progress-${step.step ?? step.seq ?? index}`,
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
    v-if="timelineEntries.length"
    class="run-timeline"
    data-testid="run-timeline"
  >
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
        v-for="entry in timelineEntries"
        :key="entry.key"
        class="timeline-row"
        :data-kind="entry.kind"
      >
        <div v-if="entry.kind === 'progress'" class="progress-row">
          <p>{{ entry.message }}</p>
        </div>
        <ToolTimelineItem v-else-if="entry.tool" :tool="entry.tool" />
      </div>
    </div>
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

.thought-row svg {
  width: 14px;
  height: 14px;
  stroke-width: 1.9;
}

.thought-icon {
  color: var(--kc-accent);
}

.progress-row {
  color: var(--kc-text);
  font-size: 14px;
  line-height: 1.65;
}

.progress-row p {
  margin: 5px 0 8px;
  white-space: pre-wrap;
}

.thought-details {
  display: grid;
  gap: 4px;
  padding: 2px 0 0;
}
</style>
