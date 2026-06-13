<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import type { DocumentContent, SourceAnchor } from '@/types/preview'
import { normalizePreviewBlocks } from '@/utils/documentWorkbench'

type PreviewSlide = {
  id: string
  slideNumber: number
  title: string
  text: string
}

const props = defineProps<{
  content: DocumentContent
  initialAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
}>()

const containerRef = ref<HTMLDivElement>()
const currentSlideIndex = ref(0)
const viewMode = ref<'grid' | 'single'>('single')

const slides = computed<PreviewSlide[]>(() => {
  return normalizePreviewBlocks(props.content)
    .filter((block) => block.type === 'slide')
    .map((block) => ({
      id: String(block.id),
      slideNumber: Number(block.slideNumber),
      title: String(block.title || `Slide ${block.slideNumber}`),
      text: String(block.text || ''),
    }))
})

const currentSlide = computed(() => slides.value[currentSlideIndex.value])
const totalSlides = computed(() => slides.value.length)

function nextSlide() {
  if (currentSlideIndex.value < totalSlides.value - 1) {
    currentSlideIndex.value++
  }
}

function prevSlide() {
  if (currentSlideIndex.value > 0) {
    currentSlideIndex.value--
  }
}

function goToSlide(index: number) {
  const clamped = Math.min(Math.max(index, 0), Math.max(totalSlides.value - 1, 0))
  currentSlideIndex.value = clamped
  viewMode.value = 'single'
}

function handleSlideClick(slideNumber: number) {
  const anchor: SourceAnchor = {
    format: 'pptx',
    unit_type: 'slide',
    slide: slideNumber,
    start_slide: slideNumber,
    end_slide: slideNumber,
  }
  emit('anchorClick', anchor)
  goToSlide(slideNumber - 1)
}

function handleKeydown(e: KeyboardEvent) {
  if (viewMode.value !== 'single') return

  if (e.key === 'ArrowLeft') {
    prevSlide()
  } else if (e.key === 'ArrowRight') {
    nextSlide()
  }
}

watch(() => props.initialAnchor, (anchor) => {
  const slideNumber = anchor?.slide || anchor?.start_slide
  if (slideNumber) {
    goToSlide(slideNumber - 1)
  }
}, { immediate: true })

watch(totalSlides, (count) => {
  if (currentSlideIndex.value >= count) {
    currentSlideIndex.value = Math.max(count - 1, 0)
  }
})

defineExpose({
  goToSlide,
})
</script>

<template>
  <div
    class="pptx-viewer"
    ref="containerRef"
    tabindex="0"
    @keydown="handleKeydown"
  >
    <div class="toolbar">
      <div class="toolbar-left">
        <div class="view-toggle">
          <button
            :class="['view-btn', { active: viewMode === 'single' }]"
            @click="viewMode = 'single'"
          >
            Single
          </button>
          <button
            :class="['view-btn', { active: viewMode === 'grid' }]"
            @click="viewMode = 'grid'"
          >
            Grid
          </button>
        </div>
      </div>

      <div class="toolbar-center">
        <template v-if="viewMode === 'single'">
          <button
            class="nav-btn"
            :disabled="currentSlideIndex === 0"
            @click="prevSlide"
          >
            <ChevronLeft class="w-4 h-4" />
          </button>

          <span class="slide-counter">
            {{ totalSlides ? currentSlideIndex + 1 : 0 }} / {{ totalSlides }}
          </span>

          <button
            class="nav-btn"
            :disabled="currentSlideIndex === totalSlides - 1 || totalSlides === 0"
            @click="nextSlide"
          >
            <ChevronRight class="w-4 h-4" />
          </button>
        </template>

        <span v-else class="stats">{{ totalSlides }} slides</span>
      </div>
    </div>

    <div v-if="viewMode === 'single'" class="single-view">
      <div
        v-if="currentSlide"
        class="slide-container"
        @click="handleSlideClick(currentSlide.slideNumber)"
      >
        <div class="slide-number-badge">{{ currentSlide.slideNumber }}</div>

        <div class="slide-content">
          <div class="slide-title">{{ currentSlide.title }}</div>
          <pre class="slide-text">{{ currentSlide.text }}</pre>
        </div>
      </div>

      <div v-else class="empty-slide">
        <p>No slide content was extracted.</p>
      </div>
    </div>

    <div v-else class="grid-view">
      <div
        v-for="slide in slides"
        :key="slide.id"
        :class="['slide-thumb', { active: currentSlideIndex === slide.slideNumber - 1 }]"
        @click="handleSlideClick(slide.slideNumber)"
      >
        <div class="thumb-number">{{ slide.slideNumber }}</div>

        <div class="thumb-content">
          <div class="thumb-title">{{ slide.title }}</div>
          <div class="thumb-preview">{{ slide.text.slice(0, 100) }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pptx-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f3f4f6;
  outline: none;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e5e7eb;
}

.toolbar-left,
.toolbar-center {
  display: flex;
  align-items: center;
  gap: 12px;
}

.view-toggle {
  display: flex;
  gap: 4px;
}

.view-btn {
  padding: 4px 12px;
  font-size: 13px;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.view-btn:hover {
  background: #f3f4f6;
}

.view-btn.active {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
}

.nav-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid #e5e7eb;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-btn:hover:not(:disabled) {
  background: #f3f4f6;
}

.nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.slide-counter {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
  min-width: 60px;
  text-align: center;
}

.stats {
  font-size: 13px;
  color: #6b7280;
}

.single-view {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: auto;
}

.slide-container {
  width: 100%;
  max-width: 800px;
  aspect-ratio: 16/9;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  padding: 40px;
  position: relative;
  cursor: pointer;
  transition: transform 0.15s;
}

.slide-container:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
}

.slide-number-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.slide-content {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.slide-title {
  font-size: 24px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 2px solid #e5e7eb;
}

.slide-text {
  flex: 1;
  font-size: 16px;
  line-height: 1.6;
  color: #374151;
  white-space: pre-wrap;
  overflow-y: auto;
}

.empty-slide {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 14px;
}

.grid-view {
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  padding: 24px;
  overflow-y: auto;
}

.slide-thumb {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  cursor: pointer;
  transition: all 0.15s;
}

.slide-thumb:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}

.slide-thumb.active {
  box-shadow: 0 0 0 2px #2563eb;
}

.thumb-number {
  padding: 8px 12px;
  background: #f9fafb;
  border-bottom: 1px solid #e5e7eb;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.thumb-content {
  padding: 12px;
  aspect-ratio: 16/10;
  display: flex;
  flex-direction: column;
}

.thumb-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 8px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.thumb-preview {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
}
</style>
