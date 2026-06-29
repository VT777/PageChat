<script setup lang="ts">
import { computed } from 'vue'
import type { EvidenceItem, Message } from '@/stores/chat'
import type { CitationDocumentLike } from '@/utils/citations'
import { assignInlineSourceNumbers, bindInlineCitations } from '@/utils/citations'
import { renderAssistantMarkdown } from '@/utils/answerMarkdown'

const props = defineProps<{
  message: Message
  documents: CitationDocumentLike[]
}>()

const emit = defineEmits<{
  'citation-click': [index: number]
  'web-source-click': [index: number]
}>()

const displayContent = computed(() => props.message.displayContent ?? props.message.content)

const webSources = computed<EvidenceItem[]>(() =>
  (props.message.evidenceItems || []).filter((item) => item.type === 'web' && item.url),
)

const renderedHtml = computed(() => {
  const content = displayContent.value
  const citationBindings = bindInlineCitations(
    content,
    props.message.evidenceItems || [],
    props.documents,
  )
  const sourceNumbers = assignInlineSourceNumbers(
    content,
    webSources.value.map((source) => source.url || ''),
  )
  return renderAssistantMarkdown({
    content,
    citationBindings,
    documentNumbers: sourceNumbers.documentNumbers,
    webSources: webSources.value,
    webNumbers: sourceNumbers.webNumbers,
  })
})

function handleClick(event: MouseEvent) {
  const target = event.target instanceof HTMLElement
    ? event.target.closest<HTMLButtonElement>('[data-citation-index], [data-web-source-index]')
    : null
  if (!target) return
  if (target.dataset.webSourceIndex !== undefined) {
    emit('web-source-click', Number(target.dataset.webSourceIndex))
    return
  }
  if (target.dataset.citationIndex !== undefined) {
    emit('citation-click', Number(target.dataset.citationIndex))
  }
}
</script>

<template>
  <div
    class="assistant-markdown"
    v-html="renderedHtml"
    @click="handleClick"
  />
</template>

<style scoped>
.assistant-markdown {
  color: var(--kc-text);
  font-size: 14px;
  line-height: 23px;
  overflow-wrap: anywhere;
}

.assistant-markdown :deep(*) {
  box-sizing: border-box;
}

.assistant-markdown :deep(p) {
  margin: 0 0 11px;
}

.assistant-markdown :deep(p:last-child) {
  margin-bottom: 0;
}

.assistant-markdown :deep(h1),
.assistant-markdown :deep(h2),
.assistant-markdown :deep(h3) {
  margin: 18px 0 8px;
  color: var(--kc-text);
  font-weight: 680;
  letter-spacing: 0;
}

.assistant-markdown :deep(h1) {
  font-size: 19px;
  line-height: 27px;
}

.assistant-markdown :deep(h2) {
  font-size: 17px;
  line-height: 25px;
}

.assistant-markdown :deep(h3) {
  font-size: 15px;
  line-height: 23px;
}

.assistant-markdown :deep(ul),
.assistant-markdown :deep(ol) {
  margin: 8px 0 12px;
  padding-left: 22px;
}

.assistant-markdown :deep(li) {
  margin: 4px 0;
  padding-left: 2px;
}

.assistant-markdown :deep(li > p) {
  margin: 4px 0;
}

.assistant-markdown :deep(blockquote) {
  margin: 12px 0;
  border-left: 3px solid rgba(47, 128, 237, 0.28);
  border-radius: 0 8px 8px 0;
  background: rgba(47, 128, 237, 0.06);
  padding: 8px 12px;
  color: var(--kc-text-secondary);
}

.assistant-markdown :deep(.answer-table-wrap) {
  max-width: 100%;
  overflow-x: auto;
  margin: 12px 0 14px;
  border: 1px solid var(--kc-border-soft);
  border-radius: 8px;
  background: #fff;
}

.assistant-markdown :deep(table) {
  width: 100%;
  min-width: max-content;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: auto;
  text-align: left;
}

.assistant-markdown :deep(th),
.assistant-markdown :deep(td) {
  border-bottom: 1px solid var(--kc-border-soft);
  padding: 7px 12px;
  vertical-align: top;
  white-space: nowrap;
}

.assistant-markdown :deep(th) {
  background: #f8fafc;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  font-weight: 650;
}

.assistant-markdown :deep(td) {
  color: var(--kc-text-secondary);
  font-size: 13px;
}

.assistant-markdown :deep(tr:last-child td) {
  border-bottom: 0;
}

.assistant-markdown :deep(code) {
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 6px;
  background: #f5f7fb;
  padding: 1px 5px;
  color: var(--kc-text);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 12px;
}

.assistant-markdown :deep(.answer-code-block) {
  margin: 12px 0;
  border: 1px solid var(--kc-border-soft);
  border-radius: 10px;
  overflow: hidden;
  background: #f8fafc;
}

.assistant-markdown :deep(.answer-code-header) {
  display: flex;
  min-height: 30px;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--kc-border-soft);
  background: #f1f5f9;
  padding: 0 11px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.assistant-markdown :deep(pre) {
  overflow-x: auto;
  margin: 12px 0;
  border: 1px solid var(--kc-border-soft);
  border-radius: 10px;
  background: #f8fafc;
  padding: 12px;
}

.assistant-markdown :deep(.answer-code-block pre) {
  margin: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.assistant-markdown :deep(pre code) {
  border: 0;
  background: transparent;
  padding: 0;
  white-space: pre;
}

.assistant-markdown :deep(a) {
  color: #145eb8;
  text-decoration: underline;
  text-decoration-color: rgba(20, 94, 184, 0.24);
  text-underline-offset: 3px;
}

.assistant-markdown :deep(a:hover) {
  text-decoration-color: rgba(20, 94, 184, 0.5);
}

.assistant-markdown :deep(img) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 10px 0;
  border-radius: 10px;
  border: 1px solid var(--kc-border-soft);
}

.assistant-markdown :deep(hr) {
  height: 1px;
  border: 0;
  background: var(--kc-border-soft);
  margin: 16px 0;
}

.assistant-markdown :deep(.inline-citation) {
  display: inline-flex;
  width: 20px;
  height: 20px;
  align-items: center;
  justify-content: center;
  vertical-align: baseline;
  border: 1px solid rgba(47, 128, 237, 0.2);
  border-radius: 7px;
  background: #eef6ff;
  color: #145eb8;
  font-size: 11px;
  font-weight: 620;
  line-height: 1;
  text-decoration: none;
  cursor: pointer;
}

.assistant-markdown :deep(.inline-citation:hover) {
  border-color: rgba(47, 128, 237, 0.36);
  background: #deefff;
}
</style>
