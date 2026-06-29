import { describe, expect, it } from 'vitest'
import { describeScopeTrace } from './retrievalScope'

describe('describeScopeTrace', () => {
  it('formats backend requested document scopes', () => {
    expect(describeScopeTrace({
      requested_document_ids: ['doc-a', 'doc-b'],
      strict_scope: true,
    })).toBe('Used 2 selected documents')
  })

  it('formats backend requested folder scopes', () => {
    expect(describeScopeTrace({
      requested_folder_id: 'folder-a',
      include_subfolders: true,
      strict_scope: true,
    })).toBe('Used selected folder and subfolders')
  })

  it('discloses expansion to all accessible documents', () => {
    expect(describeScopeTrace({
      requested_folder_id: 'folder-a',
      expanded_to_user_library: true,
    })).toBe('Expanded to all accessible documents')
  })
})
