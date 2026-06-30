<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  FileText,
  Lock,
  Mail,
  MessageSquare,
  Search,
  User,
} from 'lucide-vue-next'
import { useUserStore } from '@/stores/user'
import { PRODUCT_NAME } from '@/ui/pagechatContracts'
import { useI18n } from '@/i18n/messages'

const router = useRouter()
const userStore = useUserStore()
const { localizeText: lt, localizeError } = useI18n()
const isLogin = ref(true)
const error = ref('')

watch(isLogin, () => {
  error.value = ''
})

const loginForm = ref({
  email: '',
  password: '',
  remember: false,
})

const registerForm = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

async function handleLogin() {
  error.value = ''
  try {
    await userStore.login(loginForm.value.email, loginForm.value.password)
    router.push('/')
  } catch (err: any) {
    error.value = localizeError(err.message || '登录失败')
  }
}

async function handleRegister() {
  if (registerForm.value.password !== registerForm.value.confirmPassword) {
    error.value = lt('两次输入的密码不一致')
    return
  }

  error.value = ''
  try {
    await userStore.register(
      registerForm.value.username,
      registerForm.value.email,
      registerForm.value.password,
    )
    isLogin.value = true
    loginForm.value.email = registerForm.value.email
  } catch (err: any) {
    error.value = localizeError(err.message || '注册失败')
  }
}
</script>

<template>
  <main class="login-page">
    <section class="product-preview">
      <div class="preview-shell">
        <aside class="preview-sidebar">
          <div class="preview-brand">
            <span>P</span>
            <strong>{{ PRODUCT_NAME }}</strong>
          </div>
          <div class="preview-nav active">
            <MessageSquare />
            Chat
          </div>
          <div class="preview-nav">
            <FileText />
            Documents
          </div>
        </aside>

        <div class="preview-main">
          <header>
            <strong>Chat</strong>
            <span>TT</span>
          </header>
          <div class="preview-conversation">
            <div class="preview-step">
              <Search />
              <span>Browsed documents · 3 documents</span>
            </div>
            <div class="preview-answer">
              <p>{{ lt('根据目录结构，核心风险集中在现金流、续约条款和附件证明三处。') }}</p>
              <div>
                <span>Q2 Report p.12</span>
                <span>Contract p.4</span>
              </div>
            </div>
          </div>
          <div class="preview-composer">
            <span>Ask PageChat about your documents...</span>
            <button type="button">
              <ArrowRight />
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <div class="mobile-brand">
          <span>P</span>
          <strong>{{ PRODUCT_NAME }}</strong>
        </div>

        <div class="auth-heading">
          <h1>{{ isLogin ? lt('欢迎回来') : lt('创建账号') }}</h1>
          <p>{{ isLogin ? lt('登录后继续管理文档和对话。') : lt('创建 PageChat 账号，开始构建可追溯的文档问答工作区。') }}</p>
        </div>

        <div class="auth-tabs">
          <button :class="{ active: isLogin }" type="button" @click="isLogin = true">{{ lt('登录') }}</button>
          <button :class="{ active: !isLogin }" type="button" @click="isLogin = false">{{ lt('注册') }}</button>
        </div>

        <p v-if="error" class="auth-error">{{ error }}</p>

        <form v-if="isLogin" class="auth-form" @submit.prevent="handleLogin">
          <label>
            {{ lt('电子邮箱') }}
            <span>
              <Mail />
              <input v-model="loginForm.email" type="email" autocomplete="email" placeholder="you@example.com" />
            </span>
          </label>

          <label>
            {{ lt('密码') }}
            <span>
              <Lock />
              <input v-model="loginForm.password" type="password" autocomplete="current-password" placeholder="••••••••" />
            </span>
          </label>

          <div class="form-row">
            <label class="remember">
              <input v-model="loginForm.remember" type="checkbox" />
              {{ lt('记住我') }}
            </label>
            <button class="link-button" type="button">{{ lt('忘记密码？') }}</button>
          </div>

          <button class="submit-button" type="submit" :disabled="userStore.isLoading">
            <span v-if="userStore.isLoading" class="spinner" />
            <template v-else>
              {{ lt('登录') }}
              <ArrowRight />
            </template>
          </button>

        </form>

        <form v-else class="auth-form" @submit.prevent="handleRegister">
          <label>
            {{ lt('用户名') }}
            <span>
              <User />
              <input v-model="registerForm.username" type="text" autocomplete="username" placeholder="TT" />
            </span>
          </label>

          <label>
            {{ lt('电子邮箱') }}
            <span>
              <Mail />
              <input v-model="registerForm.email" type="email" autocomplete="email" placeholder="you@example.com" />
            </span>
          </label>

          <label>
            {{ lt('密码') }}
            <span>
              <Lock />
              <input v-model="registerForm.password" type="password" autocomplete="new-password" :placeholder="lt('至少 8 位，含大小写、数字和符号')" />
            </span>
          </label>

          <label>
            {{ lt('确认密码') }}
            <span>
              <Lock />
              <input v-model="registerForm.confirmPassword" type="password" autocomplete="new-password" :placeholder="lt('再次输入密码')" />
            </span>
          </label>

          <button class="submit-button" type="submit" :disabled="userStore.isLoading">
            <span v-if="userStore.isLoading" class="spinner" />
            <template v-else>
              {{ lt('创建账号') }}
              <ArrowRight />
            </template>
          </button>

        </form>

        <p class="auth-footnote">© 2026 {{ PRODUCT_NAME }}</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  width: 100vw;
  height: 100vh;
  grid-template-columns: minmax(0, 1.08fr) minmax(430px, 0.92fr);
  overflow: hidden;
  background: var(--kc-bg);
  color: var(--kc-text);
}

.product-preview {
  display: grid;
  min-width: 0;
  place-items: center;
  padding: 48px;
}

.preview-shell {
  display: grid;
  width: min(820px, 100%);
  height: min(620px, calc(100vh - 96px));
  min-height: 0;
  grid-template-columns: 220px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.78);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: 0 28px 90px rgba(15, 23, 42, 0.13);
}

.preview-sidebar {
  border-right: 1px solid var(--kc-border);
  background: #f8fafc;
  padding: 18px 14px;
}

.preview-brand,
.mobile-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.preview-brand span,
.mobile-brand span {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid rgba(47, 128, 237, 0.22);
  border-radius: 9px;
  background: #eaf3ff;
  color: var(--kc-accent);
  font-size: 13px;
  font-weight: 750;
}

.preview-brand strong,
.mobile-brand strong {
  font-size: 15px;
}

.preview-nav {
  display: flex;
  align-items: center;
  gap: 9px;
  height: 34px;
  margin-top: 8px;
  border-radius: var(--kc-radius-md);
  padding: 0 10px;
  color: var(--kc-text-secondary);
  font-size: 13px;
}

.preview-nav:first-of-type {
  margin-top: 28px;
}

.preview-nav.active {
  background: #eaf3ff;
  color: #145eb8;
}

.preview-nav svg,
.preview-step svg,
.preview-composer svg,
.auth-form svg,
.submit-button svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.85;
}

.preview-main {
  display: grid;
  min-height: 0;
  grid-template-rows: 54px minmax(0, 1fr) auto;
}

.preview-main header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--kc-border);
  padding: 0 20px;
}

.preview-main header span {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--kc-border);
  border-radius: 999px;
  color: var(--kc-text-secondary);
  font-size: 12px;
}

.preview-conversation {
  display: grid;
  align-content: center;
  gap: 12px;
  padding: 42px;
}

.preview-step {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 8px;
  color: var(--kc-text-tertiary);
  font-size: 12.5px;
}

.preview-answer {
  max-width: 460px;
  border: 1px solid var(--kc-border-soft);
  border-radius: var(--kc-radius-lg);
  background: #fff;
  padding: 16px;
}

.preview-answer p {
  margin: 0;
  font-size: 13.5px;
  line-height: 22px;
}

.preview-answer div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.preview-answer span {
  border: 1px solid var(--kc-border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--kc-text-tertiary);
  font-size: 11px;
}

.preview-composer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 24px 24px;
  border: 1px solid var(--kc-border);
  border-radius: 16px;
  background: #fff;
  padding: 10px 10px 10px 16px;
  box-shadow: 0 14px 38px rgba(15, 23, 42, 0.08);
}

.preview-composer span {
  color: var(--kc-text-tertiary);
  font-size: 12.5px;
}

.preview-composer button {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 0;
  border-radius: 999px;
  background: var(--kc-text);
  color: #fff;
}

.auth-panel {
  display: grid;
  min-width: 0;
  place-items: center;
  border-left: 1px solid var(--kc-border);
  background: rgba(255, 255, 255, 0.72);
  padding: 48px;
}

.auth-card {
  width: min(420px, 100%);
}

.mobile-brand {
  display: none;
  margin-bottom: 24px;
}

.auth-heading h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 680;
  line-height: 36px;
}

.auth-heading p {
  margin: 6px 0 0;
  color: var(--kc-text-secondary);
  font-size: 13px;
  line-height: 21px;
}

.auth-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  margin: 24px 0;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-lg);
  background: var(--kc-surface-muted);
  padding: 4px;
}

.auth-tabs button {
  height: 34px;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: transparent;
  color: var(--kc-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.auth-tabs button.active {
  background: #fff;
  color: var(--kc-text);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
}

.auth-form {
  display: grid;
  gap: 14px;
}

.auth-form label {
  display: grid;
  gap: 7px;
  color: var(--kc-text-secondary);
  font-size: 12px;
  font-weight: 560;
}

.auth-form label > span {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 42px;
  border: 1px solid var(--kc-border);
  border-radius: var(--kc-radius-md);
  background: #fff;
  padding: 0 12px;
}

.auth-form input {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  color: var(--kc-text);
  font-size: 13px;
  outline: none;
}

.form-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.remember {
  display: flex !important;
  grid-template-columns: unset !important;
  align-items: center;
  gap: 8px !important;
}

.remember input {
  width: 14px;
  height: 14px;
  flex: 0 0 14px;
}

.link-button {
  border: 0;
  background: transparent;
  color: var(--kc-accent);
  font-size: 12.5px;
  font-weight: 600;
}

.submit-button {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 42px;
  border: 0;
  border-radius: var(--kc-radius-md);
  background: var(--kc-text);
  color: #fff;
  font-size: 13px;
  font-weight: 650;
}

.submit-button:disabled {
  opacity: 0.55;
}

.auth-error {
  border: 1px solid #fecaca;
  border-radius: var(--kc-radius-md);
  background: #fef2f2;
  padding: 10px 12px;
  color: #b91c1c;
  font-size: 12.5px;
}

.auth-footnote {
  margin: 22px 0 0;
  color: var(--kc-text-tertiary);
  font-size: 12px;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.32);
  border-top-color: #fff;
  border-radius: 999px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 980px) {
  .login-page {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }

  .product-preview {
    display: none;
  }

  .auth-panel {
    min-height: 100vh;
    border-left: 0;
    padding: 32px 22px;
  }

  .mobile-brand {
    display: flex;
  }
}
</style>
