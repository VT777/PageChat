<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useFolderStore } from '@/stores/folder'
import { folderApi, type FolderTreeItem as FolderTreeItemType } from '@/api/folders'
import { Folder, Plus } from 'lucide-vue-next'
import FolderTreeItem from './FolderTreeItem.vue'
import CreateFolderDialog from './CreateFolderDialog.vue'

const folderStore = useFolderStore()
const emit = defineEmits<{
  'folder-deleted': [id: string]
  'folder-created': []
  'folder-renamed': []
  'document-moved': []
  'folder-moved': []
}>()

const expandedFolders = ref<Set<string>>(new Set())
const showCreateDialog = ref(false)
const createFolderParentId = ref<string | null>(null)

onMounted(() => {
  folderStore.fetchFolderTree()
})

function toggleFolder(id: string) {
  if (expandedFolders.value.has(id)) {
    expandedFolders.value.delete(id)
  } else {
    expandedFolders.value.add(id)
  }
}

function selectFolder(id: string | null) {
  folderStore.setCurrentFolder(id)
}

function isSelected(id: string | null) {
  return folderStore.currentFolderId === id
}

function handleCreateClick(parentId: string | null) {
  createFolderParentId.value = parentId
  showCreateDialog.value = true
}

async function handleFolderCreated() {
  await folderStore.fetchFolderTree()
  emit('folder-created')
}

async function handleRename(folder: FolderTreeItemType) {
  const newName = prompt('请输入新文件夹名称:', folder.name)
  if (newName && newName !== folder.name) {
    await folderApi.rename(folder.id, newName)
    await folderStore.fetchFolderTree()
    emit('folder-renamed')
  }
}

async function handleDelete(id: string) {
  if (confirm('确定要删除这个文件夹吗？\n\n⚠️ 警告：文件夹内的所有子文件夹和文档将被一并删除！')) {
    await folderApi.delete(id)
    await folderStore.fetchFolderTree()
    if (folderStore.currentFolderId === id) {
      folderStore.setCurrentFolder(null)
    }
    emit('folder-deleted', id)
  }
}

function handleDocumentMoved() {
  emit('document-moved')
}

function handleFolderMoved() {
  emit('folder-moved')
}
</script>

<template>
  <div class="w-64 h-full border-r bg-muted/30 flex flex-col">
    <!-- Header -->
    <div class="p-3 border-b flex items-center justify-between">
      <span class="font-medium text-sm">文件夹</span>
      <button 
        @click="handleCreateClick(null)"
        class="p-1.5 rounded hover:bg-muted transition-colors"
        title="新建文件夹"
      >
        <Plus class="w-4 h-4" />
      </button>
    </div>

    <!-- Tree -->
    <div class="flex-1 overflow-y-auto p-2 space-y-0.5">
      <!-- Root -->
      <div
        @click="selectFolder(null)"
        :class="[
          'flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer text-sm',
          isSelected(null) ? 'bg-primary/10 text-primary' : 'hover:bg-muted'
        ]"
      >
        <Folder class="w-4 h-4" />
        <span class="flex-1 truncate">根目录</span>
      </div>

      <!-- Folder Tree Items -->
      <FolderTreeItem
        v-for="folder in folderStore.folderTree"
        :key="folder.id"
        :folder="folder"
        :expanded-folders="expandedFolders"
        :selected-id="folderStore.currentFolderId"
        @toggle="toggleFolder"
        @select="selectFolder"
        @create="handleCreateClick"
        @rename="handleRename"
        @delete="handleDelete"
        @document-moved="handleDocumentMoved"
        @folder-moved="handleFolderMoved"
      />
    </div>

    <!-- Create Folder Dialog -->
    <CreateFolderDialog
      v-model:open="showCreateDialog"
      :parent-id="createFolderParentId"
      @created="handleFolderCreated"
    />
  </div>
</template>
