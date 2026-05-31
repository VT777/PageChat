import request from './request'

export interface Folder {
  id: string
  name: string
  parent_id: string | null
  path: string
  created_at: string
  updated_at: string
}

export interface FolderTreeItem extends Folder {
  children: FolderTreeItem[]
}

export interface FolderContents {
  items: (Folder | DocumentItem)[]
  total: number
  page: number
  page_size: number
}

export interface DocumentItem {
  type: 'document'
  id: string
  name: string
  original_name: string
  file_size: number
  file_type: string
  status: string
  page_count?: number
  processed_pages?: number
  created_at: string
  updated_at: string
}

export const folderApi = {
  // 创建文件夹
  create(data: { name: string; parent_id?: string | null }) {
    return request.post('/folders', data)
  },

  // 获取文件夹树
  getTree() {
    return request.get<FolderTreeItem[]>('/folders/tree')
  },

  // 列出文件夹（平级）
  list(parent_id?: string | null) {
    return request.get<{ items: Folder[]; total: number }>('/folders', {
      params: { parent_id }
    })
  },

  // 获取文件夹内容
  getContents(folder_id: string, page = 1, page_size = 20) {
    return request.get<FolderContents>(`/folders/${folder_id}/contents`, {
      params: { page, page_size }
    })
  },

  // 重命名
  rename(id: string, name: string) {
    return request.put(`/folders/${id}`, { name })
  },

  // 移动
  move(id: string, parent_id?: string | null) {
    return request.put(`/folders/${id}/move`, null, {
      params: { parent_id }
    })
  },

  // 删除
  delete(id: string) {
    return request.delete(`/folders/${id}`)
  }
}
