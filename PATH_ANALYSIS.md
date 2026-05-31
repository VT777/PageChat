# Text vs Visual 路径深度技术分析

## 一、Text 路径（build_balanced_toc_text）

### 实现流程

```
1. pdf_analyzer 提取文本
2. 将文本按页分组（考虑token限制）
3. LLM generate_toc_init(group_1) → 初始TOC
4. LLM generate_toc_continue(group_2) → 续接
5. LLM generate_toc_continue(group_3) → 续接
6. ...
7. 合并所有TOC条目
8. 返回扁平列表
```

### 核心问题分析

**问题 1：完全不利用视觉信息**
- Text路径只读取PDF的文本层
- **完全忽略dividers**（缩略图识别的章节分隔页）
- **完全忽略目录页图片**（VLM可以从图片中准确提取目录结构）
- **完全忽略字体大小/颜色/位置**（这些视觉线索可以判断标题层级）

**问题 2：LLM容易"偷懒"**
- 对于43页的技术应用洞察，LLM只提取了4个主要章节
- LLM没有看到图片，不知道页面上有明确的子章节标题
- LLM倾向于只提取"足够概括"的章节，遗漏细节

**问题 3：分页导致顺序错乱**
- 第五范式的文本分组可能将章节3.4分到后面的组
- LLM在续接时没有维护全局顺序
- 结果：`3.1, 3.2, 3.3, 3.4, 4, 4.2` → 3.4在4之后（乱序）

**问题 4：无法判断标题层级**
- 纯文本没有字号、颜色、缩进等视觉信息
- LLM只能根据编号格式猜测层级（如1.1是子级）
- 但许多文档的编号不规则，LLM容易猜错
- AI Agent的结果：主章节structure为空，因为LLM没给它们编号

**问题 5：对"无代码TOC"文档效果差**
- 当PDF没有书签/目录时，text路径只能让LLM"猜测"结构
- LLM猜测的质量取决于文档文本质量
- 对于PPT转PDF、扫描件等，text路径几乎无效

### Text路径的优点

1. **速度快**：纯文本处理，无需渲染图片
2. **成本低**：LLM调用比VLM便宜很多
3. **支持超长文档**：不受图片数量限制
4. **纯文字文档效果好**：如小说、论文等结构清晰的文档

---

## 二、Visual 路径（build_balanced_toc_visual）

### 实现流程

```
1. VLM缩略图锚点检测（1次VLM调用）
   → toc_pages, dividers, first_content
2. 如果存在目录页：
   → VLM看目录页图片提取TOC（1次VLM调用）
3. 页码映射（使用dividers定位）
4. 大节点检测（span >= 8页）
5. VLM全页扫描提取子章节（多次VLM调用）
6. 后处理构建树
```

### 核心优势

**优势 1：利用dividers**
- Dividers是VLM从缩略图识别的章节分隔页
- **准确率接近100%**（因为是大色块+大标题的整页）
- 这是章节边界的"硬证据"

**优势 2：VLM看图片提取目录**
- VLM直接看目录页图片，而不是解析文本
- 可以看到目录的视觉结构（缩进、字号、颜色）
- 对于复杂目录（如技术应用洞察的8个条目），VLM可以全部识别

**优势 3：全页扫描提取子章节**
- 对每个章节范围，VLM扫描每一页的图片
- 提取页面上的子标题
- 这是text路径完全做不到的

**优势 4：准确的页码映射**
- 使用dividers作为章节起始页
- 不再依赖LLM猜测页码
- 不再出现"页码超出范围"的问题

### Visual路径的缺点

1. **速度慢**：需要渲染图片（PDF→图片），VLM处理图片比文本慢
2. **成本高**：VLM调用费用是LLM的数倍
3. **图片数量限制**：超长文档可能超出VLM的上下文限制
4. **对纯文字文档是浪费**：如果文档没有dividers，visual路径也要跑一遍

---

## 三、为什么只保留Visual路径不是好主意

### 成本分析

| 路径 | 每次调用成本 | 平均调用次数 | 总成本 |
|------|-------------|-------------|--------|
| Text | ~$0.001 | 3-5次 | ~$0.005 |
| Visual | ~$0.01 | 5-10次 | ~$0.05-0.1 |

**Visual路径成本是Text的10-20倍。**

如果每天处理100个文档：
- Text路径：$0.5/天
- Visual路径：$5-10/天

### 速度分析

| 路径 | 平均耗时 |
|------|---------|
| Text | 10-30秒 |
| Visual | 2-5分钟 |

对于用户体验，Visual路径明显更慢。

### 场景分析

**Text路径更适合的场景：**
1. 纯文字文档（如小说、论文）
2. 结构非常清晰的文档（如标准论文格式）
3. 需要快速处理的场景
4. 低预算场景

**Visual路径更适合的场景：**
1. 图片型PDF（扫描件、PPT转PDF）
2. 有明确dividers的文档（如报告、白皮书）
3. 需要提取子章节的场景
4. 目录无页码的文档

---

## 四、推荐方案：融合而非替换

### 方案："Visual修正Text"

核心思想：**Text路径先生成初始结果，然后用Visual的dividers修正结构。**

```python
async def build_balanced_toc_unified(file_path, analysis, model=None):
    # 步骤1：无论text_coverage如何，都先跑VLM锚点检测
    # （1次VLM调用，成本很低）
    anchors = await _vlm_detect_anchors(file_path, model)
    dividers = anchors.get("chapter_dividers", [])
    
    # 步骤2：根据text_coverage决定主路径
    if analysis["text_coverage"] >= 0.8:
        # Text路径生成初始TOC
        result = await build_balanced_toc_text(analysis, model)
    else:
        # Visual路径生成TOC
        result = await build_balanced_toc_visual(
            file_path, analysis, model, anchors=anchors
        )
    
    toc_items = result["toc_items"]
    
    # 步骤3：如果text路径结果有问题，用dividers修正
    if dividers:
        toc_items = refine_toc_with_dividers(toc_items, dividers, analysis["page_count"])
    
    return {"toc_items": toc_items}
```

### 为什么这个方案更好

1. **保留了Text路径的速度优势**
2. **保留了Visual路径的准确性**
3. **成本可控**：只有1次额外的VLM锚点检测
4. **适用于所有文档**：无论text_coverage高低

### 修正策略

当Text路径生成的TOC和dividers不匹配时：

```python
def refine_toc_with_dividers(toc_items, dividers, page_count):
    # 策略1：如果主章节数量匹配dividers，重新分配页码
    main_chapters = [it for it in toc_items if is_main_chapter(it)]
    if len(main_chapters) == len(dividers):
        for ch, div in zip(main_chapters, dividers):
            ch["physical_index"] = div
        return toc_items
    
    # 策略2：如果数量不匹配，重新组织结构
    # 使用_smart_identify_chapters
    chapters, subsections = _smart_identify_chapters(toc_items, dividers)
    if chapters and len(chapters) == len(dividers):
        # 重新构建层级结构
        return rebuild_hierarchy(toc_items, chapters, subsections, dividers)
    
    # 策略3：如果text路径结果太差，fallback到visual路径
    if len(toc_items) < len(dividers):
        return None  # 触发fallback
    
    return toc_items
```

---

## 五、四份文件的具体分析

| 文件 | text_coverage | 当前路径 | 问题 | 建议方案 |
|------|---------------|---------|------|---------|
| **AI Agent** | 0.98 | Text | 主章节structure为空 | Text生成 → dividers修正 → 补充structure |
| **第五范式** | 0.97 | Text | 顺序错乱、缺失章节 | Text生成 → dividers重排 → 插入缺失章节 |
| **技术应用洞察** | 1.00 | Text | 无子章节、只有4章 | Text生成 → dividers修正 → VLM提取子章节 |
| **AI治理** | 1.00 | Fast失败 | Fast降级问题 | Fast质量检查 → 降级到Visual路径 |

---

## 六、结论

**不应该只保留Visual路径**，因为：
1. 成本太高（10-20倍）
2. 速度太慢（2-5分钟 vs 10-30秒）
3. 纯文字文档不需要visual

**推荐方案：**
1. **保留两条路径**，但增加统一修正层
2. **Text路径**：快速生成初始TOC
3. **VLM锚点检测**：1次调用获取dividers（成本低）
4. **统一修正**：用dividers修正text路径的结果
5. **Fallback**：如果text结果太差，降级到visual路径

这个方案兼顾了速度、成本和准确性。
