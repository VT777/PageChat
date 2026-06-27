import axios from 'axios'
import type { ChatScopeRequest } from '@/types/retrieval'
import type { ModelProviderInput, ModelProviderUpdateInput, ModelRouteMapping } from '@/types/modelSettings'
import type { WebSearchSettingsUpdate } from '@/types/webSearchSettings'

export interface ProcessingStep {
  step_type: string
  title: string
  description: string
  status: 'completed' | 'failed' | 'running' | 'pending'
  duration?: number
  details?: Record<string, any>
}

export interface ProcessingStepsResponse {
  document_id: string
  steps: ProcessingStep[]
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器 - 添加 token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理 401
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Document API
export const documentApi = {
  upload: (file: File, folder_id?: string | null, parse_mode?: string | null) => {
    const formData = new FormData()
    formData.append('file', file)
    if (folder_id) {
      formData.append('folder_id', folder_id)
    }
    if (parse_mode) {
      formData.append('parse_mode', parse_mode)
    }
    return api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  
  list: (params?: { page?: number; page_size?: number; search?: string; folder_id?: string | null; include_subfolders?: boolean }) =>
    api.get('/documents', { params }),
  
  get: (id: string) => api.get(`/documents/${id}`),
  
  delete: (id: string) => api.delete(`/documents/${id}`),
  
  reindex: (id: string, payload?: { mode?: 'smart' | 'fast' | 'balanced' }) =>
    api.post(`/documents/${id}/reindex`, {
      mode: payload?.mode || 'smart',
    }),

  preview: (id: string) => api.get(`/documents/${id}/preview`),

  getPage: (id: string, pageNum: number, includeImage: boolean = true) =>
    api.get(`/documents/${id}/page/${pageNum}`, { params: { include_image: includeImage } }),

  getPageImage: (id: string, pageNum: number) =>
    api.get(`/documents/${id}/page/${pageNum}/image`),

  move: (id: string, folder_id?: string | null) => {
    const formData = new FormData()
    if (folder_id) {
      formData.append('folder_id', folder_id)
    }
    return api.post(`/documents/${id}/move`, formData)
  },
  
  rename: (id: string, name: string) => {
    const formData = new FormData()
    formData.append('name', name)
    return api.post(`/documents/${id}/rename`, formData)
  },

  // 获取文档内容（用于多格式预览）
  getContent: (id: string) => api.get(`/documents/${id}/content`),
  
  // 根据文档名搜索文档（用于引用跳转）
  searchByName: (name: string) => 
    api.get('/documents', { 
      params: { 
        page: 1, 
        page_size: 100, 
        search: name,
        include_subfolders: true 
      } 
    }).then(res => res.data.items),

  // 批量下载
  batchDownload: (docIds: string[]) =>
    api.post('/documents/batch-download', docIds, {
      responseType: 'blob',
    }),

  // 获取处理步骤详情
  getProcessingSteps: (id: string) =>
    api.get(`/documents/${id}/processing-steps`),
}

// Chat API
export const chatApi = {
  stream: (data: {
    question: string
    document_ids?: string[]
    attachment_ids?: string[]
    conversation_id?: string
  } & ChatScopeRequest, options?: { signal?: AbortSignal }) => {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    return fetch('/api/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify(data),
      signal: options?.signal,
    })
  },
  
  getConversations: () => api.get('/chat/conversations'),
  
  getMessages: (conversationId: string) =>
    api.get(`/chat/conversations/${conversationId}/messages`),

  uploadAttachment: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/chat/attachments', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  deleteAttachment: (attachmentId: string) =>
    api.delete(`/chat/attachments/${attachmentId}`),

  fetchAttachmentBlob: (attachmentId: string) =>
    api.get(`/chat/attachments/${attachmentId}/content`, {
      responseType: 'blob',
    }),
}

// Auth API
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }),
  
  register: (username: string, email: string, password: string) =>
    api.post('/auth/register', { username, email, password }),
  
  logout: () => api.post('/auth/logout'),
  
  getMe: () => api.get('/auth/me'),
  
  verifyToken: () => api.get('/auth/verify'),
}

export const settingsApi = {
  getPageIndexSettings: () => api.get('/settings/pageindex'),
  updatePageIndexSettings: (pageindex_mode: 'smart' | 'balanced' | 'fast') =>
    api.put('/settings/pageindex', { pageindex_mode }),
  getWebSearchSettings: () => api.get('/settings/web-search'),
  updateWebSearchSettings: (payload: WebSearchSettingsUpdate) =>
    api.put('/settings/web-search', payload),
  getModelProviderPresets: () => api.get('/settings/model-providers/presets'),
  listModelProviders: () => api.get('/settings/model-providers'),
  saveModelProvider: (payload: ModelProviderInput) =>
    api.post('/settings/model-providers', payload),
  updateModelProvider: (providerId: string, payload: ModelProviderUpdateInput) =>
    api.patch(`/settings/model-providers/${providerId}`, payload),
  deleteModelProvider: (providerId: string) =>
    api.delete(`/settings/model-providers/${providerId}`),
  listModelProviderModels: (providerId: string) =>
    api.get(`/settings/model-providers/${providerId}/models`),
  testModelProvider: (providerId: string, model?: string) =>
    api.post(`/settings/model-providers/${providerId}/test`, model ? { model } : {}),
  listModelRoutes: () => api.get('/settings/model-routes'),
  saveModelRoutes: (routes: ModelRouteMapping[]) =>
    api.put('/settings/model-routes', { routes }),
  listOcrEngines: () => api.get('/settings/ocr-engines'),
  saveOcrEngine: (payload: Record<string, any>) =>
    api.post('/settings/ocr-engines', payload),
  updateOcrEngine: (profileId: string, payload: Record<string, any>) =>
    api.patch(`/settings/ocr-engines/${profileId}`, payload),
  listOcrRoutes: () => api.get('/settings/ocr-routes'),
  saveOcrRoutes: (routes: Record<string, string | null>) =>
    api.put('/settings/ocr-routes', { routes }),
}

export default api
