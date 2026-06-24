<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import SettingsModal from '@/components/settings/SettingsModal.vue'

const router = useRouter()
const open = ref(true)

function updateOpen(value: boolean) {
  open.value = value
  if (!value) {
    router.push('/')
  }
}
</script>

<template>
  <AppShell title="Chat">
    <div class="settings-route-backdrop" />
    <SettingsModal :open="open" @update:open="updateOpen" />
  </AppShell>
</template>

<style scoped>
.settings-route-backdrop {
  width: 100%;
  height: 100%;
}
</style>
