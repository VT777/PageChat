# 多格式文档预览功能实现总结

## 实现内容

### 1. 后端实现

#### 新增文件
- `backend/app/services/content_extraction_service.py` - 多格式内容提取服务
- 支持格式：TXT, Markdown, CSV, TSV, XLSX, DOCX, PPTX

#### 修改文件
- `backend/app/api/documents.py` - 新增 `/api/documents/{id}/content` 接口

### 2. 前端实现

#### 新增文件
- `frontend/src/types/preview.ts` - 预览相关类型定义
- `frontend/src/components/preview/TextViewer.vue` - TXT 文本预览
- `frontend/src/components/preview/MarkdownViewer.vue` - Markdown 预览
- `frontend/src/components/preview/TableViewer.vue` - CSV/TSV/XLSX 表格预览
- `frontend/src/components/preview/DocxViewer.vue` - DOCX 文档预览
- `frontend/src/components/preview/PptxViewer.vue` - PPTX 幻灯片预览
- `frontend/src/components/preview/UniversalPreview.vue` - 通用预览容器

#### 修改文件
- `frontend/src/api/index.ts` - 添加 `getContent` API 方法
- `frontend/src/views/ChatView.vue` - 扩展引用解析支持多格式
- `frontend/src/views/DocumentView.vue` - 集成多格式预览组件

## 支持的引用格式

### 标准格式
```
[[文档.txt line.100]]          # TXT 行号
[[文档.md section.3]]          # Markdown 章节
[[数据.csv row.50]]            # CSV 行号
[[报表.xlsx sheet1.A5]]        # Excel 单元格
[[合同.docx para.15]]          # Word 段落
[[演示.pptx slide.3]]          # PPT 幻灯片
```

### 向后兼容
```
[[文档.pdf p.3]]               # PDF 页码（原有格式）
```

## 功能特性

### TXT 预览
- 行号显示
- 点击行跳转
- 高亮当前行

### Markdown 预览
- HTML 渲染
- 目录导航
- 章节跳转

### CSV/TSV/XLSX 预览
- 表格渲染
- 工作表切换（Excel）
- 搜索过滤
- 行号显示

### DOCX 预览
- 段落列表
- 图片显示
- 段落跳转

### PPTX 预览
- 单页/缩略图视图
- 幻灯片导航
- 键盘快捷键支持

## 使用方式

### 文档管理中预览
1. 在文档列表中点击预览按钮
2. 支持的格式将显示完整内容预览
3. PDF 使用原有 PDF 预览器
4. 其他格式使用新的通用预览组件

### 聊天中引用跳转
1. 点击 AI 回复中的引用链接
2. 右侧预览面板自动加载对应文档
3. 自动跳转到引用位置

## 技术细节

### 后端 API
```
GET /api/documents/{id}/content
```

返回格式：
```json
{
  "format": "txt",
  "blocks": [...],
  "metadata": {...},
  "document": {...}
}
```

### 组件架构
```
UniversalPreview (容器)
  ├── TextViewer (TXT)
  ├── MarkdownViewer (Markdown)
  ├── TableViewer (CSV/TSV/XLSX)
  ├── DocxViewer (DOCX)
  └── PptxViewer (PPTX)
```

## 注意事项

1. **DOCX 图片**：当前版本提取所有图片作为侧边栏显示，段落内图片位置信息需要进一步解析
2. **XLSX 单元格引用**：格式 `sheet1.A5` 需要在前端进一步解析实现
3. **大文件性能**：建议使用分页或虚拟滚动优化大文件预览体验

## 后续优化建议

1. 添加文档内容缓存，避免重复加载
2. 实现虚拟滚动优化大文件性能
3. 支持文档内搜索功能
4. 优化 DOCX 图片在段落内的定位显示
