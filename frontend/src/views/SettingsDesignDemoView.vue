<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowLeft,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Database,
  KeyRound,
  Languages,
  Loader2,
  LogOut,
  Monitor,
  Moon,
  Palette,
  Search,
  ShieldCheck,
  Sun,
  User,
  X,
  Zap,
} from 'lucide-vue-next'

type SectionId = 'models' | 'indexing' | 'account' | 'appearance'

const activeSection = ref<SectionId>('models')
const selectedIndexMode = ref('smart')
const selectedTheme = ref('system')
const selectedLanguage = ref('zh-CN')

const sections: Array<{
  id: SectionId
  group: string
  label: string
  hint: string
  icon: any
}> = [
  { id: 'models', group: '系统能力', label: '模型', hint: '供应商与任务路由', icon: Bot },
  { id: 'indexing', group: '系统能力', label: '索引与文档', hint: '解析模式与重建策略', icon: Database },
  { id: 'account', group: '个人', label: '账号', hint: '登录身份与会话', icon: User },
  { id: 'appearance', group: '个人', label: '界面偏好', hint: '语言与显示主题', icon: Palette },
]

const currentSection = computed(() => sections.find(item => item.id === activeSection.value))

const providerCards = [
  {
    name: 'DashScope compatible',
    endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    key: 'sk-***8129',
    status: '已连接',
    tone: 'ready',
  },
  {
    name: 'OpenAI compatible',
    endpoint: 'https://api.openai.com/v1',
    key: '未保存密钥',
    status: '未配置',
    tone: 'empty',
  },
]

const routeRows = [
  {
    task: '文档问答',
    description: 'Agent 回答、引用组织和工具调用后的最终总结。',
    model: 'qwen3.6-plus',
    provider: 'DashScope',
    source: '用户配置',
  },
  {
    task: '检索优化',
    description: '短查询改写、同义词扩展和召回增强，不直接生成答案。',
    model: 'qwen3.6-flash',
    provider: '服务端默认',
    source: '默认',
  },
  {
    task: '索引生成',
    description: '目录、摘要和 PageIndex 结构生成。',
    model: 'qwen3.6-flash',
    provider: '服务端默认',
    source: '默认',
  },
  {
    task: '视觉 / OCR',
    description: '图表、截图和页面视觉理解。',
    model: 'qwen-vl-ocr-latest',
    provider: 'DashScope',
    source: '用户配置',
  },
]

const indexModes = [
  {
    id: 'smart',
    title: '智能模式',
    tag: '推荐',
    desc: '先预分析文档，再自动选择快速或平衡路径，适合日常上传。',
  },
  {
    id: 'balanced',
    title: '平衡模式',
    tag: '质量优先',
    desc: '更完整地生成目录、摘要和引用定位，处理时间更长。',
  },
  {
    id: 'fast',
    title: '快速模式',
    tag: '速度优先',
    desc: '减少扩展处理，缩短等待时间，适合结构清晰的短文档。',
  },
]

const themeOptions = [
  { id: 'system', label: '跟随系统', icon: Monitor },
  { id: 'light', label: '浅色', icon: Sun },
  { id: 'dark', label: '深色', icon: Moon },
]
</script>

<template>
  <div class="settings-demo">
    <div class="settings-shell">
      <aside class="settings-sidebar">
        <div class="sidebar-title">
          <button class="icon-button" aria-label="返回">
            <ArrowLeft class="h-4 w-4" />
          </button>
          <div>
            <p>设置</p>
            <h1>PageChat</h1>
          </div>
        </div>

        <nav class="nav-groups">
          <div v-for="group in ['系统能力', '个人']" :key="group" class="nav-group">
            <p class="nav-group-title">{{ group }}</p>
            <button
              v-for="item in sections.filter(section => section.group === group)"
              :key="item.id"
              :class="['nav-item', { active: activeSection === item.id }]"
              @click="activeSection = item.id"
            >
              <component :is="item.icon" class="h-5 w-5 shrink-0" />
              <span>
                <strong>{{ item.label }}</strong>
                <em>{{ item.hint }}</em>
              </span>
            </button>
          </div>
        </nav>
      </aside>

      <main class="settings-content">
        <header class="content-header">
          <div>
            <p>{{ currentSection?.hint }}</p>
            <h2>{{ currentSection?.label }}</h2>
          </div>
          <button class="icon-button" aria-label="关闭">
            <X class="h-5 w-5" />
          </button>
        </header>

        <section v-if="activeSection === 'models'" class="content-body">
          <div class="toolbar">
            <div class="search-box">
              <Search class="h-4 w-4" />
              <span>搜索供应商或模型</span>
            </div>
            <button class="primary-button">
              <KeyRound class="h-4 w-4" />
              添加供应商
            </button>
          </div>

          <section class="block">
            <div class="block-heading">
              <div>
                <h3>模型供应商</h3>
                <p>保存 OpenAI 兼容供应商，密钥只写入不回显。</p>
              </div>
              <span class="status-note success">
                <ShieldCheck class="h-4 w-4" />
                密钥已保护
              </span>
            </div>

            <div class="provider-list">
              <article
                v-for="provider in providerCards"
                :key="provider.name"
                :class="['provider-card', provider.tone]"
              >
                <div class="provider-main">
                  <div class="provider-icon">
                    <Zap class="h-4 w-4" />
                  </div>
                  <div>
                    <h4>{{ provider.name }}</h4>
                    <p>{{ provider.endpoint }}</p>
                  </div>
                </div>
                <div class="provider-meta">
                  <span>{{ provider.key }}</span>
                  <strong>{{ provider.status }}</strong>
                </div>
              </article>
            </div>
          </section>

          <section class="block">
            <div class="block-heading">
              <div>
                <h3>任务路由</h3>
                <p>只展示当前系统已经有明确执行边界的模型任务，空路由继续使用服务端默认配置。</p>
              </div>
              <button class="secondary-button">
                保存路由
              </button>
            </div>

            <div class="route-table">
              <div class="route-head">
                <span>任务</span>
                <span>模型</span>
                <span>供应商</span>
                <span>来源</span>
              </div>
              <div v-for="row in routeRows" :key="row.task" class="route-row">
                <strong>
                  {{ row.task }}
                  <small>{{ row.description }}</small>
                </strong>
                <span>{{ row.model }}</span>
                <span>{{ row.provider }}</span>
                <em :class="{ muted: row.source === '默认' }">{{ row.source }}</em>
              </div>
            </div>

            <div class="notice-row neutral">
              <CircleAlert class="h-5 w-5" />
              <div>
                <strong>普通聊天暂不作为可配置路由展示</strong>
                <p>当前后端还没有稳定的普通聊天 / 文档问答意图分流。等该路径接入用户模型配置后，再放进设置页会更准确。</p>
              </div>
            </div>
          </section>
        </section>

        <section v-else-if="activeSection === 'indexing'" class="content-body">
          <section class="block">
            <div class="block-heading">
              <div>
                <h3>PageIndex 模式</h3>
                <p>只影响后续新上传或手动重建索引的文档。</p>
              </div>
              <span class="status-note">
                <Loader2 class="h-4 w-4" />
                运行时配置
              </span>
            </div>

            <div class="mode-list">
              <button
                v-for="mode in indexModes"
                :key="mode.id"
                :class="['mode-option', { active: selectedIndexMode === mode.id }]"
                @click="selectedIndexMode = mode.id"
              >
                <span>
                  <strong>{{ mode.title }}</strong>
                  <em>{{ mode.desc }}</em>
                </span>
                <b>{{ mode.tag }}</b>
              </button>
            </div>
          </section>

          <section class="block">
            <div class="block-heading">
              <div>
                <h3>文档处理提示</h3>
                <p>设置页只暴露会真实影响处理结果的选项，不把内部质量阈值提前交给用户。</p>
              </div>
            </div>
            <div class="notice-row">
              <CircleAlert class="h-5 w-5" />
              <div>
                <strong>已完成索引的文档不会被自动改写</strong>
                <p>如果希望使用新模式，需要在文档详情里手动重建索引。</p>
              </div>
            </div>
          </section>
        </section>

        <section v-else-if="activeSection === 'account'" class="content-body">
          <section class="block">
            <div class="account-card">
              <div class="avatar">P</div>
              <div>
                <h3>admin</h3>
                <p>admin@pagechat.local</p>
              </div>
              <span class="status-note success">
                <CheckCircle2 class="h-4 w-4" />
                已登录
              </span>
            </div>
          </section>

          <section class="block">
            <button class="action-row">
              <User class="h-5 w-5" />
              <span>
                <strong>切换账号</strong>
                <em>退出当前会话并返回登录页。</em>
              </span>
            </button>
            <button class="action-row danger">
              <LogOut class="h-5 w-5" />
              <span>
                <strong>退出登录</strong>
                <em>清除本地 token 和用户状态。</em>
              </span>
            </button>
          </section>
        </section>

        <section v-else class="content-body">
          <section class="block">
            <div class="block-heading">
              <div>
                <h3>显示语言</h3>
                <p>先作为前端显示偏好处理，不引入复杂国际化后台。</p>
              </div>
              <Languages class="h-5 w-5 text-muted" />
            </div>
            <div class="select-row">
              <span>界面语言</span>
              <button class="select-button" @click="selectedLanguage = selectedLanguage === 'zh-CN' ? 'en-US' : 'zh-CN'">
                {{ selectedLanguage === 'zh-CN' ? '简体中文' : 'English' }}
                <ChevronDown class="h-4 w-4" />
              </button>
            </div>
          </section>

          <section class="block">
            <div class="block-heading">
              <div>
                <h3>主题</h3>
                <p>提供浅色、深色和跟随系统，不加入更多视觉参数。</p>
              </div>
            </div>
            <div class="theme-grid">
              <button
                v-for="theme in themeOptions"
                :key="theme.id"
                :class="['theme-option', { active: selectedTheme === theme.id }]"
                @click="selectedTheme = theme.id"
              >
                <component :is="theme.icon" class="h-5 w-5" />
                <span>{{ theme.label }}</span>
                <Check v-if="selectedTheme === theme.id" class="h-4 w-4" />
              </button>
            </div>
          </section>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.settings-demo {

  --bg: #f7f8fa;
  --panel: #ffffff;
  --panel-muted: #f4f6f8;
  --text: #101828;
  --muted: #667085;
  --line: #eaecf0;
  --active: #eef4ff;
  --active-text: #155eef;
  --success-bg: #ecfdf3;
  --success-text: #027a48;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
}

button {
  border: 0;
  color: inherit;
  cursor: pointer;
  font: inherit;
}

.settings-shell {
  display: grid;
  grid-template-columns: 224px minmax(0, 824px);
  justify-content: center;
  height: 100vh;
  min-height: 0;
}

.settings-sidebar {
  border-right: 1px solid var(--line);
  background: var(--panel);
  padding: 24px 16px;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
}

.sidebar-title p,
.content-header p,
.nav-group-title {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
}

.sidebar-title h1,
.content-header h2 {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
}

.icon-button {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: transparent;
}

.icon-button:hover {
  background: var(--panel-muted);
}

.nav-groups {
  display: grid;
  gap: 20px;
}

.nav-group-title {
  margin: 0 0 6px 12px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 44px;
  border-radius: 8px;
  background: transparent;
  padding: 8px 10px;
  text-align: left;
}

.nav-item span,
.nav-item strong,
.nav-item em {
  display: block;
  min-width: 0;
}

.nav-item strong {
  font-size: 14px;
  font-weight: 650;
}

.nav-item em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.nav-item:hover,
.nav-item.active {
  background: var(--active);
  color: var(--active-text);
}

.nav-item.active em {
  color: #528bff;
}

.settings-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--panel);
}

.content-header {
  z-index: 2;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 88px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.96);
  padding: 24px 32px 18px;
}

.content-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: grid;
  align-content: start;
  gap: 16px;
  padding: 24px 32px 40px;
}

.toolbar,
.block-heading,
.provider-card,
.provider-main,
.status-note,
.notice-row,
.account-card,
.action-row,
.select-row,
.theme-option,
.primary-button,
.secondary-button,
.select-button {
  display: flex;
  align-items: center;
}

.toolbar {
  justify-content: space-between;
  gap: 12px;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 260px;
  height: 36px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--muted);
  padding: 0 10px;
  font-size: 13px;
}

.primary-button,
.secondary-button,
.select-button {
  justify-content: center;
  gap: 8px;
  height: 36px;
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 650;
}

.primary-button {
  background: #155eef;
  color: white;
}

.secondary-button,
.select-button {
  border: 1px solid var(--line);
  background: white;
}

.block {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 16px;
}

.block-heading {
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.block-heading h3 {
  font-size: 16px;
  font-weight: 700;
}

.block-heading p {
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
}

.status-note {
  gap: 6px;
  border-radius: 999px;
  background: var(--panel-muted);
  color: #475467;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.status-note.success {
  background: var(--success-bg);
  color: var(--success-text);
}

.provider-list,
.mode-list,
.theme-grid {
  display: grid;
  gap: 10px;
}

.provider-card {
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
}

.provider-card.ready {
  border-color: #b2ddff;
  background: #f5faff;
}

.provider-main {
  gap: 12px;
  min-width: 0;
}

.provider-icon {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: white;
  color: #155eef;
}

.provider-card h4 {
  font-size: 14px;
  font-weight: 700;
}

.provider-card p,
.provider-meta span {
  color: var(--muted);
  font-size: 12px;
}

.provider-card p {
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.provider-meta {
  display: grid;
  justify-items: end;
  gap: 4px;
  white-space: nowrap;
}

.provider-meta strong {
  color: var(--success-text);
  font-size: 12px;
}

.provider-card.empty .provider-meta strong {
  color: var(--muted);
}

.route-table {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
}

.route-head,
.route-row {
  display: grid;
  grid-template-columns: 1.35fr 1.1fr 1.1fr 0.75fr;
  gap: 12px;
  align-items: center;
  padding: 10px 12px;
}

.route-head {
  background: var(--panel-muted);
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}

.route-row {
  border-top: 1px solid var(--line);
  font-size: 13px;
}

.route-row small {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 400;
}

.route-row em {
  width: max-content;
  border-radius: 999px;
  background: var(--active);
  color: var(--active-text);
  padding: 4px 8px;
  font-style: normal;
  font-weight: 650;
}

.route-row em.muted {
  background: var(--panel-muted);
  color: var(--muted);
}

.mode-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: white;
  padding: 14px;
  text-align: left;
}

.mode-option.active {
  border-color: #84caff;
  background: #f5faff;
}

.mode-option span,
.mode-option strong,
.mode-option em {
  display: block;
}

.mode-option strong {
  font-size: 14px;
  font-weight: 700;
}

.mode-option em {
  margin-top: 4px;
  color: var(--muted);
  font-size: 13px;
  font-style: normal;
}

.mode-option b {
  border-radius: 999px;
  background: var(--panel-muted);
  color: #475467;
  padding: 5px 8px;
  font-size: 12px;
  white-space: nowrap;
}

.mode-option.active b {
  background: var(--active);
  color: var(--active-text);
}

.notice-row {
  gap: 12px;
  margin-top: 14px;
  border-radius: 8px;
  background: #fffaeb;
  color: #93370d;
  padding: 14px;
}

.notice-row.neutral {
  background: #f8fafc;
  color: #344054;
}

.notice-row strong,
.notice-row p {
  display: block;
}

.notice-row p {
  margin-top: 2px;
  font-size: 13px;
}

.account-card {
  justify-content: space-between;
}

.avatar {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: #155eef;
  color: white;
  font-weight: 800;
}

.account-card h3 {
  font-size: 16px;
  font-weight: 700;
}

.account-card p {
  color: var(--muted);
  font-size: 13px;
}

.action-row {
  gap: 12px;
  width: 100%;
  border-radius: 8px;
  background: transparent;
  padding: 12px;
  text-align: left;
}

.action-row + .action-row {
  margin-top: 6px;
}

.action-row:hover {
  background: var(--panel-muted);
}

.action-row strong,
.action-row em {
  display: block;
}

.action-row em {
  color: var(--muted);
  font-size: 13px;
  font-style: normal;
}

.action-row.danger {
  color: #b42318;
}

.select-row {
  justify-content: space-between;
}

.theme-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.theme-option {
  justify-content: center;
  gap: 10px;
  min-height: 72px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: white;
  color: #344054;
}

.theme-option.active {
  border-color: #84caff;
  background: #f5faff;
  color: var(--active-text);
}

.text-muted {
  color: var(--muted);
}

@media (max-width: 860px) {
  .settings-shell {
    grid-template-columns: 72px minmax(0, 1fr);
  }

  .settings-sidebar {
    padding: 18px 10px;
  }

  .sidebar-title div,
  .nav-group-title,
  .nav-item em,
  .nav-item strong {
    display: none;
  }

  .nav-item {
    justify-content: center;
    padding: 10px;
  }

  .content-header,
  .content-body {
    padding-left: 18px;
    padding-right: 18px;
  }

  .toolbar,
  .block-heading,
  .provider-card,
  .account-card {
    align-items: stretch;
    flex-direction: column;
  }

  .search-box {
    width: 100%;
  }

  .route-head,
  .route-row {
    grid-template-columns: 1fr;
  }

  .theme-grid {
    grid-template-columns: 1fr;
  }
}
</style>


