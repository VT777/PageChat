<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useFolderStore } from '@/stores/folder'
import { useDocumentStore } from '@/stores/document'
import { X, Folder, FolderOpen, ChevronRight } from 'lucide-vue-next'
import type { Document } from '@/stores/document'
import { useI18n } from '@/i18n/messages'

const props = defineProps<{
  open: boolean
  document: Document | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'moved': []
}>()

const folderStore = useFolderStore()
const documentStore = useDocumentStore()
const selectedFolderId = ref<string | null>(null)
const loading = ref(false)
const { localizeText: lt } = useI18n()

onMounted(() => {
  folderStore.fetchFolderTree()
})

function handleClose() {
  if (!loading.value) {
    emit('update:open', false)
    selectedFolderId.value = null
  }
}

async function handleMove() {
  if (!props.document) return
  
  loading.value = true
  try {
    await documentStore.moveDocument(props.document.id, selectedFolderId.value)
    emit('moved')
    emit('update:open', false)
    selectedFolderId.value = null
  } catch (error) {
    console.error('Failed to move document:', error)
    alert(lt('移动失败，请重试'))
  } finally {
    loading.value = false
  }
}

function selectFolder(id: string | null) {
  selectedFolderId.value = id
}

function isSelected(id: string | null) {
  return selectedFolderId.value === id
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      @click="handleClose"
    >
      <div
        class="bg-background rounded-lg shadow-lg w-full max-w-md mx-4 max-h-[80vh] flex flex-col"
        @click.stop
      >
        <!-- Header -->
        <div class="flex items-center justify-between p-4 border-b">
          <h3 class="font-semibold flex items-center gap-2">
            <FolderOpen class="w-5 h-5" />
            {{ lt('移动到文件夹') }}
          </h3>
          <button
            @click="handleClose"
            class="p-1 rounded hover:bg-muted"
            :disabled="loading"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Folder List -->
        <div class="flex-1 overflow-y-auto p-4">
          <p class="text-sm text-muted-foreground mb-3">
            {{ lt('选择目标文件夹：') }}
          </p>
          
          <!-- Root -->
          <div
            @click="selectFolder(null)"
            :class="[
              'flex items-center gap-2 px-3 py-2 rounded cursor-pointer text-sm mb-1',
              isSelected(null) ? 'bg-primary/10 text-primary border border-primary/30' : 'hover:bg-muted'
            ]"
          >
            <Folder class="w-4 h-4" :class="isSelected(null) ? 'text-primary' : 'text-muted-foreground'" />
            <span class="flex-1">{{ lt('根目录') }}</span>
            <ChevronRight v-if="isSelected(null)" class="w-4 h-4 text-primary" />
          </div>

          <!-- Folders -->
          <div class="space-y-1 mt-2">
            <div
              v-for="folder in folderStore.folderTree"
              :key="folder.id"
              @click="selectFolder(folder.id)"
              :class="[
                'flex items-center gap-2 px-3 py-2 rounded cursor-pointer text-sm',
                isSelected(folder.id) ? 'bg-primary/10 text-primary border border-primary/30' : 'hover:bg-muted'
              ]"
            >
              <Folder class="w-4 h-4 text-blue-500" :class="isSelected(folder.id) ? 'text-primary' : ''" />
              <span class="flex-1 truncate">{{ folder.name }}</span>
              <ChevronRight v-if="isSelected(folder.id)" class="w-4 h-4 text-primary" />
            </div>
          </div>

          <p v-if="folderStore.folderTree.length === 0" class="text-sm text-muted-foreground text-center py-4">
            {{ lt('暂无文件夹') }}
          </p>
        </div>

        <!-- Actions -->
        <div class="flex justify-end gap-2 p-4 border-t">
          <button
            @click="handleClose"
            class="px-4 py-2 rounded-lg border hover:bg-muted"
            :disabled="loading"
          >
            {{ lt('取消') }}
          </button>
          <button
            @click="handleMove"
            class="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="loading || selectedFolderId === undefined"
          >
            <span v-if="loading">{{ lt('移动中...') }}</span>
            <span v-else>{{ lt('移动') }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
