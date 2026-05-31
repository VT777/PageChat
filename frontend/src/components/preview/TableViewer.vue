<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import type { DocumentContent, SourceAnchor } from '@/types/preview'

const props = defineProps<{
  content: DocumentContent
  initialAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
}>()

const containerRef = ref<HTMLDivElement>()
const activeRow = ref<number | null>(null)

// 表格数据
const tableData = computed(() => {
  const rows = props.content.blocks.filter(b => b.type === 'table_row')
  return rows.map(block => ({
    id: block.id,
    rowNumber: block.metadata.row_number as number,
    cells: block.content as Array<{ col: string; value: string }>
  }))
})

// 表头
const headers = computed(() => {
  return props.content.metadata.headers || []
})

// 总行数
const totalRows = computed(() => props.content.metadata.total_rows || tableData.value.length)

// 总列数
const totalCols = computed(() => props.content.metadata.total_cols || headers.value.length)

// 跳转到指定行
async function scrollToRow(rowNumber: number) {
  activeRow.value = rowNumber
  await nextTick()
  
  const element = document.getElementById(`row-${rowNumber}`)
  if (element && containerRef.value) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('highlight-row')
    setTimeout(() => {
      element.classList.remove('highlight-row')
    }, 3000)
  }
}

// 处理行点击
function handleRowClick(rowNumber: number) {
  activeRow.value = rowNumber
  const anchor: SourceAnchor = {
    format: 'csv',
    start_row: rowNumber,
    end_row: rowNumber
  }
  emit('anchorClick', anchor)
}

// 监听初始锚点
watch(() => props.initialAnchor, (anchor) => {
  if (anchor?.start_row) {
    scrollToRow(anchor.start_row)
  }
}, { immediate: true })

defineExpose({
  scrollToRow
})
</script>

<template>
  <div class="table-viewer" ref="containerRef">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="stats">
        <span>{{ totalRows }} 行</span>
        <span class="separator">·</span>
        <span>{{ totalCols }} 列</span>
      </div>
    </div>

    <!-- 表格内容 -->
    <div class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th class="row-number">#</th>
            <th v-for="header in headers" :key="header">{{ header }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in tableData"
            :key="row.id"
            :id="`row-${row.rowNumber}`"
            :class="{ active: activeRow === row.rowNumber }"
            @click="handleRowClick(row.rowNumber)"
          >
            <td class="row-number">{{ row.rowNumber }}</td>
            <td v-for="cell in row.cells" :key="cell.col">{{ cell.value }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.table-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
  font-size: 13px;
  color: #6b7280;
}

.stats {
  display: flex;
  align-items: center;
  gap: 8px;
}

.separator {
  color: #d1d5db;
}

.table-container {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.data-table th,
.data-table td {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
  text-align: left;
}

.data-table th {
  background: #f9fafb;
  font-weight: 600;
  color: #374151;
  position: sticky;
  top: 0;
  z-index: 1;
}

.data-table td {
  color: #4b5563;
}

.data-table tr:hover td {
  background: #f3f4f6;
}

.data-table tr.active td {
  background: #dbeafe;
}

.row-number {
  width: 60px;
  text-align: center;
  color: #9ca3af;
  font-size: 12px;
}

.highlight-row {
  animation: highlight-fade 3s ease-out;
}

@keyframes highlight-fade {
  0% { background: #fef3c7; }
  100% { background: transparent; }
}
</style>
