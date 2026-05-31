<script setup lang="ts">
import { ref } from 'vue'
import { Pencil, Trash2, FolderInput, Eye, FolderOpen } from 'lucide-vue-next'

defineProps<{
  type: 'folder' | 'document'
}>()

const emit = defineEmits<{
  open: []
  rename: []
  move: []
  delete: []
}>()

const isOpen = ref(false)
const position = ref({ x: 0, y: 0 })

function open(event: MouseEvent) {
  event.preventDefault()
  event.stopPropagation()
  position.value = { x: event.clientX, y: event.clientY }
  isOpen.value = true
}

function close() {
  isOpen.value = false
}

function handleAction(action: 'open' | 'rename' | 'move' | 'delete') {
  if (action === 'open') emit('open')
  else if (action === 'rename') emit('rename')
  else if (action === 'move') emit('move')
  else if (action === 'delete') emit('delete')
  close()
}

defineExpose({ open, close })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed z-50 min-w-[140px] bg-popover rounded-md shadow-lg border py-1"
      :style="{ left: position.x + 'px', top: position.y + 'px' }"
      @click.stop
    >
      <!-- Open -->
      <button
        @click="handleAction('open')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 text-sm hover:bg-accent transition-colors"
      >
        <Eye v-if="type === 'document'" class="w-4 h-4" />
        <FolderOpen v-else class="w-4 h-4" />
        <span>{{ type === 'document' ? '打开/预览' : '打开' }}</span>
      </button>

      <!-- Rename -->
      <button
        @click="handleAction('rename')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 text-sm hover:bg-accent transition-colors"
      >
        <Pencil class="w-4 h-4" />
        <span>重命名</span>
      </button>

      <!-- Move -->
      <button
        @click="handleAction('move')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 text-sm hover:bg-accent transition-colors"
      >
        <FolderInput class="w-4 h-4" />
        <span>移动到</span>
      </button>

      <!-- Divider -->
      <div class="h-px bg-border my-1" />

      <!-- Delete -->
      <button
        @click="handleAction('delete')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 text-sm text-destructive hover:bg-destructive/10 transition-colors"
      >
        <Trash2 class="w-4 h-4" />
        <span>删除</span>
      </button>

      <!-- Click outside to close -->
      <div 
        class="fixed inset-0 -z-10" 
        @click="close"
      />
    </div>
  </Teleport>
</template>
