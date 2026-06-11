<script setup lang="ts">
import { computed } from 'vue'
import { X, FileText } from 'lucide-vue-next'
import type { SourceAnchor } from '@/types/preview'
import { formatEvidenceLabel } from '@/utils/evidence'

const props = defineProps<{
  open: boolean
  anchorLabel: string
  anchorLocator: string
  highlightedSnippet: string
  documentName?: string
  displayLabel?: string | null
  sourceAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  close: []
}>()

const anchorLabel = computed(() => {
  return formatEvidenceLabel({
    documentName: props.documentName,
    displayLabel: props.displayLabel || props.anchorLabel,
    sourceAnchor: props.sourceAnchor,
    fallbackLabel: props.anchorLabel,
  })
})

const anchorLocator = computed(() => props.anchorLocator || '')

const highlightText = computed(() => props.highlightedSnippet || '暂无可预览片段')
</script>

<template>
  <transition
    enter-active-class="transition duration-200 ease-out"
    enter-from-class="translate-x-full opacity-0"
    enter-to-class="translate-x-0 opacity-100"
    leave-active-class="transition duration-150 ease-in"
    leave-from-class="translate-x-0 opacity-100"
    leave-to-class="translate-x-full opacity-0"
  >
    <aside
      v-if="open"
      class="w-[340px] border-l bg-background h-full flex flex-col"
      data-testid="source-preview-drawer"
    >
      <header class="flex items-center justify-between px-4 py-3 border-b">
        <div class="flex items-center gap-2 text-sm font-medium">
          <FileText class="w-4 h-4 text-muted-foreground" />
          来源预览
        </div>
        <button
          class="p-1.5 rounded-md hover:bg-accent"
          @click="emit('close')"
        >
          <X class="w-4 h-4" />
        </button>
      </header>

      <div class="p-4 space-y-3 text-sm">
        <p class="text-muted-foreground">{{ anchorLabel }}</p>
        <p class="text-xs text-muted-foreground/80">{{ anchorLocator }}</p>
        <div class="rounded-lg border bg-muted/40 p-3 leading-6 whitespace-pre-wrap">
          <mark class="rounded bg-amber-200/80 px-1 py-0.5 text-foreground">{{ highlightText }}</mark>
        </div>
      </div>
    </aside>
  </transition>
</template>
