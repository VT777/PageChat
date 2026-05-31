<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock, Mail, ArrowRight, Sparkles, Shield } from 'lucide-vue-next'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const isLogin = ref(true)
const error = ref('')

// 切换登录/注册时清除错误
watch(isLogin, () => {
  error.value = ''
})

const loginForm = ref({
  email: '',
  password: '',
  remember: false
})

const registerForm = ref({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

const handleLogin = async () => {
  error.value = ''
  try {
    console.log('Attempting login...')
    await userStore.login(loginForm.value.email, loginForm.value.password)
    console.log('Login successful, redirecting...')
    router.push('/')
  } catch (err: any) {
    console.error('Login error:', err)
    error.value = err.message || '登录失败'
  }
}

const handleRegister = async () => {
  if (registerForm.value.password !== registerForm.value.confirmPassword) {
    error.value = '两次输入的密码不一致'
    return
  }

  error.value = ''
  try {
    await userStore.register(
      registerForm.value.username,
      registerForm.value.email,
      registerForm.value.password
    )
    isLogin.value = true
    loginForm.value.email = registerForm.value.email
  } catch (err: any) {
    error.value = err.message || '注册失败'
  }
}
</script>

<template>
  <div class="min-h-screen flex">
    <!-- 左侧品牌区域 -->
    <div class="hidden lg:flex lg:w-1/2 relative overflow-hidden">
      <!-- 渐变背景 -->
      <div class="absolute inset-0 bg-gradient-to-br from-indigo-900 via-purple-900 to-slate-900"></div>
      
      <!-- 动态光效 -->
      <div class="absolute inset-0">
        <div class="absolute top-1/4 left-1/4 w-96 h-96 bg-indigo-500/30 rounded-full blur-3xl animate-pulse"></div>
        <div class="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-500/20 rounded-full blur-3xl animate-pulse" style="animation-delay: 1s;"></div>
        <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-blue-500/20 rounded-full blur-3xl animate-pulse" style="animation-delay: 2s;"></div>
      </div>
      
      <!-- 装饰网格 -->
      <div class="absolute inset-0 opacity-10" style="background-image: radial-gradient(circle at 1px 1px, white 1px, transparent 0); background-size: 40px 40px;"></div>
      
      <!-- 品牌内容 -->
      <div class="relative z-10 flex flex-col justify-center px-16">
        <div class="flex items-center gap-3 mb-8">
          <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-400 to-purple-500 flex items-center justify-center shadow-2xl shadow-indigo-500/30">
            <Sparkles class="w-7 h-7 text-white" />
          </div>
          <h1 class="text-4xl font-bold text-white tracking-tight">KnowClaw</h1>
        </div>
        
        <h2 class="text-5xl font-bold text-white mb-6 leading-tight">
          智能知识<br/>
          <span class="text-transparent bg-clip-text bg-gradient-to-r from-indigo-300 to-purple-300">问答平台</span>
        </h2>
        
        <p class="text-indigo-100/80 text-lg mb-12 max-w-md leading-relaxed">
          基于先进 AI 技术，让知识检索更智能、更高效。支持文档管理、智能问答、知识库构建。
        </p>
        
        <!-- 特性展示 -->
        <div class="space-y-4">
          <div class="flex items-center gap-4 text-indigo-100/90">
            <div class="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-sm flex items-center justify-center">
              <Shield class="w-5 h-5" />
            </div>
            <span>数据安全隔离，隐私保护</span>
          </div>
          <div class="flex items-center gap-4 text-indigo-100/90">
            <div class="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-sm flex items-center justify-center">
              <Sparkles class="w-5 h-5" />
            </div>
            <span>AI 驱动的智能问答</span>
          </div>
        </div>
      </div>
    </div>
    
    <!-- 右侧表单区域 -->
    <div class="w-full lg:w-1/2 flex items-center justify-center p-8 relative">
      <!-- 背景 -->
      <div class="absolute inset-0 bg-slate-50 dark:bg-slate-950"></div>
      <div class="absolute inset-0 bg-gradient-to-br from-indigo-50/50 to-purple-50/50 dark:from-indigo-950/20 dark:to-purple-950/20"></div>
      
      <!-- 登录/注册卡片 -->
      <div class="relative w-full max-w-md">
        <!-- 移动端 Logo -->
        <div class="lg:hidden flex items-center justify-center gap-3 mb-8">
          <div class="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center">
            <Sparkles class="w-6 h-6 text-white" />
          </div>
          <h1 class="text-2xl font-bold text-slate-900 dark:text-white">KnowClaw</h1>
        </div>
        
        <div class="bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl rounded-3xl shadow-2xl shadow-indigo-500/10 border border-white/20 dark:border-slate-800 p-8">
          <!-- 切换标签 -->
          <div class="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-2xl mb-8">
            <button
              @click="isLogin = true"
              :class="[
                'flex-1 py-3 px-4 rounded-xl text-sm font-medium transition-all duration-300',
                isLogin 
                  ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-lg shadow-indigo-500/10' 
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
              ]"
            >
              登录
            </button>
            <button
              @click="isLogin = false"
              :class="[
                'flex-1 py-3 px-4 rounded-xl text-sm font-medium transition-all duration-300',
                !isLogin 
                  ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-lg shadow-indigo-500/10' 
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300'
              ]"
            >
              注册
            </button>
          </div>
          
          <!-- 错误提示 -->
          <div v-if="error" class="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-600 dark:text-red-400 text-sm text-center">
            {{ error }}
          </div>
          
          <!-- 登录表单 -->
          <form v-if="isLogin" @submit.prevent="handleLogin" class="space-y-5">
            <div class="text-center mb-8">
              <h2 class="text-2xl font-bold text-slate-900 dark:text-white mb-2">欢迎回来</h2>
              <p class="text-slate-500 dark:text-slate-400 text-sm">请输入您的账号信息继续</p>
            </div>
            
            <div class="space-y-4">
              <div class="relative group">
                <Mail class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                <input
                  v-model="loginForm.email"
                  type="email"
                  placeholder="电子邮箱"
                  class="w-full pl-12 pr-4 py-4 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>
              
              <div class="relative group">
                <Lock class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                <input
                  v-model="loginForm.password"
                  type="password"
                  placeholder="密码"
                  class="w-full pl-12 pr-4 py-4 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>
            </div>
            
            <div class="flex items-center justify-between text-sm">
              <label class="flex items-center gap-2 cursor-pointer group">
                <input 
                  v-model="loginForm.remember"
                  type="checkbox" 
                  class="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
                <span class="text-slate-600 dark:text-slate-400 group-hover:text-slate-800 dark:group-hover:text-slate-200 transition-colors">记住我</span>
              </label>
              <a href="#" class="text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium transition-colors">
                忘记密码？
              </a>
            </div>
            
            <button
              type="submit"
              :disabled="userStore.isLoading"
              class="w-full py-4 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white font-semibold rounded-xl shadow-lg shadow-indigo-500/30 hover:shadow-indigo-500/40 transition-all duration-300 flex items-center justify-center gap-2 disabled:opacity-70 disabled:cursor-not-allowed group"
            >
              <span v-if="userStore.isLoading" class="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span v-else>
                登录
                <ArrowRight class="inline-block w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
              </span>
            </button>
          </form>
          
          <!-- 注册表单 -->
          <form v-else @submit.prevent="handleRegister" class="space-y-5">
            <div class="text-center mb-8">
              <h2 class="text-2xl font-bold text-slate-900 dark:text-white mb-2">创建账号</h2>
              <p class="text-slate-500 dark:text-slate-400 text-sm">开始您的智能知识之旅</p>
            </div>
            
            <div class="space-y-4">
              <div class="relative group">
                <User class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                <input
                  v-model="registerForm.username"
                  type="text"
                  placeholder="用户名"
                  class="w-full pl-12 pr-4 py-4 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>
              
              <div class="relative group">
                <Mail class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                <input
                  v-model="registerForm.email"
                  type="email"
                  placeholder="电子邮箱"
                  class="w-full pl-12 pr-4 py-4 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>
              
              <div class="relative group">
                <Lock class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                <input
                  v-model="registerForm.password"
                  type="password"
                  placeholder="密码"
                  class="w-full pl-12 pr-4 py-4 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>
              
              <div class="relative group">
                <Lock class="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-400 group-focus-within:text-indigo-500 transition-colors" />
                <input
                  v-model="registerForm.confirmPassword"
                  type="password"
                  placeholder="确认密码"
                  class="w-full pl-12 pr-4 py-4 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>
            </div>
            
            <div class="text-xs text-slate-500 dark:text-slate-400 text-center">
              注册即表示您同意我们的
              <a href="#" class="text-indigo-600 dark:text-indigo-400 hover:underline">服务条款</a>
              和
              <a href="#" class="text-indigo-600 dark:text-indigo-400 hover:underline">隐私政策</a>
            </div>
            
            <button
              type="submit"
              :disabled="userStore.isLoading"
              class="w-full py-4 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white font-semibold rounded-xl shadow-lg shadow-indigo-500/30 hover:shadow-indigo-500/40 transition-all duration-300 flex items-center justify-center gap-2 disabled:opacity-70 disabled:cursor-not-allowed group"
            >
              <span v-if="userStore.isLoading" class="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
              <span v-else>
                创建账号
                <ArrowRight class="inline-block w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
              </span>
            </button>
          </form>
        </div>
        
        <!-- 底部版权 -->
        <p class="text-center text-slate-400 dark:text-slate-600 text-sm mt-8">
          © 2025 KnowClaw. All rights reserved.
        </p>
      </div>
    </div>
  </div>
</template>
