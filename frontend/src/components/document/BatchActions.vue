<script setup lang="ts">
import { computed } from 'vue'
import { FolderIcon, Trash2, RefreshCw, CheckSquare, Square } from 'lucide-vue-next'
import { useI18n } from '@/i18n/messages'

interface Props {
  selectedCount: number
  totalCount: number
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'selectAll'): void
  (e: 'deselectAll'): void
  (e: 'move'): void
  (e: 'delete'): void
  (e: 'reindex'): void
}>()

const isAllSelected = computed(() => props.selectedCount === props.totalCount && props.totalCount > 0)
const { localizeText: lt } = useI18n()

function toggleSelectAll() {
  if (isAllSelected.value) {
    emit('deselectAll')
  } else {
    emit('selectAll')
  }
}
</script>

<template>
  <div class="batch-actions-bar">
    <div class="batch-info">
      <button @click="toggleSelectAll" class="select-all-btn">
        <CheckSquare v-if="isAllSelected" class="w-4 h-4" />
        <Square v-else class="w-4 h-4" />
        <span v-if="selectedCount > 0">{{ lt('已选择') }} {{ selectedCount }} {{ lt('项') }}</span>
        <span v-else>{{ lt('全选') }}</span>
      </button>
    </div>
    
    <div v-if="selectedCount > 0" class="batch-buttons">
      <button @click="$emit('move')" class="batch-btn" :title="lt('移动到文件夹')">
        <FolderIcon class="w-4 h-4" />
        <span>{{ lt('移动') }}</span>
      </button>
      
      <button @click="$emit('reindex')" class="batch-btn" :title="lt('重新索引')">
        <RefreshCw class="w-4 h-4" />
        <span>{{ lt('重新索引') }}</span>
      </button>
      
      <button @click="$emit('delete')" class="batch-btn batch-btn-danger" :title="lt('删除')">
        <Trash2 class="w-4 h-4" />
        <span>{{ lt('删除') }}</span>
      </button>
    </div>
    <div v-else class="batch-hint">
      {{ lt('请选择要操作的文档') }}
    </div>
  </div>
</template>

<style scoped>
.batch-actions-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--primary);
  color: var(--primary-foreground);
  border-radius: 8px;
  margin-bottom: 16px;
}

.batch-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.select-all-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 6px;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.select-all-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.batch-buttons {
  display: flex;
  gap: 8px;
}

.batch-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  border-radius: 6px;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.batch-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.batch-btn-danger:hover {
  background: var(--destructive);
}

.batch-hint {
  font-size: 14px;
  opacity: 0.8;
}
</style>
