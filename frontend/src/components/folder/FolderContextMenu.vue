<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Pencil, Trash2, FolderInput, Plus } from 'lucide-vue-next'
import type { Folder } from '@/api/folders'

const props = defineProps<{
  folder: Folder
}>()

const emit = defineEmits<{
  create: [parentId: string]
  rename: [folder: Folder]
  delete: [id: string]
  move: [folder: Folder]
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

function handleAction(action: 'create' | 'rename' | 'delete' | 'move') {
  if (action === 'create') {
    emit('create', props.folder.id)
  } else if (action === 'delete') {
    emit('delete', props.folder.id)
  } else if (action === 'rename') {
    emit('rename', props.folder)
  } else if (action === 'move') {
    emit('move', props.folder)
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
        @click="handleAction('create')"
        class="w-full px-3 py-2 text-left flex items-center gap-2 hover:bg-muted text-sm"
      >
        <Plus class="w-4 h-4" />
        新建子文件夹
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
