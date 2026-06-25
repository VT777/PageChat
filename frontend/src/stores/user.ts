import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

interface User {
  id: string
  username: string
}

function extractAuthError(data: any, fallback: string): string {
  if (typeof data?.error === 'string' && data.error.trim()) {
    return data.error
  }

  if (typeof data?.detail === 'string' && data.detail.trim()) {
    return data.detail
  }

  if (Array.isArray(data?.detail)) {
    const messages = data.detail
      .map((item: any) => item?.msg || item?.message)
      .filter((message: unknown): message is string => typeof message === 'string' && message.trim().length > 0)
    if (messages.length > 0) {
      return messages.join('；')
    }
  }

  return fallback
}

export const useUserStore = defineStore('user', () => {
  // State
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<User | null>(null)
  const isLoading = ref(false)

  // Getters
  const isLoggedIn = computed(() => !!token.value && !!user.value)
  const username = computed(() => user.value?.username || '')

  // Actions
  function setToken(newToken: string | null) {
    token.value = newToken
    if (newToken) {
      localStorage.setItem('token', newToken)
    } else {
      localStorage.removeItem('token')
    }
  }

  function setUser(userData: User | null) {
    user.value = userData
  }

  async function fetchUserInfo() {
    if (!token.value) return
    
    try {
      const response = await fetch('/api/auth/me', {
        headers: {
          'Authorization': `Bearer ${token.value}`
        }
      })
      
      if (response.ok) {
        const data = await response.json()
        user.value = data
      } else {
        // Token无效，清除登录状态
        logout()
      }
    } catch (error) {
      console.error('Failed to fetch user info:', error)
    }
  }

  async function login(email: string, password: string) {
    isLoading.value = true
    try {
      const trimmedEmail = email.trim()
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ email: trimmedEmail, password })
      })

      const data = await response.json()
      
      // Handle wrapped response format
      if (!response.ok || !data.success) {
        throw new Error(extractAuthError(data, '登录失败'))
      }

      setToken(data.token)
      user.value = { id: data.user.id, username: data.user.username }
      return true
    } catch (error) {
      throw error
    } finally {
      isLoading.value = false
    }
  }

  async function register(username: string, email: string, password: string) {
    isLoading.value = true
    try {
      const trimmedUsername = username.trim()
      const trimmedEmail = email.trim()
      const response = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ username: trimmedUsername, email: trimmedEmail, password })
      })

      const data = await response.json()
      
      // Handle wrapped response format
      if (!response.ok || !data.success) {
        throw new Error(extractAuthError(data, '注册失败'))
      }

      setToken(data.token)
      user.value = { id: data.user.id, username: data.user.username }
      return true
    } catch (error) {
      throw error
    } finally {
      isLoading.value = false
    }
  }

  function logout() {
    setToken(null)
    user.value = null
  }

  // Initialize on store creation
  if (token.value) {
    fetchUserInfo()
  }

  return {
    token,
    user,
    isLoading,
    isLoggedIn,
    username,
    setToken,
    setUser,
    fetchUserInfo,
    login,
    register,
    logout
  }
})
