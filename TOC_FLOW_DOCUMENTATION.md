# KnowClaw TOC 生成流程详解

## 一、总体流程概览（5阶段）

当用户上传一个 PDF 文件时，系统通过 **5个阶段** 生成文档的目录树（TOC）。

```
用户上传 PDF
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 0: PDF 预分析（纯代码，<100ms）                       │
│  - 提取页面文本、检测图片页、乱码页                           │
│  - 三级代码提取：书签 → 链接注解 → 正则                       │
│  - 输出：文档画像（页数、文本覆盖率、代码TOC、文本质量）       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: TOC 提取（三条路径）                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Fast 路径     │  │ Text 路径     │  │ Visual 路径   │       │
│  │ (书签/链接)   │  │ (LLM文本分析) │  │ (VLM图像分析) │       │
│  │ 便宜+快速     │  │ 中等成本      │  │ 昂贵+准确     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 2: 后处理                                             │
│  - 清洗去重、页码修正、层级构建、完整性检查                   │
│  - 输出：树形 TOC                                            │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 3: 节点填充（可选）                                   │
│  - 为每个节点提取文本、生成摘要、分配 node_id                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
  返回完整的 PageIndex 树
```

### 核心决策树

```
PDF 上传后：
  │
  ├─ 有书签/链接/正则 TOC？
  │   ├─ YES → Fast 路径（最优先）
  │   │         ├─ 内容匹配通过？
  │   │         │   ├─ YES → 直接返回
  │   │         │   └─ NO  → 降级到 Balanced
  │   │         └─ 页码偏移校正 → LLM质检
  │   │
  │   └─ NO → 进入 Balanced 路径
  │             │
  │             ├─ 文本质量好？
  │             │   ├─ YES → Text 路径（LLM读文本）
  │             │   │         ├─ generate_toc_init/continue
  │             │   │         └─ 验证修复循环
  │             │   │
  │             │   └─ NO  → Visual 路径（VLM看图片）
  │             │             ├─ 锚点检测（缩略图）
  │             │             ├─ 分支A：有目录页
  │             │             ├─ 分支B：有分隔页
  │             │             └─ 分支C：无任何锚点
  │             │
  └─ 所有路径结果 → Post-processing（后处理）
                    ├─ 清洗去重
                    ├─ 页码修正
                    ├─ 层级构建
                    └─ 完整性检查
```

---

## 二、Phase 0: PDF 预分析

### 2.1 入口函数

**文件**: `backend/pageindex/pdf_analyzer.py`  
**函数**: `analyze_pdf_structure()` [行397]  
**耗时**: < 100ms（纯代码，零 AI 调用）

### 2.2 核心任务

```python
def analyze_pdf_structure(file_path: str) -> Dict[str, Any]:
    # 1. 逐页分析
    for i in range(page_count):
        text = page.get_text()           # PyMuPDF 提取文本
        images = page.get_images()       # 检测图片
        ptype = _classify_page(text, images)  # 分类：text/image_only/garbled/empty
    
    # 2. 文本质量检测（新增）
    quality = _check_text_quality(page_texts)
    if quality["is_low_quality"]:
        text_coverage = 0.3  # 强制降级
        is_garbled = True
    
    # 3. 三级代码 TOC 提取
    code_toc = extract_toc_from_bookmarks(doc)        # Level 1
    if not code_toc:
        code_toc = extract_toc_from_link_annotations(doc)  # Level 2
    if not code_toc and text_coverage > 0.3:
        code_toc = extract_toc_by_regex(page_texts)   # Level 3
    
    return {
        "page_count": 43,
        "text_coverage": 0.30,
        "is_garbled_pdf": True,
        "code_toc": {
            "items": [...],  # 41个书签项
            "source": "bookmarks"
        },
        "page_list": [("文本", token数), ...],  # 每页文本+估算token
        "text_quality": {"meaningful_ratio": 0.25, ...}
    }
```

### 2.3 三级代码提取详解

| 级别 | 函数 | 行号 | 方法 | 准确度 | 速度 |
|------|------|------|------|--------|------|
| **Level 1** | `extract_toc_from_bookmarks()` | 160 | PDF 原生书签 | ⭐⭐⭐⭐⭐ | <1ms |
| **Level 2** | `extract_toc_from_link_annotations()` | 178 | TOC页内部链接 | ⭐⭐⭐⭐ | <10ms |
| **Level 3** | `extract_toc_by_regex()` | 225 | 正则匹配文本 | ⭐⭐⭐ | <100ms |

**关键输出**：`code_toc` 字段
- 如果有书签/链接 → `items` 包含完整 TOC 项（含页码）
- 如果只有正则 → `items` 可能只有标题，页码需校正
- 如果都没有 → `items` 为 None

---

## 三、Phase 1: TOC 提取（三条路径）

### 3.1 路由决策

**文件**: `backend/app/services/pageindex_service.py`  
**函数**: `_generate_index_v2()` [行2053]

```python
# 路由逻辑
has_code_toc = analysis["code_toc"]["items"] is not None
if requested_mode == "smart":
    execution_mode = "fast" if has_code_toc else "balanced"
```

---

### 3.2 Fast 路径详解

**文件**: `backend/pageindex/fast_toc.py`  
**函数**: `try_fast_toc()` [行198]  
**适用**: 有书签/链接/正则 TOC 的文档  
**成本**: ~$0.01（1次LLM调用）  
**成功率**: 约 60%（可能因验证失败降级）

#### 3.2.1 完整流程

```python
async def try_fast_toc(analysis, model):
    toc_items = analysis["code_toc"]["items"]  # 41个书签项
    source = analysis["code_toc"]["source"]     # "bookmarks"
    
    # Step 1: 页码偏移校正（正则TOC需要）
    if source == "regex":
        check = verify_content_match(toc_items, page_list)
        if check["offset_median"] != 0:
            apply_offset(toc_items, check["offset_median"])
    
    # Step 2: 内容验证 ⚠️【问题点】
    match_info = verify_content_match(toc_items, page_list)
    # 检查TOC标题是否出现在对应页面文本中
    
    if match_info["match_rate"] < 0.1:  # 匹配率<10%则拒绝
        print("[FAST-TOC] Match rate < 10%, rejecting")
        return None  # ← 技术应用洞察报告在此失败！
    
    # Step 3: 覆盖度检查
    last_page = max(it["physical_index"] for it in toc_items)
    if last_page < page_count * 0.3:
        return None  # 覆盖不足30%
    
    # Step 4: LLM质检
    valid = await llm_validate_toc(toc_items, page_count, match_info, model)
    if not valid:
        # P1-fix: 如果匹配率>30%且覆盖>50%，则接受
        if match_info["match_rate"] >= 0.3 and last_page >= page_count * 0.5:
            valid = True
    
    return {"toc_items": toc_items, "source": source}
```

#### 3.2.2 为什么技术应用洞察报告在此失败？

```
书签数据（41项，页码准确）：
  [0] pi=1  默认节
  [1] pi=1  幻灯片 1: 2025全球人工智能技术应用洞察报告
  [2] pi=4  第一章
  [3] pi=5  幻灯片 5: 全球人工智能技术发展现状
  ...

验证过程：
  verify_content_match() 检查 "全球人工智能技术发展现状" 
  是否出现在 page_list[4]（第5页文本）中
  
  实际 page_list[4] 内容："Chapter 1\n��\n��\n��"（乱码！）
  
  匹配结果：0/41 = 0% ❌
  
  → Fast 路径返回 None
  → 降级到 Balanced 路径
```

**根本问题**：书签是 PDF 元数据， inherently 可信。但系统把它当作文本提取的 TOC 来验证，而页面文本是乱码，导致误杀。

---

### 3.3 Balanced 路径总览

当 Fast 路径失败或无代码 TOC 时，进入 Balanced 路径。

```python
# 路径选择
balanced_path = decide_balanced_path(analysis)
# text_coverage >= 0.8 → "text"
# else → "visual"
```

#### 3.3.1 技术应用洞察报告的路径

```
text_coverage = 0.30 (< 0.8)
is_garbled = True
→ balanced_path = "visual"
```

---

### 3.4 Balanced-Text 路径详解

**文件**: `backend/pageindex/balanced_toc.py` + `backend/pageindex/page_index.py`  
**函数**: `build_balanced_toc_text()` [行759]  
**适用**: 文本质量好（覆盖率>80%）的文档  
**成本**: ~$0.05（多次 LLM 调用）

#### 3.4.1 核心流程

```python
async def build_balanced_toc_text(analysis, model, dividers=None):
    # 1. 调用 meta_processor 生成 TOC
    toc_items = await meta_processor(
        page_list,
        mode="process_no_toc",  # 无目录模式
        start_index=1,
        opt=opt,  # 配置：模型、token限制等
        logger=logger,
        doc_type="general",
    )
    
    # 2. 用 dividers 修正结构（P2新增）
    if dividers:
        toc_items = _refine_toc_with_dividers(toc_items, dividers, page_count)
    
    return {"toc_items": toc_items, "source": "llm_text"}
```

#### 3.4.2 meta_processor 内部流程

**文件**: `backend/pageindex/page_index.py`  
**函数**: `meta_processor()` [行2406]

```python
async def meta_processor(page_list, mode, ...):
    # 1. 文本分组（每组合并到 ~60000 tokens）
    group_texts = page_list_to_group_text(page_contents, token_lengths)
    
    # 2. 初始 TOC 生成
    toc = generate_toc_init(group_texts[0], model)
    
    # 3. 逐组续接
    for group in group_texts[1:]:
        additional = generate_toc_continue(toc, group, model)
        toc.extend(additional)
    
    # 4. 验证修复循环
    accuracy, incorrect = verify_toc(toc, page_list)
    while accuracy < 0.6 and attempts < 3:
        toc = fix_incorrect_toc(toc, incorrect, ...)
        accuracy, incorrect = verify_toc(toc, page_list)
    
    return toc
```

**generate_toc_init** [行955]：
- 调用 LLM（qwen3.6-flash）
- Prompt: `TOC_GENERATE_INIT_PROMPT`
- 要求 LLM 从文本中提取层级结构
- 返回 JSON 数组：`[{structure, title, physical_index}, ...]`

---

### 3.5 Balanced-Visual 路径详解（重点）

**文件**: `backend/pageindex/balanced_toc.py`  
**函数**: `build_balanced_toc_visual()` [行49]  
**适用**: 文本质量差或图片型 PDF  
**成本**: ~$0.10-0.20（多次 VLM 调用）  
**分支**: A（有目录页）/ B（有分隔页）/ C（无锚点）

#### 3.5.1 总流程

```python
async def build_balanced_toc_visual(file_path, analysis, model, anchors=None):
    # Phase 0.5: 锚点检测（缩略图网格）
    if anchors is None:
        anchors = await _vlm_detect_anchors(file_path, model)
    
    toc_pages = anchors["toc_pages"]      # [2]
    dividers = anchors["chapter_dividers"] # [5, 13, 25, 38]
    first_content = anchors["first_content_page"]  # 6
    
    # Phase 1: 分支选择
    if toc_pages:
        return await _branch_a_toc_page(...)   # ← 技术应用洞察报告进此分支
    elif dividers:
        if divider_density > 0.4:
            return await _branch_b_dense_dividers(...)
        else:
            return await _branch_b_normal_dividers(...)
    else:
        return await _branch_c_fulltext(...)
```

#### 3.5.2 锚点检测详解

**函数**: `_vlm_detect_anchors()` [行942]

```
输入: PDF 文件
处理:
  1. 将 PDF 每 12 页渲染为一张缩略图网格（4列 x 3行）
  2. 发送给 VLM（qwen3.6-flash）
  3. VLM 识别：
     - toc_pages: 哪些页面是目录页
     - chapter_dividers: 哪些页面是章节分隔页
     - first_content_page: 正文从哪页开始

输出: 
  {
    "toc_pages": [2],
    "chapter_dividers": [5, 13, 25, 38],
    "first_content_page": 6
  }
```

#### 3.5.3 分支 A：有目录页（重点中的重点）

**函数**: `_branch_a_toc_page()` [行114]  
**这是技术应用洞察报告实际走过的路径！**

```python
async def _branch_a_toc_page(file_path, page_count, toc_pages, dividers, model, ...):
    # Step 1: 渲染目录页+后续5页为高清图
    pages_to_render = [p-1 for p in toc_pages] + range(last_toc, last_toc+5)
    images = render_pages_to_images(file_path, pages_to_render, dpi=150)
    
    # Step 2: VLM 提取 TOC（只转录标题，不计算页码）
    prompt = VLM_TOC_EXTRACT_PROMPT  # "提取目录条目，不要计算页码"
    raw = await vlm_call_with_images(images, prompt, model)
    result = parse_vlm_json(raw)
    toc_items = result["toc_items"]  # ← 提取了8项（实际有41项！）
    
    # Step 3: 从 number 字段推断层级结构
    _infer_structure_from_numbers(toc_items)
    
    # Step 4: 智能页码映射 ⚠️【核心问题区域】
    _map_toc_physical_pages(
        toc_items, page_count, first_content_page, last_toc_page,
        ocr_text_map=None, dividers=dividers
    )
    
    # Step 5: 大节点检测
    LARGE_NODE_THRESHOLD = 8
    large_count = 0
    for i, item in enumerate(toc_items):
        span = estimated_end - start + 1
        if span >= LARGE_NODE_THRESHOLD:
            large_count += 1
    
    # Step 6: 判断是否需要完整扫描
    need_full_scan = len(toc_items) < 10 and large_count > 0 and model
    
    if need_full_scan:
        # Phase 2: 完整扫描全部页面
        page_titles = await _vlm_scan_document_pages(file_path, page_count, model)
        # Phase 3: 用目录标题匹配章节边界，提取子章节
        # ...
    
    return {"toc_items": toc_items, "source": "vlm_toc"}
```

#### 3.5.4 智能页码映射详解（问题根源）

**函数**: `_map_toc_physical_pages()` [行1194]

```python
def _map_toc_physical_pages(toc_items, page_count, first_content_page, last_toc_page, 
                            ocr_text_map=None, dividers=None):
    
    # 提取有 page 值的条目
    items_with_page = [it for it in toc_items if it.get("page") is not None]
    
    if not items_with_page:
        # ⚠️ 无页码！进入均匀分布
        print("[TOC-MAP] No logical pages found, using uniform distribution")
        
        # 尝试用 dividers（但条件苛刻）
        if dividers:
            top_items = [it for it in toc_items if "." not in str(it.get("structure", ""))]
            if len(top_items) == len(dividers):
                # 完美匹配！用 dividers
                for item, div in zip(top_items, dividers):
                    item["physical_index"] = div
                return
            # ⚠️ 不匹配（8 top_items vs 4 dividers）→ 失败
        
        # ⚠️ 最终 fallback：均匀分布
        _map_uniformly(toc_items, page_count, first_content_page)
```

**均匀分布算法** (`_map_uniformly` [行1344])：

```python
def _map_uniformly(toc_items, page_count, first_content_page):
    n = len(toc_items)  # 8
    available = page_count - first_content_page + 1  # 43-5+1 = 39
    
    for i, item in enumerate(toc_items):
        physical = first_content_page + i * available / n
        item["physical_index"] = round(physical)
    
    # 结果：p.5, p.10, p.15, p.20, p.24, p.29, p.34, p.39
    # 但真实位置应该是：p.5, p.13, p.25, p.38！
```

#### 3.5.5 为什么完整扫描没有触发？

```python
# 大节点检测
LARGE_NODE_THRESHOLD = 8  # 跨度>=8页才算大节点

均匀分布后的跨度：
  p.5-9   span=5  (< 8)
  p.10-14 span=5  (< 8)
  p.15-19 span=5  (< 8)
  ...
  
large_count = 0  # 没有大节点！

need_full_scan = len(toc_items) < 10 and large_count > 0
               = 8 < 10 and 0 > 0
               = True and False
               = False  # ← 完整扫描不触发！
```

**真实的章节跨度**（如果位置正确）：
```
第一章: p.5-12  span=8  (>= 8 ✓)
第二章: p.13-24 span=12 (>= 8 ✓)
第三章: p.25-37 span=13 (>= 8 ✓)
第四章: p.38-43 span=6  (< 8)

large_count 应该是 3！
```

#### 3.5.6 分支 B：无目录但有分隔页

**适用**: 无目录页，但有章节分隔页的文档

```python
async def _branch_b_normal_dividers(file_path, page_count, dividers, model):
    # 1. 将分隔页作为章节边界
    # 2. 对每个章节范围做 VLM 子标题提取
    # 3. 返回层级 TOC
```

#### 3.5.7 分支 C：无任何锚点

**适用**: 纯图片型文档，无目录、无分隔页

```python
async def _branch_c_fulltext(file_path, page_count, model):
    # 1. 分层全文分析
    # 2. 渲染页面缩略图网格
    # 3. VLM 识别章节结构
    # 4. 递归细分大章节
```

---

## 四、Phase 2: 后处理

### 4.1 入口函数

**文件**: `backend/pageindex/post_processing.py`  
**函数**: `post_process_toc()` [行437]

### 4.2 完整流程

```python
def post_process_toc(toc_items, page_count, dividers=None):
    # Step 1: 清洗
    items = clean_toc_items(toc_items)
    # - 转 int、去重、排序、过滤无效
    # - 确保单调递增（后一项页码 >= 前一项）
    
    # Step 2: P3 统一修正层（用 dividers 交叉验证）
    if dividers:
        items = refine_toc_with_dividers(items, dividers, page_count)
        # - 修复重复 physical_index
        # - 插入缺失章节
        # - 推断空 structure
    
    # Step 3: 边界校验
    items = validate_indices(items, page_count)
    # - 确保页码在 [1, page_count] 范围内
    
    # Step 4: 补充 Preface
    items = add_preface(items)
    # - 如果第一项不在第1页，插入 Preface 节点
    
    # Step 5: 设置页面范围
    items = assign_page_ranges(items, page_count)
    # - start_index = physical_index
    # - end_index = next_start - 1（最后一项到 page_count）
    
    # Step 6: 构建树
    tree = build_tree(items)
    # - 用 structure 字段（"1", "1.1", "2"）构建父子关系
    # - "1" 是顶级，"1.1" 是子级，"1.1.1" 是孙级
    
    # Step 7: 修复父节点范围
    fix_parent_ranges(tree)
    # - 父节点 end_index 至少覆盖到最后一个子节点
    
    # Step 8: 完整性检查
    completeness = check_completeness(tree, page_count)
    # - coverage: 覆盖页数比例
    # - gaps: 未覆盖页面
    # - quality: good/ok/warning/bad
    
    return tree, completeness
```

### 4.3 层级构建详解

**函数**: `build_tree()` [行136]

```python
def build_tree(toc_items):
    # 用栈构建父子关系
    root_nodes = []
    stack = []
    
    for item in toc_items:
        structure = item["structure"]  # e.g., "1.2.3"
        depth = structure.count(".") + 1  # e.g., 3
        
        # 弹出比当前深的节点
        while stack and _get_depth(stack[-1]["structure"]) >= depth:
            stack.pop()
        
        # 挂到正确的父节点下
        if stack:
            stack[-1]["nodes"].append(item)
        else:
            root_nodes.append(item)  # 顶级节点
        
        stack.append(item)
    
    return root_nodes
```

### 4.4 完整性检查标准

**函数**: `check_completeness()` [行221]

```python
def check_completeness(tree, page_count):
    covered_pages = set()
    for node in all_nodes:
        for p in range(node["start_index"], node["end_index"] + 1):
            covered_pages.add(p)
    
    coverage = len(covered_pages) / page_count
    uncovered = page_count - len(covered_pages)
    max_allowed = min(max(2, ceil(page_count * 0.05)), 10)
    
    if uncovered <= 3 and coverage >= 0.95:
        quality = "good"
    elif uncovered <= max_allowed:
        quality = "ok"
    else:
        quality = "warning" or "bad"
    
    return {"quality": quality, "coverage": coverage, ...}
```

---

## 五、Phase 3: 节点填充（可选）

### 5.1 入口

**文件**: `backend/app/services/pageindex_service.py`  
**在 `_generate_index_v2()` Phase 2 之后**

### 5.2 任务

```python
# 为每个节点填充：
- node_id: 唯一标识符
- text: 章节文本内容（从对应页面提取）
- summary: 章节摘要（LLM生成）
- nodes: 子节点列表（已在 Phase 2 构建）
```

---

## 六、问题定位总结

### 6.1 技术应用洞察报告的问题链路

```
1. PDF 有 41 个书签（页码准确）
   │
   ▼
2. Fast 路径：verify_content_match() 检查标题是否出现在页面文本中
   │   页面文本 = "Chapter 1\n��\n��\n��"（乱码！）
   │   匹配率 = 0%
   │
   ▼
3. Fast 路径返回 None，降级到 Balanced
   │
   ▼
4. Balanced-Visual 路径被选中（text_coverage=0.3）
   │
   ▼
5. VLM 从目录页图像提取到 8 项（非 41 项）
   │   目录页图像中没有页码数字
   │
   ▼
6. _map_toc_physical_pages() 发现无页码
   │   top_items(8) != dividers(4) → 不匹配
   │
   ▼
7. 回退到 _map_uniformly() → 伪造位置
   │   p.5, p.10, p.15, p.20, p.24, p.29, p.34, p.39
   │
   ▼
8. 大节点检测：所有跨度 5 页 (< 8)
   │   large_count = 0
   │
   ▼
9. need_full_scan = False
   │   完整扫描不触发！
   │
   ▼
10. 返回 8 个大标题，无子章节
```

### 6.2 修复切入点

| 切入点 | 文件 | 函数 | 行号 | 效果 |
|--------|------|------|------|------|
| **信任书签** | fast_toc.py | try_fast_toc() | 242 | Fast路径成功，无需Balanced |
| **移除均匀分布** | balanced_toc.py | _map_toc_physical_pages() | 1215 | 触发完整扫描 |
| **强制完整扫描** | balanced_toc.py | _branch_a_toc_page() | 305 | 无视large_count，直接扫描 |
| **Dividers修正** | post_processing.py | refine_toc_with_dividers() | 335 | 后处理重排 |

**最佳修复组合**：信任书签 + 移除均匀分布

---

## 七、代码文件索引

| 阶段 | 文件 | 核心函数 | 行号范围 |
|------|------|----------|----------|
| Phase 0 | pdf_analyzer.py | analyze_pdf_structure() | 397-493 |
| Phase 1-Fast | fast_toc.py | try_fast_toc() | 198-275 |
| Phase 1-Text | balanced_toc.py | build_balanced_toc_text() | 759-821 |
| Phase 1-Text | page_index.py | meta_processor() | 2406-2724 |
| Phase 1-Text | page_index.py | process_no_toc() | 966-991 |
| Phase 1-Visual | balanced_toc.py | build_balanced_toc_visual() | 49-106 |
| Phase 1-Visual | balanced_toc.py | _branch_a_toc_page() | 114-518 |
| Phase 1-Visual | balanced_toc.py | _vlm_detect_anchors() | 942-955 |
| Phase 1-Visual | balanced_toc.py | _map_toc_physical_pages() | 1194-1355 |
| Phase 1-Visual | balanced_toc.py | _map_uniformly() | 1344-1355 |
| Phase 2 | post_processing.py | post_process_toc() | 437-487 |
| Phase 2 | post_processing.py | build_tree() | 136-171 |
| Phase 3 | pageindex_service.py | _generate_index_v2() | 2053-2295 |
| 全流程 | pageindex_service.py | generate_index() | 2297-2315 |

---

*文档版本: 2025-05-29*  
*涵盖代码: backend/pageindex/*.py, backend/app/services/pageindex_service.py*
