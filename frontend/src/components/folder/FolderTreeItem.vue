<script setup lang="ts">
import { computed, ref } from 'vue'
import { Folder, ChevronRight, ChevronDown, Plus } from 'lucide-vue-next'
import type { FolderTreeItem } from '@/api/folders'
import FolderContextMenu from './FolderContextMenu.vue'
import { useDocumentStore } from '@/stores/document'
import { useFolderStore } from '@/stores/folder'

const props = defineProps<{
  folder: FolderTreeItem
  expandedFolders: Set<string>
  selectedId: string | null
  level?: number
}>()

const emit = defineEmits<{
  toggle: [id: string]
  select: [id: string]
  create: [id: string]
  rename: [folder: FolderTreeItem]
  delete: [id: string]
  move: [folder: FolderTreeItem]
  'document-moved': []
  'folder-moved': []
}>()

const documentStore = useDocumentStore()
const folderStore = useFolderStore()
const isDragOver = ref(false)

const contextMenuRef = ref<InstanceType<typeof FolderContextMenu> | null>(null)

function onContextMenu(e: MouseEvent) {
  e.preventDefault()
  contextMenuRef.value?.open(e)
}

const isExpanded = computed(() => props.expandedFolders.has(props.folder.id))
const isSelected = computed(() => props.selectedId === props.folder.id)
const hasChildren = computed(() => props.folder.children?.length > 0)
const paddingLeft = computed(() => `${(props.level || 0) * 16 + 8}px`)

function onToggle(e: Event) {
  e.stopPropagation()
  emit('toggle', props.folder.id)
}

function onSelect() {
  emit('select', props.folder.id)
}

function onCreate(e: Event) {
  e.stopPropagation()
  emit('create', props.folder.id)
}

// Drag and drop handlers
function onDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) {
    e.dataTransfer.dropEffect = 'move'
  }
  isDragOver.value = true
}

function onDragLeave() {
  isDragOver.value = false
}

// Helper: Check if target folder is a child of source folder
function isDescendantOf(parentId: string, targetId: string): boolean {
  function checkChildren(folders: FolderTreeItem[], parent: string): boolean {
    for (const folder of folders) {
      if (folder.id === parent) {
        // Found the parent, now check if target is in its children
        return hasDescendant(folder.children || [], targetId)
      }
      if (folder.children?.length) {
        const result = checkChildren(folder.children, parent)
        if (result) return true
      }
    }
    return false
  }
  
  function hasDescendant(folders: FolderTreeItem[], target: string): boolean {
    for (const folder of folders) {
      if (folder.id === target) return true
      if (folder.children?.length && hasDescendant(folder.children, target)) {
        return true
      }
    }
    return false
  }
  
  return checkChildren(folderStore.folderTree, parentId)
}

async function onDrop(e: DragEvent) {
  e.preventDefault()
  e.stopPropagation()
  isDragOver.value = false
  
  const data = e.dataTransfer?.getData('application/json')
  if (!data) {
    console.log('No data in drop event')
    return
  }
  
  try {
    const { type, id, name } = JSON.parse(data)
    console.log('Drop event:', { type, id, name, targetFolder: props.folder.name })
    
    if (type === 'document') {
      console.log('Moving document to folder:', props.folder.name)
      await documentStore.moveDocument(id, props.folder.id)
      console.log('Document moved successfully')
      emit('document-moved')
    } else if (type === 'folder' && id !== props.folder.id) {
      // Prevent dropping a folder into itself or its children
      if (isDescendantOf(id, props.folder.id)) {
        console.warn('Cannot move folder into its own descendant')
        return
      }
      await folderStore.moveFolder(id, props.folder.id)
      emit('folder-moved')
    }
  } catch (error) {
    console.error('Failed to handle drop:', error)
  }
}
</script>

<template>
  <div>
    <!-- Folder Item -->
    <div
      @click="onSelect"
      @contextmenu="onContextMenu"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
      :class="[
        'flex items-center gap-1 px-2 py-1.5 rounded cursor-pointer text-sm group transition-colors',
        isSelected ? 'bg-primary/10 text-primary' : 'hover:bg-muted',
        isDragOver && 'bg-primary/20 border-2 border-dashed border-primary'
      ]"
      :style="{ paddingLeft }"
    >
      <!-- Expand/Collapse Icon -->
      <button
        v-if="hasChildren"
        @click="onToggle"
        class="p-0.5 rounded hover:bg-muted-foreground/20"
      >
        <ChevronDown v-if="isExpanded" class="w-3 h-3" />
        <ChevronRight v-else class="w-3 h-3" />
      </button>
      <span v-else class="w-4" />

      <!-- Folder Icon -->
      <Folder class="w-4 h-4 text-blue-500" />

      <!-- Name -->
      <span class="flex-1 truncate">{{ folder.name }}</span>

      <!-- Create Subfolder Button -->
      <button
        @click="onCreate"
        class="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-muted-foreground/20"
        title="新建子文件夹"
      >
        <Plus class="w-3 h-3" />
      </button>
    </div>

    <!-- Children -->
    <div v-if="isExpanded && hasChildren" class="space-y-0.5">
      <FolderTreeItem
        v-for="child in folder.children"
        :key="child.id"
        :folder="child"
        :expanded-folders="expandedFolders"
        :selected-id="selectedId"
        :level="(level || 0) + 1"
        @toggle="$emit('toggle', $event)"
        @select="$emit('select', $event)"
        @create="$emit('create', $event)"
        @rename="$emit('rename', $event)"
        @delete="$emit('delete', $event)"
        @move="$emit('move', $event)"
        @document-moved="$emit('document-moved')"
        @folder-moved="$emit('folder-moved')"
      />
    </div>

    <!-- Context Menu -->
    <FolderContextMenu
      ref="contextMenuRef"
      :folder="folder"
      @create="$emit('create', folder.id)"
      @rename="$emit('rename', folder)"
      @delete="$emit('delete', folder.id)"
      @move="$emit('move', folder)"
    />
  </div>
</template>
