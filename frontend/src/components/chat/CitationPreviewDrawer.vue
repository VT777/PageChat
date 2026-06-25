<script setup lang="ts">
import { computed } from 'vue'
import { FileText, X } from 'lucide-vue-next'
import PdfReferenceViewer from '@/components/PdfReferenceViewer.vue'
import UniversalPreview from '@/components/preview/UniversalPreview.vue'
import type { SourceAnchor } from '@/types/preview'

const props = defineProps<{
  open: boolean
  docId?: string
  documentName: string
  displayLabel: string
  fileType: string
  sourceAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  close: []
}>()

const normalizedFileType = computed(() => {
  const value = (props.fileType || props.sourceAnchor?.format || '').toLowerCase()
  return value.startsWith('.') ? value : value ? `.${value}` : '.pdf'
})

const isPdf = computed(() => normalizedFileType.value === '.pdf')
const initialPage = computed(() => props.sourceAnchor?.start_page || 1)
const canPreview = computed(() => Boolean(props.docId))
</script>

<template>
  <transition name="drawer-slide">
    <aside v-if="open" class="citation-drawer" data-testid="citation-preview-drawer">
      <header class="drawer-header">
        <div class="drawer-title">
          <FileText />
          <div>
            <strong>{{ displayLabel || documentName }}</strong>
            <span>{{ documentName }}</span>
          </div>
        </div>
        <button type="button" aria-label="关闭预览" @click="emit('close')">
          <X />
        </button>
      </header>

      <main class="drawer-body">
        <div v-if="!canPreview" class="drawer-state">
          未找到对应文档，无法打开来源预览。
        </div>
        <PdfReferenceViewer
          v-else-if="isPdf && docId"
          :file-url="`/api/documents/${docId}/file`"
          :file-name="documentName"
          :initial-page="initialPage"
          :visible="open"
          embedded
          @close="emit('close')"
        />
        <UniversalPreview
          v-else-if="docId"
          :doc-id="docId"
          :doc-name="documentName"
          :file-type="normalizedFileType"
          :initial-anchor="sourceAnchor"
          raw-only
        />
      </main>
    </aside>
  </transition>
</template>

<style scoped>
.citation-drawer {
  position: fixed;
  top: 0;
  right: 0;
  z-index: 60;
  display: grid;
  width: min(620px, 42vw);
  min-width: 420px;
  height: 100vh;
  grid-template-rows: auto minmax(0, 1fr);
  border-left: 1px solid rgba(209, 213, 219, 0.72);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: -24px 0 48px rgba(15, 23, 42, 0.12);
  backdrop-filter: blur(20px);
}

.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid var(--kc-border-soft);
  padding: 14px 16px;
}

.drawer-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.drawer-title > svg {
  width: 17px;
  height: 17px;
  flex: 0 0 auto;
  color: var(--kc-accent);
}

.drawer-title div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.drawer-title strong,
.drawer-title span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-title strong {
  color: var(--kc-text);
  font-size: 13px;
  font-weight: 650;
}

.drawer-title span {
  color: var(--kc-text-tertiary);
  font-size: 11.5px;
}

.drawer-header button {
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--kc-text-tertiary);
}

.drawer-header button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.drawer-header button svg {
  width: 16px;
  height: 16px;
}

.drawer-body {
  min-height: 0;
  overflow: hidden;
  background: #f8fafc;
}

.drawer-state {
  display: grid;
  height: 100%;
  place-items: center;
  padding: 24px;
  color: var(--kc-text-tertiary);
  font-size: 13px;
  text-align: center;
}

.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition: transform 180ms ease, opacity 180ms ease;
}

.drawer-slide-enter-from,
.drawer-slide-leave-to {
  opacity: 0;
  transform: translateX(24px);
}

@media (max-width: 960px) {
  .citation-drawer {
    width: min(100vw, 560px);
    min-width: 0;
  }
}
</style>
