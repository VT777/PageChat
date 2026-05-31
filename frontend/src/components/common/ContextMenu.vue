<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

interface MenuItem {
  label: string
  icon: any
  action: string
  class?: string
  divider?: boolean
}

defineProps<{
  items: MenuItem[]
}>()

const emit = defineEmits<{
  select: [action: string]
}>()

const isOpen = ref(false)
const position = ref({ x: 0, y: 0 })

function open(event: MouseEvent) {
  event.preventDefault()
  position.value = { x: event.clientX, y: event.clientY }
  isOpen.value = true
}

function close() {
  isOpen.value = false
}

function handleClick(action: string) {
  emit('select', action)
  close()
}

onMounted(() => {
  document.addEventListener('click', close)
})

onUnmounted(() => {
  document.removeEventListener('click', close)
})

defineExpose({ open })
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed z-50 min-w-[160px] bg-popover rounded-lg shadow-lg border py-1"
      :style="{ left: position.x + 'px', top: position.y + 'px' }"
      @click.stop
    >
      <template v-for="(item, index) in items" :key="index">
        <div v-if="item.divider" class="h-px bg-border my-1" />
        <button
          v-else
          @click="handleClick(item.action)"
          :class="[
            'w-full px-3 py-2 text-left flex items-center gap-2 text-sm transition-colors',
            item.class || 'hover:bg-accent text-foreground'
          ]"
        >
          <component :is="item.icon" class="w-4 h-4" /
          <span>{{ item.label }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>
