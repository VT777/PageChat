import { describe, expect, it } from 'vitest'
import {
  DEMO_LIBRARY_DOCUMENTS,
  DEMO_LIBRARY_FOLDERS,
  buildLibrarySelectionSummary,
  demoBreadcrumbForFolder,
  demoDocumentsForFolder,
  demoFoldersForParent,
  shouldShowDemoLibrary,
} from './demoLibrary'

describe('PageChat demo library', () => {
  it('provides a root demo folder and documents inside that folder', () => {
    const [folder] = DEMO_LIBRARY_FOLDERS

    expect(demoFoldersForParent(null)).toEqual(DEMO_LIBRARY_FOLDERS)
    expect(demoFoldersForParent(folder.id)).toEqual([])
    expect(demoDocumentsForFolder(null)).toEqual([])
    expect(demoDocumentsForFolder(folder.id)).toEqual(DEMO_LIBRARY_DOCUMENTS)
    expect(DEMO_LIBRARY_DOCUMENTS.every((document) => document.folder_id === folder.id)).toBe(true)
  })

  it('uses stable breadcrumbs for the demo folder route', () => {
    const [folder] = DEMO_LIBRARY_FOLDERS

    expect(demoBreadcrumbForFolder(null)).toEqual([{ id: null, label: 'root', isRoot: true }])
    expect(demoBreadcrumbForFolder(folder.id)).toEqual([
      { id: null, label: 'root', isRoot: true },
      { id: folder.id, label: folder.name, isRoot: false },
    ])
  })

  it('shows demo content only when the real library is empty and unfiltered', () => {
    expect(shouldShowDemoLibrary({
      loading: false,
      folderCount: 0,
      documentCount: 0,
      searchQuery: '',
    })).toBe(true)
    expect(shouldShowDemoLibrary({
      loading: false,
      folderCount: 1,
      documentCount: 0,
      searchQuery: '',
    })).toBe(false)
    expect(shouldShowDemoLibrary({
      loading: false,
      folderCount: 0,
      documentCount: 0,
      searchQuery: 'sales',
    })).toBe(false)
  })

  it('summarizes mixed folder and document selections', () => {
    expect(buildLibrarySelectionSummary({ documentCount: 1, folderCount: 0 })).toBe('已选择 1 个文件')
    expect(buildLibrarySelectionSummary({ documentCount: 0, folderCount: 1 })).toBe('已选择 1 个文件夹')
    expect(buildLibrarySelectionSummary({ documentCount: 2, folderCount: 1 })).toBe('已选择 2 个文件、1 个文件夹')
  })
})
