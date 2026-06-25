<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, Sparkles } from 'lucide-vue-next'

const props = defineProps<{
  content: string
  active?: boolean
}>()

const expanded = ref(false)

watch(() => props.active, (active) => {
  expanded.value = Boolean(active)
}, { immediate: true })

const label = computed(() => props.active ? 'Thinking' : 'Thought for a moment')
</script>

<template>
  <section v-if="content" class="thinking-block">
    <button class="thinking-toggle" type="button" @click="expanded = !expanded">
      <Sparkles />
      <span>{{ label }}</span>
      <ChevronDown v-if="expanded" />
      <ChevronRight v-else />
    </button>
    <div v-if="expanded" class="thinking-content">
      {{ content }}
    </div>
  </section>
</template>

<style scoped>
.thinking-block {
  display: grid;
  gap: 6px;
  margin-bottom: 8px;
}

.thinking-toggle {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 6px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  padding: 2px 4px 2px 0;
  color: var(--kc-text-tertiary);
  font-size: 12px;
  font-weight: 560;
}

.thinking-toggle:hover {
  color: var(--kc-text-secondary);
}

.thinking-toggle svg {
  width: 14px;
  height: 14px;
  stroke-width: 1.9;
}

.thinking-content {
  max-width: min(760px, 100%);
  border-left: 1px solid var(--kc-border-soft);
  padding: 4px 0 4px 13px;
  color: var(--kc-text-secondary);
  font-size: 12.5px;
  line-height: 20px;
  white-space: pre-wrap;
}
</style>
