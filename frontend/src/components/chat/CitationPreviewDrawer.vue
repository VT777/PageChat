<script setup lang="ts">
import { computed } from 'vue'
import { ExternalLink, FileText, Globe, X } from 'lucide-vue-next'
import PdfReferenceViewer from '@/components/PdfReferenceViewer.vue'
import UniversalPreview from '@/components/preview/UniversalPreview.vue'
import type { SourceAnchor } from '@/types/preview'

const props = defineProps<{
  open: boolean
  sourceType?: 'document' | 'web'
  docId?: string
  documentName: string
  displayLabel: string
  fileType: string
  sourceAnchor?: SourceAnchor | null
  url?: string
  domain?: string
  snippet?: string
  contentPreview?: string
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
const isWeb = computed(() => props.sourceType === 'web')
</script>

<template>
  <transition name="drawer-slide">
    <aside v-if="open" class="citation-drawer" data-testid="citation-preview-drawer">
      <header class="drawer-header">
        <div class="drawer-title">
          <Globe v-if="isWeb" />
          <FileText v-else />
          <div>
            <strong>{{ displayLabel || documentName }}</strong>
            <span>{{ isWeb ? (domain || url) : documentName }}</span>
          </div>
        </div>
        <button type="button" aria-label="关闭预览" @click="emit('close')">
          <X />
        </button>
      </header>

      <main class="drawer-body">
        <section v-if="isWeb" class="web-source-preview">
          <div class="web-source-icon">
            <Globe />
          </div>
          <div class="web-source-content">
            <p class="web-source-domain">{{ domain || url }}</p>
            <h3>{{ displayLabel || 'Web source' }}</h3>
            <p v-if="snippet" class="web-source-snippet">{{ snippet }}</p>
            <p v-if="contentPreview" class="web-source-preview-text">{{ contentPreview }}</p>
            <a v-if="url" :href="url" target="_blank" rel="noreferrer">
              <ExternalLink />
              Open source
            </a>
          </div>
        </section>
        <div v-else-if="!canPreview" class="drawer-state">
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
  display: grid;
  width: 100%;
  min-width: 0;
  height: 100%;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  border-left: 1px solid rgba(209, 213, 219, 0.72);
  background: rgba(255, 255, 255, 0.96);
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

.web-source-preview {
  display: flex;
  gap: 14px;
  padding: 20px;
}

.web-source-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid rgba(47, 128, 237, 0.18);
  border-radius: 12px;
  background: #eaf3ff;
  color: var(--kc-accent);
}

.web-source-icon svg {
  width: 18px;
  height: 18px;
}

.web-source-content {
  display: grid;
  min-width: 0;
  gap: 9px;
}

.web-source-domain {
  margin: 0;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  font-weight: 600;
}

.web-source-content h3 {
  margin: 0;
  color: var(--kc-text);
  font-size: 17px;
  font-weight: 680;
  line-height: 24px;
}

.web-source-snippet,
.web-source-preview-text {
  margin: 0;
  color: var(--kc-text-secondary);
  font-size: 13px;
  line-height: 21px;
}

.web-source-preview-text {
  border-top: 1px solid var(--kc-border-soft);
  padding-top: 10px;
}

.web-source-content a {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 7px;
  border: 1px solid rgba(47, 128, 237, 0.18);
  border-radius: 999px;
  background: #eef6ff;
  padding: 7px 11px;
  color: #145eb8;
  font-size: 12px;
  font-weight: 650;
  text-decoration: none;
}

.web-source-content a:hover {
  background: #deefff;
}

.web-source-content a svg {
  width: 13px;
  height: 13px;
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
</style>
