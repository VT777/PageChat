# PDF TOC提取架构设计文档 v4.1

## 一、目标与不变量

### 1.1 目标
建立一套统一的PDF目录提取架构，分别处理文本型文档和图片型文档，并在降级过程中保留已获得的目录信息。

### 1.2 架构不变量
1. **找到目录页后必须保存目录信息**：文本型保存 `analysis["toc_raw"]` 和 `analysis["toc_entries"]`，图片型保存 `analysis["toc_entries"]`。
2. **降级不丢信息**：从分支A或分支A+B降级时进入 `B-enhanced`，不得进入 `B-bare`。
3. **B-enhanced 与 B-bare 语义不同**：`B-enhanced` 有TOC结构作为提示，`B-bare` 完全没有TOC信息。
4. **字段统一**：结构化目录条目统一使用 `structure: string`，例如 `"1"`、`"1.1"`。
5. **图片型offset不能复用文本匹配**：图片型必须通过VLM在候选页面窗口中验证标题位置。
6. **搜索逐步扩展**：正文搜索统一采用 `50 → 100 → 150 → 全文档兜底` 的渐进策略。

---

## 二、整体架构

### 2.1 顶层流程

```
PDF输入
  │
  ▼
Phase 0: 预分析 analyze_pdf_structure
  ├─ page_texts[]
  ├─ code_toc[]
  ├─ image_coverage
  └─ is_image_only_pdf
  │
  ├─ code_toc优质 ──► Fast路径
  │                    ├─ 成功 → Phase 2后处理
  │                    └─ 失败 → Balanced路径（保留code_toc参考）
  │
  └─ code_toc缺失/劣质 ──► Balanced路径
```

### 2.2 Balanced路径

```
Balanced路径
  │
  ├─ Step 1: 判定文档类型
  │   ├─ image_coverage < 0.3 → text
  │   └─ image_coverage >= 0.3 或 is_image_only_pdf → image
  │
  ├─ Step 2: 查找目录页
  │   ├─ text: 文本特征检测，失败后VLM检测
  │   └─ image: VLM检测
  │
  ├─ 找到目录页？
  │   │
  │   ├─ YES
  │   │   ├─ Step 3: 提取目录内容
  │   │   │   ├─ text: toc_raw → toc_entries
  │   │   │   └─ image: toc_entries
  │   │   ├─ Step 4: 判断是否有页码
  │   │   │   ├─ 有页码 → 分支A
  │   │   │   │   ├─ 成功 → Phase 2
  │   │   │   │   └─ 失败 → 分支A+B（携带toc_entries）
  │   │   │   └─ 无页码 → 分支A+B
  │   │   │       ├─ 成功 → Phase 2
  │   │   │       └─ 失败 → B-enhanced（携带toc_entries）
  │   │   └─ B-enhanced失败 → C兜底扫描 → Phase 2
  │   │
  │   └─ NO
  │       └─ B-bare（无TOC信息）
  │           ├─ 锚点检测成功 → 分段提取 → extracted_items → Phase 2
  │           └─ 锚点检测失败 → C兜底扫描 → Phase 2
```

### 2.3 分支入口规则

| 条件 | 入口分支 | TOC信息状态 |
|------|----------|-------------|
| 找到目录页且有页码 | A | 有 `toc_entries`，有 `page` |
| 找到目录页但无页码 | A+B | 有 `toc_entries`，无 `physical_index` |
| A或A+B失败 | B-enhanced | 有 `toc_entries`，定位不完整 |
| 未找到目录页 | B-bare | 无TOC信息 |
| B-enhanced或B-bare失败 | C | enhanced可携带TOC，bare无TOC |

---

## 三、统一数据结构

### 3.1 analysis对象

```python
analysis = {
    "page_texts": [(text, font_info), ...],
    "code_toc": [],
    "image_coverage": 0.0,
    "is_image_only_pdf": False,
    "toc_pages": [],
    "toc_raw": None,
    "toc_entries": [],
    "toc_has_page_numbers": False,
    "dividers": [],
}
```

### 3.2 TOC条目

```python
toc_item = {
    "structure": "1.1",          # 统一为字符串
    "title": "章节标题",
    "page": None,               # 目录页中的页码，可为空
    "physical_index": None,     # PDF物理页码，定位后填充
}
```

### 3.3 主章节识别

不要只依赖 `"." not in structure`。主章节识别使用以下优先级：

1. `structure` 无点号，例如 `"1"`、`"2"`
2. 中文编号，例如 `"一"`、`"二"`、`"第一章"`
3. 英文编号，例如 `"Part 01"`、`"Chapter 1"`
4. VLM/LLM返回的 `level == 1` 可转换为 `structure`
5. 如果仍无法识别主章节，进入C兜底扫描

---

## 四、文本型文档路径

### 4.1 目录页检测

文本型文档先用文本特征检测前20页：

- 标题关键词：`目录`、`Contents`、`Table of Contents`
- 页码模式：`标题 ... 数字`
- 章节编号：`第X章`、`1.1`、`一、`
- 连续性：目录页通常连续出现

文本检测失败后再用VLM检测前20页缩略图。

### 4.2 找到目录页后的处理

```python
async def extract_text_toc_entries(page_texts, toc_pages, model, analysis):
    toc_raw = "".join(page_texts[i][0] + "\n" for i in toc_pages)
    analysis["toc_raw"] = toc_raw

    has_page_numbers = analyze_toc_page_numbers(toc_raw)
    analysis["toc_has_page_numbers"] = has_page_numbers

    toc_entries = await transform_toc_to_entries(toc_raw, model)
    # 必须保存，供A/A+B/B-enhanced复用
    analysis["toc_entries"] = toc_entries
    return toc_entries, has_page_numbers
```

### 4.3 分支A：有页码目录

```python
async def branch_a_text(toc_entries, page_texts, model):
    # 1. 使用目录页中的 page 字段
    # 2. 在正文中搜索标题出现位置
    # 3. physical_index - page 取众数作为offset
    # 4. 应用offset并抽样验证
    # 5. 失败时返回 None，由调用方进入A+B
```

### 4.4 分支A+B：无页码目录或A失败

```python
async def branch_ab_text(toc_entries, page_texts, model):
    # 1. 关键词预筛选
    # 2. 对候选页使用 <physical_index_X> 标签
    # 3. LLM确认章节起始页
    # 4. 定位率 >= 70% 成功
    # 5. 失败返回 None，由调用方进入B-enhanced
```

标签格式与PageIndex官方一致：

```text
<physical_index_5>
页面文本
<physical_index_5>
```

### 4.5 B-enhanced：有TOC信息的锚点检测

```python
async def branch_b_enhanced_text(toc_entries, page_texts, model):
    main_chapters = extract_main_chapters(toc_entries)
    if not main_chapters:
        return None  # 进入C

    dividers = locate_main_chapters_by_text(main_chapters, page_texts)
    if len(dividers) < max(1, len(main_chapters) * 0.5):
        return None  # 进入C

    return extract_sections_by_dividers_text(dividers, page_texts, model)
```

### 4.6 B-bare：无TOC信息的锚点检测

```python
def branch_b_bare_text(page_texts):
    """
    无TOC信息时，按 50 → 100 → 150 渐进扫描锚点。
    找到足够分隔页后返回；否则返回空列表，由调用方进入C。
    """
    dividers = []
    scanned = 0
    for max_pages in [50, 100, 150]:
        scan_end = min(len(page_texts), max_pages)
        for i in range(scanned, scan_end):
            text = page_texts[i][0]
            if looks_like_text_divider(text):
                dividers.append(i + 1)

        if len(dividers) >= 2 or scan_end >= len(page_texts):
            break
        scanned = scan_end

    return dividers
```

### 4.7 C：文本全文档扫描

参考PageIndex `process_no_toc`：给每页文本增加 `<physical_index_X>` 标签，按token限制分批，让LLM生成或续写目录结构。

---

## 五、图片型文档路径

### 5.1 目录页检测

图片型文档直接渲染前20页缩略图，由VLM判断目录页，并返回：

```json
{"toc_pages": [3, 4], "has_page_numbers": true, "confidence": "high"}
```

### 5.2 找到目录页后的处理

```python
async def extract_visual_toc_entries(file_path, toc_pages, model, analysis):
    images = render_pages_to_images(file_path, [p - 1 for p in toc_pages], dpi=200)
    toc_entries = await vlm_extract_toc_entries(images, model)

    # 统一字段: structure/title/page
    toc_entries = normalize_toc_entries(toc_entries)
    analysis["toc_entries"] = toc_entries
    analysis["toc_has_page_numbers"] = any(e.get("page") for e in toc_entries)
    return toc_entries, analysis["toc_has_page_numbers"]
```

### 5.3 分支A：有页码目录

图片型offset必须在候选窗口中搜索标题，不能只渲染 `page - 1` 单页。

```python
async def calculate_page_offset_visual(file_path, toc_entries, page_count, model):
    candidates = []
    offset_candidates = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]

    sample_items = [e for e in toc_entries if e.get("page")][:5]
    for item in sample_items:
        for offset in offset_candidates:
            physical_index = item["page"] + offset
            if physical_index < 1 or physical_index > page_count:
                continue

            image = render_page(file_path, physical_index - 1, dpi=180)
            if await vlm_check_title_starts_page(image, item["title"], model):
                candidates.append(offset)
                break

    return most_common(candidates) if candidates else None
```

如果 `offset is None` 或验证准确率不足80%，进入A+B。

### 5.4 分支A+B：无页码目录或A失败

```python
async def branch_ab_visual_search(file_path, toc_entries, page_count, model):
    searched = set()
    found = []

    for max_pages in [50, 100, 150]:
        end = min(max_pages, page_count)
        ranges = build_unsearched_batches(1, end, searched, batch_size=10)

        for start, stop in ranges:
            batch_found = await search_chapters_in_range(
                file_path=file_path,
                toc_entries=toc_entries,
                start_page=start,
                end_page=stop,
                model=model,
            )
            found.extend(batch_found)
            searched.update(range(start, stop + 1))

        match_rate = len(unique_by_structure(found)) / max(1, len(toc_entries))
        if match_rate >= 0.7 or end >= page_count:
            break

    if match_rate >= 0.7:
        return apply_search_results(toc_entries, found)
    return None  # 进入B-enhanced
```

视觉搜索prompt必须携带 `toc_entries`，用于“按图索骥”。

### 5.5 B-enhanced：有TOC信息的锚点检测

```python
async def branch_b_enhanced_visual(file_path, toc_entries, page_count, model):
    main_chapters = extract_main_chapters(toc_entries)
    if not main_chapters:
        return None  # 进入C

    grids = render_thumbnail_grids(file_path, pages=range(min(page_count, 150)))
    prompt = build_enhanced_anchor_prompt(main_chapters)
    result = await vlm_call_with_images(grids, prompt, model)

    dividers = result.get("chapter_dividers", [])
    if not dividers:
        return None  # 进入C

    return extract_sections_by_dividers_visual(file_path, dividers, toc_entries, model)
```

增强锚点检测可以使用TOC主章节作为提示，但不能强迫VLM按TOC生成不存在的分隔页。

### 5.6 B-bare：无TOC信息的锚点检测

B-bare不携带任何目录提示，仅通过通用视觉特征识别分隔页。

```python
async def branch_b_bare_visual(file_path, page_count, model):
    """
    无TOC信息时，按 50 → 100 → 150 渐进扫描视觉锚点。
    找到分隔页后进入分段提取；找不到则返回None，由调用方进入C。
    """
    dividers = []
    scanned = 0
    for max_pages in [50, 100, 150]:
        scan_end = min(page_count, max_pages)
        grids = render_thumbnail_grids(
            file_path,
            pages=range(scanned, scan_end),
            pages_per_grid=12,
        )
        result = await vlm_detect_dividers_bare(grids, model)
        dividers.extend(result.get("chapter_dividers", []))

        if dividers or scan_end >= page_count:
            break
        scanned = scan_end

    if not dividers:
        return None
    return extract_sections_by_dividers_visual(file_path, dividers, None, model)
```

```text
你是PDF文档结构分析专家。这些是文档缩略图网格。

任务：识别章节分隔页。

正例：
1. 空白/极简页：几乎空白，只有Part/Chapter/章节标题
2. 大标题页：页面中央或顶部有明显大标题
3. 风格突变页：背景、排版、插图风格与前后页明显不同

反例：
1. 目录页：有目录/Contents和多个条目
2. 内容页：有正文段落、图表或表格
3. 子章节页：1.1/1.2这类小节标题

约束：
1. 宁可漏判，不要误判
2. 连续标题页只取第一个
3. 排除封面、目录、参考文献、附录索引页
4. 没有明显分隔页时返回空列表

输出JSON：
{"chapter_dividers": [], "confidence": "high|medium|low", "reasoning": "..."}
```

### 5.7 C：图片全文档扫描

最后兜底：按10页一批渲染全文档，让VLM自主发现章节结构，然后去重、排序、构建树。

---

## 六、多来源融合

### 6.1 融合入口

```python
def merge_toc_sources(file_path, toc_from_page, toc_from_search, dividers, extracted_items):
    """
    toc_from_page: 目录页提取结构，可为空
    toc_from_search: 正文搜索定位结果，可为空
    dividers: 锚点检测结果，可为空
    extracted_items: 分段提取或全文档扫描结果，可为空
    """
```

### 6.2 融合规则

1. 如果有 `toc_from_page`，它作为结构骨架。
2. `toc_from_search` 只补充 `physical_index`，不覆盖标题。
3. `dividers` 通过提取分隔页标题后与TOC标题模糊匹配，不能按数组索引映射。
4. 如果没有 `toc_from_page`，使用 `extracted_items` 作为骨架。
5. 未匹配的divider可以作为额外主章节，但必须去重。

```python
def merge_toc_sources(file_path, toc_from_page, toc_from_search, dividers, extracted_items):
    base_items = toc_from_page or extracted_items or []
    merged = {item["structure"]: dict(item) for item in base_items}

    for item in toc_from_search or []:
        struct = item.get("structure")
        if struct in merged and item.get("physical_index"):
            merged[struct].setdefault("physical_index", item["physical_index"])

    for div_page in dividers or []:
        div_title = extract_divider_title(file_path, div_page)
        matched_struct = find_best_title_match(div_title, merged.values())
        if matched_struct:
            merged[matched_struct]["physical_index"] = div_page
        elif div_title:
            struct = next_main_structure(merged)
            merged[struct] = {
                "structure": struct,
                "title": div_title,
                "physical_index": div_page,
            }

    return build_tree(sorted(merged.values(), key=lambda x: x.get("physical_index") or 10**9))
```

---

## 七、当前待改进点

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P0 | 保存 `toc_entries` | 文本型和图片型找到目录页后都必须保存结构化TOC |
| P0 | A+B正文搜索 | 无页码目录不能直接进入B-bare |
| P0 | 图片offset候选窗口 | 图片型不能使用文本fuzzy match，也不能只验证单页 |
| P1 | B-enhanced实现 | A/A+B失败后携带TOC结构继续锚点检测 |
| P1 | 渐进搜索 | 统一 `50 → 100 → 150 → C` |
| P1 | 主章节识别 | 兼容 `1`、`第一章`、`Part 01`、`level==1` |
| P2 | 融合策略 | divider通过标题匹配，不按索引匹配 |

---

## 八、v4.1修正点

相比v4.0，本版本修正以下问题：

1. 顶层图明确 `B-enhanced/B-bare` 失败后进入C，而不是直接进入Phase 2。
2. 文本型目录提取后也保存 `analysis["toc_entries"]`。
3. `B-enhanced` 增加 `main_chapters` 为空的兜底逻辑。
4. 图片A+B函数签名补齐 `page_count`。
5. 图片A+B渐进搜索改为增量扫描，避免重复扫描同一范围。
6. 图片offset改为候选窗口搜索标题，不再单页验证后读取不存在的 `physical_index`。
7. 主章节识别不再只依赖 `"." not in structure`。
8. `merge_toc_sources()` 补齐 `file_path` 和 `extracted_items` 入参，可处理B-bare/C结果。
9. 扫描范围统一为 `50 → 100 → 150 → C`。
10. 明确只有 `B-enhanced` 使用目录信息，`B-bare` 不使用目录信息。
