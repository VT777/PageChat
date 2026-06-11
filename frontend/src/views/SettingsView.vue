<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { User, LogOut, Settings, ChevronRight, Shield, Bell, Palette, MessageSquare, SlidersHorizontal } from 'lucide-vue-next'
import { settingsApi } from '@/api'
import ModelProviderSettings from '@/components/settings/ModelProviderSettings.vue'
import ModelRouteSettings from '@/components/settings/ModelRouteSettings.vue'

const router = useRouter()
const userStore = useUserStore()

const activeSection = ref('account')

const sections = [
  { id: 'account', label: '账号设置', icon: User, description: '管理您的账号信息和登录状态' },
  { id: 'appearance', label: '外观', icon: Palette, description: '自定义界面主题和显示方式' },
  { id: 'notifications', label: '通知', icon: Bell, description: '配置通知偏好和提醒方式' },
  { id: 'chat', label: '聊天设置', icon: MessageSquare, description: '调整对话行为和响应偏好' },
  { id: 'models', label: 'Models', icon: SlidersHorizontal, description: 'Configure providers and task routes' },
  { id: 'security', label: '安全', icon: Shield, description: '管理密码和安全性选项' }
]

const currentSection = computed(() => sections.find(s => s.id === activeSection.value))

type PageIndexMode = 'smart' | 'balanced' | 'fast'

const pageIndexMode = ref<PageIndexMode>('smart')
const modeLoading = ref(false)
const modeSaving = ref(false)
const modeMessage = ref('')
const routeSettingsRef = ref<InstanceType<typeof ModelRouteSettings> | null>(null)

async function loadPageIndexSettings() {
  modeLoading.value = true
  modeMessage.value = ''
  try {
    const response = await settingsApi.getPageIndexSettings()
    const mode = response.data?.pageindex_mode
    if (mode === 'fast' || mode === 'balanced' || mode === 'smart') {
      pageIndexMode.value = mode
    } else {
      pageIndexMode.value = 'smart'
    }
  } catch (error: any) {
    if (error?.response?.status === 404) {
      modeMessage.value = '当前后端不支持该设置，请重启后端服务后重试'
    } else {
      modeMessage.value = '加载索引模式失败，请稍后重试'
    }
  } finally {
    modeLoading.value = false
  }
}

async function savePageIndexMode(mode: PageIndexMode) {
  if (modeSaving.value || pageIndexMode.value === mode) {
    return
  }

  const previous = pageIndexMode.value
  pageIndexMode.value = mode
  modeSaving.value = true
  modeMessage.value = ''
  try {
    await settingsApi.updatePageIndexSettings(mode)
    modeMessage.value = mode === 'smart'
      ? '已切换为智能模式：系统会先预分析再自动路由'
      : mode === 'fast'
        ? '已切换为精简模式：后续新索引任务会优先速度'
        : '已切换为平衡模式：后续新索引任务会优先完整度'
  } catch (error: any) {
    pageIndexMode.value = previous
    if (error?.response?.status === 404) {
      modeMessage.value = '当前后端不支持该设置，请重启后端服务后重试'
    } else {
      modeMessage.value = '保存失败，请重试'
    }
  } finally {
    modeSaving.value = false
  }
}

onMounted(() => {
  loadPageIndexSettings()
})

function handleLogout() {
  userStore.logout()
  router.push('/')
}

function handleSwitchAccount() {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-background">
    <!-- Header -->
    <header class="flex items-center justify-between px-6 py-4 border-b bg-background/95 backdrop-blur sticky top-0 z-10">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
          <span class="text-primary-foreground font-bold text-sm">K</span>
        </div>
        <h1 class="text-xl font-semibold">设置</h1>
      </div>
      <button @click="$router.back()" class="px-4 py-2 text-sm font-medium rounded-lg bg-secondary hover:bg-secondary/80 transition-colors">
        返回
      </button>
    </header>

    <!-- Main Content -->
    <div class="max-w-6xl mx-auto p-6">
      <div class="flex gap-6">
        <!-- Sidebar Menu -->
        <aside class="w-64 flex-shrink-0">
          <nav class="space-y-1">
            <button
              v-for="section in sections"
              :key="section.id"
              @click="activeSection = section.id"
              :class="[
                'w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left transition-colors',
                activeSection === section.id ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'
              ]"
            >
              <component :is="section.icon" class="w-5 h-5" />
              <span class="font-medium">{{ section.label }}</span>
            </button>
          </nav>

          <!-- User Info Card -->
          <div class="mt-6 p-4 rounded-lg border bg-card">
            <div class="flex items-center gap-3 mb-3">
              <div class="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                <User class="w-5 h-5 text-primary" />
              </div>
              <div class="flex-1 min-w-0">
                <p class="font-medium truncate">{{ userStore.username || '未登录' }}</p>
                <p class="text-xs text-muted-foreground truncate">{{ userStore.isLoggedIn ? '已登录' : '访客模式' }}</p>
              </div>
            </div>
            <div class="space-y-2">
              <button
                v-if="userStore.isLoggedIn"
                @click="handleSwitchAccount"
                class="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm rounded-lg border hover:bg-accent transition-colors"
              >
                <User class="w-4 h-4" />
                切换账号
              </button>
              <button
                v-if="userStore.isLoggedIn"
                @click="handleLogout"
                class="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors"
              >
                <LogOut class="w-4 h-4" />
                退出登录
              </button>
            </div>
          </div>
        </aside>

        <!-- Settings Content -->
        <main class="flex-1">
          <div class="bg-card rounded-lg border">
            <!-- Section Header -->
            <div class="px-6 py-4 border-b">
              <div class="flex items-center gap-3">
                <component :is="currentSection?.icon" class="w-6 h-6 text-primary" />
                <div>
                  <h2 class="text-lg font-semibold">{{ currentSection?.label }}</h2>
                  <p class="text-sm text-muted-foreground">{{ currentSection?.description }}</p>
                </div>
              </div>
            </div>

            <!-- Section Content -->
            <div class="p-6">
              <!-- Account Section -->
              <div v-if="activeSection === 'account'" class="space-y-6">
                <div class="flex items-center justify-between p-4 rounded-lg border bg-muted/50">
                  <div class="flex items-center gap-4">
                    <div class="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center">
                      <User class="w-6 h-6 text-primary" />
                    </div>
                    <div>
                      <p class="font-medium">用户名</p>
                      <p class="text-sm text-muted-foreground">{{ userStore.username || '未登录' }}</p>
                    </div>
                  </div>
                  <button v-if="userStore.isLoggedIn" class="px-4 py-2 text-sm font-medium rounded-lg border hover:bg-accent transition-colors">
                    修改
                  </button>
                </div>

                <div class="space-y-3">
                  <h3 class="font-medium">账号操作</h3>
                  <div class="space-y-2">
                    <button
                      v-if="userStore.isLoggedIn"
                      @click="handleSwitchAccount"
                      class="w-full flex items-center justify-between p-4 rounded-lg border hover:bg-accent transition-colors"
                    >
                      <div class="flex items-center gap-3">
                        <User class="w-5 h-5 text-muted-foreground" />
                        <div class="text-left">
                          <p class="font-medium">切换账号</p>
                          <p class="text-sm text-muted-foreground">退出当前账号并登录其他账号</p>
                        </div>
                      </div>
                      <ChevronRight class="w-5 h-5 text-muted-foreground" />
                    </button>
                    
                    <button
                      v-if="userStore.isLoggedIn"
                      @click="handleLogout"
                      class="w-full flex items-center justify-between p-4 rounded-lg border hover:bg-destructive/10 hover:border-destructive/50 transition-colors"
                    >
                      <div class="flex items-center gap-3">
                        <LogOut class="w-5 h-5 text-destructive" />
                        <div class="text-left">
                          <p class="font-medium text-destructive">退出登录</p>
                          <p class="text-sm text-muted-foreground">退出当前账号</p>
                        </div>
                      </div>
                      <ChevronRight class="w-5 h-5 text-muted-foreground" />
                    </button>
                  </div>
                </div>
              </div>

              <div v-else-if="activeSection === 'chat'" class="space-y-6">
                <div class="rounded-lg border p-4 bg-muted/30">
                  <h3 class="font-medium mb-2">文档索引模式</h3>
                  <p class="text-sm text-muted-foreground mb-4">
                    控制新上传/重建索引文档时的策略。该设置仅影响后续任务，不会改变已完成的索引。
                  </p>

                  <div class="space-y-3">
                    <button
                      @click="savePageIndexMode('smart')"
                      :disabled="modeLoading || modeSaving"
                      :class="[
                        'w-full text-left border rounded-lg p-4 transition-colors',
                        pageIndexMode === 'smart' ? 'border-primary bg-primary/5' : 'hover:bg-accent',
                        (modeLoading || modeSaving) ? 'opacity-70 cursor-not-allowed' : ''
                      ]"
                    >
                      <div class="flex items-center justify-between">
                        <div>
                          <p class="font-medium">智能模式（推荐）</p>
                          <p class="text-sm text-muted-foreground mt-1">先预分析文档，再在精简和平衡之间自动路由</p>
                        </div>
                        <span v-if="pageIndexMode === 'smart'" class="text-xs px-2 py-1 rounded bg-primary text-primary-foreground">当前</span>
                      </div>
                    </button>

                    <button
                      @click="savePageIndexMode('balanced')"
                      :disabled="modeLoading || modeSaving"
                      :class="[
                        'w-full text-left border rounded-lg p-4 transition-colors',
                        pageIndexMode === 'balanced' ? 'border-primary bg-primary/5' : 'hover:bg-accent',
                        (modeLoading || modeSaving) ? 'opacity-70 cursor-not-allowed' : ''
                      ]"
                    >
                      <div class="flex items-center justify-between">
                        <div>
                          <p class="font-medium">平衡模式</p>
                          <p class="text-sm text-muted-foreground mt-1">索引更完整，耗时更长，适合常规文档</p>
                        </div>
                        <span v-if="pageIndexMode === 'balanced'" class="text-xs px-2 py-1 rounded bg-primary text-primary-foreground">当前</span>
                      </div>
                    </button>

                    <button
                      @click="savePageIndexMode('fast')"
                      :disabled="modeLoading || modeSaving"
                      :class="[
                        'w-full text-left border rounded-lg p-4 transition-colors',
                        pageIndexMode === 'fast' ? 'border-primary bg-primary/5' : 'hover:bg-accent',
                        (modeLoading || modeSaving) ? 'opacity-70 cursor-not-allowed' : ''
                      ]"
                    >
                      <div class="flex items-center justify-between">
                        <div>
                          <p class="font-medium">精简模式（更快）</p>
                          <p class="text-sm text-muted-foreground mt-1">减少索引扩展处理，明显缩短耗时，检索准确率可能轻微下降</p>
                        </div>
                        <span v-if="pageIndexMode === 'fast'" class="text-xs px-2 py-1 rounded bg-primary text-primary-foreground">当前</span>
                      </div>
                    </button>
                  </div>

                  <p v-if="modeLoading" class="text-sm text-muted-foreground mt-3">正在加载设置...</p>
                  <p v-else-if="modeSaving" class="text-sm text-muted-foreground mt-3">正在保存设置...</p>
                  <p v-if="modeMessage" class="text-sm mt-3" :class="modeMessage.includes('失败') ? 'text-destructive' : 'text-emerald-600'">{{ modeMessage }}</p>
                </div>
              </div>

              <div v-else-if="activeSection === 'models'" class="space-y-6">
                <div class="rounded-lg border p-4 bg-muted/30">
                  <ModelProviderSettings @changed="routeSettingsRef?.load()" />
                </div>
                <div class="rounded-lg border p-4 bg-muted/30">
                  <ModelRouteSettings ref="routeSettingsRef" />
                </div>
              </div>

              <!-- Placeholder for other sections -->
              <div v-else class="text-center py-12 text-muted-foreground">
                <Settings class="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>{{ currentSection?.label }}功能开发中...</p>
                <p class="text-sm mt-2">敬请期待后续更新</p>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  </div>
</template>
