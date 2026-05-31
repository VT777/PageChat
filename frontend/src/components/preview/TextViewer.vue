<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import type { DocumentContent, SourceAnchor, TocItem } from '@/types/preview'

const props = defineProps<{
  content: DocumentContent
  toc?: TocItem[]
  initialAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
}>()

const containerRef = ref<HTMLDivElement>()
const activeLine = ref<number | null>(null)
const activeTocLine = ref<number | null>(null)

// 文本行
const lines = computed(() => {
  return props.content.blocks.map(block => ({
    id: block.id,
    lineNumber: block.metadata.line_number as number,
    text: block.content as string,
    isHeading: block.type === 'heading'
  }))
})

function inferHeadingLevel(text: string): number | null {
  const t = String(text || '').trim()
  if (!t) return null
  if (/^第[一二三四五六七八九十百千万0-9]+[章节部篇]/.test(t)) return 1
  if (/^[一二三四五六七八九十百千万]+[、\.．]/.test(t)) return 1
  if (/^[（(][一二三四五六七八九十百千万0-9]+[)）]/.test(t)) return 2
  if (/^\d+(?:\.\d+){0,3}[、\.．]/.test(t)) return Math.min((t.match(/\./g)?.length || 0) + 1, 3)
  return null
}

function flattenToc(items: TocItem[] = []): TocItem[] {
  const result: TocItem[] = []
  const walk = (nodes: TocItem[]) => {
    for (const n of nodes) {
      result.push(n)
      if (n.children && n.children.length > 0) walk(n.children)
    }
  }
  walk(items)
  return result
}

const tocItems = computed(() => {
  if (props.toc && props.toc.length > 0) {
    return flattenToc(props.toc).map((item) => {
      const a = item.source_anchor || {}
      return {
        id: item.node_id,
        title: item.title,
        lineNumber: Number(a.start_line || item.start_page || 1),
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
        title: line.text.trim() || `第 ${line.lineNumber} 行`,
        lineNumber: line.lineNumber,
        level,
      }
    })
    .filter((x): x is { id: string; title: string; lineNumber: number; level: number } => Boolean(x))

  if (headingItems.length > 0) return headingItems

  const fallback: { id: string; title: string; lineNumber: number; level: number }[] = []
  for (let i = 0; i < lines.value.length; i += 40) {
    const lineNumber = lines.value[i]?.lineNumber
    if (!lineNumber) continue
    fallback.push({
      id: `chunk_${Math.floor(i / 40) + 1}`,
      title: `文本段 ${Math.floor(i / 40) + 1}`,
      lineNumber,
      level: 1,
    })
  }
  return fallback
})

// 总字符数
const charCount = computed(() => props.content.metadata.char_count || 0)

// 跳转到指定行
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

// 处理行点击
function handleLineClick(lineNumber: number) {
  activeTocLine.value = lineNumber
  const anchor: SourceAnchor = {
    format: 'txt',
    start_line: lineNumber,
    end_line: lineNumber
  }
  emit('anchorClick', anchor)
}

function handleTocClick(lineNumber: number) {
  const anchor: SourceAnchor = {
    format: 'txt',
    start_line: lineNumber,
    end_line: lineNumber,
  }
  emit('anchorClick', anchor)
  scrollToLine(lineNumber)
}

// 监听初始锚点
watch(() => props.initialAnchor, (anchor) => {
  if (anchor?.start_line) {
    scrollToLine(anchor.start_line)
  }
}, { immediate: true })

// 格式化行号
function formatLineNumber(n: number): string {
  return n.toString().padStart(4, '0')
}

defineExpose({
  scrollToLine
})
</script>

<template>
  <div class="text-viewer" ref="containerRef">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="stats">
        <span>{{ lines.length }} 行</span>
        <span class="separator">·</span>
        <span>{{ charCount.toLocaleString() }} 字符</span>
      </div>
    </div>
    
    <!-- 内容区域 -->
    <div class="main-content">
      <aside class="toc-sidebar">
        <div class="toc-title">目录</div>
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
  word-break: break-all;
}

.line.heading .line-content {
  font-weight: 600;
  color: #111827;
}
</style>
