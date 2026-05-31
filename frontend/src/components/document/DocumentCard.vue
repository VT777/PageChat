<script setup lang="ts">
import { computed } from 'vue'
import { Eye, Trash2, RefreshCw, FolderInput, CheckCircle2, AlertCircle, Loader2 } from 'lucide-vue-next'
import FileTypeIcon from './FileTypeIcon.vue'
import type { Document } from '@/stores/document'

interface Props {
  document: Document
  selected?: boolean
  selectable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  selected: false,
  selectable: false,
})

const emit = defineEmits<{
  toggleSelect: [id: string]
  preview: [id: string]
  reindex: [id: string]
  delete: [id: string]
  move: [doc: Document]
  showSteps: [id: string]
}>()

const isProcessing = computed(() => props.document.status.startsWith('processing'))
const isCompleted = computed(() => props.document.status === 'completed')
const isFailed = computed(() => props.document.status.startsWith('failed'))

const statusConfig = computed(() => {
  if (isProcessing.value) {
    return {
      label: '处理中',
      icon: Loader2,
      color: 'text-amber-500',
      bg: 'bg-amber-50 dark:bg-amber-950/30',
      border: 'border-amber-200 dark:border-amber-800',
    }
  }
  if (isFailed.value) {
    return {
      label: '失败',
      icon: AlertCircle,
      color: 'text-red-500',
      bg: 'bg-red-50 dark:bg-red-950/30',
      border: 'border-red-200 dark:border-red-800',
    }
  }
  return {
    label: '已完成',
    icon: CheckCircle2,
    color: 'text-emerald-500',
    bg: 'bg-emerald-50 dark:bg-emerald-950/30',
    border: 'border-emerald-200 dark:border-emerald-800',
  }
})

// 阶段式进度条：根据后端 status 映射进度
const progress = computed(() => {
  const status = props.document.status || ''
  if (status === 'completed') return 100
  if (status.startsWith('processing:analyze')) return 10
  if (status.startsWith('processing:indexing')) return 40
  if (status.startsWith('processing:writing_index')) return 70
  if (status.startsWith('processing:generating_summaries')) return 90
  if (status.startsWith('processing')) return 5
  return 0
})

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <div
    :class="[
      'group relative rounded-xl border bg-card p-4 transition-all hover:shadow-md',
      selected ? 'ring-2 ring-primary border-primary' : 'border-border',
    ]"
  >
    <!-- Checkbox -->
    <div v-if="selectable" class="absolute top-3 left-3 z-10">
      <input
        type="checkbox"
        :checked="selected"
        @change="emit('toggleSelect', document.id)"
        class="w-4 h-4 rounded border-muted-foreground accent-primary cursor-pointer"
      />
    </div>

    <!-- File Icon -->
    <div class="flex justify-center mb-3" :class="selectable ? 'mt-4' : ''">
      <FileTypeIcon :file-type="document.file_type" size="lg" />
    </div>

    <!-- Name -->
    <div class="mb-2">
      <h3
        class="text-sm font-medium text-foreground truncate text-center"
        :title="document.original_name"
      >
        {{ document.original_name }}
      </h3>
    </div>

    <!-- Meta -->
    <div class="flex items-center justify-center gap-2 text-xs text-muted-foreground mb-3">
      <span>{{ formatSize(document.file_size) }}</span>
      <span>·</span>
      <span>{{ formatDate(document.created_at) }}</span>
    </div>

    <!-- Status Badge -->
    <div class="flex justify-center mb-3">
      <div
        :class="[
          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border',
          statusConfig.bg,
          statusConfig.border,
          statusConfig.color,
        ]"
      >
        <component :is="statusConfig.icon" class="w-3.5 h-3.5" :class="isProcessing && 'animate-spin'" />
        <span>{{ statusConfig.label }}</span>
      </div>
    </div>

    <!-- Progress Bar (processing) -->
    <div v-if="isProcessing" class="mb-3">
      <div class="flex justify-between text-xs text-muted-foreground mb-1">
        <span>处理进度</span>
        <span>{{ progress }}%</span>
      </div>
      <div class="h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          class="h-full bg-primary rounded-full transition-all duration-500"
          :style="{ width: progress + '%' }"
        />
      </div>
      <button
        v-if="document.status.startsWith('processing')"
        @click="emit('showSteps', document.id)"
        class="mt-1.5 text-xs text-primary hover:underline w-full text-center"
      >
        查看详情
      </button>
    </div>

    <!-- Error Message -->
    <div v-if="isFailed && document.error_message" class="mb-3">
      <p class="text-xs text-red-500 text-center line-clamp-2">{{ document.error_message }}</p>
    </div>

    <!-- Quick Actions -->
    <div class="flex items-center justify-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        v-if="isCompleted"
        @click="emit('preview', document.id)"
        class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
        title="预览"
      >
        <Eye class="w-4 h-4" />
      </button>
      <button
        v-if="!isProcessing"
        @click="emit('reindex', document.id)"
        class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
        title="重新解析"
      >
        <RefreshCw class="w-4 h-4" />
      </button>
      <button
        @click="emit('move', document)"
        class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
        title="移动到"
      >
        <FolderInput class="w-4 h-4" />
      </button>
      <button
        @click="emit('delete', document.id)"
        class="p-1.5 rounded-md hover:bg-muted text-destructive hover:text-destructive"
        title="删除"
      >
        <Trash2 class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>
