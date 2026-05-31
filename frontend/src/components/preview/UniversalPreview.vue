<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Loader2, AlertCircle, FileText } from 'lucide-vue-next'
import TextViewer from './TextViewer.vue'
import MarkdownViewer from './MarkdownViewer.vue'
import TableViewer from './TableViewer.vue'
import DocxViewer from './DocxViewer.vue'
import PptxViewer from './PptxViewer.vue'
import { documentApi } from '@/api'
import type { DocumentContent, SourceAnchor } from '@/types/preview'

const props = defineProps<{
  docId: string
  docName: string
  fileType: string
  initialAnchor?: SourceAnchor | null
}>()

const emit = defineEmits<{
  anchorClick: [anchor: SourceAnchor]
  error: [message: string]
}>()

// 状态
const content = ref<DocumentContent | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// 获取到的文档内容
const hasContent = computed(() => content.value !== null)

// 获取格式类型
const formatType = computed(() => {
  const ext = props.fileType.toLowerCase()
  if (ext === '.txt') return 'text'
  if (ext === '.md' || ext === '.markdown') return 'markdown'
  if (ext === '.csv' || ext === '.tsv') return 'table'
  if (ext === '.xlsx' || ext === '.xls') return 'table'
  if (ext === '.docx' || ext === '.doc') return 'docx'
  if (ext === '.pptx' || ext === '.ppt') return 'pptx'
  return 'unknown'
})

// 是否支持该格式
const isSupported = computed(() => formatType.value !== 'unknown')

// 加载内容
async function loadContent() {
  if (!isSupported.value) {
    error.value = `不支持的文件格式: ${props.fileType}`
    return
  }

  loading.value = true
  error.value = null

  try {
    const response = await documentApi.getContent(props.docId)
    content.value = response.data as DocumentContent
    } catch (err: any) {
    console.error('Failed to load document content:', err)
    error.value = err.response?.data?.detail || '加载文档内容失败'
    emit('error', error.value || '未知错误')
  } finally {
    loading.value = false
  }
}

// 处理锚点点击
function handleAnchorClick(anchor: SourceAnchor) {
  emit('anchorClick', anchor)
}

// 监听 docId 变化，重新加载
watch(() => props.docId, () => {
  loadContent()
}, { immediate: true })

defineExpose({
  reload: loadContent
})
</script>

<template>
  <div class="universal-preview">
    <!-- 加载中 -->
    <div v-if="loading" class="state-container">
      <Loader2 class="w-8 h-8 animate-spin text-primary" />
      <span class="mt-4 text-muted-foreground">加载文档内容...</span>
    </div>

    <!-- 错误 -->
    <div v-else-if="error" class="state-container">
      <AlertCircle class="w-12 h-12 text-destructive" />
      <span class="mt-4 text-muted-foreground">{{ error }}</span>
    </div>

    <!-- 不支持 -->
    <div v-else-if="!isSupported" class="state-container">
      <FileText class="w-12 h-12 text-muted-foreground" />
      <span class="mt-4 text-muted-foreground">
        不支持预览此格式: {{ fileType }}
      </span>
    </div>

    <!-- 内容 -->
    <template v-else-if="hasContent && content">
      <!-- TXT -->
      <TextViewer
        v-if="formatType === 'text'"
        :content="content"
        :toc="content.toc"
        :initial-anchor="initialAnchor"
        @anchor-click="handleAnchorClick"
      />

      <!-- Markdown -->
      <MarkdownViewer
        v-else-if="formatType === 'markdown'"
        :content="content"
        :toc="content.toc"
        :initial-anchor="initialAnchor"
        @anchor-click="handleAnchorClick"
      />

      <!-- CSV / TSV / XLSX -->
      <TableViewer
        v-else-if="formatType === 'table'"
        :content="content"
        :initial-anchor="initialAnchor"
        @anchor-click="handleAnchorClick"
      />

      <!-- DOCX -->
      <DocxViewer
        v-else-if="formatType === 'docx'"
        :content="content"
        :toc="content.toc"
        :initial-anchor="initialAnchor"
        @anchor-click="handleAnchorClick"
      />

      <!-- PPTX -->
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
}
</style>
