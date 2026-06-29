import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

describe('ChatComposer contract', () => {
  it('exposes a request-level thinking toggle in the composer payload', () => {
    const source = readFileSync(new URL('./ChatComposer.vue', import.meta.url), 'utf-8')

    expect(source).toContain('thinkingEnabled: boolean')
    expect(source).toContain('pagechat_thinking_enabled')
    expect(source).toContain('thinkingEnabled.value')
    expect(source).toContain("'thinking-toggle'")
  })
  it('uses global i18n labels for composer chrome actions', () => {
    const source = readFileSync(new URL('./ChatComposer.vue', import.meta.url), 'utf-8')

    expect(source).toContain("import { useI18n }")
    expect(source).toContain('composerActionLabel(action.id)')
    expect(source).toContain("t('composer.placeholder')")
    expect(source).toContain("t('composer.thinking')")
    expect(source).not.toContain("action.id === 'library' ?")
  })

  it('opens one unified library picker for documents and folders', () => {
    const source = readFileSync(new URL('./ChatComposer.vue', import.meta.url), 'utf-8')

    expect(source).toContain("import LibraryScopePicker from './LibraryScopePicker.vue'")
    expect(source).toContain('LibraryScopePicker')
    expect(source).toContain('showLibraryPicker')
    expect(source).not.toContain("pickerMode = ref<'file' | 'folder'")
    expect(source).not.toContain("action.id === 'file' ? 'file' : 'folder'")
  })

})
