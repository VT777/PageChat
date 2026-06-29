<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { DocumentContent, SourceAnchor } from '@/types/preview'
import { normalizePreviewBlocks } from '@/utils/documentWorkbench'

type PreviewCell = {
  col: string
  value: string
}

type PreviewRow = {
  id: string
  rowNumber: number
  sheet?: string
  cells: PreviewCell[]
}

const props = defineProps<{
  content: DocumentContent
  initialAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
}>()

const containerRef = ref<HTMLDivElement>()
const activeRow = ref<number | null>(null)

const tableData = computed<PreviewRow[]>(() => {
  return normalizePreviewBlocks(props.content)
    .filter((block) => block.type === 'table_row')
    .map((block) => ({
      id: String(block.id),
      rowNumber: Number(block.rowNumber),
      sheet: block.sheet ? String(block.sheet) : undefined,
      cells: block.cells as PreviewCell[],
    }))
})

const headers = computed(() => {
  const explicit = Array.isArray(props.content.metadata.headers) ? props.content.metadata.headers : []
  if (explicit.length > 0) return explicit

  const firstRow = tableData.value[0]
  if (!firstRow) return []
  return firstRow.cells.map((cell) => cell.col)
})

const sheetNames = computed(() => {
  return Array.from(new Set(tableData.value.map((row) => row.sheet).filter(Boolean))) as string[]
})

const totalRows = computed(() => {
  const metadata = props.content.metadata as Record<string, unknown>
  return Number(metadata.total_rows || metadata.row_count || tableData.value.length)
})

const totalCols = computed(() => {
  const metadata = props.content.metadata as Record<string, unknown>
  const firstRowCols = tableData.value[0]?.cells.length || 0
  return Number(metadata.total_cols || metadata.col_count || headers.value.length || firstRowCols)
})

async function scrollToRow(rowNumber: number) {
  activeRow.value = rowNumber
  await nextTick()

  const element = document.getElementById(rowElementId(rowNumber))
  if (element && containerRef.value) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('highlight-row')
    setTimeout(() => {
      element.classList.remove('highlight-row')
    }, 3000)
  }
}

function rowElementId(rowNumber: number) {
  return `row-${rowNumber}`
}

function handleRowClick(row: PreviewRow) {
  const rowNumber = row.rowNumber
  activeRow.value = rowNumber
  const anchor: SourceAnchor = {
    format: props.content.format,
    unit_type: 'row_range',
    sheet: row.sheet,
    start_row: rowNumber,
    end_row: rowNumber,
  }
  emit('anchorClick', anchor)
}

watch(() => props.initialAnchor, (anchor) => {
  if (anchor?.start_row) {
    scrollToRow(anchor.start_row)
  }
}, { immediate: true })

defineExpose({
  scrollToRow,
})
</script>

<template>
  <div class="table-viewer" ref="containerRef">
    <div class="toolbar">
      <div class="stats">
        <span>{{ totalRows }} rows</span>
        <span class="separator">/</span>
        <span>{{ totalCols }} columns</span>
        <template v-if="sheetNames.length > 0">
          <span class="separator">/</span>
          <span>{{ sheetNames.join(', ') }}</span>
        </template>
      </div>
    </div>

    <div class="table-container">
      <table v-if="tableData.length > 0" class="data-table">
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
            :id="rowElementId(row.rowNumber)"
            :class="{ active: activeRow === row.rowNumber }"
            @click="handleRowClick(row)"
          >
            <td class="row-number">{{ row.rowNumber }}</td>
            <td v-for="(cell, index) in row.cells" :key="`${row.id}-${index}`">{{ cell.value }}</td>
          </tr>
        </tbody>
      </table>

      <div v-else class="empty-state">No table rows were extracted.</div>
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

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  color: #9ca3af;
  font-size: 14px;
}

.highlight-row {
  animation: highlight-fade 3s ease-out;
}

@keyframes highlight-fade {
  0% { background: #fef3c7; }
  100% { background: transparent; }
}
</style>
