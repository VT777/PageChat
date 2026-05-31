# Systematic Debugging Report - Phase 4

## 问题汇总与根因分析

### 问题 1: AI Agent 2026 - 第二章融入第一章

**根因**: Fast 模式提取的 117 个 TOC items 中，部分条目的 `structure` 字段为空，导致 `post_process_toc` 的 `build_tree` 无法正确识别章节边界，将多个章节合并为 2 个 top-level nodes。

**证据**:
- 117 items, 8 top-level nodes (但 post-processing 后只剩 2 个)
- 存在空的 structure 字段
- Duplicate physical_index: [85]

**修复方案**:
1. 在 `try_fast_toc` 返回前，为没有 structure 的条目补充 structure（基于物理位置顺序推断）
2. 在 `post_process_toc` 的 `build_tree` 中，当 structure 为空时，使用 physical_index 的单调性来分割章节

---

### 问题 2: 第五范式 - 一级目录乱序、丢失

**根因**: 
1. Regex 提取的 code TOC 页码错误（提取了年份如 1945, 1956 而不是页码）
2. `verify_content_match` 在页码 1945 附近搜索标题，但文档只有 68 页，match_rate=8% < 20%，fast TOC 被拒绝
3. 降级到 balanced 后，divider 检测只找到 [1, 49, 61] 三个 dividers，将文档分成 3 大块，丢失了中间章节

**证据**:
- Code TOC: structure=1, title=ENIAC, physical_index=1945
- Fast TOC: match_rate=8%, rejecting
- Balanced result: 20 items, 2 top-level (post-processing 后 10 个)

**修复方案**:
1. 在 `extract_toc_from_regex` 或 `verify_content_match` 中，过滤明显不合理的页码（> page_count * 2 或 > 1000）
2. 改进 regex 模式，避免将年份识别为页码

---

### 问题 3: 为什么全是 balanced 模式

**根因**: Fast TOC 质量验证过于严格，多个文件因不同原因失败：

| 文件 | 失败原因 | 详细说明 |
|------|---------|---------|
| 第五范式 | match_rate=8% | Regex 提取的页码是年份（1945, 1956） |
| AI眼镜 | match_rate=0% | Regex 提取的部分页码错误（2800, 2700） |
| 技术应用洞察 | match_rate=0% | Bookmarks 标题和页面内容不匹配（PPT 转换的 PDF） |
| AI Agent | fast 成功 | 执行模式为 fast |

**修复方案**:
1. **Code TOC 过滤**: 在提取后过滤掉 `physical_index > page_count * 2` 或 `physical_index > 1000` 的条目
2. **放宽验证阈值**: 将 `match_rate < 20%` 改为 `match_rate < 10%`（或更智能的判断）
3. **Bookmarks 特殊处理**: 对于 bookmarks 来源的 TOC，如果 `match_rate < 20%` 但 `physical_index` 都在范围内，可以接受（因为 PPT 转换的 PDF 书签标题和页面内容可能不同）

---

### 问题 4: 技术应用洞察 - TOC 太简单

**根因**: Balanced visual 模式只提取了 8 个主要章节，遗漏了所有子章节。目录页可能包含更多层级但 VLM 没有识别。

**证据**:
- 8 items only (for 43-page report)
- 执行模式：balanced (因为 fast 失败)
- "No logical pages found, using uniform distribution"

**修复方案**:
1. 增强 VLM TOC 提取 prompt，明确要求提取所有层级包括子章节
2. 或者在 balanced visual 路径后，对大节点进行子章节发现（类似 AI 治理报告的处理）

---

### 问题 5: 上传后直接显示已完成

**根因**: 
1. 后端 `save_document` 插入 status='pending'
2. 前端 `uploadDocument` 只检查 `data.status.startsWith('processing')`，但初始状态是 'pending'，不加入 polling
3. 如果后台处理很快完成，用户刷新页面后看到 completed；如果还没完成，显示为"已完成"（因为前端状态显示逻辑将非 processing、非 failed 的状态都显示为"已完成"）

**证据**:
- 后端: `INSERT ... status='pending'`
- 前端: `if (data.status.startsWith('processing')) { processingDocIds.value.add(data.id) }`
- DocumentCard.vue: `if (isProcessing) ... else ... return { label: '已完成' }`

**修复方案**:
1. 前端 `uploadDocument` 将 'pending' 状态也加入 polling:
   ```javascript
   if (data.status && (data.status.startsWith('processing') || data.status === 'pending')) {
     processingDocIds.value.add(data.id)
     ensurePolling()
   }
   ```
2. 或者修改状态显示逻辑，将 'pending' 显示为"等待处理"

---

### 问题 6: AI 治理报告 - 显示已完成但没有预览按钮

**根因**: 
1. 实际状态: `failed:fast_toc_incomplete`
2. 前端 `isFailed = computed(() => props.document.status === 'failed')` 只匹配精确字符串 'failed'
3. `failed:fast_toc_incomplete` 不匹配，所以显示为"已完成"
4. 但 `isCompleted = computed(() => props.document.status === 'completed')` 也不匹配
5. 所以预览按钮不显示

**证据**:
- 数据库: status='failed:fast_toc_incomplete'
- DocumentCard.vue: `const isFailed = computed(() => props.document.status === 'failed')`
- DocumentCard.vue: `const isCompleted = computed(() => props.document.status === 'completed')`

**修复方案**:
1. 前端状态判断改为前缀匹配:
   ```javascript
   const isFailed = computed(() => props.document.status.startsWith('failed'))
   const isCompleted = computed(() => props.document.status === 'completed')
   ```
2. 同时需要确保后端在 fast 失败时正确降级到 balanced（而不是直接标记为 failed）

---

## 实施优先级

### P0 (紧急)
- **问题 6**: 修复前端状态判断逻辑（1 行代码）
- **问题 5**: 修复前端 polling 逻辑（2 行代码）

### P1 (高优先级)
- **问题 3**: 修复 Code TOC 过滤和 fast TOC 验证阈值
- **问题 2**: 改进 regex 页码提取，过滤不合理页码

### P2 (中优先级)
- **问题 1**: 修复空 structure 的 TOC items
- **问题 4**: 增强 VLM TOC 提取的层级识别

### P3 (长期优化)
- 建立完整的 TOC 质量评估体系
- 为不同来源的 code TOC（bookmarks, regex, links）设置不同的验证策略
