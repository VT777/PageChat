# PDF TOC提取架构设计文档 v4.0

## 一、目标与定位

### 1.1 目标
设计统一的PDF目录提取架构，支持文本型和图片型文档，最大化利用目录页信息。

### 1.2 核心原则
1. **目录信息不浪费**：找到目录页后，TOC内容跨分支保留
2. **降级不失忆**：从高优先级分支降级时，携带已获取的信息
3. **路径差异化**：文本型走文本处理路径，图片型走视觉处理路径
4. **渐进搜索**：搜索空间从小到大逐步扩展，避免一次性全量扫描

---

## 二、整体架构

### 2.1 顶层：文档类型判定

```
输入: PDF文件
      │
      ▼
Phase 0: 预分析 (analyze_pdf_structure)
  产出 analysis 对象:
    ├─ page_texts[]              # 每页文本 + 字体信息
    ├─ code_toc[]                # PDF书签（可能为空）
    ├─ image_coverage: float     # 图片占比
    └─ is_image_only_pdf: bool
      │
      ├── code_toc优质 → Fast路径
      │
      └── 无/劣质code_toc → Balanced路径
            │
            ├── image_coverage < 0.3 → 文本型文档
            └── image_coverage >= 0.3 → 图片型文档
```

### 2.2 Fast路径

```
code_toc[] → 解析条目 → offset校正 → 页码验证(抽样) → LLM质检
                                                          │
                              ┌────────────────────────────┤
                              ▼                            ▼
                          通过 → Phase2               失败 → Balanced路径
                                                       (保留code_toc为参考)
```

### 2.3 Balanced路径总览

```
Balanced路径入口
│
├─ Step 1: 查找目录页
│   ├─ [文本型] 文本特征检测 → VLM降级
│   └─ [图片型] VLM视觉检测
│
├─ 决策: 找到目录页?
│   │
│   ├─ YES ──────────────────────────────────────────────────────┐
│   │                                                             │
│   │  Step 2: 提取目录内容                                       │
│   │    ├─ [文本型] extract_toc_text_content() → toc_raw         │
│   │    └─ [图片型] extract_toc_visual_content() → toc_entries   │
│   │                                                             │
│   │  Step 3: 分析是否有页码 → has_page_numbers                  │
│   │                                                             │
│   │  ┌─ has_page_numbers = true ──► 分支A                       │
│   │  │   提取结构化TOC + 计算offset + 校验                       │
│   │  │   ├─ 通过 → Phase2                                      │
│   │  │   └─ 失败 ↓ (携带toc_entries)                            │
│   │  │                                                          │
│   │  └─ has_page_numbers = false ─► 分支A+B                     │
│   │      提取目录结构 + 正文搜索定位                              │
│   │      ├─ 通过 → Phase2                                      │
│   │      └─ 失败 ↓ (携带toc_entries)                            │
│   │                                                             │
│   │  降级入口: 分支B-enhanced (有TOC信息)                        │
│   │    toc_entries作为可选提示 → 锚点检测 + 分段提取              │
│   │    ├─ 通过 → Phase2                                        │
│   │    └─ 失败 ↓                                               │
│   │                                                             │
│   └─ NO ───────────────────────────────────────────────────────┐
│                                                                 │
│     分支B-bare (无TOC信息)                                       │
│       锚点检测（纯视觉/文本特征）→ 分段提取 → 全文档扫描兜底       │
│       └─ 通过/失败 → Phase2                                    │
│                                                                 │
└───────────────────────┬─────────────────────────────────────────┘
                        │
                   分支C: 兜底全文档扫描
                          └─ Phase2
```

---

## 三、文本型文档路径

### 3.1 判定条件
```python
is_text_doc = analysis["image_coverage"] < 0.3 and not analysis.get("is_image_only_pdf", False)
```

### 3.2 Step 1: 查找目录页

#### 3.2.1 文本特征检测（前20页）
评分配置：标题关键词(+40) + 页码模式(+30) + 递增性(+20) + 章节编号(+10) - 噪音(-20)
连续性：score < 60 停止扫描

#### 3.2.2 降级：VLM视觉检测
文本检测失败时，渲染前20页缩略图让VLM识别目录页。

### 3.3 Step 2 & 3: 提取并分析目录内容

```python
def process_toc_text(page_texts, toc_pages, model):
    # 提取原始文本
    toc_raw = "".join(page_texts[i][0] + "\n" for i in toc_pages)
    analysis["toc_raw"] = toc_raw  # 始终保存

    # 分析是否有页码
    has_page_numbers = analyze_toc_page_numbers(toc_raw)
    analysis["toc_has_page_numbers"] = has_page_numbers
    return toc_raw, has_page_numbers
```

### 3.4 分支A：有页码目录

```python
async def branch_a_with_pages(toc_raw, page_texts, model):
    """
    1. LLM提取结构化TOC: [{structure, title, page}, ...]
    2. calculate_page_offset(toc_items, page_texts)
       - 匹配标题在正文前20页的位置 → difference = physical_index - page
       - 取众数作为offset
    3. 应用: physical_index = page + offset
    4. 抽样验证3-5条: 准确率 >= 80% → 成功
    5. 失败 → 降级到分支A+B（携带toc_entries）
    """
```

### 3.5 分支A+B：无页码目录

```python
async def branch_ab_search_in_content(toc_raw, page_texts, model):
    """
    1. LLM提取结构: [{structure, title, page: null}, ...]
    2. 正文搜索定位:
       a. quick_keyword_locate() 关键词预筛选 → 候选页列表
       b. locate_chapters_in_content() LLM在候选页确认
          - 使用 <physical_index_X> 标签包裹每页文本
          - 分批处理（每批20页），逐批匹配目录标题
    3. 定位成功率 >= 70% → 成功
    4. 失败 → 降级到分支B-enhanced（携带toc_entries）
    """
```

**注意**：`<physical_index_X>` 标签统一用于文本路径，与PageIndex官方一致。

### 3.6 分支B-enhanced：有TOC信息的锚点检测（从A/A+B降级）

```python
async def branch_b_enhanced_text(toc_entries, page_texts, model):
    """
    场景: 找到了TOC页并提取了结构，但无法精确定位章节页码
    
    策略: 用TOC结构信息指导分段
    1. 文本锚点检测 + 用toc_entries中的主标题辅助匹配
    2. 按分隔页分段，每段内用LLM提取子标题
    3. 按TOC结构编号分配structure
    
    与B-bare的区别: 知道要找哪些章节，知道层级结构
    """
    # toc_entries 示例: [{"structure":"1","title":"第一章"}, ...]
    
    # 根据TOC层级确定主章节分隔点（structure没有点号的条目）
    main_chapters = [e for e in toc_entries if "." not in e["structure"]]
    
    # 在正文中扫描这些主标题出现的位置
    dividers = []
    for ch in main_chapters:
        keywords = ch["title"][:5]  # 取前5个字做关键词
        for i, (text, _) in enumerate(page_texts):
            if keywords in text[:100]:  # 页面开头出现
                dividers.append(i + 1)
                break
    
    # 如果找不到，降级到分支C
    if len(dividers) < len(main_chapters) * 0.5:
        return await branch_c_full_scan_text(page_texts, model)
    
    # 分段提取
    return await extract_by_dividers_text(dividers, page_texts, model)
```

### 3.7 分支B-bare：无TOC信息的锚点检测（直接入口）

```python
def detect_text_anchors_bare(page_texts, max_scan_pages=100):
    """
    场景: 未找到目录页，无任何TOC信息
    
    扫描范围: min(len(page_texts), max_scan_pages)
    默认 max_scan_pages = 100，覆盖绝大多数文档正文部分
    """
    scan_end = min(len(page_texts), max_scan_pages)
    dividers = []
    
    for i in range(scan_end):
        text = page_texts[i][0]
        if len(text.strip()) < 50:
            dividers.append(i + 1)
            continue
        first_lines = "\n".join(text.strip().split("\n")[:3])
        if re.search(r'(第[一二三四五六七八九十百]+章|Part\s+\d+|Chapter\s+\d+)', first_lines):
            dividers.append(i + 1)
    
    return dividers
```

### 3.8 分支C：全文档扫描兜底（文本型）

```python
def process_full_scan_text(page_texts, model):
    """
    参考PageIndex process_no_toc 实现
    所有页面加 <physical_index_X> 标签 → LLM分批提取
    """
    page_contents = []
    for i, (text, _) in enumerate(page_texts):
        page_contents.append(
            f"<physical_index_{i+1}>\n{text}\n<physical_index_{i+1}>\n\n"
        )
    
    # 根据token限制分批
    groups = page_list_to_group_text(page_contents)
    toc = generate_toc_init(groups[0], model)
    for group in groups[1:]:
        additional = generate_toc_continue(toc, group, model)
        toc.extend(additional)
    return toc
```

---

## 四、图片型文档路径

### 4.1 判定条件
```python
is_image_doc = analysis.get("is_image_only_pdf", False) \
               or analysis.get("image_coverage", 0.0) >= 0.3
```

### 4.2 Step 1: VLM视觉查找目录页

渲染前20页缩略图网格（400x560/页，8页/张），VLM判断哪些是目录页。
输出 `toc_pages[]` 和 `has_page_numbers`。

### 4.3 Step 2 & 3: 提取并分析目录视觉内容

```python
async def extract_toc_visual(file_path, toc_pages, model):
    """VLM提取目录页内容，统一使用 structure 字段"""
    
    prompt = """
    提取目录页内容，输出结构化条目。
    每个条目包含:
    - structure: "1", "1.1" 格式的编号（必须为字符串）
    - title: 章节标题
    - page: 页码（如果有，否则 null）
    """
    
    result = await vlm_call_with_images(images, prompt, model)
    toc_entries = parse_json(result)
    
    # 保存到analysis
    analysis["toc_entries"] = toc_entries
    analysis["toc_has_page_numbers"] = any(e.get("page") for e in toc_entries)
    
    return toc_entries, analysis["toc_has_page_numbers"]
```

### 4.4 分支A：有页码目录

```python
async def branch_a_visual_with_pages(file_path, toc_entries, model):
    """
    1. VLM提取 → [{structure, title, page}, ...]
    2. 计算offset（图片型专用）:
       - 选取3-5个有页码的条目
       - 渲染对应页面高清图
       - VLM验证: "该页是否以标题'XXX'开头?"
       - physical_index - page → offset值列表 → 取众数
    3. 应用offset: physical_index = page + offset
    4. VLM抽样验证: 准确率 >= 80% → 成功
    5. 失败 → 降级到分支A+B（携带toc_entries）
    """
    
async def calculate_page_offset_visual(file_path, toc_items, model):
    """图片型文档专用offset计算（替代文本路径的fuzzy_match）"""
    differences = []
    for item in toc_items:
        if not item.get("page"):
            continue
        # 渲染该页码对应的页面
        image = render_page(file_path, item["page"] - 1)
        result = await vlm_check_title_in_page(image, item["title"], model)
        if result["found"]:
            differences.append(result["physical_index"] - item["page"])
    return most_common(differences) if differences else 0
```

### 4.5 分支A+B：无页码目录

```python
async def branch_ab_visual_search(file_path, toc_entries, model):
    """
    1. 提取目录结构: [{structure, title, page: null}, ...]
    2. 视觉搜索定位（携带toc_entries）:
       - 渲染正文缩略图（每批10页）
       - Prompt携带完整toc_entries作为参考
       - VLM在页面中匹配标题
    3. 渐进搜索:
       - 第一轮: 前50页 → 统计匹配率
       - 第二轮: 如果匹配率 < 70%，扩展到前100页
       - 第三轮: 匹配率仍低 → 降级到分支B-enhanced
    4. 匹配率 >= 70% → 成功
    5. 失败 → 降级到分支B-enhanced（携带toc_entries）
    """
    
    # 渐进式搜索
    search_ranges = [50, 100, 150]
    for max_pages in search_ranges:
        if max_pages > page_count:
            max_pages = page_count
        found = await search_chapters_in_range(file_path, toc_entries, 1, max_pages, model)
        match_rate = len(found) / len(toc_entries)
        if match_rate >= 0.7 or max_pages >= page_count:
            break
    
    if match_rate >= 0.7:
        return apply_search_results(toc_entries, found)
    else:
        return None  # 降级到B-enhanced
```

**视觉搜索Prompt（携带目录信息）**：

```
【目录参考】（从文档目录页提取，共N个章节）
[
  {"structure": "1", "title": "第一章 引言"},
  {"structure": "1.1", "title": "研究背景"},
  ...
]

这些是文档第X~Y页的缩略图。请查找以上章节的起始位置。

要求:
- 按structure顺序优先匹配前几个主要章节
- 只匹配以标题开头的页面（大字/加粗/居中）
- 当前批次没找到的留空，不要猜测
```

### 4.6 分支B-enhanced：有TOC信息的锚点检测（从A/A+B降级）

```python
async def branch_b_enhanced_visual(file_path, toc_entries, page_count, model):
    """
    场景: 找到了TOC页并提取了结构，但无法精确定位章节页码
    
    关键区别: 有 toc_entries 作为辅助信息
    1. VLM锚点检测时携带TOC主章节标题作为线索
    2. 验证检测到的锚点与TOC结构的一致性
    3. 不一致时优先信任锚点检测结果，用TOC标题做交叉验证
    """
    
    main_chapters = [e for e in toc_entries if "." not in e["structure"]]
    
    # 渲染缩略图
    grids = render_thumbnail_grids(file_path, list(range(page_count)),
                                   pages_per_grid=12, cols=3)
    
    prompt = f"""
    【任务】识别文档的章节分隔页
    
    【辅助信息】文档包含 {len(main_chapters)} 个主要章节:
    {json.dumps([e["title"] for e in main_chapters], ensure_ascii=False)}
    
    请在缩略图中:
    1. 尝试找到以上章节标题对应的页面
    2. 如果找不到，按通用分隔页特征识别
    3. 记录每个分隔页对应的可能是哪个章节
    
    输出格式:
    {{
      "chapter_dividers": [页码列表],
      "matched_titles": ["匹配到的章节标题"],  // 可选
      "confidence": "high|medium|low"
    }}
    """
    
    return await vlm_call_with_images(grids, prompt, model)
```

### 4.7 分支B-bare：无TOC信息的锚点检测（直接入口）

```python
async def branch_b_bare_visual(file_path, page_count, model):
    """
    场景: 未找到目录页，无任何TOC信息
    
    仅通过视觉特征识别分隔页，不携带任何目录提示
    """
```

**泛化提示词**：

```
你是PDF文档结构分析专家。这些是文档缩略图网格。

【任务】识别"章节分隔页"

【正例 - 什么是分隔页？】
1. 空白/极简页: 几乎空白，只有"Part 2"几个大字
2. 大标题页: 页面中央有大号标题，与正文明显不同
3. 风格突变: 背景颜色或排版突然改变

【反例 - 什么不是分隔页？】
1. 目录页: 有"目录"标题 + 多个条目
2. 内容页: 有正文段落、图表、表格
3. 子章节标题: "1.1 xxx" 这种属于章节内部

【不同文档类型的特征】
- 学术论文: "1 Introduction", "2 Methodology" 标题页
- 商业报告: "市场分析", "竞争格局" 等章节封面
- 技术文档: "Part I", "Chapter 1" 分隔页
- 书籍: "第一章" + 插图 + 标题组合
- 手册: "Section 1: Installation" 标题页

【约束】
1. 宁可漏判，不要误判
2. 连续标题页只取第一个
3. 只标记主章节分隔页，不标记子章节
4. 排除封面和参考文献页
5. 空列表是合法输出

【输出】
{"chapter_dividers": [], "confidence": "...", "reasoning": "..."}
```

### 4.8 分支C：全文档视觉扫描兜底

```python
async def branch_c_full_scan_visual(file_path, page_count, model):
    """
    兜底方案: 分批渲染 + VLM自主发现章节
    每批10页，逐批提取 → 合并 → 去重 → 构建树
    """
```

---

## 五、分支入口与降级规则总结

```
┌─────────────────────────────────────────────────────────────────┐
│                     Balanced路径入口                             │
├──────────────┬────────────────┬─────────────────────────────────┤
│ 找到TOC页？   │ 有页码？        │ 分支                            │
├──────────────┼────────────────┼─────────────────────────────────┤
│ YES          │ YES            │ 分支A                           │
│ YES          │ NO             │ 分支A+B                         │
│ NO           │ N/A            │ 分支B-bare (无TOC信息)           │
├──────────────┼────────────────┼─────────────────────────────────┤
│                  降级路径（信息传递）                             │
├─────────────────────────────────────────────────────────────────┤
│ A 失败  ──→ A+B     (携带: toc_entries with page numbers)       │
│ A+B 失败 ─→ B-enhanced (携带: toc_entries without positions)    │
│ B-enhanced 失败 ─→ C (携带: TOC结构信息)                        │
│ B-bare 失败 ─→ C (无信息)                                       │
│ C 失败 ─→ 返回空树 + 错误信息                                   │
└─────────────────────────────────────────────────────────────────┘
```

**关键变化**：
- 分支B拆分为 **B-enhanced**（有TOC信息）和 **B-bare**（无TOC信息）
- A+B降级到B-enhanced而非之前的B，保留了目录结构
- 降级时通过`analysis`对象传递已获取的信息（toc_entries等）

---

## 六、多来源信息融合

### 6.1 信息来源

| 来源 | 文本路径 | 图片路径 | 场景 |
|------|---------|---------|------|
| 目录页 | ✓ | ✓ | A, A+B, B-enhanced |
| 正文搜索 | ✓ | ✓ | A+B (文本搜索/视觉搜索) |
| 锚点检测 | ✓ | ✓ | B-enhanced, B-bare |
| 分段提取 | ✓ | ✓ | B-enhanced, B-bare |
| 全文档扫描 | ✓ | ✓ | C (兜底) |

### 6.2 融合策略

```python
def merge_toc_sources(toc_from_page, toc_from_search, dividers, doc_type):
    """
    骨架: toc_from_page (目录页提取的结构)
    定位: toc_from_search (正文搜索/视觉搜索找到的position)
    修正: dividers (锚点检测的章节边界)
    
    divider与TOC条目匹配逻辑（替代简单索引映射）:
    - 对每个divider，提取divider页的标题
    - 与toc_entries中的title做模糊匹配
    - 匹配成功的更新physical_index
    - 未匹配的作为额外章节添加
    """
    
    merged = {}
    
    # 1. 目录结构为骨架
    for item in toc_from_page:
        merged[item["structure"]] = dict(item)
    
    # 2. 正文搜索补充定位
    for item in toc_from_search:
        s = item["structure"]
        if s in merged and not merged[s].get("physical_index"):
            merged[s]["physical_index"] = item.get("physical_index")
    
    # 3. divider信息修正（通过标题匹配，非索引映射）
    if dividers:
        for div_page in dividers:
            div_title = extract_divider_title(file_path, div_page)
            matched = False
            for struct, entry in merged.items():
                if fuzzy_match(div_title, entry["title"]):
                    merged[struct]["physical_index"] = div_page
                    matched = True
                    break
            if not matched:
                # 新增章节（目录中可能遗漏）
                new_struct = str(len(merged) + 1)
                merged[new_struct] = {
                    "structure": new_struct,
                    "title": div_title,
                    "physical_index": div_page
                }
    
    return build_tree(merged)
```

---

## 七、文本路径 vs 图片路径对比

| 维度 | 文本型 | 图片型 |
|------|--------|--------|
| TOC查找 | 文本特征检测 → VLM降级 | 直接VLM检测 |
| TOC提取 | LLM提取原始文本 | VLM提取视觉内容 |
| Offset计算 | **fuzzy_match(page_texts)** | **VLM验证页面（专用函数）** |
| 正文搜索 | 关键词预筛选 + LLM定位 | 渲染缩略图 + VLM匹配 |
| 锚点检测 | 文本特征（空白/标题模式） | VLM视觉特征 |
| 扫描范围 | **min(total, 100)** 统一 | **min(total, 100)** 统一 |
| 搜索扩展 | 渐进式 50→100 | 渐进式 50→100 |
| 全文档扫描 | `<physical_index_X>` + LLM | 分批渲染 + VLM |
| 字段命名 | **统一使用 structure(string)** | **统一使用 structure(string)** |

---

## 八、当前待改进点

### 8.1 文本路径

| # | 现状 | 目标 | 优先级 |
|---|------|------|--------|
| 1 | 目录页文本未保存 | 始终保存到 analysis.toc_raw | P0 |
| 2 | 无页码目录放弃 | 正文搜索定位（关键词+LLM） | P0 |
| 3 | 降级丢弃信息 | B-enhanced携带toc_entries | P1 |
| 4 | 缺少关键词预筛选 | quick_keyword_locate() | P1 |
| 5 | 无offset交叉验证 | 有页码+无页码双重验证 | P2 |

### 8.2 图片路径

| # | 现状 | 目标 | 优先级 |
|---|------|------|--------|
| 1 | 目录视觉内容未保存 | 保存到 analysis.toc_entries | P0 |
| 2 | 无页码直接走B-bare | 先走A+B视觉搜索 | P0 |
| 3 | B-enhanced不存在 | 实现降级路径的TOC信息传递 | P1 |
| 4 | 搜索范围固定50页 | 渐进扩展 50→100→150 | P1 |
| 5 | 字段命名 level/structure混用 | 统一为 structure(string) | P1 |

### 8.3 通用

| # | 现状 | 目标 | 优先级 |
|---|------|------|--------|
| 1 | 单来源构建树 | 多来源融合（见第六章） | P1 |
| 2 | 降级丢弃信息 | analysis传递已获取信息 | P1 |
| 3 | divider按索引映射 | 按标题模糊匹配 | P2 |
| 4 | 扫描范围不一致 | 统一 min(total, 100) | P2 |

---

## 九、实施优先级

### Phase 1 (P0): 基础信息保存
1. 目录内容始终提取保存（文本+图片）
2. 无页码目录的正文搜索（先走A+B再降级）
3. 图片型offset专用函数 `calculate_page_offset_visual()`

### Phase 2 (P1): 降级路径修复
4. B-enhanced分支实现（接收toc_entries参数）
5. 降级时信息传递（analysis.toc_entries跨分支保留）
6. 渐进式搜索扩展（50→100→150）
7. 字段统一为 `structure`(string)

### Phase 3 (P2): 优化
8. 多来源融合 `merge_toc_sources()`
9. divider标题匹配映射（非索引映射）
10. 扫描范围统一

---

*本文档解决了v3.0的7个逻辑冲突，核心修改：
(1) 分支B拆分为B-enhanced/B-bare，解决降级信息丢失；
(2) 图片型offset独立实现，不再引用文本路径；
(3) 统一structure字段命名；
(4) 搜索范围渐进扩展；
(5) divider映射改为标题匹配而非索引映射。*
