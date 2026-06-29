<script setup lang="ts">
import { ref } from 'vue'
import { ChevronRight, ChevronDown } from 'lucide-vue-next'

interface TocNode {
  node_id: string
  title: string
  structure?: string
  level: number
  summary: string
  start_page: number | null
  end_page: number | null
  children: TocNode[]
}

interface Props {
  nodes: TocNode[]
  defaultExpanded?: boolean
}

withDefaults(defineProps<Props>(), {
  defaultExpanded: false,
})

const emit = defineEmits<{
  jump: [pageNum: number]
}>()

// Track expanded state per node_id
const expandedNodes = ref<Set<string>>(new Set())

function isExpanded(nodeId: string): boolean {
  return expandedNodes.value.has(nodeId)
}

function toggleNode(nodeId: string) {
  if (expandedNodes.value.has(nodeId)) {
    expandedNodes.value.delete(nodeId)
  } else {
    expandedNodes.value.add(nodeId)
  }
}

function handleJump(pageNum: number | null) {
  if (pageNum !== null && pageNum > 0) {
    emit('jump', pageNum)
  }
}
</script>

<template>
  <div class="space-y-0.5">
    <div
      v-for="node in nodes"
      :key="node.node_id"
    >
      <!-- Node Row -->
      <div
        class="flex items-start gap-1 group"
        :style="{ paddingLeft: (node.level * 12) + 'px' }"
      >
        <!-- Expand/Collapse button (only if has children) -->
        <button
          v-if="node.children?.length"
          @click.stop="toggleNode(node.node_id)"
          class="mt-1.5 p-0.5 rounded hover:bg-muted flex-shrink-0 text-muted-foreground"
        >
          <ChevronDown v-if="isExpanded(node.node_id)" class="w-3.5 h-3.5" />
          <ChevronRight v-else class="w-3.5 h-3.5" />
        </button>
        <!-- Spacer for leaf nodes to align with expandable ones -->
        <div v-else class="w-5 flex-shrink-0" />

        <!-- Title + Page info -->
        <button
          @click="handleJump(node.start_page)"
          :disabled="!node.start_page"
          :title="node.summary || node.title"
          :class="[
            'flex-1 text-left px-2 py-1.5 rounded-md text-sm transition-colors',
            node.start_page
              ? 'hover:bg-muted cursor-pointer'
              : 'cursor-default opacity-60',
          ]"
        >
          <span class="truncate block">
            <span v-if="node.structure" class="structure-num">{{ node.structure }}</span>
            {{ node.title }}
          </span>
          <span
            v-if="node.start_page"
            class="text-xs text-muted-foreground mt-0.5 block"
          >
            Page {{ node.start_page }}
            <span v-if="node.end_page && node.end_page !== node.start_page">
              - {{ node.end_page }}
            </span>
          </span>
          <span v-if="node.summary" class="summary-popover">
            {{ node.summary }}
          </span>
        </button>
      </div>

      <!-- Children (recursive) -->
      <TocTree
        v-if="node.children?.length && isExpanded(node.node_id)"
        :nodes="node.children"
        @jump="handleJump"
      />
    </div>
  </div>
</template>

<style scoped>
.structure-num {
  color: #888;
  font-size: 12px;
  margin-right: 6px;
  font-weight: 500;
}

button {
  position: relative;
}

.summary-popover {
  position: absolute;
  left: 12px;
  right: 12px;
  top: calc(100% + 4px);
  z-index: 20;
  display: none;
  max-height: 120px;
  overflow-y: auto;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  padding: 8px;
  color: #374151;
  box-shadow: 0 8px 20px rgb(15 23 42 / 0.14);
  font-size: 12px;
  line-height: 1.45;
  white-space: normal;
}

button:hover .summary-popover,
button:focus-visible .summary-popover {
  display: block;
}
</style>
