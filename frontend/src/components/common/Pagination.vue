<script setup lang="ts">
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { computed } from 'vue'
import { useI18n } from '@/i18n/messages'

const props = defineProps<{
  currentPage: number
  pageSize: number
  total: number
}>()

const emit = defineEmits<{
  change: [page: number]
}>()

const { localizeText: lt } = useI18n()
const totalPages = computed(() => Math.ceil(props.total / props.pageSize))

const pages = computed(() => {
  const pages: (number | string)[] = []
  const current = props.currentPage
  const total = totalPages.value

  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
  } else {
    if (current <= 3) {
      pages.push(1, 2, 3, 4, '...', total)
    } else if (current >= total - 2) {
      pages.push(1, '...', total - 3, total - 2, total - 1, total)
    } else {
      pages.push(1, '...', current - 1, current, current + 1, '...', total)
    }
  }
  return pages
})

function goToPage(page: number) {
  if (page >= 1 && page <= totalPages.value && page !== props.currentPage) {
    emit('change', page)
  }
}

function jumpToPage(input: string) {
  const page = parseInt(input)
  if (!isNaN(page)) {
    goToPage(page)
  }
}
</script>

<template>
  <div class="flex items-center justify-between gap-4 py-4">
    <!-- Info -->
    <span class="text-sm text-muted-foreground">
      {{ lt('共') }} {{ total }} {{ lt('项') }}，{{ totalPages }} {{ lt('页') }}
    </span>

    <!-- Pagination Controls -->
    <div class="flex items-center gap-2">
      <!-- Previous -->
      <button
        @click="goToPage(currentPage - 1)"
        :disabled="currentPage === 1"
        class="p-2 rounded-lg border hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <ChevronLeft class="w-4 h-4" />
      </button>

      <!-- Page Numbers -->
      <div class="flex items-center gap-1">
        <template v-for="(page, index) in pages" :key="index">
          <button
            v-if="page !== '...'"
            @click="goToPage(page as number)"
            :class="[
              'min-w-[36px] h-9 px-3 rounded-lg text-sm font-medium transition-colors',
              page === currentPage
                ? 'bg-primary text-primary-foreground'
                : 'border hover:bg-muted'
            ]"
          >
            {{ page }}
          </button>
          <span v-else class="px-2 text-muted-foreground">...</span>
        </template>
      </div>

      <!-- Next -->
      <button
        @click="goToPage(currentPage + 1)"
        :disabled="currentPage === totalPages"
        class="p-2 rounded-lg border hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <ChevronRight class="w-4 h-4" />
      </button>

      <!-- Jump To -->
      <div class="flex items-center gap-2 ml-4 text-sm">
        <span class="text-muted-foreground">{{ lt('跳至') }}</span>
        <input
          type="number"
          min="1"
          :max="totalPages"
          class="w-16 px-2 py-1.5 rounded-lg border text-center"
          @keyup.enter="jumpToPage(($event.target as HTMLInputElement).value)"
        />
        <span class="text-muted-foreground">{{ lt('页') }}</span>
      </div>
    </div>
  </div>
</template>
