<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AlertCircle, FileText, Loader2 } from 'lucide-vue-next'
import TextViewer from './TextViewer.vue'
import MarkdownViewer from './MarkdownViewer.vue'
import TableViewer from './TableViewer.vue'
import DocxViewer from './DocxViewer.vue'
import PptxViewer from './PptxViewer.vue'
import { documentApi } from '@/api'
import type { DocumentContent, SourceAnchor } from '@/types/preview'
import { formatPreviewKind, isPreviewSupported, unsupportedPreviewMessage } from '@/utils/documentWorkbench'

const props = defineProps<{
  docId: string
  docName: string
  fileType: string
  initialAnchor?: SourceAnchor | null
  rawOnly?: boolean
}>()

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
  error: [message: string]
}>()

const content = ref<DocumentContent | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const hasContent = computed(() => content.value !== null)
const formatType = computed(() => formatPreviewKind(props.fileType))
const isSupported = computed(() => isPreviewSupported(props.fileType))

async function loadContent() {
  if (!isSupported.value) {
    error.value = unsupportedPreviewMessage(props.fileType)
    return
  }

  loading.value = true
  error.value = null

  try {
    const response = await documentApi.getContent(props.docId)
    content.value = response.data as DocumentContent
  } catch (err: any) {
    console.error('Failed to load document content:', err)
    error.value = err.response?.data?.detail || 'Failed to load document content'
    emit('error', error.value || 'Unknown preview error')
  } finally {
    loading.value = false
  }
}

function handleAnchorClick(anchor: SourceAnchor) {
  emit('anchorClick', anchor)
}

watch(() => props.docId, () => {
  content.value = null
  loadContent()
}, { immediate: true })

defineExpose({
  reload: loadContent,
})
</script>

<template>
  <div class="universal-preview">
    <div v-if="loading" class="state-container">
      <Loader2 class="w-8 h-8 animate-spin text-primary" />
      <span class="mt-4 text-muted-foreground">Loading document preview...</span>
    </div>

    <div v-else-if="error" class="state-container">
      <AlertCircle class="w-12 h-12 text-destructive" />
      <span class="mt-4 text-muted-foreground">{{ error }}</span>
    </div>

    <div v-else-if="!isSupported" class="state-container">
      <FileText class="w-12 h-12 text-muted-foreground" />
      <span class="mt-4 text-muted-foreground">
        {{ unsupportedPreviewMessage(fileType) }}
      </span>
    </div>

    <template v-else-if="hasContent && content">
      <TextViewer
        v-if="formatType === 'text'"
        :content="content"
        :toc="content.toc"
        :initial-anchor="initialAnchor"
        :show-toc="!rawOnly"
        @anchor-click="handleAnchorClick"
      />

      <MarkdownViewer
        v-else-if="formatType === 'markdown'"
        :content="content"
        :toc="content.toc"
        :initial-anchor="initialAnchor"
        :show-toc="!rawOnly"
        @anchor-click="handleAnchorClick"
      />

      <TableViewer
        v-else-if="formatType === 'table'"
        :content="content"
        :initial-anchor="initialAnchor"
        @anchor-click="handleAnchorClick"
      />

      <DocxViewer
        v-else-if="formatType === 'docx'"
        :content="content"
        :toc="content.toc"
        :initial-anchor="initialAnchor"
        :show-toc="!rawOnly"
        @anchor-click="handleAnchorClick"
      />

      <PptxViewer
        v-else-if="formatType === 'pptx'"
        :content="content"
        :initial-anchor="initialAnchor"
        @anchor-click="handleAnchorClick"
      />
    </template>
  </div>
</template>

<style scoped>
.universal-preview {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.state-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  text-align: center;
}
</style>
