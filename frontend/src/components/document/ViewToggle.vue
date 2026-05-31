<script setup lang="ts">
import { LayoutGrid, List } from 'lucide-vue-next'

type ViewMode = 'grid' | 'list'

defineProps<{
  modelValue: ViewMode
}>()

const emit = defineEmits<{
  'update:modelValue': [mode: ViewMode]
}>()

function setMode(mode: ViewMode) {
  emit('update:modelValue', mode)
}
</script>

<template>
  <div class="inline-flex rounded-lg border bg-background p-0.5">
    <button
      @click="setMode('grid')"
      :class="[
        'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors',
        modelValue === 'grid'
          ? 'bg-primary text-primary-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted'
      ]"
      title="网格视图"
    >
      <LayoutGrid class="w-4 h-4" />
      <span class="hidden sm:inline">网格</span>
    </button>
    <button
      @click="setMode('list')"
      :class="[
        'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors',
        modelValue === 'list'
          ? 'bg-primary text-primary-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted'
      ]"
      title="列表视图"
    >
      <List class="w-4 h-4" />
      <span class="hidden sm:inline">列表</span>
    </button>
  </div>
</template>
