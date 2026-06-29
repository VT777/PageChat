<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs'
import { X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { currentPdfRenderDimensions } from '@/utils/pdfRenderScale'
import { fetchPdfBlobUrl } from '@/utils/pdfFetch'

// 设置 PDF.js worker
import pdfWorker from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker

interface Props {
  fileUrl: string
  fileName: string
  initialPage?: number
  visible: boolean
  embedded?: boolean  // 是否为内嵌模式（显示在右侧panel中）
}

interface Emits {
  (e: 'close'): void
  (e: 'page-change', page: number): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

// PDF 文档
let pdfDocument: pdfjsLib.PDFDocumentProxy | null = null
let pdfObjectUrl: string | null = null
const totalPages = ref(0)
const isLoading = ref(true)
const error = ref<string | null>(null)

// 页面信息
interface PageInfo {
  pageNum: number
  rendered: boolean
  rendering: boolean
  width: number
  height: number
}

const pages = ref<PageInfo[]>([])
const renderedCanvases = new Map<number, HTMLCanvasElement>()

const scrollContainerRef = ref<HTMLDivElement | null>(null)
const currentVisiblePage = ref(1)

// 缩放
const zoomPercent = ref(100)

// 加载 PDF
const loadPdf = async () => {
  if (!props.visible) return
  
  try {
    isLoading.value = true
    error.value = null
    totalPages.value = 0
    pages.value = []
    renderedCanvases.clear()
    releasePdfResources()
    
    pdfObjectUrl = await fetchPdfBlobUrl(props.fileUrl)
    const loadingTask = pdfjsLib.getDocument({
      url: pdfObjectUrl,
    })
    pdfDocument = await loadingTask.promise
    totalPages.value = pdfDocument.numPages
    
    console.log('[PDF Ref] Loaded, pages:', totalPages.value)
    
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
    
    // 开始渲染
    await nextTick()
    setTimeout(() => {
      renderVisiblePages()
      // 滚动到初始页面
      if (props.initialPage && props.initialPage > 1) {
        const initial = props.initialPage
        setTimeout(() => scrollToPage(initial), 200)
      }
    }, 50)
    
  } catch (err: any) {
    console.error('[PDF Ref] Load failed:', err)
    releasePdfResources()
    error.value = err?.message ? `加载失败：${err.message}` : '加载失败'
    isLoading.value = false
  }
}

function releasePdfResources() {
  if (pdfDocument) {
    pdfDocument.destroy()
    pdfDocument = null
  }
  if (pdfObjectUrl) {
    URL.revokeObjectURL(pdfObjectUrl)
    pdfObjectUrl = null
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
    
    const containerWidth = scrollContainerRef.value?.clientWidth || 800
    const availableWidth = containerWidth - 40
    
    const viewport1 = page.getViewport({ scale: 1 })
    const baseScale = availableWidth / viewport1.width
    const finalScale = baseScale * (zoomPercent.value / 100)
    
    const cssViewport = page.getViewport({ scale: finalScale })
    const dimensions = currentPdfRenderDimensions(cssViewport.width, cssViewport.height)
    const renderViewport = page.getViewport({ scale: finalScale * dimensions.outputScale })
    
    pageInfo.width = dimensions.cssWidth
    pageInfo.height = dimensions.cssHeight
    
    const canvas = document.createElement('canvas')
    canvas.width = dimensions.backingWidth
    canvas.height = dimensions.backingHeight
    canvas.style.display = 'block'
    canvas.style.width = `${dimensions.cssWidth}px`
    canvas.style.height = `${dimensions.cssHeight}px`
    
    const ctx = canvas.getContext('2d')
    if (ctx) {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      await page.render({ canvasContext: ctx, viewport: renderViewport, canvas } as any).promise
      
      renderedCanvases.set(pageInfo.pageNum, canvas)
      pageInfo.rendered = true
      
      // 插入到 DOM
      await nextTick()
      const container = scrollContainerRef.value?.querySelector(`[data-page="${pageInfo.pageNum}"]`)
      if (container && !container.querySelector('canvas')) {
        container.innerHTML = ''
        container.appendChild(canvas)
      }
    }
  } catch (err: any) {
    console.error(`[PDF Ref] Render page ${pageInfo.pageNum} failed:`, err)
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
  
  let foundVisible = false
  
  for (let i = 0; i < pages.value.length; i++) {
    const pageInfo = pages.value[i]
    
    let pageTop = 0
    for (let j = 0; j < i; j++) {
      pageTop += (pages.value[j].height || 800) + 16
    }
    
    const pageBottom = pageTop + (pageInfo.height || 800)
    const buffer = containerHeight
    const isVisible = pageBottom >= scrollTop - buffer && pageTop <= scrollTop + containerHeight + buffer
    
    if (isVisible && !pageInfo.rendered && !pageInfo.rendering) {
      renderPage(i)
    }
    
    if (!foundVisible && pageBottom > scrollTop + containerHeight / 2) {
      currentVisiblePage.value = pageInfo.pageNum
      foundVisible = true
      emit('page-change', pageInfo.pageNum)
    }
  }
  
  if (!foundVisible && pages.value.length > 0) {
    currentVisiblePage.value = pages.value[pages.value.length - 1].pageNum
    emit('page-change', currentVisiblePage.value)
  }
}

// 滚动到指定页面
const scrollToPage = (pageNum: number) => {
  if (!scrollContainerRef.value || pageNum < 1 || pageNum > totalPages.value) return
  
  const pageIndex = pageNum - 1
  
  if (!pages.value[pageIndex]?.rendered) {
    renderPage(pageIndex).then(() => doScroll(pageIndex))
  } else {
    doScroll(pageIndex)
  }
}

const doScroll = (pageIndex: number) => {
  const pageNum = pageIndex + 1
  const element = document.getElementById(`pdf-page-${pageNum}`)
  if (!element || !scrollContainerRef.value) return
  
  // 使用 scrollIntoView 精确定位，与 TextViewer/DocxViewer 保持一致
  element.scrollIntoView({ behavior: 'smooth', block: 'start' })
  currentVisiblePage.value = pageNum
}

// 缩放
const zoomIn = () => {
  zoomPercent.value = Math.min(zoomPercent.value + 20, 300)
  clearAllPages()
  setTimeout(renderVisiblePages, 50)
}

const zoomOut = () => {
  zoomPercent.value = Math.max(zoomPercent.value - 20, 50)
  clearAllPages()
  setTimeout(renderVisiblePages, 50)
}

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
  scrollTimeout = setTimeout(renderVisiblePages, 100)
}

// 监听 visible 变化
watch(() => props.visible, (newVal) => {
  if (newVal) {
    loadPdf()
  }
})

// 监听 initialPage 变化
watch(() => props.initialPage, (newVal) => {
  if (newVal && props.visible) {
    scrollToPage(newVal)
  }
})

onMounted(() => {
  if (props.visible) {
    loadPdf()
  }
})

onUnmounted(() => {
  renderedCanvases.clear()
  releasePdfResources()
})

// 暴露方法给父组件
defineExpose({
  scrollToPage
})
</script>

<template>
  <!-- 弹窗模式：带 overlay -->
  <transition name="fade" v-if="!embedded">
    <div v-if="visible" class="pdf-ref-overlay" @click.self="$emit('close')">
      <div class="pdf-ref-container">
        <!-- 顶部工具栏 -->
        <div class="pdf-ref-toolbar">
          <div class="toolbar-left">
            <button class="toolbar-btn" @click="$emit('close')">
              <X class="w-5 h-5" />
            </button>
            <span class="file-name">{{ fileName }}</span>
          </div>
          
          <div class="toolbar-center">
            <span class="page-info">{{ currentVisiblePage }} / {{ totalPages }}</span>
          </div>
          
          <div class="toolbar-right">
            <button class="toolbar-btn" @click="zoomOut">
              <ZoomOut class="w-4 h-4" />
            </button>
            <span class="zoom-level">{{ zoomPercent }}%</span>
            <button class="toolbar-btn" @click="zoomIn">
              <ZoomIn class="w-4 h-4" />
            </button>
          </div>
        </div>
        
        <!-- PDF 内容区域 -->
        <div 
          class="pdf-ref-scroll-container" 
          ref="scrollContainerRef"
          @scroll="handleScroll"
        >
          <div v-if="isLoading" class="state-message">
            <div class="loading-spinner"></div>
            <span>正在加载PDF...</span>
          </div>
          
          <div v-else-if="error" class="state-message error">
            <span>{{ error }}</span>
          </div>
          
          <div v-else class="pages-wrapper">
            <div 
              v-for="page in pages" 
              :key="page.pageNum"
              :id="`pdf-page-${page.pageNum}`"
              class="page-item"
              :class="{ 'page-visible': page.pageNum === currentVisiblePage }"
              :style="{ minHeight: (page.height || 800) + 'px' }"
            >
              <div 
                :data-page="page.pageNum"
                class="page-container"
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
    </div>
  </transition>

  <!-- 内嵌模式：直接显示内容 -->
  <div v-else-if="embedded && visible" class="pdf-embedded-container">
    <div class="pdf-embedded-toolbar">
      <div class="toolbar-left">
        <span class="file-name">{{ fileName }}</span>
      </div>
      <div class="toolbar-center">
        <span class="page-info">{{ currentVisiblePage }} / {{ totalPages }}</span>
      </div>
      <div class="toolbar-right">
        <button class="toolbar-btn" @click="zoomOut">
          <ZoomOut class="w-4 h-4" />
        </button>
        <span class="zoom-level">{{ zoomPercent }}%</span>
        <button class="toolbar-btn" @click="zoomIn">
          <ZoomIn class="w-4 h-4" />
        </button>
      </div>
    </div>
    
    <div 
      class="pdf-ref-scroll-container" 
      ref="scrollContainerRef"
      @scroll="handleScroll"
    >
      <div v-if="isLoading" class="state-message">
        <div class="loading-spinner"></div>
        <span>正在加载PDF...</span>
      </div>
      
      <div v-else-if="error" class="state-message error">
        <span>{{ error }}</span>
      </div>
      
      <div v-else class="pages-wrapper">
        <div 
          v-for="page in pages" 
          :key="page.pageNum"
          :id="`pdf-page-${page.pageNum}`"
          class="page-item"
          :class="{ 'page-visible': page.pageNum === currentVisiblePage }"
          :style="{ minHeight: (page.height || 800) + 'px' }"
        >
          <div 
            :data-page="page.pageNum"
            class="page-container"
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
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.pdf-ref-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 40px;
}

.pdf-ref-container {
  width: 90vw;
  height: 90vh;
  background: #1a1a1a;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

/* 工具栏 */
.pdf-ref-toolbar {
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

.toolbar-btn:hover {
  background: #333;
  color: white;
}

.file-name {
  color: #e5e5e5;
  font-size: 14px;
  font-weight: 500;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-info {
  color: #a3a3a3;
  font-size: 13px;
  font-weight: 500;
}

.zoom-level {
  color: #888;
  font-size: 12px;
  min-width: 40px;
  text-align: center;
}

/* 滚动区域 */
.pdf-ref-scroll-container {
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
  gap: 16px;
  padding-bottom: 40px;
}

.page-item {
  display: flex;
  justify-content: center;
  width: 100%;
}

.page-container {
  background: white;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
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

/* 内嵌模式样式 */
.pdf-embedded-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.pdf-embedded-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #242424;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.pdf-embedded-toolbar .toolbar-left,
.pdf-embedded-toolbar .toolbar-center,
.pdf-embedded-toolbar .toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pdf-embedded-toolbar .file-name {
  color: #e5e5e5;
  font-size: 13px;
  font-weight: 500;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pdf-embedded-toolbar .page-info {
  color: #a3a3a3;
  font-size: 12px;
}

.pdf-embedded-toolbar .zoom-level {
  color: #888;
  font-size: 11px;
  min-width: 35px;
  text-align: center;
}

.pdf-embedded-toolbar .toolbar-btn {
  padding: 6px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: #a3a3a3;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pdf-embedded-toolbar .toolbar-btn:hover {
  background: #333;
  color: white;
}

/* 响应式 */
@media (max-width: 768px) {
  .pdf-ref-overlay {
    padding: 0;
  }
  
  .pdf-ref-container {
    width: 100vw;
    height: 100vh;
    border-radius: 0;
  }
}
</style>
