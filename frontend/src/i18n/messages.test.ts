import { describe, expect, it, beforeEach, vi } from 'vitest'
import { resetI18nForTests, setLanguage, t } from './messages'

describe('PageChat i18n messages', () => {
  beforeEach(() => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) || null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    })
    localStorage.clear()
    resetI18nForTests()
  })

  it('translates core shell and composer labels between Chinese and English', () => {
    expect(t('nav.newChat')).toBe('New Chat')
    expect(t('settings.title')).toBe('Settings')
    expect(t('composer.library')).toBe('Select files/folders')

    setLanguage('zh-CN')

    expect(t('nav.newChat')).toBe('新对话')
    expect(t('settings.title')).toBe('设置')
    expect(t('composer.library')).toBe('选择文件/文件夹')
  })

  it('persists the selected interface language', () => {
    setLanguage('zh-CN')

    expect(localStorage.getItem('pagechat_interface_language')).toBe('zh-CN')
  })

  it('falls back to the message key for unknown labels', () => {
    expect(t('unknown.key')).toBe('unknown.key')
  })
})
