<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Eye, RefreshCw, Trash2, FolderInput, Pencil } from 'lucide-vue-next'
import type { Document } from '@/stores/document'

const props = defineProps<{
  document: Document
}>()

const emit = defineEmits<{
  preview: [id: string]
  reindex: [id: string]
  delete: [id: string]
  move: [doc: Document]
  rename: [doc: Document]
}>()

const isOpen = ref(false)
const position = ref({ x: 0, y: 0 })

function open(event: MouseEvent) {
  event.preventDefault()
  position.value = { x: event.clientX, y: event.clientY }
  isOpen.value = true
}

function close() {
  isOpen.value = false
}

function handleAction(action: 'preview' | 'reindex' | 'delete' | 'move' | 'rename') {
  if (action === 'preview') {
    emit('preview', props.document.id)
  } else if (action === 'reindex') {
    emit('reindex', props.document.id)
  } else if (action === 'rename') {
    emit('rename', props.document)
  } else if (action === 'delete') {
    emit('delete', props.document.id)
  } else if (action === 'move') {
    emit('move', props.document)
  }
  close()
}

onMounted(() => {
  document.addEventListener('click', close)
})

onUnmounted(() => {
  document.removeEventListener('click', close)
})

defineExpose({ open })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed z-50 min-w-[160px] bg-background rounded-lg shadow-lg border py-1"
      :style="{ left: position.x + 'px', top: position.y + 'px' }"
      @click.stop
    >
      <button
        v-if="document.status === 'completed'"
        @click="handleAction('preview')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-muted text-sm"
      >
        <Eye class="w-4 h-4" />
        打开/预览
      </button>
      
      <button
        v-if="!document.status.startsWith('processing')"
        @click="handleAction('reindex')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-muted text-sm"
      >
        <RefreshCw class="w-4 h-4" />
        重新解析
      </button>
      
      <button
        @click="handleAction('rename')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-muted text-sm"
      >
        <Pencil class="w-4 h-4" />
        重命名
      </button>

      <button
        @click="handleAction('move')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-muted text-sm"
      >
        <FolderInput class="w-4 h-4" />
        移动到
      </button>

      <div class="h-px bg-border my-1" />
      
      <button
        @click="handleAction('delete')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-muted text-sm text-destructive"
      >
        <Trash2 class="w-4 h-4" />
        删除
      </button>
    </div>
  </Teleport>
</template>
