<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs'
import { 
  X, 
  ZoomIn, 
  ZoomOut, 
  RotateCw,
  FileText,
  BookOpen,
  ChevronUp,
  ChevronDown
} from 'lucide-vue-next'
import { formatFileSize, formatDate } from '@/lib/utils'
import TocTree from './TocTree.vue'

// 设置 PDF.js worker
import pdfWorker from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

interface TocItem {
  node_id: string
  title: string
  level: number
  summary: string
  start_page: number | null
  end_page: number | null
  children?: TocItem[]
}

interface PreviewData {
  id: string
  name: string
  file_type: string
  file_size: number
  status: string
  page_count: number | null
  description?: string
  created_at: string
  updated_at: string
  toc: TocItem[]
  stats: {
    node_count: number
    text_chars: number
    has_summaries: number
    summary_coverage: string
  }
}

interface Props {
  fileUrl: string
  fileName: string
  previewData: PreviewData
  initialPage?: number
}

interface Emits {
  (e: 'close'): void
}

const props = withDefaults(defineProps<Props>(), {
  initialPage: 1
})

const emit = defineEmits<Emits>()

// PDF 文档
let pdfDocument: pdfjsLib.PDFDocumentProxy | null = null
const totalPages = ref(0)
const isLoading = ref(true)
const error = ref<string | null>(null)

// 页面信息（不包括 canvas，避免 Vue 响应式问题）
interface PageInfo {
  pageNum: number
  rendered: boolean
  rendering: boolean
  width: number
  height: number
}

const pages = ref<PageInfo[]>([])
const renderedCanvases = new Map<number, HTMLCanvasElement>() // 存储已渲染的 canvas，避开 Vue 响应式

const scrollContainerRef = ref<HTMLDivElement | null>(null)
const currentVisiblePage = ref(1)

// 缩放：百分比
const zoomPercent = ref(100)
const rotation = ref(0)

// 面板状态
const activeTab = ref<'info' | 'toc'>('toc')

// 计算属性
const displayPageInfo = computed(() => {
  return `${currentVisiblePage.value} / ${totalPages.value}`
})

// 加载 PDF
const loadPdf = async () => {
  try {
    isLoading.value = true
    error.value = null
    renderedCanvases.clear()
    
    const token = localStorage.getItem('token')
    const loadingTask = pdfjsLib.getDocument({
      url: props.fileUrl,
      httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined,
      withCredentials: false,
    })
    pdfDocument = await loadingTask.promise
    totalPages.value = pdfDocument.numPages
    
    console.log('[PDF] Loaded, pages:', totalPages.value)
    
    // 初始化页面数组
    pages.value = Array.from({ length: totalPages.value }, (_, i) => ({
      pageNum: i + 1,
      rendered: false,
      rendering: false,
      width: 0,
      height: 0
    }))
    
    // 等待 DOM 就绪
    await nextTick()
    await new Promise(resolve => setTimeout(resolve, 100))
    
    isLoading.value = false
    
    // 开始渲染可见页面
    await nextTick()
    setTimeout(() => {
      renderVisiblePages()
    }, 50)
    
    // 滚动到初始页面
    if (props.initialPage > 1) {
      setTimeout(() => {
        scrollToPage(props.initialPage)
      }, 200)
    }
    
  } catch (err: any) {
    console.error('[PDF] Load failed:', err)
    error.value = '加载失败，请刷新重试'
    isLoading.value = false
  }
}

// 渲染指定页面
const renderPage = async (pageIndex: number) => {
  if (!pdfDocument || pageIndex < 0 || pageIndex >= pages.value.length) return
  
  const pageInfo = pages.value[pageIndex]
  if (pageInfo.rendered || pageInfo.rendering) return
  
  pageInfo.rendering = true
  
  try {
    const page = await pdfDocument.getPage(pageInfo.pageNum)
    
    // 获取容器宽度
    const containerWidth = scrollContainerRef.value?.clientWidth || 800
    const availableWidth = containerWidth - 80
    
    // 获取 PDF 原始尺寸
    const viewport1 = page.getViewport({ scale: 1, rotation: rotation.value })
    
    // 计算缩放
    const baseScale = availableWidth / viewport1.width
    const finalScale = baseScale * (zoomPercent.value / 100)
    
    const viewport = page.getViewport({ scale: finalScale, rotation: rotation.value })
    
    // 存储尺寸信息
    pageInfo.width = viewport.width
    pageInfo.height = viewport.height
    
    // 创建 canvas
    const canvas = document.createElement('canvas')
    canvas.width = viewport.width
    canvas.height = viewport.height
    canvas.style.display = 'block'
    
    // 渲染
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      await page.render({ canvasContext: ctx, viewport, canvas } as any).promise
      
      // 存储 canvas（不放入响应式数据）
      renderedCanvases.set(pageInfo.pageNum, canvas)
      pageInfo.rendered = true
      
      // 将 canvas 插入到对应的容器中
      await nextTick()
      const container = scrollContainerRef.value?.querySelector(`[data-page="${pageInfo.pageNum}"]`)
      if (container && !container.querySelector('canvas')) {
        container.innerHTML = ''
        container.appendChild(canvas)
        console.log(`[PDF] Page ${pageInfo.pageNum} canvas inserted`)
      }
      
      console.log(`[PDF] Page ${pageInfo.pageNum} rendered`)
    }
  } catch (err: any) {
    console.error(`[PDF] Render page ${pageInfo.pageNum} failed:`, err)
  } finally {
    pageInfo.rendering = false
  }
}

// 渲染可见页面
const renderVisiblePages = () => {
  if (!scrollContainerRef.value) return
  
  const container = scrollContainerRef.value
  const scrollTop = container.scrollTop
  const containerHeight = container.clientHeight
  
  // 找出可见的页面索引
  let foundVisible = false
  const renderPromises: Promise<void>[] = []
  
  for (let i = 0; i < pages.value.length; i++) {
    const pageInfo = pages.value[i]
    
    // 估算页面位置
    let pageTop = 0
    for (let j = 0; j < i; j++) {
      pageTop += (pages.value[j].height || 800) + 20
    }
    
    const pageBottom = pageTop + (pageInfo.height || 800)
    
    // 检查页面是否在可视区域内（加上下缓冲区）
    const buffer = containerHeight
    const isVisible = pageBottom >= scrollTop - buffer && pageTop <= scrollTop + containerHeight + buffer
    
    if (isVisible && !pageInfo.rendered && !pageInfo.rendering) {
      renderPromises.push(renderPage(i))
    }
    
    // 更新当前可见页面
    if (!foundVisible && pageBottom > scrollTop + containerHeight / 2) {
      currentVisiblePage.value = pageInfo.pageNum
      foundVisible = true
    }
  }
  
  if (!foundVisible && pages.value.length > 0) {
    currentVisiblePage.value = pages.value[pages.value.length - 1].pageNum
  }
  
  // 批量执行渲染
  Promise.all(renderPromises)
}

// 滚动到指定页面
const scrollToPage = (pageNum: number) => {
  if (!scrollContainerRef.value || pageNum < 1 || pageNum > totalPages.value) return
  
  const pageIndex = pageNum - 1
  
  // 如果页面未渲染，先渲染
  if (!pages.value[pageIndex]?.rendered) {
    renderPage(pageIndex).then(() => {
      doScroll(pageIndex)
    })
  } else {
    doScroll(pageIndex)
  }
}

const doScroll = (pageIndex: number) => {
  if (!scrollContainerRef.value) return

  const container = scrollContainerRef.value
  const targetPageNum = pageIndex + 1
  const targetEl = container.querySelector(`[data-page="${targetPageNum}"]`) as HTMLElement | null

  let scrollTop = 0
  if (targetEl) {
    const containerRect = container.getBoundingClientRect()
    const targetRect = targetEl.getBoundingClientRect()
    scrollTop = container.scrollTop + (targetRect.top - containerRect.top) - 8
  } else {
    for (let i = 0; i < pageIndex; i++) {
      scrollTop += (pages.value[i]?.height || 800) + 20
    }
  }

  container.scrollTo({
    top: Math.max(0, scrollTop),
    behavior: 'smooth'
  })
  
  currentVisiblePage.value = pageIndex + 1
}

// 上一页
const previousPage = () => {
  if (currentVisiblePage.value > 1) {
    scrollToPage(currentVisiblePage.value - 1)
  }
}

// 下一页
const nextPage = () => {
  if (currentVisiblePage.value < totalPages.value) {
    scrollToPage(currentVisiblePage.value + 1)
  }
}

// 放大
const zoomIn = () => {
  zoomPercent.value = Math.min(zoomPercent.value + 20, 300)
  console.log('[PDF] Zoom in:', zoomPercent.value + '%')
  clearAllPages()
  setTimeout(renderVisiblePages, 50)
}

// 缩小
const zoomOut = () => {
  zoomPercent.value = Math.max(zoomPercent.value - 20, 50)
  console.log('[PDF] Zoom out:', zoomPercent.value + '%')
  clearAllPages()
  setTimeout(renderVisiblePages, 50)
}

// 旋转
const rotate = () => {
  rotation.value = (rotation.value + 90) % 360
  clearAllPages()
  setTimeout(renderVisiblePages, 50)
}

// 清除所有页面（用于重新渲染）
const clearAllPages = () => {
  renderedCanvases.clear()
  pages.value.forEach(page => {
    page.rendered = false
    page.rendering = false
    page.width = 0
    page.height = 0
  })
}

// 处理滚动
let scrollTimeout: ReturnType<typeof setTimeout> | null = null
const handleScroll = () => {
  if (scrollTimeout) clearTimeout(scrollTimeout)
  scrollTimeout = setTimeout(() => {
    renderVisiblePages()
  }, 100)
}

// 处理键盘
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
    previousPage()
  } else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
    nextPage()
  } else if (e.key === 'Escape') {
    emit('close')
  }
}

// 点击目录项
const handleTocClick = (pageNum: number) => {
  if (pageNum && pageNum >= 1) {
    scrollToPage(pageNum)
  }
}

onMounted(() => {
  loadPdf()
  window.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown)
  renderedCanvases.clear()
  if (pdfDocument) {
    pdfDocument.destroy()
    pdfDocument = null
  }
})
</script>

<template>
  <div class="pdf-preview-overlay" @click.self="$emit('close')">
    <div class="pdf-preview-container">
      <!-- 顶部工具栏 -->
      <div class="preview-toolbar">
        <div class="toolbar-left">
          <button class="toolbar-btn" @click="$emit('close')">
            <X class="w-5 h-5" />
          </button>
          <span class="file-name">{{ fileName }}</span>
        </div>
        
        <div class="toolbar-center">
          <button class="toolbar-btn" @click="previousPage">
            <ChevronUp class="w-5 h-5" />
          </button>
          
          <span class="page-info">{{ displayPageInfo }}</span>
          
          <button class="toolbar-btn" @click="nextPage">
            <ChevronDown class="w-5 h-5" />
          </button>
        </div>
        
        <div class="toolbar-right">
          <button class="toolbar-btn" @click="zoomOut">
            <ZoomOut class="w-5 h-5" />
          </button>
          <span class="zoom-level">{{ zoomPercent }}%</span>
          <button class="toolbar-btn" @click="zoomIn">
            <ZoomIn class="w-5 h-5" />
          </button>
          <button class="toolbar-btn" @click="rotate">
            <RotateCw class="w-5 h-5" />
          </button>
        </div>
      </div>
      
      <!-- 主体：左右两栏 -->
      <div class="preview-body">
        <!-- 左侧：连续滚动 PDF -->
        <div 
          class="pdf-scroll-container" 
          ref="scrollContainerRef"
          @scroll="handleScroll"
        >
          <div v-if="isLoading" class="state-message">
            <div class="loading-spinner"></div>
            <span>正在加载PDF...</span>
          </div>
          
          <div v-else-if="error" class="state-message error">
            <span>{{ error }}</span>
            <button class="retry-btn" @click="loadPdf">重试</button>
          </div>
          
          <div v-else class="pages-wrapper">
            <div 
              v-for="page in pages" 
              :key="page.pageNum"
              class="page-item"
              :class="{ 'page-visible': page.pageNum === currentVisiblePage }"
              :style="{ minHeight: (page.height || 800) + 'px' }"
            >
              <div class="page-number">{{ page.pageNum }}</div>
              
              <div class="page-canvas-wrapper">
                <!-- 页面容器，使用 data-page 标记 -->
                <div 
                  :data-page="page.pageNum"
                  class="page-container"
                  :class="{ 'is-rendered': page.rendered }"
                  :style="page.rendered ? { width: page.width + 'px', height: page.height + 'px' } : {}"
                >
                  <div v-if="!page.rendered" class="page-placeholder">
                    <div class="loading-spinner small"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        
        <!-- 右侧：信息面板 -->
        <div class="info-panel">
          <div class="panel-tabs">
            <button class="tab-btn" :class="{ active: activeTab === 'toc' }" @click="activeTab = 'toc'">
              <BookOpen class="w-4 h-4" />
              <span>目录</span>
            </button>
            <button class="tab-btn" :class="{ active: activeTab === 'info' }" @click="activeTab = 'info'">
              <FileText class="w-4 h-4" />
              <span>信息</span>
            </button>
          </div>
          
          <!-- 目录 -->
          <div v-if="activeTab === 'toc'" class="panel-content">
            <div v-if="previewData.toc.length === 0" class="empty-state">
              暂无目录信息
            </div>
            <div v-else class="toc-tree-container">
              <TocTree 
                :nodes="previewData.toc" 
                :current-page="currentVisiblePage"
                @select="handleTocClick"
              />
            </div>
          </div>
          
          <!-- 信息 -->
          <div v-else class="panel-content">
            <div class="info-section">
              <h4 class="section-title">基本信息</h4>
              <div class="info-list">
                <div class="info-row">
                  <span class="info-label">文件名</span>
                  <span class="info-value">{{ previewData.name }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">文件类型</span>
                  <span class="info-value">{{ previewData.file_type.toUpperCase() }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">文件大小</span>
                  <span class="info-value">{{ formatFileSize(previewData.file_size) }}</span>
                </div>
                <div class="info-row">
                  <span class="info-label">页数</span>
                  <span class="info-value">{{ previewData.page_count || '-' }} 页</span>
                </div>
                <div class="info-row">
                  <span class="info-label">创建时间</span>
                  <span class="info-value">{{ formatDate(previewData.created_at) }}</span>
                </div>
              </div>
            </div>
            
            <div v-if="previewData.description" class="info-section">
              <h4 class="section-title">文档摘要</h4>
              <p class="description-text">{{ previewData.description }}</p>
            </div>
            
            <div class="info-section">
              <h4 class="section-title">索引统计</h4>
              <div class="stats-grid">
                <div class="stat-item">
                  <span class="stat-num">{{ previewData.stats.node_count }}</span>
                  <span class="stat-label">章节数</span>
                </div>
                <div class="stat-item">
                  <span class="stat-num">{{ previewData.stats.summary_coverage }}</span>
                  <span class="stat-label">摘要覆盖率</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-preview-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 20px;
}

.pdf-preview-container {
  width: 95vw;
  height: 95vh;
  background: #1a1a1a;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* 工具栏 */
.preview-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #242424;
  border-bottom: 1px solid #333;
}

.toolbar-left, .toolbar-center, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.toolbar-btn {
  padding: 8px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: #a3a3a3;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.toolbar-btn:hover:not(:disabled) {
  background: #333;
  color: white;
}

.file-name {
  color: #e5e5e5;
  font-size: 14px;
  font-weight: 500;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-info {
  color: #a3a3a3;
  font-size: 13px;
  min-width: 60px;
  text-align: center;
}

.zoom-level {
  color: #a3a3a3;
  font-size: 13px;
  min-width: 45px;
  text-align: center;
}

/* 主体内容 */
.preview-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* 左侧滚动区域 */
.pdf-scroll-container {
  flex: 1;
  background: #0a0a0a;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 20px;
}

.pages-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  padding-bottom: 40px;
}

.page-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.page-number {
  color: #666;
  font-size: 12px;
  padding: 4px 12px;
  background: #1a1a1a;
  border-radius: 4px;
}

.page-item.page-visible .page-number {
  color: #3b82f6;
  background: #1e3a5f;
}

.page-canvas-wrapper {
  display: flex;
  justify-content: center;
}

.page-container {
  background: white;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
  border-radius: 4px;
  overflow: hidden;
}

.page-container canvas {
  display: block;
}

.page-placeholder {
  width: 600px;
  height: 800px;
  background: #1a1a1a;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.state-message {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #a3a3a3;
  height: 100%;
}

.state-message.error {
  color: #ef4444;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #333;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-spinner.small {
  width: 24px;
  height: 24px;
  border-width: 2px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.retry-btn {
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.retry-btn:hover {
  background: #2563eb;
}

/* 右侧信息面板 */
.info-panel {
  width: 380px;
  background: #1a1a1a;
  border-left: 1px solid #333;
  display: flex;
  flex-direction: column;
}

.panel-tabs {
  display: flex;
  border-bottom: 1px solid #333;
}

.tab-btn {
  flex: 1;
  padding: 14px;
  background: transparent;
  border: none;
  color: #a3a3a3;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.2s;
}

.tab-btn.active {
  color: #3b82f6;
  background: #1e3a5f;
}

.tab-btn:hover:not(.active) {
  background: #242424;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.empty-state {
  text-align: center;
  color: #666;
  padding: 40px 20px;
}

/* 目录 */
.toc-tree-container {
  height: 100%;
  overflow-y: auto;
}

.toc-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.title-text {
  color: #e5e5e5;
  font-size: 14px;
  line-height: 1.4;
}

.page-num {
  color: #3b82f6;
  font-size: 12px;
  flex-shrink: 0;
}

.toc-summary {
  margin-top: 6px;
  color: #888;
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 信息面板 */
.info-section {
  margin-bottom: 24px;
}

.section-title {
  color: #e5e5e5;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}

.info-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.info-label {
  color: #888;
  font-size: 13px;
  flex-shrink: 0;
}

.info-value {
  color: #e5e5e5;
  font-size: 13px;
  text-align: right;
  word-break: break-all;
}

.description-text {
  color: #a3a3a3;
  font-size: 13px;
  line-height: 1.6;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.stat-item {
  background: #242424;
  padding: 16px;
  border-radius: 8px;
  text-align: center;
}

.stat-num {
  color: #3b82f6;
  font-size: 20px;
  font-weight: 600;
  display: block;
}

.stat-label {
  color: #888;
  font-size: 12px;
  margin-top: 4px;
}

/* 响应式 */
@media (max-width: 1024px) {
  .info-panel {
    width: 300px;
  }
}

@media (max-width: 768px) {
  .pdf-preview-container {
    width: 100vw;
    height: 100vh;
    border-radius: 0;
  }
  
  .preview-body {
    flex-direction: column;
  }
  
  .info-panel {
    width: 100%;
    height: 200px;
    border-left: none;
    border-top: 1px solid #333;
  }
  
  .file-name {
    display: none;
  }
}
</style>
