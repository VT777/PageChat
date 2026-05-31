# 技术方案设计：章节划分修复 + LLM 质检

## 一、章节划分问题：方案对比与选择

### 当前问题

**技术应用洞察**:
- Dividers: [5, 13, 25, 38] (4 个章节边界)
- TOC items: 8 个 (4 个主章节 + 4 个子章节)
- 现有代码把阿拉伯数字 (2,4,6,8) 也当作 top-level → 8 个 items 竞争 4 个 dividers
- 结果：后 4 个 items 走 uniform distribution → 所有 span 4-5 页 → 躲过大节点检测

### 方案对比

#### 方案 A：Structure 模式识别（纯规则）

**思路**：
```python
def _identify_chapter_levels(toc_items):
    # 分析 structure 字段的模式
    patterns = {
        'chinese': ['一', '二', '三', '四', '五', ...],  # 主章节
        'arabic': ['1', '2', '3', '4', ...],  # 可能是主章节或子章节
        'roman': ['I', 'II', 'III', ...],
    }
    
    # 检测交替模式：中文数字 → 阿拉伯数字 → 中文数字 → 阿拉伯数字
    if is_alternating_chinese_arabic(toc_items):
        # 中文数字是主章节，阿拉伯数字是子章节
        chapters = [item for item in toc_items if is_chinese_number(item['structure'])]
        subsections = [item for item in toc_items if is_arabic_number(item['structure'])]
        return chapters, subsections
```

**优点**：
- 零额外成本（无需 VLM）
- 对结构清晰的文档效果很好

**缺点**：
- 如果所有章节都用阿拉伯数字（1, 2, 3, 4），无法区分主/子章节
- 如果 structure 字段为空，完全失效
- 需要维护多种编号规则（中文、阿拉伯、罗马、英文等）

#### 方案 B：全页扫描（VLM）

**思路**：
```python
# 触发条件：dividers 数量和 items 数量不匹配
if len(dividers) != len(top_items):
    page_titles = await _vlm_scan_document_pages(file_path, page_count)
    # 匹配 TOC 标题和页面标题，确定真正的章节边界
```

**优点**：
- 最准确，能处理任意格式
- 能识别页面上的实际标题层级

**缺点**：
- 成本高（VLM 调用，~2 分钟/文档）
- 对简单问题"杀鸡用牛刀"

#### 方案 C：基于位置的分组（回退策略）

**思路**：
```python
# 强制分组：用 dividers 作为边界
# dividers [5, 13, 25, 38] → 4 个区间
# 8 个 items → 每个区间分配 2 个 items
# 第一个 items 为章节，其余为子章节
```

**优点**：
- 简单，无需额外信息
- 保底策略

**缺点**：
- 如果某个章节没有子章节，会强行制造子章节
- 如果某个章节有很多子章节，会丢失

#### 方案 D：混合策略（推荐）

**三层架构**：

```
第一层：Structure 智能识别（低成本，覆盖 80% 场景）
    ↓ 如果 structure 不可靠或 dividers 不匹配
第二层：标题内容分析（中成本，覆盖 15% 场景）
    ↓ 如果仍然无法匹配
第三层：全页扫描（高成本，覆盖 5% 场景）
    ↓ 如果 VLM 不可用
第四层：强制位置分组（保底策略）
```

**详细设计**：

**第一层：Structure 模式识别**
```python
def _smart_identify_chapters(toc_items, dividers):
    """
    智能识别主章节和子章节
    返回: (chapters, subsections_map)
    """
    # 1. 检查是否有明确的层级标记（如 1, 1.1, 2, 2.1）
    has_dot_notation = any('.' in str(it.get('structure', '')) for it in toc_items)
    if has_dot_notation:
        chapters = [it for it in toc_items if '.' not in str(it.get('structure', ''))]
        subsections = [it for it in toc_items if '.' in str(it.get('structure', ''))]
        return chapters, subsections
    
    # 2. 检查交替模式（中文数字 + 阿拉伯数字）
    structures = [str(it.get('structure', '')) for it in toc_items]
    if is_alternating_pattern(structures):
        # 假设奇数位置是主章节，偶数位置是子章节
        # 或者基于编号类型判断
        chapters = []
        subsections = []
        for i, (item, struct) in enumerate(zip(toc_items, structures)):
            if is_chinese_number(struct) or is_roman_number(struct):
                chapters.append(item)
            else:
                subsections.append(item)
        return chapters, subsections
    
    # 3. 基于标题长度/内容判断
    # 主章节通常更短、更概括
    # 子章节通常更长、更具体
    avg_len = sum(len(it.get('title', '')) for it in toc_items) / len(toc_items)
    chapters = [it for it in toc_items if len(it.get('title', '')) <= avg_len * 0.8]
    subsections = [it for it in toc_items if len(it.get('title', '')) > avg_len * 0.8]
    
    if len(chapters) == len(dividers):
        return chapters, subsections
    
    # 4. 无法识别，返回 None 触发下一层
    return None, None
```

**第二层：标题内容分析（启发式规则）**
```python
def _analyze_title_patterns(toc_items, dividers):
    """
    基于标题内容判断层级
    """
    # 规则 1：包含"章"、"部分"、"Part" 的是主章节
    chapter_keywords = ['章', '部分', 'part', 'chapter', 'section']
    
    chapters = []
    subsections = []
    
    for item in toc_items:
        title = item.get('title', '').lower()
        if any(kw in title for kw in chapter_keywords):
            chapters.append(item)
        else:
            subsections.append(item)
    
    if len(chapters) == len(dividers):
        return chapters, subsections
    
    return None, None
```

**第三层：全页扫描（VLM）**
```python
async def _vlm_resolve_chapter_boundaries(file_path, toc_items, dividers, page_count, model):
    """
    用 VLM 扫描文档，确定章节边界
    """
    # 扫描每页标题
    page_titles = await _vlm_scan_document_pages(file_path, page_count, model)
    
    # 匹配 TOC 标题和页面标题
    chapter_boundaries = []
    for item in toc_items:
        title = item.get('title', '')
        # 在 page_titles 中查找匹配
        for pt in page_titles:
            if pt.get('type') == 'chapter' and is_title_match(title, pt['title']):
                chapter_boundaries.append({
                    'item': item,
                    'page': pt['physical_index']
                })
                break
    
    # 验证 dividers 和匹配结果是否一致
    if len(chapter_boundaries) == len(dividers):
        return chapter_boundaries
    
    return None
```

**第四层：强制位置分组（保底）**
```python
def _force_group_by_position(toc_items, dividers, page_count):
    """
    用 dividers 强制分组
    """
    n_groups = len(dividers)
    n_items = len(toc_items)
    
    # 计算每个区间应该分配多少 items
    items_per_group = n_items // n_groups
    remainder = n_items % n_groups
    
    groups = []
    idx = 0
    for i in range(n_groups):
        count = items_per_group + (1 if i < remainder else 0)
        group_items = toc_items[idx:idx + count]
        groups.append({
            'divider': dividers[i],
            'items': group_items,
            'start_page': dividers[i],
            'end_page': dividers[i + 1] - 1 if i + 1 < n_groups else page_count
        })
        idx += count
    
    return groups
```

### 最终选择：混合方案 D

**理由**：
1. **分层处理**：先用低成本方法（规则），再用高成本方法（VLM）
2. **渐进式降级**：每层失败自动进入下一层
3. **可扩展性**：可以不断添加新的识别规则
4. **保底机制**：无论如何都能给出结果

**触发条件**：
- 当 `len(dividers) != len(top_items)` 时触发
- 或者当 `len(toc_items) > len(dividers) * 2` 时（明显有子章节）

---

## 二、LLM 质检设计

### 问题
现有质检 `check_completeness` 只检查页面覆盖率，不检查：
- 章节划分是否合理
- 是否存在大节点未拆分
- 结构是否过于扁平
- 是否有遗漏章节

### 方案：LLM 最终质检

**位置**：在 `post_process_toc` 之后，返回结果之前

**输入**：
```json
{
  "document_info": {
    "page_count": 43,
    "title": "2025全球人工智能技术应用洞察报告",
    "has_dividers": true,
    "divider_count": 4
  },
  "toc_tree": [
    {
      "title": "第一章",
      "start_index": 5,
      "end_index": 12,
      "nodes": [...]
    }
  ],
  "toc_items_flat": [
    {"structure": "一", "title": "全球人工智能技术概览", "physical_index": 5},
    {"structure": "2", "title": "全球人工智能技术应用全景图谱", "physical_index": 11}
  ],
  "route_info": {
    "execution_mode": "balanced",
    "balanced_path": "visual",
    "has_code_toc": true,
    "code_toc_source": "bookmarks"
  }
}
```

**Prompt 设计**：

```
你是文档结构分析专家。请评估以下文档目录（TOC）的质量。

文档信息：
- 总页数: {page_count}
- 目录来源: {source} (bookmarks/regex/vlm)
- 是否有章节分隔页: {has_dividers}

目录结构：
{toc_tree_formatted}

原始目录条目：
{toc_items_formatted}

请从以下维度评估并返回 JSON：

1. 结构合理性 (structure_score: 0-100)
   - 章节数量是否和文档长度匹配（43 页文档通常 3-6 章）
   - 是否存在过于扁平的结构（如 9 个顶级节点）
   - 层级是否清晰

2. 大节点检测 (large_nodes: list)
   - 检查 span > 8 页的节点是否有子节点
   - 如果没有，标记为 "missing_children"

3. 遗漏检测 (missing_chapters: list)
   - 检查是否有 dividers 但未在 TOC 中体现
   - 检查页码是否连续

4. 整体评分 (overall_score: 0-100)
   - 综合以上维度

5. 修复建议 (suggestions: list)
   - 如果发现问题，给出具体建议
   - 例如："第 3 章 span=15 页但没有子节点，建议拆分"

返回格式：
{
  "structure_score": 85,
  "large_nodes": [
    {"title": "AI十大行业应用洞察", "span": 12, "issue": "missing_children"}
  ],
  "missing_chapters": [],
  "overall_score": 75,
  "suggestions": [
    "建议对 span > 8 页的章节进行子章节提取"
  ],
  "needs_repair": true
}
```

**处理逻辑**：

```python
async def llm_quality_check(toc_tree, toc_items, page_count, route_info, model="qwen3.6-flash"):
    """
    LLM 最终质检
    """
    prompt = build_quality_check_prompt(toc_tree, toc_items, page_count, route_info)
    
    try:
        response = await call_llm(prompt, model)
        result = parse_json(response)
        
        if result.get("needs_repair"):
            # 根据建议修复
            for suggestion in result.get("suggestions", []):
                if "子章节" in suggestion:
                    # 触发子章节提取
                    await extract_sub_chapters(toc_tree, suggestion)
                elif "遗漏" in suggestion:
                    # 触发补充提取
                    await supplement_missing_chapters(toc_tree, suggestion)
        
        return result
    except Exception as e:
        # LLM 失败，返回基础质检结果
        return {"overall_score": 50, "needs_repair": False, "error": str(e)}
```

**成本优化**：
1. **分层质检**：先运行规则质检（低成本），只有通过规则质检的才运行 LLM 质检
2. **采样**：对于大文档，只质检 top-level 节点
3. **缓存**：相同结构的文档复用质检结果

---

## 三、实施计划

### Phase 1: 立即修复（P0）
1. 修复 `_assign_divider_positions` → 使用混合方案第一层
2. 前端状态判断修复（`startsWith('failed')`）
3. 前端 polling 修复（加入 `pending` 状态）

### Phase 2: 结构修复（P1）
1. 实现 `_smart_identify_chapters` 函数
2. 实现 `_analyze_title_patterns` 函数
3. 实现 `_force_group_by_position` 保底策略
4. 在 `_branch_a_toc_page` 中集成

### Phase 3: LLM 质检（P2）
1. 设计质检 prompt
2. 实现 `llm_quality_check` 函数
3. 在 `post_process_toc` 后调用
4. 根据质检结果触发修复

### Phase 4: 测试（P3）
1. 对所有 5 个测试文件重新运行
2. 验证章节划分正确性
3. 验证大节点检测触发
4. 验证 LLM 质检效果
