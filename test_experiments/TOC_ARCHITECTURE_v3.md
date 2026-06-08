# PDF TOC提取架构设计文档 v3.0

## 一、目标与定位

### 1.1 目标
设计一个统一的PDF目录提取架构，支持文本型和图片型文档，最大化利用目录页信息，提高超长文档的处理质量。

### 1.2 核心原则
1. **目录信息不浪费**：无论是否有页码、是否能提取，目录内容始终保存并利用
2. **路径差异化**：文本型走文本处理路径，图片型走视觉处理路径
3. **多源验证**：结合目录页、正文搜索、分割页、内容提取多源信息
4. **渐进降级**：高质量路径优先，逐步降级到兜底方案

---

## 二、整体架构图

### 2.1 顶层架构

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ 输入: PDF文件路径                                                                │
│ 输出: TOC树结构 (嵌套dict/list)                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Phase 0: 预分析 (analyze_pdf_structure)                                          │
│ ────────────────────────────────────────────────────────────────                │
│ 输入: PDF文件                                                                    │
│ 处理:                                                                            │
│   1. PyMuPDF提取所有页面文本 → page_texts[]                                     │
│   2. 提取PDF书签/Outline → code_toc[]                                           │
│   3. 提取页面链接 → links[]                                                     │
│   4. 正则匹配目录页 → regex_matches[]                                           │
│   5. 统计image_coverage (图片占比)                                              │
│ 输出: analysis对象                                                               │
│   ├─ page_texts: [(text, font_info), ...]                                      │
│   ├─ code_toc: [{page, title, level}, ...] 或 []                               │
│   ├─ image_coverage: float (0.0~1.0)                                           │
│   ├─ is_image_only_pdf: bool                                                   │
│   └─ toc_page_candidates: [page_idx, ...] (可选)                               │
└─────────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
           ┌────────▼────────┐              ┌──────▼──────┐
           │  Fast路径        │              │ Balanced路径 │
           │ (code_toc优质)   │              │ (无/劣质TOC) │
           │                  │              │              │
           │ 条件:            │              │ 入口条件:    │
           │ code_toc存在     │              │ code_toc缺失 │
           │ 且条目数>3       │              │ 或质量评分   │
           │ 且层级深度>1     │              │ < 阈值       │
           └────────┬────────┘              └──────┬──────┘
                    │                               │
                    ▼                               ▼
```

### 2.2 Fast路径详细流程

```
Fast路径 (有code_toc)
│
├─ Step 1: 提取条目
│   输入: code_toc[]
│   处理: 解析书签结构 → {structure, title, page, level}
│   输出: toc_items[]
│
├─ Step 2: Offset校正
│   输入: toc_items[], page_texts[]
│   处理: 匹配toc_items中的page与page_texts的实际内容
│   输出: offset值 (通常为0或封面页数)
│
├─ Step 3: 应用Offset
│   处理: physical_index = page + offset
│   输出: 带physical_index的toc_items[]
│
├─ Step 4: 页码验证 (抽样)
│   输入: toc_items[], page_texts[]
│   处理: 随机抽3-5个条目，验证physical_index页是否包含title
│   输出: 准确率 (matched/total)
│
├─ Step 5: LLM质检 (TocQualityChecker)
│   输入: toc_items[] (前20个条目)
│   处理: LLM评估结构合理性、层级完整性
│   输出: quality_score (0~100)
│
├─ 决策点:
│   ├─ 准确率 ≥ 80% 且 quality_score ≥ 60  → 成功，进入Phase 2
│   ├─ 准确率 < 80% 或 quality_score < 60   → 失败，降级到Balanced路径
│   │                                         (保留code_toc信息作为参考)
│   └─ 失败时: analysis["code_toc_failed"] = True
│
└─ 成功输出: toc_items[] → Phase 2
```

### 2.3 Balanced路径详细流程

```
Balanced路径 (无code_toc或Fast路径失败)
│
├─ Step 1: 文档类型判定
│   条件: analysis["image_coverage"] >= 0.3 → 图片型
│         analysis["image_coverage"] < 0.3  → 文本型
│   输出: doc_type = "text" | "image"
│
├─ Step 2: 查找目录页 (TOC Page Detection)
│   │
│   ├─ [文本型] 文本特征检测 (前20页)
│   │   输入: page_texts[0:20]
│   │   评分: 标题关键词(+40) + 页码模式(+30) + 递增性(+20) + 章节编号(+10) - 噪音(-20)
│   │   连续: 目录页通常连续，score < 60 停止
│   │   输出: toc_pages[] 或 []
│   │
│   ├─ [文本型] 降级: VLM视觉检测 (文本检测失败时)
│   │   输入: 前20页大缩略图 (400x560, 8页/张)
│   │   处理: VLM识别目录页特征
│   │   输出: toc_pages[] 或 []
│   │
│   └─ [图片型] VLM视觉检测 (直接)
│       输入: 前20页大缩略图 (400x560, 8页/张)
│       处理: VLM识别目录页特征
│       输出: toc_pages[] 或 []
│
├─ 决策点A: 是否找到目录页?
│   │
│   ├─ 是 → 进入Step 3: 目录内容提取与分析
│   │
│   └─ 否 → 进入分支B: 无目录页处理
│       │
│       ├─ [文本型] 文本锚点检测
│       │   方法: 空白页(<50字符) / 章节标题模式("第X章"/"Part X") / 分隔符
│       │   输出: dividers[] 或 []
│       │
│       ├─ [图片型] VLM锚点检测
│       │   方法: 视觉特征识别 (空白/大标题/风格突变)
│       │   输出: dividers[] 或 []
│       │
│       └─ 决策点B: 是否找到分隔页?
│           ├─ 是 → 进入分支B-1: 分段提取
│           │   处理: 按dividers切分，每段提取子章节
│           │   输出: toc_items[]
│           │
│           └─ 否 → 进入分支C: 兜底扫描
│               [文本型] 全文档扫描 (参考PageIndex)
│                 方法: <physical_index_X>标签 + LLM分批提取
│               [图片型] 全文档视觉扫描
│                 方法: 分批渲染 + VLM自主发现章节
│               输出: toc_items[]
│
├─ Step 3: 目录内容提取 (仅当找到目录页时)
│   │
│   ├─ [文本型] 提取原始文本
│   │   处理: 合并toc_pages的文本 → toc_raw
│   │   保存: analysis["toc_raw"] = toc_raw
│   │
│   ├─ [图片型] 视觉内容提取
│   │   处理: 渲染toc_pages高清图 → VLM提取条目
│   │   保存: analysis["toc_entries"] = [{structure, title, page?}, ...]
│   │
│   └─ Step 3.1: 分析是否有页码
│       方法: 正则检测 "标题...数字" 模式 / VLM判断
│       输出: has_page_numbers = True | False
│
├─ 决策点C: 是否有页码?
│   │
│   ├─ 是 → 进入分支A: 有页码目录处理
│   │   │
│   │   ├─ Step A1: 提取结构化目录
│   │   │   输入: toc_raw (文本型) / toc_images (图片型)
│   │   │   处理: LLM/VLM提取 → {structure, title, page}
│   │   │   输出: toc_items[]
│   │   │
│   │   ├─ Step A2: 计算Offset
│   │   │   [文本型] 匹配toc_items中的page与page_texts中的实际位置
│   │   │   [图片型] VLM验证正文页面，匹配标题位置
│   │   │   方法: 取众数 difference = physical_index - page
│   │   │   输出: offset
│   │   │
│   │   ├─ Step A3: 应用Offset
│   │   │   处理: physical_index = page + offset
│   │   │   输出: 带physical_index的toc_items[]
│   │   │
│   │   └─ Step A4: 校验
│   │       抽样验证3-5个条目在正文中的准确性
│   │       ├─ 准确率 >= 80% → 成功，进入Phase 2
│   │       └─ 准确率 < 80% → 降级到分支A+B
│   │
│   └─ 否 → 进入分支A+B: 无页码目录处理
│       │
│       ├─ Step AB1: 提取目录结构 (无页码)
│       │   处理: LLM/VLM提取 → {structure, title, page: null}
│       │   输出: toc_items[] (无physical_index)
│       │
│       ├─ Step AB2: 正文搜索定位
│       │   [文本型] 关键词预筛选 + LLM精确定位
│       │     方法: extract_keywords() → 全页搜索 → 候选页 → LLM确认
│       │   [图片型] 视觉搜索定位 (携带目录信息)
│       │     方法: 渲染正文缩略图 + VLM匹配目录标题
│       │     关键: Prompt携带目录标题列表，"按图索骥"
│       │   输出: toc_items[] (带physical_index)
│       │
│       └─ Step AB3: 验证
│           ├─ 定位成功率 >= 70% → 成功，进入Phase 2
│           └─ 定位成功率 < 70% → 降级到分支B (无目录页处理)
│
├─ 分支降级路径总结:
│   分支A (有页码) → 失败 → 分支A+B (无页码搜索)
│   分支A+B → 失败 → 分支B (无目录页，锚点检测)
│   分支B → 失败 → 分支C (兜底扫描)
│   所有分支保留已提取信息，不丢失已有数据
│
└─ 最终输出: toc_items[] → Phase 2
```

### 2.4 Phase 2: 后处理流程

```
Phase 2: 后处理 (post_processing)
│
├─ 输入: toc_items[] (来自Fast或Balanced路径)
├─ 附加输入: analysis对象 (包含toc_raw, toc_entries, dividers等)
│
├─ Step 1: 数据清洗
│   - 移除空标题、重复条目
│   - 标准化structure格式 ("1.1" → "1.1")
│
├─ Step 2: 页码去重与排序
│   - 同一physical_index多个条目 → 保留层级高的
│   - 按physical_index排序
│
├─ Step 3: 分配页码范围 (divider_rebuild)
│   条件: 存在dividers[] 且 有层级结构
│   处理: 根据divider位置重建树结构
│   方法: rebuild_structure_by_dividers()
│
├─ Step 4: 构建树结构
│   输入: 扁平toc_items[]
│   处理: 根据structure层级构建嵌套树
│   输出: tree = {structure, title, physical_index, nodes: [...]}
│
├─ Step 5: 页码范围分配 (无divider时)
│   处理: 每个节点的end_page = 下一个兄弟节点的start_page - 1
│   输出: 每个节点添加start_page, end_page
│
└─ 输出: 最终TOC树
    {
      "structure": "1",
      "title": "第一章",
      "physical_index": 5,
      "start_page": 5,
      "end_page": 12,
      "nodes": [...]
    }
```

### 2.5 信息流转图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         全局信息存储 (analysis对象)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Phase 0产出                    Balanced路径产出                            │
│  ───────────                    ───────────────                             │
│  ├─ page_texts[]                ├─ toc_raw (目录原始文本)                    │
│  ├─ code_toc[]                  ├─ toc_entries[] (目录结构化条目)            │
│  ├─ image_coverage              ├─ toc_pages[] (目录页索引)                  │
│  └─ is_image_only_pdf           ├─ has_page_numbers (是否有页码)             │
│                                 ├─ dividers[] (分隔页列表)                   │
│                                 └─ toc_items[] (最终提取条目)                │
│                                                                             │
│  信息复用策略:                                                               │
│  ─────────────                                                             │
│  • toc_entries → 分支A+B的定位搜索 ("按图索骥")                             │
│  • toc_raw → 质量校验和人工检查                                             │
│  • dividers → Phase 2的结构重建                                             │
│  • code_toc (即使失败) → 作为参考信息保留                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 三、文本型文档路径（Text Path）

### 3.1 判定条件
```python
is_text_doc = analysis["image_coverage"] < 0.3 and not analysis.get("is_image_only_pdf", False)
```

### 3.2 Step 1: 查找目录页

#### 3.2.1 文本特征检测
**扫描范围**：前 20 页
**输入**：`analysis["page_texts"]`

**评分标准**：
- 标题关键词（+40）："目录"、"Contents"、"List of Figures"
- 页码模式（+30）：≥5个 `标题...数字` 匹配
- 递增性（+20）：页码单调递增
- 章节编号（+10）："第X章"、"1.1"、"一、"
- 反噪音（-20）：过多"表1"、"图1"、日期

**连续性检测**：目录页通常连续出现，score < 60 停止

#### 3.2.2 降级：VLM视觉检测（文本检测失败时）
- 渲染前20页大缩略图（400x560像素）
- VLM判断哪些页面是目录页

### 3.3 Step 2: 提取并分析目录内容

#### 3.3.1 提取目录原始文本
```python
def extract_toc_text_content(page_texts, toc_pages):
    """提取目录页的原始文本内容"""
    toc_raw = ""
    for page_idx in toc_pages:
        toc_raw += page_texts[page_idx][0] + "\n"
    return toc_raw
```

#### 3.3.2 分析是否有页码
```python
def analyze_toc_page_numbers(toc_raw):
    """
    分析目录是否有页码
    返回: {
        "has_page_numbers": bool,
        "confidence": float,
        "sample_entries": [...]
    }
    """
    # 检查是否有 "标题...数字" 模式
    # 检查数字是否在合理范围（1-999）
    # 检查递增性
```

### 3.4 分支A：有页码目录的处理

#### 3.4.1 提取结构化目录
```python
async def extract_structured_toc_with_pages(toc_raw, model):
    """
    提取带页码的结构化目录
    返回: [{"structure": "1", "title": "xxx", "page": 5}, ...]
    """
    prompt = """
    从以下目录文本中提取结构化目录。
    要求：
    1. 保留层级结构（1, 1.1, 1.2, 2...）
    2. 提取标题和页码
    3. 如果页码不明确，标记为null
    
    输出格式：
    [{"structure": "1", "title": "引言", "page": 1}, ...]
    """
```

#### 3.4.2 计算Offset
参考官方PageIndex实现：
```python
def calculate_page_offset(toc_items, page_texts, start_page=1):
    """
    通过匹配目录中的页码和实际页码，计算offset
    
    方法：
    1. 提取目录中有页码的条目
    2. 在正文前几页中搜索这些标题
    3. 找到匹配后，计算 physical_index - page = offset
    4. 取众数作为最终offset
    """
    matching_pairs = []
    
    for item in toc_items:
        if item.get("page"):
            # 在正文前几页搜索该标题
            for i in range(start_page, min(start_page + 20, len(page_texts))):
                if fuzzy_match(item["title"], page_texts[i][0]):
                    offset = (i + 1) - item["page"]
                    matching_pairs.append(offset)
                    break
    
    if matching_pairs:
        # 取众数
        return most_common(matching_pairs)
    return 0
```

#### 3.4.3 应用Offset并校验
```python
async def apply_offset_and_validate(toc_items, offset, page_texts, model):
    """
    应用offset到所有条目，并校验准确性
    
    步骤：
    1. 应用offset: physical_index = page + offset
    2. 抽样验证：在正文中验证几个关键章节
    3. 计算准确率
    4. 准确率 >= 80% → 成功 / 否则 → 降级到分支A+B
    """
```

### 3.5 分支A+B：无页码目录的处理

#### 3.5.1 提取结构（无页码）
```python
async def extract_structured_toc_no_pages(toc_raw, model):
    """
    提取不带页码的结构化目录
    返回: [{"structure": "1", "title": "xxx", "page": null}, ...]
    """
```

#### 3.5.2 正文搜索定位（参考官方PageIndex）
```python
async def locate_chapters_in_content(toc_items, page_texts, model, start_page=1):
    """
    在正文中搜索每个章节的起始位置
    参考官方：toc_index_extractor + extract_matching_page_pairs
    
    方法：
    1. 准备带标签的文本: <page_X>内容</page_X>
    2. 分批处理（每批20页）
    3. LLM在批次中查找章节位置
    4. 更新条目的 physical_index
    """
    
    # 官方风格实现
    tagged_pages = []
    for i, page_text in enumerate(page_texts):
        tagged = f"<physical_index_{i+1}>\n{page_text[0]}\n</physical_index_{i+1}>"
        tagged_pages.append(tagged)
    
    # 分批让LLM查找
    batch_size = 20
    for batch_start in range(start_page - 1, len(page_texts), batch_size):
        batch_text = "\n".join(tagged_pages[batch_start:batch_start + batch_size])
        
        prompt = f"""
        给定以下文档片段和目录结构，请为每个目录条目找到起始页码。
        
        文档片段（带页码标记）：
        {batch_text}
        
        目录条目（需要定位的）：
        {json.dumps([{"title": item["title"], "structure": item["structure"]} 
                     for item in toc_items if not item.get("physical_index")])}
        
        只返回在本批次中找到的条目，页码格式保持 <physical_index_X>
        """
        
        result = await llm_completion(model=model, prompt=prompt)
        # 解析结果并更新 physical_index
```

#### 3.5.3 关键词快速定位（优化）
```python
def quick_keyword_locate(toc_items, page_texts):
    """
    关键词快速定位（LLM前的预筛选）
    
    方法：
    1. 提取标题关键词
    2. 在所有页面中搜索
    3. 返回候选页列表（减少LLM工作量）
    """
    candidates = {}
    
    for item in toc_items:
        if item.get("physical_index"):
            continue  # 已定位
        
        title = item["title"]
        keywords = extract_keywords(title)  # 提取关键词
        
        candidate_pages = []
        for i, page_text in enumerate(page_texts):
            text = page_text[0]
            match_score = sum(1 for kw in keywords if kw.lower() in text.lower())
            if match_score >= len(keywords) * 0.5:
                candidate_pages.append((i + 1, match_score))
        
        candidates[item["structure"]] = sorted(candidate_pages, key=lambda x: x[1], reverse=True)[:5]
    
    return candidates
```

### 3.6 分支B：无目录页的处理

**场景**：Step 1 未找到目录页，完全没有目录信息可参考。

**核心逻辑**：不依赖任何目录信息，直接对全文进行扫描。与图片型文档分支B类似，但使用文本特征。

#### 3.6.1 文本锚点检测（无目录信息）

由于没有目录页，只能基于文本特征识别可能的章节分隔位置：

- **空白页检测**：页面文本极少（<50字符）
- **大标题检测**：页面以大字号、加粗文字开头
- **章节编号模式**："第X章"、"Part X"、"Chapter X"
- **分隔符检测**：大量"-"、"="等分隔线

```python
def detect_text_anchors_no_toc(page_texts):
    """
    无目录页时的文本锚点检测
    
    方法：
    1. 扫描所有页面，识别潜在的分隔页特征
    2. 返回候选分隔页列表
    3. 如果没有明显分隔页，返回空列表（进入全文档扫描）
    """
    dividers = []
    for i, (text, _) in enumerate(page_texts):
        # 空白页
        if len(text.strip()) < 50:
            dividers.append(i + 1)
            continue
        
        # 章节标题页特征
        first_lines = text.strip().split('\n')[:3]
        for line in first_lines:
            if re.match(r'^(第[一二三四五六七八九十]+章|Part\s+\d+|Chapter\s+\d+)', line):
                dividers.append(i + 1)
                break
    
    return dividers
```

#### 3.6.2 全文档扫描兜底（参考PageIndex）

如果锚点检测未找到分隔页，退化为全文档扫描：

```python
def process_no_toc_text(page_texts, model):
    """
    无目录页时的全文档扫描（参考PageIndex process_no_toc）
    
    方法：
    1. 将所有页面文本加上 <physical_index_X> 标签
    2. 分批让LLM提取章节结构
    3. 合并结果
    """
    
    # 添加物理页码标签（参考PageIndex）
    page_contents = []
    for i, (text, _) in enumerate(page_texts):
        page_text = f"<physical_index_{i+1}>\n{text}\n<physical_index_{i+1}>\n\n"
        page_contents.append(page_text)
    
    # 分批处理（每批20页，token限制）
    batch_size = 20
    all_items = []
    
    for batch_start in range(0, len(page_contents), batch_size):
        batch_text = "".join(page_contents[batch_start:batch_start + batch_size])
        
        prompt = f"""
        请从以下文档片段中提取章节结构。
        
        文档片段：
        {batch_text}
        
        要求：
        1. 提取所有章节标题
        2. 记录每个章节的physical_index（从标签中提取）
        3. 保持层级关系
        
        输出格式：
        [
          {{"structure": "1", "title": "章节标题", "physical_index": 5}},
          {{"structure": "1.1", "title": "子章节标题", "physical_index": 6}}
        ]
        """
        
        result = llm_completion(model=model, prompt=prompt)
        batch_items = extract_json(result)
        all_items.extend(batch_items)
    
    return all_items
```

### 3.7 文本路径完整流程

```
文本型文档
  → Step 1: 查找目录页
    → 文本特征检测（前20页）
      → 找到 → Step 2（有目录页）
      → 没找到 → VLM视觉检测（文本检测失败时）
        → 找到 → Step 2（有目录页）
        → 没找到 → 分支B（无目录页，进入锚点检测）
  → Step 2: 提取并分析目录内容（仅当找到目录页时）
    → 提取原始文本
    → 分析是否有页码
      → 有页码 → 分支A
        → 提取结构化目录（structure, title, page）
        → 计算offset
        → 应用offset
        → 抽样校验（准确率>=80%？）
          → 是 → 进入后处理 ✓
          → 否 → 降级到分支A+B
      → 无页码 → 分支A+B
        → 提取结构化目录（structure, title, page=null）
        → 正文搜索定位（关键词预筛选 + LLM精确定位）
        → 验证定位结果
          → 成功 → 进入后处理 ✓
          → 失败 → 降级到分支B
  → 分支B: 无目录页（Step 1未找到目录页，或分支A+B失败）
    → 文本锚点检测（空白页/章节标题/分隔符）
      → 找到分隔页 → 分段提取子章节 → 合并构建树
      → 未找到分隔页 → 全文档扫描兜底（参考PageIndex）
```

---

## 四、图片型文档路径（Visual Path）

### 4.1 判定条件
```python
is_image_doc = (
    analysis.get("is_image_only_pdf", False)
    or analysis.get("image_coverage", 0.0) >= 0.3
)
```

### 4.2 Step 1: 查找目录页

#### 4.2.1 VLM视觉检测
**图像规格**：
- 单页尺寸：400 x 560 像素（比锚点检测更大）
- 排列：4 x 2 = 8页/张
- 页码标注：左上角清晰标注物理页码
- 范围：前20页 → 约3张图

**VLM Prompt**：
```
你是 PDF 文档分析专家。这些是文档前20页的缩略图网格。

任务：找出哪些页面是"目录页"。

判断标准（满足任意一项）：
1. 页面顶部有"目录"、"Contents"等标题
2. 页面上有多个条目，每个条目带有页码数字
3. 条目有层级结构（如"第一章"、"1.1"等编号）

注意：
- "图目录"/"表目录"也是目录页
- 目录页通常连续出现（2-5页）
- 有些目录可能没有页码，但有完整的标题和层级

输出格式（严格JSON）：
{
  "toc_pages": [3, 4, 5],
  "confidence": "high|medium|low",
  "reasoning": "第3页有'目录'标题和多个带页码的条目...",
  "has_page_numbers": true|false  // 是否有页码
}
```

### 4.3 Step 2: 提取并分析目录内容

#### 4.3.1 提取目录视觉内容
```python
async def extract_toc_visual_content(file_path, toc_pages, model):
    """
    使用VLM从目录页图片中提取内容
    
    返回: {
        "toc_text": "目录的文本表示",
        "has_page_numbers": bool,
        "structure_hint": "层级结构描述"
    }
    """
    images = render_pages_to_images(file_path, [p-1 for p in toc_pages], dpi=200)
    
    prompt = """
    请提取该目录页的所有内容。
    
    要求：
    1. 提取所有标题，保留层级编号（如"1"、"1.1"、"第二章"）
    2. 如果有页码，记录页码
    3. 如果没有页码，只记录标题和层级
    4. 保持原文，不要概括
    
    输出格式：
    {
      "entries": [
        {"level": 1, "title": "第一章 引言", "page": 5},
        {"level": 2, "title": "1.1 研究背景", "page": 6}
      ],
      "has_page_numbers": true
    }
    """
    
    result = await vlm_call_with_images(images, prompt, model=model, max_tokens=4000)
    return parse_json(result)
```

#### 4.3.2 保存目录信息到analysis
```python
# 保存到analysis，供后续步骤使用
analysis["toc_visual_content"] = toc_content
analysis["toc_has_page_numbers"] = has_page_numbers
analysis["toc_entries"] = entries  # [{level, title, page?}, ...]
```

### 4.4 分支A：有页码目录的处理

#### 4.4.1 VLM视觉提取带页码目录
```python
async def extract_visual_toc_with_pages(file_path, toc_pages, model):
    """
    从目录页图片中提取带页码的结构化目录
    
    方法：
    1. 渲染目录页高清图
    2. VLM提取条目（structure, title, page）
    3. 校验页码合理性
    4. 计算offset（如果页码是相对页码）
    """
```

#### 4.4.2 计算Offset并应用
同文本路径3.4.2

#### 4.4.3 VLM校验（在正文中验证）
```python
async def validate_toc_entries_visual(toc_items, file_path, model):
    """
    在正文页面中抽样验证TOC条目的准确性
    
    方法：
    1. 选取3-5个关键条目
    2. 渲染对应页面的高清图
    3. VLM验证：该页是否以该标题开头
    4. 计算准确率
    """
```

### 4.5 分支A+B：无页码目录的处理

#### 4.5.1 提取目录结构（无页码）
```python
async def extract_visual_toc_no_pages(file_path, toc_pages, model):
    """
    从目录页图片中提取不带页码的结构
    返回: [{"structure": "1", "title": "xxx"}, ...]
    """
```

#### 4.5.2 正文视觉搜索定位（携带目录信息）

**场景**：已提取目录结构（4.5.1），但目录中无页码，需要在正文中定位每个章节的起始页。

**核心逻辑**：携带从目录页提取的章节标题列表，让VLM在正文中搜索匹配。

```python
async def locate_chapters_visual(toc_items, file_path, page_count, model):
    """
    在正文中视觉搜索每个章节的起始位置
    
    输入：
    - toc_items: 从目录页提取的结构化条目 [{"structure": "1", "title": "xxx"}, ...]
    - file_path: PDF文件路径
    - page_count: 总页数
    
    方法：
    1. 渲染正文前N页缩略图
    2. VLM搜索：在页面中查找与目录标题匹配的章节起始位置
    3. 返回 physical_index
    
    关键：必须携带目录信息，告诉VLM"我要找哪些标题"
    """
    
    # 准备待定位的章节标题列表（从4.5.1提取）
    pending_titles = [
        {"structure": item["structure"], "title": item["title"]}
        for item in toc_items
        if not item.get("physical_index")
    ]
    
    # 批量渲染正文页面
    batch_size = 10
    for batch_start in range(1, min(50, page_count), batch_size):  # 只搜前50页
        images = render_pages_to_images(
            file_path, 
            list(range(batch_start - 1, min(batch_start + batch_size - 1, page_count)))
        )
        
        prompt = f"""
        这些是文档第{batch_start}页到第{min(batch_start + batch_size - 1, page_count)}页的缩略图。
        
        【目录参考信息】（从文档目录页提取）
        文档包含以下主要章节，请在当前页面中查找它们的起始位置：
        {json.dumps(pending_titles, ensure_ascii=False, indent=2)}
        
        任务：
        1. 在当前页面中查找以上章节标题
        2. 如果某页以该章节标题开头（大字、加粗、居中的标题），记录该页码
        3. 优先匹配structure编号靠前的重要章节
        
        注意：
        - 只匹配完整的章节标题，不要匹配正文段落中的相似文字
        - 如果当前批次没找到某些章节，不要猜测，留空即可
        
        输出格式：
        {{
          "found_chapters": [
            {{"title": "章节标题", "page": 物理页码, "structure": "1"}},
          ],
          "not_found": ["未找到的章节标题"]
        }}
        """
        
        result = await vlm_call_with_images(images, prompt, model=model)
        # 解析结果并更新 toc_items 的 physical_index
```

### 4.6 分支B：无目录页的处理

**场景**：Step 1 未找到目录页，完全没有目录信息可参考。

**核心逻辑**：不依赖任何目录信息，直接对全文进行扫描和结构提取。参考PageIndex的 `process_no_toc` 实现。

#### 4.6.1 锚点检测（无目录信息）

**核心挑战**：没有目录页，完全不知道文档结构，只能通过视觉特征推断分隔页位置。

**图像规格**：
- 每个网格显示连续页面（如12页/张，3×4排列）
- 单页分辨率：300×400 像素（足够看清文字大小和布局）
- 页面左上角标注物理页码
- 覆盖范围：全文档或前50页（根据文档长度）

**泛化提示词设计原则**：
1. **多类型文档覆盖**：学术论文、技术文档、商业报告、书籍、手册等
2. **正面+反面例子**：明确什么算分隔页，什么不算
3. **层级识别**：区分主章节分隔页和子章节分隔页
4. **容错机制**：不强制要求找到分隔页，允许返回空列表

```python
async def _vlm_detect_anchors_no_toc(file_path, page_count, model):
    """
    无目录页时的锚点检测 - 泛化版
    
    支持多种文档类型的分隔页识别
    """
    
    # 根据文档长度决定扫描范围
    scan_pages = min(50, page_count) if page_count < 100 else page_count
    
    # 渲染缩略图网格
    grids = render_thumbnail_grids(
        file_path, 
        pages=list(range(scan_pages)),
        pages_per_grid=12, 
        cols=3,
        page_width=300,
        page_height=400
    )
    
    prompt = f"""
    你是PDF文档结构分析专家。这些是文档的缩略图网格（每页左上角标注了物理页码）。
    
    【任务】识别所有"章节分隔页"（Chapter Divider Pages）
    
    【什么是章节分隔页？】
    章节分隔页是标志新章节开始的页面，通常具有以下特征之一：
    
    1. **空白/极简页**
       - 页面几乎空白，只有少量装饰性元素
       - 可能只有章节编号（如"Chapter 3"）或章节标题
       - 示例：只有"Part II"几个大字的页面
    
    2. **大标题页**
       - 页面顶部或中央有大号字体的标题
       - 标题下方可能有副标题或简短描述
       - 标题与正文有明显的大小差异
       - 示例："第一章 绪论"、"Section 1: Introduction"
    
    3. **风格突变页**
       - 背景颜色与前后页明显不同（如深色背景vs白色背景）
       - 页面布局与前后页显著不同
       - 可能出现大幅插图或装饰图案
       - 示例：前10页是白底黑字，第11页突然变成蓝底白字
    
    【什么NOT是章节分隔页？】
    
    1. **目录页**：有"目录"/"Contents"标题，包含多个条目和页码
    2. **内容页**：有正文段落、图表、表格的页面
    3. **图表页**：包含大型图表但属于某章节内部的页面
    4. **页眉/页脚变化**：仅页眉文字变化，内容连续性未中断
    5. **子章节标题**：如"1.1 背景"这种小标题页（属于章节内部）
    
    【不同类型文档的分隔页特征】
    
    - **学术论文**：通常是"1 Introduction"、"2 Methodology"等标题页
    - **技术文档**：可能是"Chapter 1: Getting Started"、"Part I: Overview"
    - **商业报告**：可能是"Executive Summary"、"Market Analysis"等章节封面
    - **书籍**：常有"第一章"、"Part One"、大幅插图+标题的组合
    - **手册/指南**：可能是"Section 1: Installation"、"Step 1: Preparation"
    
    【重要约束】
    1. **宁可漏判，不要误判**：不确定的页面不要标记为分隔页
    2. **连续标题页只取第一个**：如果第5页和第6页都是标题页，只标记第5页
    3. **忽略子章节**：只标记主章节的分隔页（如"Part 1"、"Chapter 1"），不标记"1.1"、"1.2"等
    4. **文档开头和结尾**：第1页通常是封面，最后几页通常是参考文献/附录，不标记为分隔页
    5. **空列表是合法的**：如果文档没有明显的分隔页，返回空列表
    
    【输出格式】
    ```json
    {{
      "chapter_dividers": [5, 13, 25, 35, 41],
      "divider_types": ["chapter_title", "chapter_title", "blank", "style_change", "chapter_title"],
      "confidence": "high",
      "reasoning": "第5页有'Part 1'大标题；第13页有'Part 2'...",
      "skipped_pages": [1, 62],
      "skipped_reasons": ["封面页", "参考文献页"]
    }}
    ```
    
    字段说明：
    - chapter_dividers: 分隔页的物理页码列表（按升序排列）
    - divider_types: 每个分隔页的类型，与chapter_dividers一一对应
    - confidence: 整体置信度（high/medium/low）
    - reasoning: 判断理由的简要说明
    - skipped_pages: 明确排除的页面（如封面、目录、参考文献）
    - skipped_reasons: 排除原因
    """
    
    result = await vlm_call_with_images(grids, prompt, model=model, max_tokens=2000)
    return parse_json(result)
```

**关键改进点**：

| 改进项 | 原版 | 泛化版 |
|--------|------|--------|
| 文档类型覆盖 | 未提及 | 明确列出5种文档类型 |
| 判断标准 | 3条简单标准 | 3类正面标准 + 5类反面标准 |
| 示例 | 无 | 每类标准提供具体示例 |
| 约束条件 | 3条 | 5条详细约束 |
| 输出字段 | 3个 | 6个（增加reasoning、skipped等） |
| 误判控制 | "可以返回空列表" | "宁可漏判，不要误判" |
| 子章节处理 | 未提及 | 明确忽略子章节 |

#### 4.6.2 分段提取（无目录提示）

由于没有目录信息，分段提取时无法预知要找哪些子章节，只能让VLM自主提取：

```python
async def _branch_b_no_toc(
    file_path, page_count, dividers, model
):
    """
    无目录页时的分段提取（参考PageIndex process_no_toc）
    
    方法：
    1. 按分隔页切分文档为多个片段
    2. 对每个片段，让VLM提取章节结构
    3. 合并所有片段的结构
    
    与有目录页的区别：
    - 不知道要找哪些标题，VLM自主发现
    - 没有structure编号参考，由后端分配
    """
    
    for i, div in enumerate(dividers):
        end = dividers[i + 1] - 1 if i + 1 < len(dividers) else page_count
        
        # 提取divider页的主标题（如果有的话）
        main_title = await extract_divider_title(file_path, div, model)
        
        # 提取内容页的子标题（无提示，VLM自主提取）
        content_pages = list(range(div + 1, end + 1))
        if content_pages:
            sub_titles = await extract_content_titles(
                file_path, content_pages, model
            )
            # sub_titles 结构: [{"title": "xxx", "page": 页码}, ...]
```

#### 4.6.3 全文档扫描兜底（参考PageIndex）

如果锚点检测也未找到分隔页，则退化为全文档扫描：

```python
async def process_no_toc_visual(file_path, page_count, model):
    """
    无目录页且无分隔页时的兜底方案
    
    参考PageIndex的 process_no_toc：
    1. 将文档分批渲染（每批N页）
    2. 对每批调用VLM提取章节结构
    3. 合并所有批次的结构
    
    注意：这是最后的兜底方案，准确率可能较低
    """
    
    # 分批处理（每批10页）
    batch_size = 10
    all_items = []
    
    for batch_start in range(1, page_count + 1, batch_size):
        batch_end = min(batch_start + batch_size - 1, page_count)
        images = render_pages_to_images(
            file_path,
            list(range(batch_start - 1, batch_end))
        )
        
        prompt = f"""
        这些是文档第{batch_start}页到第{batch_end}页的内容。
        
        任务：提取该片段中的章节结构。
        
        要求：
        1. 提取所有章节标题（大字、加粗、居中的文字）
        2. 记录每个章节的起始页码
        3. 保持层级关系（主标题、子标题）
        
        输出格式：
        [
          {{"structure": "1", "title": "章节标题", "physical_index": 页码}},
          {{"structure": "1.1", "title": "子章节标题", "physical_index": 页码}}
        ]
        """
        
        result = await vlm_call_with_images(images, prompt, model=model)
        batch_items = parse_json(result)
        all_items.extend(batch_items)
    
    # 去重、合并、构建树
    return deduplicate_and_build_tree(all_items)
```

### 4.7 图片路径完整流程

```
图片型文档
  → Step 1: VLM视觉查找目录页（前20页大缩略图）
    → 找到 → Step 2（有目录页）
    → 没找到 → 分支B（无目录页，进入锚点检测）
  → Step 2: 提取并分析目录视觉内容（仅当找到目录页时）
    → 渲染目录页高清图
    → VLM提取条目（structure, title, page?）
    → 分析是否有页码
      → 有页码 → 分支A
        → 计算offset（通过正文页面验证）
        → 应用offset到所有条目
        → VLM校验（抽样验证准确率）
          → 准确率>=80% → 进入后处理 ✓
          → 准确率<80% → 降级到分支A+B
      → 无页码 → 分支A+B
        → 保存目录结构（structure, title, page=null）
        → 正文视觉搜索定位（携带目录信息，VLM在正文中匹配标题）
        → 验证定位结果
          → 成功 → 进入后处理 ✓
          → 失败 → 降级到分支B
  → 分支B: 无目录页（Step 1未找到目录页，或分支A+B失败）
    → 锚点检测（无目录信息，仅通过视觉特征识别分隔页）
      → 找到分隔页 → 分段提取（VLM自主提取子章节） → 合并构建树
      → 未找到分隔页 → 全文档扫描兜底（参考PageIndex process_no_toc）
```

---

## 五、多来源信息融合（后处理前）

### 5.1 信息来源

| 来源 | 文本路径 | 图片路径 | 信息类型 |
|------|---------|---------|---------|
| 目录页 | ✓ | ✓ | 章节标题、层级结构、页码 |
| 正文搜索 | ✓ | ✓ | physical_index |
| 分割页 | - | ✓ | 章节边界 |
| 内容提取 | ✓ | ✓ | 子章节标题 |

### 5.2 融合策略

```python
def merge_toc_sources(toc_from_page, toc_from_content, dividers, doc_type):
    """
    合并多来源TOC信息
    
    优先级（文本型）：
    1. 目录页提取的结构（骨架）
    2. 正文搜索找到的physical_index（定位）
    3. 内容提取的子标题（补充细节）
    
    优先级（图片型）：
    1. 目录页提取的结构（骨架）
    2. 分割页信息（章节边界修正）
    3. 正文视觉搜索（定位）
    4. 分段内容提取（子章节补充）
    """
    
    merged = {}
    
    # 1. 以目录结构为骨架
    for item in toc_from_page:
        struct = item["structure"]
        merged[struct] = {
            "structure": struct,
            "title": item["title"],
            "physical_index": item.get("physical_index"),
            "nodes": []
        }
    
    # 2. 补充正文搜索/视觉搜索找到的位置
    for item in toc_from_content:
        struct = item["structure"]
        if struct in merged:
            if not merged[struct]["physical_index"] and item.get("physical_index"):
                merged[struct]["physical_index"] = item["physical_index"]
    
    # 3. 图片型：用divider信息修正主章节位置
    if doc_type == "image" and dividers:
        for i, div in enumerate(dividers):
            struct = str(i + 1)
            if struct in merged:
                merged[struct]["physical_index"] = div
    
    # 4. 构建树结构
    tree = build_tree_from_merged(merged)
    
    return tree
```

---

## 六、当前待改进点（现状 vs 目标）

### 6.1 文本路径待改进

| # | 现状 | 目标 | 优先级 |
|---|------|------|--------|
| 1 | 目录页文本未保存 | 始终提取并保存目录原始文本 | P0 |
| 2 | 无页码目录直接放弃 | 提取结构后正文搜索定位 | P0 |
| 3 | 缺少关键词预筛选 | 关键词匹配 + LLM精确定位 | P1 |
| 4 | 没有offset计算 | 参考官方：匹配计算offset | P1 |
| 5 | 缺少交叉验证 | 有页码和无页码方式交叉验证 | P2 |

### 6.2 图片路径待改进

| # | 现状 | 目标 | 优先级 |
|---|------|------|--------|
| 1 | 目录视觉内容未保存 | VLM提取并保存目录条目 | P0 |
| 2 | 无页码目录直接走分支B | 正文视觉搜索定位 | P0 |
| 3 | 锚点检测准确率低 | 优化VLM视觉特征识别（空白/标题/风格变化） | P1 |
| 4 | 分支B无引导信息 | 全文档扫描分段提取，自主发现章节结构 | P1 |
| 5 | 分割页识别与内容提取分离 | 信息共享，指导提取 | P2 |

### 6.3 通用待改进

| # | 现状 | 目标 | 优先级 |
|---|------|------|--------|
| 1 | 单来源信息构建树 | 多来源融合构建树 | P1 |
| 2 | 失败直接降级 | 渐进降级，保留已有信息 | P2 |
| 3 | 缺少目录信息缓存 | 目录内容存入analysis复用 | P1 |

---

## 七、实施优先级与依赖关系

### Phase 1: 基础改进（P0）
1. **目录内容始终提取保存**
   - 文本路径：`extract_toc_text_content()`
   - 图片路径：`extract_toc_visual_content()`
   - 保存到 `analysis["toc_entries"]`

2. **无页码目录的正文搜索**
   - 文本路径：`locate_chapters_in_content()`（参考官方）
   - 图片路径：`locate_chapters_visual()`

**依赖**：无
**预期效果**：解决大量"有目录但无页码"文档的问题

### Phase 2: 锚点检测优化（P1）
3. **改进锚点检测准确率**
   - 优化VLM对空白页、章节标题页、风格变化页的识别
   - 减少对"分隔页"的误判（如将内容页误判为分隔页）

4. **分支B全文档扫描优化**
   - 优化分批策略（每批页数、重叠页数）
   - 改进VLM自主发现章节结构的提示词

**依赖**：Phase 1
**预期效果**：提高分割页识别准确率和子章节提取质量

### Phase 3: 文本路径优化（P1）
5. **关键词预筛选 + LLM精确定位**
   - 实现 `quick_keyword_locate()`
   - 减少LLM调用量

6. **Offset计算与验证**
   - 参考官方 `calculate_page_offset()`
   - 实现交叉验证

**依赖**：Phase 1
**预期效果**：文本路径更准确，减少LLM依赖

### Phase 4: 多源融合（P2）
7. **多来源信息融合**
   - 实现 `merge_toc_sources()`
   - 统一文本型和图片型的后处理

8. **渐进降级机制**
   - 保留已有信息，逐步降级
   - 避免"全有或全无"

**依赖**：Phase 2, Phase 3
**预期效果**：最终树结构质量提升

---

## 八、关键设计决策

### 8.1 目录页信息利用策略
**决策**：无论是否能提取完整条目，目录内容始终保存
**理由**：
- 即使提取失败，目录中的章节标题列表对锚点检测和分段提取都有参考价值
- 避免"能用就用，不能用就扔"的浪费

### 8.2 无页码目录处理策略
**决策**：提取结构 → 正文搜索定位 → 验证
**理由**：
- 参考官方PageIndex实现，使用 `<physical_index_X>` 标签
- 关键词预筛选 + LLM精确定位，平衡速度和准确性

### 8.3 图片路径提示词策略
**决策**：分支A+B使用目录信息作为prompt上下文，分支B不使用
**理由**：
- 分支A+B（有目录页但无页码）：携带目录标题列表，让VLM在正文中"按图索骥"
- 分支B（无目录页）：没有任何目录信息可参考，VLM只能自主发现章节结构
- 区分两种场景，避免给分支B错误的引导信息

### 8.4 多源融合策略
**决策**：目录结构为骨架，其他来源补充定位信息
**理由**：
- 目录页通常有最准确的层级结构
- 正文搜索和分割页提供定位信息
- 内容提取补充子章节细节

---

## 九、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| VLM调用增加 | 成本上升 | 关键词预筛选减少LLM调用；批量处理 |
| 正文搜索慢 | 超长文档处理时间长 | 限制搜索范围（前50页）；异步并行 |
| 误判匹配 | 章节定位错误 | 交叉验证；抽样校验；容错修复 |
| 复杂度增加 | 维护困难 | 模块化设计；清晰的分支逻辑；详细日志 |

---

*本文档基于 COMPLETE_PIPELINE_v2.1.md 和官方PageIndex实现分析，提出v3.0架构设计，重点解决超长图片型文档处理中的目录信息利用不足问题。*
