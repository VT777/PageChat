import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true }
    },
    {
      path: '/',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/documents',
      name: 'documents',
      component: () => import('@/views/DocumentView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/design-demo',
      name: 'design-demo',
      component: () => import('@/views/DesignDemoView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/settings-design-demo',
      name: 'settings-design-demo',
      component: () => import('@/views/SettingsDesignDemoView.vue'),
      meta: { public: true }
    },
  ],
})

// 路由守卫 - 用户隔离
router.beforeEach((to, _from, next) => {
  // 检查是否已登录（从 localStorage 读取）
  const isAuthenticated = localStorage.getItem('token') !== null
  
  // 如果访问需要登录的页面但未登录，跳转到登录页
  if (to.meta.requiresAuth && !isAuthenticated) {
    next('/login')
  }
  // 如果已登录但访问登录页，跳转到首页
  else if (to.path === '/login' && isAuthenticated) {
    next('/')
  }
  else {
    next()
  }
})

export default router
