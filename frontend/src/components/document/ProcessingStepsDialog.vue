<script setup lang="ts">
import { ref, watch } from 'vue'
import { X, CheckCircle2, AlertCircle, Loader2, Clock } from 'lucide-vue-next'
import type { ProcessingStep } from '@/api'

interface Props {
  visible: boolean
  documentName: string
  steps: ProcessingStep[]
  isLoading: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
  close: []
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)

watch(() => props.visible, (val) => {
  if (val) {
    dialogRef.value?.showModal()
  } else {
    dialogRef.value?.close()
  }
})

function handleClose() {
  emit('close')
}

function getStepIcon(step: ProcessingStep) {
  if (step.status === 'completed') return CheckCircle2
  if (step.status === 'failed') return AlertCircle
  if (step.status === 'running') return Loader2
  return Clock
}

function getStepColor(step: ProcessingStep) {
  if (step.status === 'completed') return 'text-emerald-500'
  if (step.status === 'failed') return 'text-red-500'
  if (step.status === 'running') return 'text-amber-500'
  return 'text-muted-foreground opacity-60'
}

function getStepBg(step: ProcessingStep) {
  if (step.status === 'completed') return 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800'
  if (step.status === 'failed') return 'bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800'
  if (step.status === 'running') return 'bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-800'
  return 'bg-muted/50 border-border opacity-70'
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}秒`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (mins < 60) return `${mins}分${secs}秒`
  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60
  return `${hours}小时${remainingMins}分`
}
</script>

<template>
  <dialog
    ref="dialogRef"
    class="rounded-xl shadow-2xl border bg-background p-0 backdrop:bg-black/50 w-full max-w-lg"
    @close="handleClose"
  >
    <div class="flex items-center justify-between p-4 border-b">
      <h2 class="text-lg font-semibold">处理详情</h2>
      <button
        @click="handleClose"
        class="p-1 rounded-md hover:bg-muted text-muted-foreground hover:text-foreground"
      >
        <X class="w-5 h-5" />
      </button>
    </div>

    <div class="p-4">
      <p class="text-sm text-muted-foreground mb-4">
        文档：{{ documentName }}
      </p>

      <div v-if="isLoading" class="flex items-center justify-center py-8">
        <Loader2 class="w-6 h-6 animate-spin text-primary" />
        <span class="ml-2 text-sm text-muted-foreground">加载中...</span>
      </div>

      <div v-else-if="steps.length === 0" class="text-center py-8 text-muted-foreground">
        暂无处理步骤信息
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="(step, index) in steps"
          :key="step.step_type"
          :class="[
            'relative rounded-lg border p-3 transition-colors',
            getStepBg(step),
          ]"
        >
          <!-- Connector line -->
          <div
            v-if="index < steps.length - 1"
            class="absolute left-[1.4rem] bottom-[-0.75rem] w-px h-3 bg-border"
          />

          <div class="flex items-start gap-3">
            <component
              :is="getStepIcon(step)"
              :class="[
                'w-5 h-5 mt-0.5 flex-shrink-0',
                getStepColor(step),
                step.status === 'running' && 'animate-spin',
              ]"
            />
            <div class="flex-1 min-w-0">
              <div class="flex items-center justify-between">
                <h3 class="text-sm font-medium">{{ step.title }}</h3>
                <span v-if="step.duration" class="text-xs text-muted-foreground">
                  {{ formatDuration(step.duration) }}
                </span>
              </div>
              <p class="text-xs text-muted-foreground mt-1">{{ step.description }}</p>
              <div
                v-if="step.details && Object.keys(step.details).length > 0"
                class="mt-2 p-2 rounded bg-background/50 text-xs font-mono text-muted-foreground overflow-x-auto"
              >
                <pre>{{ JSON.stringify(step.details, null, 2) }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="p-4 border-t flex justify-end">
      <button
        @click="handleClose"
        class="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
      >
        关闭
      </button>
    </div>
  </dialog>
</template>

<style scoped>
dialog::backdrop {
  background: rgba(0, 0, 0, 0.5);
}
dialog[open] {
  animation: dialog-in 0.2s ease-out;
}
@keyframes dialog-in {
  from {
    opacity: 0;
    transform: translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
