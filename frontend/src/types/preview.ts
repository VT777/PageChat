/**
 * 通用文档预览类型定义
 */

// 内容块类型
export interface ContentBlock {
  id: string
  type: 'text' | 'heading' | 'paragraph' | 'table_row' | 'sheet' | 'slide' | 'image'
  content: any
  metadata: Record<string, any>
  source_anchor?: SourceAnchor
}

// 文档内容响应
export interface DocumentContent {
  format: 'txt' | 'markdown' | 'csv' | 'tsv' | 'xlsx' | 'docx' | 'pptx' | 'pdf'
  blocks: ContentBlock[]
  images?: DocxImage[]  // DOCX 专用
  toc?: TocItem[]
  metadata: DocumentMetadata
  document: DocumentInfo
}

export interface TocItem {
  node_id: string
  title: string
  level: number
  summary?: string
  start_page?: number | null
  end_page?: number | null
  source_anchor?: Record<string, any>
  children?: TocItem[]
}

// DOCX 图片
export interface DocxImage {
  id: string
  data: string  // base64 data URL
  name: string
}

// 文档元信息
export interface DocumentMetadata {
  // TXT / Markdown
  total_lines?: number
  char_count?: number
  section_count?: number
  
  // CSV / TSV
  total_rows?: number
  total_cols?: number
  headers?: string[]
  delimiter?: string
  
  // XLSX
  sheet_count?: number
  sheets?: string[]
  
  // DOCX
  paragraph_count?: number
  image_count?: number
  
  // PPTX
  slide_count?: number
}

// 文档基本信息
export interface DocumentInfo {
  id: string
  name: string
  file_type: string
  file_size: number
}

// 表格单元格
export interface TableCell {
  col: string
  value: string
}

// 表格行
export interface TableRow {
  row_number: number
  cells: TableCell[]
}

// XLSX 工作表
export interface ExcelSheet {
  name: string
  rows: TableRow[]
  row_count: number
  col_count: number
}

// PPTX 幻灯片
export interface Slide {
  slide_number: number
  title: string
  text: string
  text_count: number
}

// 引用位置信息
export interface SourceAnchor {
  format: string
  unit_type?: string
  // PDF
  start_page?: number
  end_page?: number
  // TXT
  start_line?: number
  end_line?: number
  // CSV / TSV
  start_row?: number
  end_row?: number
  // XLSX
  sheet?: string
  // DOCX
  start_paragraph?: number
  end_paragraph?: number
  // PPTX
  slide?: number
  start_slide?: number
  end_slide?: number
}

// 预览器公共 Props
export interface BaseViewerProps {
  content: DocumentContent
  initialAnchor?: SourceAnchor | null
  onAnchorClick?: (anchor: SourceAnchor) => void
}
