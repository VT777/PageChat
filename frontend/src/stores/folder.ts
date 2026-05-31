import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { folderApi, type Folder, type FolderTreeItem } from '@/api/folders'

export const useFolderStore = defineStore('folder', () => {
  // State
  const folders = ref<Folder[]>([])
  const folderTree = ref<FolderTreeItem[]>([])
  const currentFolderId = ref<string | null>(null)
  const loading = ref(false)

  // Getters
  const currentFolder = computed(() => {
    return folders.value.find(f => f.id === currentFolderId.value) || null
  })

  const currentFolderPath = computed(() => {
    if (!currentFolderId.value) return []
    return buildPath(folderTree.value, currentFolderId.value)
  })

  // Actions
  async function fetchFolderTree() {
    loading.value = true
    try {
      const { data } = await folderApi.getTree()
      folderTree.value = data
    } catch (error) {
      console.error('Failed to fetch folder tree:', error)
    } finally {
      loading.value = false
    }
  }

  async function fetchFolders(parent_id?: string | null) {
    loading.value = true
    try {
      const { data } = await folderApi.list(parent_id)
      folders.value = data.items
    } catch (error) {
      console.error('Failed to fetch folders:', error)
    } finally {
      loading.value = false
    }
  }

  async function createFolder(name: string, parent_id?: string | null) {
    try {
      const { data } = await folderApi.create({ name, parent_id })
      await fetchFolderTree()
      return data
    } catch (error) {
      console.error('Failed to create folder:', error)
      throw error
    }
  }

  async function renameFolder(id: string, name: string) {
    try {
      await folderApi.rename(id, name)
      await fetchFolderTree()
    } catch (error) {
      console.error('Failed to rename folder:', error)
      throw error
    }
  }

  async function deleteFolder(id: string) {
    try {
      await folderApi.delete(id)
      await fetchFolderTree()
      if (currentFolderId.value === id) {
        currentFolderId.value = null
      }
    } catch (error) {
      console.error('Failed to delete folder:', error)
      throw error
    }
  }

  async function moveFolder(id: string, parent_id: string | null) {
    try {
      await folderApi.move(id, parent_id)
      await fetchFolderTree()
    } catch (error) {
      console.error('Failed to move folder:', error)
      throw error
    }
  }

  function setCurrentFolder(id: string | null) {
    currentFolderId.value = id
  }

  // Helper: 构建路径数组
  function buildPath(tree: FolderTreeItem[], targetId: string, currentPath: Folder[] = []): Folder[] {
    for (const folder of tree) {
      if (folder.id === targetId) {
        return [...currentPath, folder]
      }
      if (folder.children?.length) {
        const result = buildPath(folder.children, targetId, [...currentPath, folder])
        if (result.length) return result
      }
    }
    return []
  }

  return {
    folders,
    folderTree,
    currentFolderId,
    currentFolder,
    currentFolderPath,
    loading,
    fetchFolderTree,
    fetchFolders,
    createFolder,
    renameFolder,
    deleteFolder,
    moveFolder,
    setCurrentFolder
  }
})
