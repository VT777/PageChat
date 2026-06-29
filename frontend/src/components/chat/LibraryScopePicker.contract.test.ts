import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

describe('LibraryScopePicker contract', () => {
  it('renders a navigable mixed document and folder picker', () => {
    const source = readFileSync(new URL('./LibraryScopePicker.vue', import.meta.url), 'utf-8')

    expect(source).toContain('folderApi.list')
    expect(source).toContain('documentApi.list')
    expect(source).toContain('currentFolderId')
    expect(source).toContain('breadcrumbItems')
    expect(source).toContain('filteredFolders')
    expect(source).toContain('filteredDocuments')
    expect(source).toContain("emit('toggle-document'")
    expect(source).toContain("emit('toggle-folder'")
    expect(source).toContain('include_subfolders: false')
  })
})
