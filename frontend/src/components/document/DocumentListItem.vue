<script setup lang="ts">
import { computed } from 'vue'
import { Eye, Trash2, RefreshCw, FolderInput, CheckCircle2, AlertCircle, Loader2 } from 'lucide-vue-next'
import FileTypeIcon from './FileTypeIcon.vue'
import type { Document } from '@/stores/document'
import { useI18n } from '@/i18n/messages'

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
const { language, localizeText: lt, localizeError } = useI18n()

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
  return date.toLocaleDateString(language.value, {
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
      'group flex items-center gap-4 rounded-lg border bg-card px-4 py-3 transition-all hover:shadow-sm',
      selected ? 'ring-2 ring-primary border-primary' : 'border-border',
    ]"
  >
    <!-- Checkbox -->
    <div v-if="selectable">
      <input
        type="checkbox"
        :checked="selected"
        @change="emit('toggleSelect', document.id)"
        class="w-4 h-4 rounded border-muted-foreground accent-primary cursor-pointer"
      />
    </div>

    <!-- File Icon -->
    <FileTypeIcon :file-type="document.file_type" size="sm" />

    <!-- Name & Meta -->
    <div class="flex-1 min-w-0">
      <h3 class="text-sm font-medium text-foreground truncate" :title="document.original_name">
        {{ document.original_name }}
      </h3>
      <div class="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
        <span>{{ formatSize(document.file_size) }}</span>
        <span>{{ formatDate(document.created_at) }}</span>
        <span v-if="document.page_count">{{ document.page_count }} {{ lt('页') }}</span>
      </div>
    </div>

    <!-- Status -->
    <div class="flex items-center gap-2 w-40">
      <div v-if="isProcessing" class="flex-1">
        <div class="flex justify-between text-xs text-muted-foreground mb-1">
          <span class="flex items-center gap-1 text-amber-500">
            <Loader2 class="w-3 h-3 animate-spin" />
            {{ lt('处理中') }}
          </span>
          <span>{{ progress }}%</span>
        </div>
        <div class="h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            class="h-full bg-primary rounded-full transition-all duration-500"
            :style="{ width: progress + '%' }"
          />
        </div>
      </div>

      <div
        v-else-if="isFailed"
        class="flex items-center gap-1 text-xs text-red-500"
        :title="localizeError(document.error_message || '')"
      >
        <AlertCircle class="w-3.5 h-3.5" />
        <span>{{ lt('失败') }}</span>
      </div>

      <div v-else class="flex items-center gap-1 text-xs text-emerald-500">
        <CheckCircle2 class="w-3.5 h-3.5" />
        <span>{{ lt('已完成') }}</span>
      </div>

      <button
        v-if="isProcessing"
        @click="emit('showSteps', document.id)"
        class="text-xs text-primary hover:underline whitespace-nowrap"
      >
        {{ lt('查看详情') }}
      </button>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        v-if="isCompleted"
        @click="emit('preview', document.id)"
        class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
        :title="lt('预览')"
      >
        <Eye class="w-4 h-4" />
      </button>
      <button
        v-if="!isProcessing"
        @click="emit('reindex', document.id)"
        class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
        :title="lt('重新解析')"
      >
        <RefreshCw class="w-4 h-4" />
      </button>
      <button
        @click="emit('move', document)"
        class="p-1.5 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
        :title="lt('移动到')"
      >
        <FolderInput class="w-4 h-4" />
      </button>
      <button
        @click="emit('delete', document.id)"
        class="p-1.5 rounded-md hover:bg-muted text-destructive hover:text-destructive"
        :title="lt('删除')"
      >
        <Trash2 class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>
