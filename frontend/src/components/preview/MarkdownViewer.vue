<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { marked } from 'marked'
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
const activeSection = ref<string | null>(null)

// Markdown 内容
const markdownHtml = computed(() => {
  return props.content.blocks
    .map((block) => {
      const raw = String(block.content || '')
      const html = marked.parse(raw, { breaks: true, gfm: true }) as string
      const lineNumber = Number(block.metadata?.line_number || 0)
      return `<div id="md-block-${block.id}" data-line="${lineNumber}" class="md-block">${html}</div>`
    })
    .join('')
})

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

// 标题列表（用于目录）
const headings = computed(() => {
  if (props.toc && props.toc.length > 0) {
    return flattenToc(props.toc).map(item => {
      const a = item.source_anchor || {}
      return {
        id: item.node_id,
        level: Math.max(1, (item.level || 0) + 1),
        text: item.title,
        lineNumber: Number(a.start_line || item.start_page || 1),
        blockId: undefined as string | undefined,
      }
    })
  }

  return props.content.blocks
    .filter(block => block.type === 'heading')
    .map(block => ({
      id: block.id,
      level: block.metadata.level as number,
      text: block.content as string,
      lineNumber: block.metadata.line_number as number,
      blockId: block.id,
    }))
})

// 总字符数
const charCount = computed(() => props.content.metadata.char_count || 0)

// 章节数
const sectionCount = computed(() => props.content.metadata.section_count || 0)

// 跳转到指定章节
async function scrollToSection(sectionId: string) {
  activeSection.value = sectionId
  await nextTick()
  
  const element = document.getElementById(`md-block-${sectionId}`)
  if (element && containerRef.value) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
    element.classList.add('highlight-section')
    setTimeout(() => {
      element.classList.remove('highlight-section')
    }, 3000)
  }
}

function scrollToLine(lineNumber: number) {
  const targetLine = lineNumber
  const exact = props.content.blocks.find(
    b => Number(b.metadata?.line_number || 0) === targetLine
  )
  const section = exact || [...props.content.blocks]
    .reverse()
    .find((b) => Number(b.metadata?.line_number || 0) <= targetLine)
  if (section) {
    scrollToSection(section.id)
  }
}

// 处理标题点击
function handleHeadingClick(heading: { id: string; lineNumber: number; blockId?: string }) {
  const anchor: SourceAnchor = {
    format: 'markdown',
    start_line: heading.lineNumber,
    end_line: heading.lineNumber
  }
  emit('anchorClick', anchor)
  activeSection.value = heading.id
  if (heading.blockId) {
    scrollToSection(heading.blockId)
    return
  }
  scrollToLine(heading.lineNumber)
}

// 监听初始锚点
watch(() => props.initialAnchor, (anchor) => {
  if (anchor?.start_line) {
    scrollToLine(anchor.start_line)
  }
}, { immediate: true })

defineExpose({
  scrollToSection
})
</script>

<template>
  <div class="markdown-viewer" ref="containerRef">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="stats">
        <span>{{ sectionCount }} 章节</span>
        <span class="separator">·</span>
        <span>{{ charCount.toLocaleString() }} 字符</span>
      </div>
    </div>

    <div class="main-content">
      <!-- 目录 -->
      <aside v-if="headings.length > 0" class="toc-sidebar">
        <div class="toc-title">目录</div>
        <nav class="toc-nav">
          <div
            v-for="heading in headings"
            :key="heading.id"
            :class="['toc-item', `level-${heading.level}`, { active: activeSection === heading.id }]"
            @click="handleHeadingClick(heading)"
          >
            {{ heading.text }}
          </div>
        </nav>
      </aside>

      <!-- 内容 -->
      <article class="markdown-body" v-html="markdownHtml"></article>
    </div>
  </div>
</template>

<style scoped>
.markdown-viewer {
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

.toc-item.level-1 {
  font-weight: 500;
}

.toc-item.level-2 {
  padding-left: 16px;
  font-size: 12px;
}

.toc-item.level-3 {
  padding-left: 24px;
  font-size: 12px;
  color: #6b7280;
}

.markdown-body {
  flex: 1;
  padding: 24px 32px;
  overflow-y: auto;
  font-size: 14px;
  line-height: 1.6;
  color: #24292f;
}

.markdown-body :deep(.md-block) {
  scroll-margin-top: 16px;
}

.markdown-body :deep(h1) {
  font-size: 2em;
  border-bottom: 1px solid #d0d7de;
  padding-bottom: 0.3em;
  margin-bottom: 1em;
}

.markdown-body :deep(h2) {
  font-size: 1.5em;
  border-bottom: 1px solid #d0d7de;
  padding-bottom: 0.3em;
  margin-top: 1.5em;
  margin-bottom: 1em;
}

.markdown-body :deep(h3) {
  font-size: 1.25em;
  margin-top: 1.5em;
  margin-bottom: 1em;
}

.markdown-body :deep(p) {
  margin-bottom: 1em;
}

.markdown-body :deep(code) {
  background: #f6f8fa;
  padding: 0.2em 0.4em;
  border-radius: 3px;
  font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
  font-size: 0.9em;
}

.markdown-body :deep(pre) {
  background: #f6f8fa;
  padding: 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin-bottom: 1em;
}

.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin-bottom: 1em;
  padding-left: 2em;
}

.markdown-body :deep(li) {
  margin-bottom: 0.25em;
}

.markdown-body :deep(blockquote) {
  border-left: 4px solid #d0d7de;
  padding-left: 1em;
  color: #57606a;
  margin-bottom: 1em;
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin-bottom: 1em;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #d0d7de;
  padding: 6px 13px;
}

.markdown-body :deep(th) {
  background: #f6f8fa;
  font-weight: 600;
}

.markdown-body :deep(tr:nth-child(2n)) {
  background: #f6f8fa;
}

.highlight-section {
  animation: highlight-fade 3s ease-out;
}

@keyframes highlight-fade {
  0% { background: #fef3c7; }
  100% { background: transparent; }
}
</style>
