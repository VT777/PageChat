<script setup lang="ts">
import { ref, watch } from 'vue'
import { useFolderStore } from '@/stores/folder'
import { X, FolderPlus } from 'lucide-vue-next'

const props = defineProps<{
  open: boolean
  parentId: string | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'created': []
}>()

const folderStore = useFolderStore()
const folderName = ref('')
const error = ref('')
const loading = ref(false)

watch(() => props.open, (newOpen) => {
  if (newOpen) {
    folderName.value = ''
    error.value = ''
  }
})

function validateName(name: string): string | null {
  if (!name.trim()) {
    return '文件夹名称不能为空'
  }
  if (name.length > 255) {
    return '文件夹名称不能超过255个字符'
  }
  if (name.includes('/') || name.includes('\\')) {
    return '文件夹名称不能包含 / 或 \\ '
  }
  return null
}

async function handleSubmit() {
  const validationError = validateName(folderName.value)
  if (validationError) {
    error.value = validationError
    return
  }

  loading.value = true
  error.value = ''

  try {
    await folderStore.createFolder(folderName.value.trim(), props.parentId)
    emit('created')
    emit('update:open', false)
  } catch (err: any) {
    error.value = err.response?.data?.detail || '创建文件夹失败'
  } finally {
    loading.value = false
  }
}

function handleClose() {
  if (!loading.value) {
    emit('update:open', false)
  }
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
        class="bg-background rounded-lg shadow-lg w-full max-w-md mx-4"
        @click.stop
      >
        <!-- Header -->
        <div class="flex items-center justify-between p-4 border-b">
          <div class="flex items-center gap-2">
            <FolderPlus class="w-5 h-5" />
            <h3 class="font-semibold">新建文件夹</h3>
          </div>
          <button
            @click="handleClose"
            class="p-1 rounded hover:bg-muted"
            :disabled="loading"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Content -->
        <div class="p-4 space-y-4">
          <div>
            <label class="block text-sm font-medium mb-1">文件夹名称</label>
            <input
              v-model="folderName"
              type="text"
              placeholder="请输入文件夹名称"
              class="w-full px-3 py-2 rounded-lg border focus:outline-none focus:ring-2 focus:ring-primary"
              :disabled="loading"
              @keyup.enter="handleSubmit"
              ref="inputRef"
            />
            <p v-if="error" class="text-sm text-destructive mt-1">{{ error }}</p>
          </div>

          <!-- Actions -->
          <div class="flex justify-end gap-2">
            <button
              @click="handleClose"
              class="px-4 py-2 rounded-lg border hover:bg-muted"
              :disabled="loading"
            >
              取消
            </button>
            <button
              @click="handleSubmit"
              class="px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              :disabled="loading || !folderName.trim()"
            >
              <span v-if="loading">创建中...</span>
              <span v-else>创建</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>