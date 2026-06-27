import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('ChatComposer document picker contract', () => {
  it('loads selectable files from the full library or selected folder', () => {
    const source = readFileSync(new URL('./ChatComposer.vue', import.meta.url), 'utf8')

    expect(source).toContain('documentApi.list')
    expect(source).toContain('include_subfolders: true')
    expect(source).toContain('selectedFolderIds.value[0]')
    expect(source).not.toContain('documentStore.fetchDocuments(1, undefined, null, false, 20)')
  })
})
