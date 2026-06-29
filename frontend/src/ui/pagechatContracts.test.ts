import { describe, expect, it } from 'vitest'
import {
  APP_NAV_ITEMS,
  COMPOSER_ACTIONS,
  DOCUMENT_FILE_PRESENTATIONS,
  PARSING_BATCH_CONCURRENCY_SETTING,
  PARSE_MODE_OPTIONS,
  PRODUCT_NAME,
  SETTINGS_NAV_SECTIONS,
  WEB_SEARCH_MODE_OPTIONS,
  WEB_SEARCH_PROVIDER_OPTIONS,
  buildConversationExportMarkdown,
  buildDocumentBreadcrumb,
  buildDocumentChatRoute,
  buildDocumentSelectionSummary,
  documentOnlyChatContexts,
  buildFolderChatRoute,
  documentPresentationForType,
  documentSelectionActionIds,
  hasSelectableLibraryItems,
  parseDocumentChatRouteQuery,
  parseFolderChatRouteContexts,
  parseFolderChatRouteQuery,
  resolveDocumentChatContext,
  selectableDocumentIds,
  summarizeToolStep,
} from './pagechatContracts'
import { defaultWebSearchSettings } from '@/types/webSearchSettings'

describe('PageChat UI contracts', () => {
  it('uses PageChat as the only product name for the authenticated shell', () => {
    expect(PRODUCT_NAME).toBe('PageChat')
  })

  it('keeps the global navigation compact and product-specific', () => {
    expect(APP_NAV_ITEMS.map((item) => item.id)).toEqual(['new-chat', 'documents'])
    expect(APP_NAV_ITEMS.map((item) => item.label)).toEqual(['New Chat', 'Documents'])
    expect(APP_NAV_ITEMS.every((item) => item.icon.length > 0)).toBe(true)
  })

  it('keeps settings sections aligned with the approved PageChat configuration model', () => {
    expect(SETTINGS_NAV_SECTIONS.primary.map((item) => item.id)).toEqual([
      'providers',
      'ocr',
      'parsing',
      'qa',
    ])
    expect(SETTINGS_NAV_SECTIONS.primary.map((item) => item.label)).toEqual([
      '模型供应商',
      'OCR 设置',
      '解析设置',
      '问答设置',
    ])
    expect(SETTINGS_NAV_SECTIONS.footer.map((item) => item.id)).toEqual(['language', 'account'])
  })

  it('orders parsing modes with smart first and uses Chinese labels', () => {
    expect(PARSE_MODE_OPTIONS.map((mode) => mode.id)).toEqual(['smart', 'balanced', 'fast'])
    expect(PARSE_MODE_OPTIONS[0].label).toBe('智能')
    expect(PARSE_MODE_OPTIONS[0].badge).toBe('推荐')
  })

  it('describes batch parsing concurrency as a bounded behavior setting', () => {
    expect(PARSING_BATCH_CONCURRENCY_SETTING).toMatchObject({
      id: 'batchParseConcurrency',
      label: '批量解析并发上限',
      min: 1,
      max: 12,
      defaultValue: 3,
    })
    expect(PARSING_BATCH_CONCURRENCY_SETTING.description).toContain('同时进入解析流程')
  })

  it('models web search as user-requested or automatic answering behavior', () => {
    expect(WEB_SEARCH_MODE_OPTIONS.map((mode) => mode.id)).toEqual(['on-demand', 'auto'])
    expect(WEB_SEARCH_MODE_OPTIONS.map((mode) => mode.label)).toEqual(['用户要求使用', '自动调用'])
    expect(WEB_SEARCH_PROVIDER_OPTIONS).toEqual([
      { id: 'anysearch', label: 'AnySearch' },
    ])
    expect(defaultWebSearchSettings()).toMatchObject({
      provider: 'anysearch',
      mode: 'on-demand',
      zone: 'cn',
      language: 'zh-CN',
      max_results: 5,
      content_types: ['web', 'news'],
    })
  })

  it('keeps composer actions behind the plus menu', () => {
    expect(COMPOSER_ACTIONS.map((action) => action.id)).toEqual([
      'image',
      'web-search',
      'library',
    ])
    expect(COMPOSER_ACTIONS.map((action) => action.label)).toEqual([
      '添加图片',
      '网页搜索',
      '选择文件/文件夹',
    ])
  })

  it('uses distinct document presentations for folders and common document formats', () => {
    expect(DOCUMENT_FILE_PRESENTATIONS.folder.icon).toBe('Folder')
    expect(documentPresentationForType('.pdf').icon).toBe('FileText')
    expect(documentPresentationForType('docx').icon).toBe('FileType')
    expect(documentPresentationForType('.xlsx').icon).toBe('FileSpreadsheet')
    expect(documentPresentationForType('pptx').icon).toBe('Presentation')
    expect(documentPresentationForType('.md').icon).toBe('FileCode')
    expect(documentPresentationForType('.png').icon).toBe('FileImage')
  })

  it('builds a stable breadcrumb that always starts with root', () => {
    expect(buildDocumentBreadcrumb([])).toEqual([{ id: null, label: 'root', isRoot: true }])
    expect(buildDocumentBreadcrumb([
      { id: 'folder-a', name: 'Research' },
      { id: 'folder-b', name: 'Q2' },
    ])).toEqual([
      { id: null, label: 'root', isRoot: true },
      { id: 'folder-a', label: 'Research', isRoot: false },
      { id: 'folder-b', label: 'Q2', isRoot: false },
    ])
  })

  it('keeps document selection as a default row behavior with focused bulk actions', () => {
    expect(documentSelectionActionIds()).toEqual(['chat', 'download', 'reindex', 'move', 'delete'])
    expect(documentSelectionActionIds() as string[]).not.toContain('batch')
    expect(buildDocumentSelectionSummary(1)).toBe('已选择 1 个文件')
    expect(buildDocumentSelectionSummary(3)).toBe('已选择 3 个文件')
  })

  it('selects only actionable documents from the current document list', () => {
    expect(selectableDocumentIds([
      { id: 'doc-a' },
      { id: 'demo-doc', selectable: false },
      { id: 'doc-b' },
    ])).toEqual(['doc-a', 'doc-b'])
  })

  it('enables bulk selection when the current list only contains folders', () => {
    expect(hasSelectableLibraryItems([], ['folder-a'])).toBe(true)
    expect(hasSelectableLibraryItems([], [])).toBe(false)
  })

  it('routes document row chat actions to chat with selected document context', () => {
    expect(buildDocumentChatRoute({
      id: 'doc-sales',
      name: 'sales_orders.xlsx',
      original_name: '区域销售表现样例.xlsx',
    })).toEqual({
      path: '/',
      query: {
        documentId: 'doc-sales',
        documentName: '区域销售表现样例.xlsx',
      },
    })
  })

  it('routes selected documents to chat with a strict multi-file context', () => {
    const route = buildDocumentChatRoute([
      { id: 'doc-a', original_name: 'sales-a.pdf' },
      { id: 'doc-b', name: 'sales-b.xlsx' },
    ])

    expect(route.path).toBe('/')
    expect(parseDocumentChatRouteQuery(route.query)).toEqual([
      { id: 'doc-a', label: 'sales-a.pdf' },
      { id: 'doc-b', label: 'sales-b.xlsx' },
    ])
  })

  it('routes selected folders to chat with a folder context', () => {
    const route = buildFolderChatRoute({
      id: 'folder-sales',
      name: '销售分析',
    })

    expect(route).toEqual({
      path: '/',
      query: {
        folderId: 'folder-sales',
        folderName: '销售分析',
      },
    })
    expect(parseFolderChatRouteQuery(route.query)).toEqual({
      id: 'folder-sales',
      label: '销售分析',
    })
  })

  it('routes multiple selected folders to chat with persistent folder contexts', () => {
    const route = buildFolderChatRoute([
      { id: 'folder-sales', name: '销售分析' },
      { id: 'folder-contracts', name: '合同归档' },
    ])

    expect(route.path).toBe('/')
    expect(parseFolderChatRouteContexts(route.query)).toEqual([
      { id: 'folder-sales', label: '销售分析' },
      { id: 'folder-contracts', label: '合同归档' },
    ])
  })

  it('preserves the stored document context label when resolving chat chips', () => {
    expect(resolveDocumentChatContext(
      'doc-cn',
      [{ id: 'doc-cn', label: '中文报告.pdf' }],
      [{ id: 'doc-cn', original_name: 'report.pdf', name: 'report.pdf' }],
    )).toEqual({ id: 'doc-cn', label: '中文报告.pdf' })
  })

  it('does not let folder contexts seed document chips', () => {
    expect(documentOnlyChatContexts([
      { id: 'doc-sales', label: 'sales_orders.xlsx' },
      { id: 'folder-sales', label: '销售分析', type: 'folder' },
    ])).toEqual([
      { id: 'doc-sales', label: 'sales_orders.xlsx' },
    ])
    expect(resolveDocumentChatContext(
      'folder-sales',
      [{ id: 'folder-sales', label: '销售分析', type: 'folder' }],
      [],
    )).toEqual({ id: 'folder-sales', label: 'folder-sales' })
  })

  it('summarizes tool calls as inline one-line workflow steps', () => {
    expect(summarizeToolStep({
      toolName: 'get_folder_tree',
      arguments: {},
      result: { folders: [{ id: 'root' }] },
      status: 'done',
    })).toEqual({
      action: 'Viewed folder structure',
      detail: '1 folder',
      icon: 'FolderTree',
      tone: 'success',
    })

    expect(summarizeToolStep({
      toolName: 'find_related_documents',
      arguments: { query: 'revenue' },
      result: { documents: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] },
      status: 'done',
    }).action).toBe('Browsed documents')

    expect(summarizeToolStep({
      toolName: 'get_document_image',
      arguments: { page: 4 },
      result: {},
      status: 'calling',
    })).toMatchObject({
      action: 'Viewing page image',
      icon: 'Image',
      tone: 'running',
    })
  })

  it('uses concrete official-style tool summaries without generic ran wording', () => {
    const summaries = [
      summarizeToolStep({
        toolName: 'list_folder_contents',
        arguments: { folder_name: 'root' },
        result: { folders: [{ id: 'sales' }], documents: [{ id: 'a' }, { id: 'b' }] },
        status: 'done',
      }),
      summarizeToolStep({
        toolName: 'aggregate_tables',
        arguments: { operation: 'sum', group_by: '地区' },
        result: { rows: [{ region: '华东' }, { region: '华南' }, { region: '西南' }] },
        status: 'done',
      }),
      summarizeToolStep({
        toolName: 'read_document_pages',
        arguments: {
          document_name: '2025年度销售复盘.pdf',
          start_page: 43,
          end_page: 44,
        },
        result: {},
        status: 'done',
      }),
      summarizeToolStep({
        toolName: 'get_document_toc',
        arguments: { document_name: '2025年度销售复盘.pdf' },
        result: { toc: [{ id: 'intro' }] },
        status: 'done',
      }),
      summarizeToolStep({
        toolName: 'web_search',
        arguments: { query: 'PageChat' },
        result: { results: [{ title: 'A' }, { title: 'B' }] },
        status: 'done',
      }),
      summarizeToolStep({
        toolName: 'search_within_document',
        arguments: { query: '收入', document_name: '重庆.pdf' },
        result: { matches: [{ page: 3 }, { page: 8 }] },
        status: 'done',
      }),
    ]

    expect(summaries[0]).toMatchObject({
      action: 'Viewed folder contents',
      detail: '1 folder, 2 documents',
      icon: 'FolderTree',
    })
    expect(summaries[1]).toMatchObject({
      action: 'Aggregated table data',
      detail: '3 rows',
      icon: 'FileSpreadsheet',
    })
    expect(summaries[2]).toMatchObject({
      action: 'Read pages 43-44',
      detail: '"2025年度销售复盘.pdf"',
      icon: 'BookOpen',
    })
    expect(summaries[3]).toMatchObject({
      action: 'Read the document structure',
      detail: '"2025年度销售复盘.pdf"',
      icon: 'ListTree',
    })
    expect(summaries[4]).toMatchObject({
      action: 'Searched the web',
      detail: '2 results',
      icon: 'Globe',
    })
    expect(summaries[5]).toMatchObject({
      action: 'Searched within document',
      detail: '"重庆.pdf"',
      icon: 'FileSearch',
    })
    expect(summaries.every((summary) => !summary.action.startsWith('Ran '))).toBe(true)
  })

  it('exports conversations as readable markdown with tool call summaries', () => {
    const markdown = buildConversationExportMarkdown({
      title: '销售分析',
      exportedAt: '2026-06-25T10:00:00+08:00',
      messages: [
        {
          role: 'user',
          content: '总结销售变化',
          toolSteps: [],
        },
        {
          role: 'assistant',
          content: '华东增长最快。',
          toolSteps: [
            {
              toolName: 'list_folder_contents',
              arguments: { folder_name: 'root' },
              result: { folders: [{ id: 'sales' }], documents: [{ id: 'a' }] },
              status: 'done',
            },
          ],
        },
      ],
    })

    expect(markdown).toContain('# 销售分析')
    expect(markdown).toContain('Exported: 2026-06-25T10:00:00+08:00')
    expect(markdown).toContain('## User')
    expect(markdown).toContain('总结销售变化')
    expect(markdown).toContain('## PageChat')
    expect(markdown).toContain('- Viewed folder contents: 1 folder, 1 document')
    expect(markdown).toContain('华东增长最快。')
  })
})
