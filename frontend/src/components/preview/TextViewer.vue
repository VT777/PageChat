<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { DocumentContent, SourceAnchor, TocItem } from '@/types/preview'

const props = withDefaults(defineProps<{
  content: DocumentContent
  toc?: TocItem[]
  initialAnchor?: SourceAnchor | null
  showToc?: boolean
}>(), {
  showToc: true,
})

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
}>()

const containerRef = ref<HTMLDivElement>()
const activeLine = ref<number | null>(null)
const activeTocLine = ref<number | null>(null)

const lines = computed(() => {
  return props.content.blocks.map((block, index) => ({
    id: block.id,
    lineNumber: Number(block.metadata?.line_number || block.source_anchor?.start_line || index + 1),
    text: String(block.content || ''),
    isHeading: block.type === 'heading',
  }))
})

function inferHeadingLevel(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  if (/^#{1,6}\s+/.test(trimmed)) return Math.min(trimmed.match(/^#+/)?.[0].length || 1, 3)
  if (/^\d+(?:\.\d+){0,3}\s+/.test(trimmed)) return Math.min((trimmed.match(/\./g)?.length || 0) + 1, 3)
  if (/^(chapter|section)\s+\d+/i.test(trimmed)) return 1
  return null
}

function flattenToc(items: TocItem[] = []): TocItem[] {
  const result: TocItem[] = []
  const walk = (nodes: TocItem[]) => {
    for (const node of nodes) {
      result.push(node)
      if (node.children?.length) walk(node.children)
    }
  }
  walk(items)
  return result
}

const tocItems = computed(() => {
  if (props.toc && props.toc.length > 0) {
    return flattenToc(props.toc).map((item) => {
      const anchor = item.source_anchor || {}
      return {
        id: item.node_id,
        title: item.title,
        lineNumber: Number(anchor.start_line || item.start_page || 1),
        level: Math.max(1, (item.level || 0) + 1),
      }
    })
  }

  const headingItems = lines.value
    .map((line) => {
      const level = line.isHeading ? 1 : inferHeadingLevel(line.text)
      if (!level) return null
      return {
        id: line.id,
        title: line.text.trim().replace(/^#{1,6}\s+/, '') || `Line ${line.lineNumber}`,
        lineNumber: line.lineNumber,
        level,
      }
    })
    .filter((item): item is { id: string; title: string; lineNumber: number; level: number } => Boolean(item))

  if (headingItems.length > 0) return headingItems

  const fallback: { id: string; title: string; lineNumber: number; level: number }[] = []
  for (let i = 0; i < lines.value.length; i += 40) {
    const lineNumber = lines.value[i]?.lineNumber
    if (!lineNumber) continue
    fallback.push({
      id: `chunk_${Math.floor(i / 40) + 1}`,
      title: `Text block ${Math.floor(i / 40) + 1}`,
      lineNumber,
      level: 1,
    })
  }
  return fallback
})

const charCount = computed(() => props.content.metadata.char_count || lines.value.reduce((sum, line) => sum + line.text.length, 0))

async function scrollToLine(lineNumber: number) {
  activeLine.value = lineNumber
  activeTocLine.value = lineNumber
  await nextTick()

  const element = document.getElementById(`line-${lineNumber}`)
  if (element && containerRef.value) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('highlight-line')
    setTimeout(() => {
      element.classList.remove('highlight-line')
    }, 3000)
  }
}

function handleLineClick(lineNumber: number) {
  activeTocLine.value = lineNumber
  const anchor: SourceAnchor = {
    format: props.content.format,
    unit_type: 'line',
    start_line: lineNumber,
    end_line: lineNumber,
  }
  emit('anchorClick', anchor)
}

function handleTocClick(lineNumber: number) {
  const anchor: SourceAnchor = {
    format: props.content.format,
    unit_type: 'line',
    start_line: lineNumber,
    end_line: lineNumber,
  }
  emit('anchorClick', anchor)
  scrollToLine(lineNumber)
}

watch(() => props.initialAnchor, (anchor) => {
  if (anchor?.start_line) {
    scrollToLine(anchor.start_line)
  }
}, { immediate: true })

function formatLineNumber(n: number): string {
  return n.toString().padStart(4, '0')
}

defineExpose({
  scrollToLine,
})
</script>

<template>
  <div class="text-viewer" ref="containerRef">
    <div class="toolbar">
      <div class="stats">
        <span>{{ lines.length }} lines</span>
        <span class="separator">/</span>
        <span>{{ charCount.toLocaleString() }} chars</span>
      </div>
    </div>

    <div class="main-content">
      <aside v-if="showToc" class="toc-sidebar">
        <div class="toc-title">Contents</div>
        <div class="toc-nav">
          <button
            v-for="item in tocItems"
            :key="item.id"
            class="toc-item"
            :class="[`level-${item.level}`, { active: activeTocLine === item.lineNumber }]"
            @click="handleTocClick(item.lineNumber)"
          >
            {{ item.title }}
          </button>
        </div>
      </aside>

      <div class="content">
        <div
          v-for="line in lines"
          :key="line.id"
          :id="`line-${line.lineNumber}`"
          :class="['line', { heading: line.isHeading, active: activeLine === line.lineNumber }]"
          @click="handleLineClick(line.lineNumber)"
        >
          <span class="line-number">{{ formatLineNumber(line.lineNumber) }}</span>
          <span class="line-content">{{ line.text || '\u00A0' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.text-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fafafa;
}

.main-content {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.toc-sidebar {
  width: 240px;
  border-right: 1px solid #e5e7eb;
  background: #fafafa;
  overflow-y: auto;
  padding: 16px;
}

.toc-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.toc-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.toc-item {
  border: none;
  background: transparent;
  text-align: left;
  padding: 6px 8px;
  font-size: 13px;
  color: #4b5563;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.toc-item:hover {
  background: #e5e7eb;
  color: #111827;
}

.toc-item.active {
  background: #dbeafe;
  color: #2563eb;
}

.toc-item.level-2 { padding-left: 16px; font-size: 12px; }
.toc-item.level-3 { padding-left: 24px; font-size: 12px; color: #6b7280; }

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

.content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
}

.line {
  display: flex;
  align-items: flex-start;
  padding: 2px 16px;
  cursor: pointer;
  transition: background 0.15s;
}

.line:hover {
  background: #f3f4f6;
}

.line.active {
  background: #dbeafe;
}

.line.highlight-line {
  background: #fef3c7;
  animation: highlight-fade 3s ease-out;
}

@keyframes highlight-fade {
  0% { background: #fcd34d; }
  100% { background: transparent; }
}

.line-number {
  min-width: 48px;
  color: #9ca3af;
  text-align: right;
  padding-right: 16px;
  user-select: none;
}

.line-content {
  flex: 1;
  color: #374151;
  white-space: pre-wrap;
  word-break: break-word;
}

.line.heading .line-content {
  font-weight: 600;
  color: #111827;
}
</style>
