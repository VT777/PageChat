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
const activeParagraph = ref<number | null>(null)
const activeTocParagraph = ref<number | null>(null)

// 段落列表
const paragraphs = computed(() => {
  return props.content.blocks
    .filter(block => block.type === 'paragraph')
    .map(block => ({
      id: block.id,
      paraNumber: block.metadata.paragraph_number as number,
      text: block.content as string,
      hasImages: (block.metadata.images?.length || 0) > 0
    }))
})

function inferHeadingLevel(text: string): number | null {
  const t = String(text || '').trim()
  if (!t) return null
  if (/^第[一二三四五六七八九十百千万0-9]+[章节部篇]/.test(t)) return 1
  if (/^[一二三四五六七八九十百千万]+[、\.．]/.test(t)) return 1
  if (/^[（(][一二三四五六七八九十百千万0-9]+[)）]/.test(t)) return 2
  const m = t.match(/^(\d+(?:\.\d+){0,3})[、\.．]/)
  if (m) return Math.min((m[1].match(/\./g)?.length || 0) + 1, 3)
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
        paraNumber: Number(a.start_paragraph || item.start_page || 1),
        title: item.title,
        level: Math.max(1, (item.level || 0) + 1),
      }
    })
  }

  const items = paragraphs.value
    .map((p) => {
      const level = inferHeadingLevel(p.text)
      if (!level) return null
      return {
        id: p.id,
        paraNumber: p.paraNumber,
        title: p.text.trim(),
        level,
      }
    })
    .filter((x): x is { id: string; paraNumber: number; title: string; level: number } => Boolean(x))

  if (items.length > 0) return items

  const fallback: { id: string; paraNumber: number; title: string; level: number }[] = []
  for (let i = 0; i < paragraphs.value.length; i += 20) {
    const para = paragraphs.value[i]
    if (!para) continue
    fallback.push({
      id: `chunk_${Math.floor(i / 20) + 1}`,
      paraNumber: para.paraNumber,
      title: `段落组 ${Math.floor(i / 20) + 1}`,
      level: 1,
    })
  }
  return fallback
})

// 图片列表
const images = computed(() => props.content.images || [])

// 统计信息
const stats = computed(() => ({
  paragraphs: props.content.metadata.paragraph_count || 0,
  images: props.content.metadata.image_count || 0
}))

// 跳转到指定段落
async function scrollToParagraph(paraNumber: number) {
  activeParagraph.value = paraNumber
  activeTocParagraph.value = paraNumber
  await nextTick()
  
  const element = document.getElementById(`para-${paraNumber}`)
  if (element && containerRef.value) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' })
    element.classList.add('highlight-paragraph')
    setTimeout(() => {
      element.classList.remove('highlight-paragraph')
    }, 3000)
  }
}

// 处理段落点击
function handleParagraphClick(paraNumber: number) {
  activeTocParagraph.value = paraNumber
  const anchor: SourceAnchor = {
    format: 'docx',
    start_paragraph: paraNumber,
    end_paragraph: paraNumber
  }
  emit('anchorClick', anchor)
}

function handleTocClick(paraNumber: number) {
  const anchor: SourceAnchor = {
    format: 'docx',
    start_paragraph: paraNumber,
    end_paragraph: paraNumber,
  }
  emit('anchorClick', anchor)
  scrollToParagraph(paraNumber)
}

// 处理图片点击
function handleImageClick(imageId: string) {
  // 可以扩展为打开大图预览
  console.log('Image clicked:', imageId)
}

// 监听初始锚点
watch(() => props.initialAnchor, (anchor) => {
  if (anchor?.start_paragraph) {
    scrollToParagraph(anchor.start_paragraph)
  }
}, { immediate: true })

defineExpose({
  scrollToParagraph
})
</script>

<template>
  <div class="docx-viewer" ref="containerRef">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="stats">
        <span>{{ stats.paragraphs }} 段落</span>
        <span class="separator">·</span>
        <span>{{ stats.images }} 图片</span>
      </div>
    </div>

    <div class="main-content">
      <aside class="toc-sidebar">
        <div class="toc-title">目录</div>
        <div class="toc-nav">
          <button
            v-for="item in tocItems"
            :key="item.id"
            class="toc-item"
            :class="[`level-${item.level}`, { active: activeTocParagraph === item.paraNumber }]"
            @click="handleTocClick(item.paraNumber)"
          >
            {{ item.title }}
          </button>
        </div>
      </aside>

      <!-- 段落列表 -->
      <div class="paragraphs-container">
        <div
          v-for="para in paragraphs"
          :key="para.id"
          :id="`para-${para.paraNumber}`"
          :class="['paragraph', { active: activeParagraph === para.paraNumber }]"
          @click="handleParagraphClick(para.paraNumber)"
        >
          <span class="para-number">{{ para.paraNumber }}</span>
          <span class="para-text">{{ para.text }}</span>
        </div>
        
        <!-- 无内容提示 -->
        <div v-if="paragraphs.length === 0" class="empty-state">
          <p>文档无文本内容</p>
        </div>
      </div>

      <!-- 图片列表（侧边栏） -->
      <aside v-if="images.length > 0" class="images-sidebar">
        <div class="images-title">文档图片 ({{ images.length }})</div>
        
        <div class="images-list">
          <div
            v-for="(image, index) in images"
            :key="image.id"
            class="image-item"
            @click="handleImageClick(image.id)"
          >
            <img
              :src="image.data"
              :alt="image.name"
              class="image-thumb"
              loading="lazy"
            />
            <div class="image-name">图片 {{ index + 1 }}</div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.docx-viewer {
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

.paragraphs-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  font-size: 14px;
  line-height: 1.8;
}

.paragraph {
  display: flex;
  align-items: flex-start;
  padding: 8px 0;
  border-bottom: 1px solid #f3f4f6;
  cursor: pointer;
  transition: background 0.15s;
}

.paragraph:hover {
  background: #f9fafb;
}

.paragraph.active {
  background: #dbeafe;
}

.paragraph.highlight-paragraph {
  animation: highlight-fade 3s ease-out;
}

@keyframes highlight-fade {
  0% { background: #fef3c7; }
  100% { background: transparent; }
}

.para-number {
  min-width: 40px;
  color: #9ca3af;
  font-size: 12px;
  padding-right: 16px;
  user-select: none;
  flex-shrink: 0;
}

.para-text {
  flex: 1;
  color: #374151;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #9ca3af;
  font-size: 14px;
}

.images-sidebar {
  width: 200px;
  border-left: 1px solid #e5e7eb;
  background: #fafafa;
  overflow-y: auto;
  padding: 16px;
}

.images-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
}

.images-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.image-item {
  cursor: pointer;
  transition: transform 0.15s;
}

.image-item:hover {
  transform: scale(1.02);
}

.image-thumb {
  width: 100%;
  aspect-ratio: 4/3;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.image-name {
  margin-top: 4px;
  font-size: 11px;
  color: #6b7280;
  text-align: center;
}
</style>
