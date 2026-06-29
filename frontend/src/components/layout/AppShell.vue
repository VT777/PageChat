<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Download,
  FileText,
  MessageSquare,
  MoreHorizontal,
  Plus,
  SlidersHorizontal,
  Trash2,
} from 'lucide-vue-next'
import { useChatStore } from '@/stores/chat'
import SettingsModal from '@/components/settings/SettingsModal.vue'
import { APP_NAV_ITEMS, PRODUCT_NAME } from '@/ui/pagechatContracts'
import { calculatePopoverPosition } from '@/ui/popoverPosition'
import { useI18n } from '@/i18n/messages'

const props = withDefaults(defineProps<{
  title: string
  subtitle?: string
}>(), {
  subtitle: '',
})

const router = useRouter()
const route = useRoute()
const chatStore = useChatStore()
const { t, navLabel } = useI18n()
const showSettings = ref(false)
const openChatMenuId = ref<string | null>(null)
const chatMenuPosition = ref({ top: 0, left: 0, maxHeight: 220 })
const chatMenuStyle = computed(() => ({
  top: `${chatMenuPosition.value.top}px`,
  left: `${chatMenuPosition.value.left}px`,
  maxHeight: `${chatMenuPosition.value.maxHeight}px`,
}))

const navIconMap = {
  MessageSquare,
  FileText,
}

function isActiveNav(itemRoute?: string) {
  if (!itemRoute) return false
  if (itemRoute === '/') return route.path === '/'
  return route.path.startsWith(itemRoute)
}

function handleNav(id: string, itemRoute?: string) {
  if (id === 'new-chat') {
    chatStore.openDraftChat()
    router.push({ path: '/', query: { draft: String(Date.now()) } })
    return
  }
  if (itemRoute) router.push(itemRoute)
}

async function openConversation(conversationId: string) {
  openChatMenuId.value = null
  await chatStore.loadConversation(conversationId)
  router.push('/')
}

function safeExportName(title: string) {
  const sanitized = title.replace(/[\\/:*?"<>|]+/g, '-').trim()
  return `${sanitized || 'pagechat-conversation'}.md`
}

function exportConversation(conversationId: string, title: string) {
  openChatMenuId.value = null
  const markdown = chatStore.exportConversationMarkdown(conversationId)
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = window.URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = safeExportName(title)
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.URL.revokeObjectURL(url)
}

async function deleteConversation(conversationId: string) {
  openChatMenuId.value = null
  if (!window.confirm(t('nav.deleteConfirm'))) return
  await chatStore.deleteConversation(conversationId)
  if (chatStore.currentSessionId === null && route.path === '/') {
    router.push({ path: '/', query: { draft: String(Date.now()) } })
  }
}

function toggleChatMenu(conversationId: string, event: MouseEvent) {
  if (openChatMenuId.value === conversationId) {
    openChatMenuId.value = null
    return
  }

  const trigger = event.currentTarget as HTMLElement | null
  const rect = trigger?.getBoundingClientRect()
  if (rect) {
    chatMenuPosition.value = calculatePopoverPosition({
      anchorRect: { top: rect.top, right: rect.right, bottom: rect.bottom },
      popoverSize: { width: 148, height: 78 },
      viewportSize: { width: window.innerWidth, height: window.innerHeight },
      gutter: 6,
    })
  }
  openChatMenuId.value = conversationId
}

function closeChatMenu() {
  openChatMenuId.value = null
}

function handleMenuKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeChatMenu()
}

watch(() => route.fullPath, closeChatMenu)

onMounted(() => {
  chatStore.loadConversationsFromStorage({ restoreLastActive: false, restoreDraft: false })
  document.addEventListener('click', closeChatMenu)
  window.addEventListener('scroll', closeChatMenu, true)
  window.addEventListener('keydown', handleMenuKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeChatMenu)
  window.removeEventListener('scroll', closeChatMenu, true)
  window.removeEventListener('keydown', handleMenuKeydown)
})
</script>

<template>
  <div class="pc-shell">
    <aside class="pc-sidebar" aria-label="PageChat navigation">
      <div class="pc-brand">
        <div class="pc-brand-mark">P</div>
        <span>{{ PRODUCT_NAME }}</span>
      </div>

      <nav class="pc-nav">
        <button
          v-for="item in APP_NAV_ITEMS"
          :key="item.id"
          :class="['pc-nav-item', { active: isActiveNav(item.route) }]"
          type="button"
          @click="handleNav(item.id, item.route)"
        >
          <span class="pc-icon-cell">
            <component :is="navIconMap[item.icon as keyof typeof navIconMap]" class="pc-icon" />
          </span>
          <span>{{ navLabel(item.id) }}</span>
          <Plus v-if="item.id === 'new-chat'" class="pc-nav-plus" />
        </button>
      </nav>

      <div class="pc-sidebar-section">
        <div class="pc-sidebar-label">{{ t('nav.chats') }}</div>
        <div class="pc-chat-list">
          <div
            v-for="conversation in chatStore.conversations"
            :key="conversation.id"
            :class="['pc-chat-item', { active: chatStore.currentSessionId === conversation.id, 'menu-open': openChatMenuId === conversation.id }]"
            @click="openConversation(conversation.id)"
          >
            <MessageSquare class="pc-chat-icon" />
            <span>{{ conversation.title }}</span>
            <button
              class="pc-chat-more-button"
              type="button"
              title="More"
              aria-label="More chat actions"
              @click.stop="toggleChatMenu(conversation.id, $event)"
            >
              <MoreHorizontal class="pc-chat-more" />
            </button>
          </div>
          <div v-if="chatStore.conversations.length === 0" class="pc-empty-chats">
            {{ t('nav.noChats') }}
          </div>
        </div>
      </div>

      <div class="pc-sidebar-spacer" />

      <button
        :class="['pc-settings-entry', { active: showSettings }]"
        type="button"
        @click="showSettings = true"
        :title="t('nav.settings')"
      >
        <SlidersHorizontal class="pc-icon" />
        <span>{{ t('nav.settings') }}</span>
      </button>
    </aside>

    <main class="pc-main">
      <header class="pc-topbar">
        <div class="pc-topbar-title">
          <h1>{{ props.title }}</h1>
          <p v-if="props.subtitle">{{ props.subtitle }}</p>
        </div>
      </header>

      <section class="pc-workspace">
        <slot />
      </section>
    </main>

    <Teleport to="body">
      <div
        v-if="openChatMenuId"
        class="pc-chat-menu pc-chat-menu-layer"
        :style="chatMenuStyle"
        @click.stop
      >
        <button
          type="button"
          @click="exportConversation(openChatMenuId, chatStore.conversations.find((item) => item.id === openChatMenuId)?.title || 'PageChat conversation')"
        >
          <Download />
          <span>{{ t('nav.exportConversation') }}</span>
        </button>
        <button class="danger" type="button" @click="deleteConversation(openChatMenuId)">
          <Trash2 />
          <span>{{ t('nav.deleteConversation') }}</span>
        </button>
      </div>
    </Teleport>

    <SettingsModal v-model:open="showSettings" />
  </div>
</template>

<style scoped>
.pc-shell {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  width: 100vw;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  background: var(--kc-bg);
  color: var(--kc-text);
}

.pc-sidebar {
  display: flex;
  min-height: 0;
  flex-direction: column;
  border-right: 1px solid var(--kc-border);
  background: rgba(255, 255, 255, 0.82);
  padding: 14px;
  backdrop-filter: blur(22px);
}

.pc-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  padding: 0 8px;
  font-size: 15px;
  font-weight: 650;
}

.pc-brand-mark {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid rgba(47, 128, 237, 0.24);
  border-radius: 8px;
  background: linear-gradient(180deg, #ffffff, #eaf3ff);
  color: var(--kc-accent);
  font-size: 13px;
  font-weight: 700;
}

.pc-nav {
  display: grid;
  gap: 4px;
  margin-top: 14px;
}

.pc-nav-item,
.pc-settings-entry,
.pc-chat-item {
  display: flex;
  align-items: center;
  width: 100%;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  color: var(--kc-text-secondary);
  text-align: left;
  transition: background 150ms ease, color 150ms ease;
}

.pc-nav-item {
  gap: 8px;
  height: 34px;
  padding: 0 8px;
  font-size: 13px;
  font-weight: 560;
}

.pc-nav-item:hover,
.pc-settings-entry:hover,
.pc-chat-item:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.pc-nav-item.active,
.pc-settings-entry.active,
.pc-chat-item.active {
  background: #eaf3ff;
  color: #145eb8;
}

.pc-icon-cell {
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
}

.pc-icon,
.pc-chat-icon {
  width: 16px;
  height: 16px;
  stroke-width: 1.8;
}

.pc-nav-plus {
  margin-left: auto;
  width: 14px;
  height: 14px;
  opacity: 0.58;
}

.pc-sidebar-section {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  margin-top: 18px;
}

.pc-sidebar-label {
  padding: 0 8px 8px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
  font-weight: 650;
  text-transform: uppercase;
}

.pc-chat-list {
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.pc-chat-item {
  position: relative;
  gap: 8px;
  height: 32px;
  margin-bottom: 2px;
  padding: 0 8px;
  font-size: 12px;
  cursor: pointer;
}

.pc-chat-item > span {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pc-chat-more-button {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  border: 0;
  border-radius: var(--kc-radius-sm);
  background: transparent;
  color: var(--kc-text-tertiary);
}

.pc-chat-more-button:hover,
.pc-chat-item.menu-open .pc-chat-more-button {
  background: rgba(15, 23, 42, 0.06);
  color: var(--kc-text);
}

.pc-chat-more {
  width: 14px;
  height: 14px;
  opacity: 0;
}

.pc-chat-item:hover .pc-chat-more,
.pc-chat-item.menu-open .pc-chat-more {
  opacity: 1;
}

.pc-chat-menu {
  position: fixed;
  z-index: 30;
  display: grid;
  width: 136px;
  gap: 2px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-lg);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: var(--kc-shadow-popover);
  padding: 6px;
  backdrop-filter: blur(18px);
}

.pc-chat-menu button {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 30px;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  padding: 0 8px;
  color: var(--kc-text-secondary);
  font-size: 12px;
  text-align: left;
}

.pc-chat-menu button:hover {
  background: var(--kc-surface-muted);
  color: var(--kc-text);
}

.pc-chat-menu button.danger {
  color: var(--kc-danger);
}

.pc-chat-menu svg {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  stroke-width: 1.85;
}

.pc-empty-chats {
  padding: 10px 8px;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.pc-sidebar-spacer {
  flex: 0 0 10px;
}

.pc-settings-entry {
  gap: 10px;
  height: 34px;
  padding: 0 10px;
  font-size: 13px;
  font-weight: 560;
}

.pc-main {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: 52px minmax(0, 1fr);
}

.pc-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--kc-border);
  background: rgba(255, 255, 255, 0.72);
  padding: 0 22px;
  backdrop-filter: blur(20px);
}

.pc-topbar-title {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 10px;
}

.pc-topbar h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
  line-height: 24px;
}

.pc-topbar p {
  margin: 0;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.pc-workspace {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

@media (max-width: 900px) {
  .pc-shell {
    grid-template-columns: 72px minmax(0, 1fr);
  }

  .pc-brand span,
  .pc-nav-item span,
  .pc-settings-entry span,
  .pc-sidebar-label,
  .pc-chat-list {
    display: none;
  }
}
</style>
