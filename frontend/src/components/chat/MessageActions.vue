<script setup lang="ts">
import { ref } from 'vue'
import { Copy, RefreshCw, RotateCcw, Check } from 'lucide-vue-next'

interface Props {
  messageId: string
  role: 'user' | 'assistant'
  content: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'copy', content: string): void
  (e: 'retry', messageId: string): void
  (e: 'rollback', messageId: string): void
}>()

const showCopied = ref(false)

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.content)
    showCopied.value = true
    setTimeout(() => {
      showCopied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
  }
}

function handleRetry() {
  emit('retry', props.messageId)
}

function handleRollback() {
  if (confirm('确定要回滚到这条消息吗？这将删除之后的所有消息。')) {
    emit('rollback', props.messageId)
  }
}
</script>

<template>
  <div class="message-actions">
    <!-- 复制成功提示 -->
    <transition name="fade">
      <div v-if="showCopied" class="copied-tooltip">
        <Check class="w-3 h-3" />
        <span>已复制</span>
      </div>
    </transition>
    
    <!-- 操作按钮 -->
    <div class="action-buttons">
      <!-- 复制按钮 - 所有消息都有 -->
      <button 
        @click="copyContent" 
        class="action-btn"
        title="复制内容"
      >
        <Copy class="w-4 h-4" />
      </button>
      
      <!-- 重新生成 - 仅 AI 消息 -->
      <button 
        v-if="role === 'assistant'"
        @click="handleRetry" 
        class="action-btn action-btn-retry"
        title="重新生成"
      >
        <RefreshCw class="w-4 h-4" />
      </button>
      
      <!-- 回滚 - 仅用户消息 -->
      <button 
        v-if="role === 'user'"
        @click="handleRollback" 
        class="action-btn action-btn-rollback"
        title="回滚到此处"
      >
        <RotateCcw class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.message-actions {
  display: flex;
  align-items: center;
  position: relative;
}

.action-buttons {
  display: flex;
  gap: 4px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.action-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: rgba(255, 255, 255, 0.9);
  color: var(--muted-foreground);
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}

.action-btn:hover {
  background: white;
  border-color: var(--border);
  color: var(--foreground);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.action-btn:active {
  transform: translateY(0);
}

/* 重新生成按钮 - 蓝色主题 */
.action-btn-retry:hover {
  background: #3b82f6;
  border-color: #3b82f6;
  color: white;
}

/* 回滚按钮 - 橙色主题 */
.action-btn-rollback:hover {
  background: #f97316;
  border-color: #f97316;
  color: white;
}

.copied-tooltip {
  position: absolute;
  top: -35px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--primary);
  color: var(--primary-foreground);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  animation: slideDown 0.3s ease;
  z-index: 10;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(-10px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
