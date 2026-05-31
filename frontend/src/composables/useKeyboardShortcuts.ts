import { onMounted, onUnmounted } from 'vue'

export interface ShortcutConfig {
  key: string
  ctrl?: boolean
  shift?: boolean
  alt?: boolean
  meta?: boolean
  handler: () => void
  description: string
}

export function useKeyboardShortcuts(shortcuts: ShortcutConfig[]) {
  const handleKeydown = (e: KeyboardEvent) => {
    for (const shortcut of shortcuts) {
      const keyMatch = e.key.toLowerCase() === shortcut.key.toLowerCase()
      const ctrlMatch = shortcut.ctrl ? e.ctrlKey || e.metaKey : true
      const shiftMatch = shortcut.shift ? e.shiftKey : true
      const altMatch = shortcut.alt ? e.altKey : true
      
      if (keyMatch && ctrlMatch && shiftMatch && altMatch) {
        e.preventDefault()
        shortcut.handler()
        return
      }
    }
  }
  
  onMounted(() => {
    document.addEventListener('keydown', handleKeydown)
  })
  
  onUnmounted(() => {
    document.removeEventListener('keydown', handleKeydown)
  })
}

// 预定义的常用快捷键
export const commonShortcuts = {
  newChat: (handler: () => void): ShortcutConfig => ({
    key: 'n',
    ctrl: true,
    handler,
    description: '新建对话 (Ctrl+N)'
  }),
  
  sendMessage: (handler: () => void): ShortcutConfig => ({
    key: 'Enter',
    ctrl: true,
    handler,
    description: '发送消息 (Ctrl+Enter)'
  }),
  
  search: (handler: () => void): ShortcutConfig => ({
    key: 'k',
    ctrl: true,
    handler,
    description: '快速搜索 (Ctrl+K)'
  }),
  
  closeModal: (handler: () => void): ShortcutConfig => ({
    key: 'Escape',
    handler,
    description: '关闭弹窗 (Esc)'
  }),
  
  showHelp: (handler: () => void): ShortcutConfig => ({
    key: '/',
    ctrl: true,
    handler,
    description: '显示快捷键帮助 (Ctrl+/)'
  })
}
