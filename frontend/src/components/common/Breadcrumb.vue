<script setup lang="ts">
import { ChevronRight, Home } from 'lucide-vue-next'
import type { Folder } from '@/api/folders'

const props = defineProps<{
  path: Folder[]
}>()

const emit = defineEmits<{
  navigate: [folderId: string | null]
}>()

function navigateTo(index: number) {
  if (index === -1) {
    emit('navigate', null) // 根目录
  } else {
    emit('navigate', props.path[index].id)
  }
}
</script>

<template>
  <nav class="flex items-center gap-1 text-sm">
    <!-- Root -->
    <button
      @click="navigateTo(-1)"
      :class="[
        'flex items-center gap-1 px-2 py-1 rounded transition-colors',
        path.length === 0 ? 'text-primary font-medium' : 'text-muted-foreground hover:text-foreground'
      ]"
    >
      <Home class="w-4 h-4" />
      <span>根目录</span>
    </button>

    <!-- Path Items -->
    <template v-for="(folder, index) in path" :key="folder.id">
      <ChevronRight class="w-4 h-4 text-muted-foreground" />
      <button
        @click="navigateTo(index)"
        :class="[
          'px-2 py-1 rounded transition-colors truncate max-w-[150px]',
          index === path.length - 1 ? 'text-primary font-medium' : 'text-muted-foreground hover:text-foreground'
        ]"
      >
        {{ folder.name }}
      </button>
    </template>
  </nav>
</template>
