# TOC生成问题根因分析报告

## 执行摘要

经过系统分析，发现所有6个问题共享**3个核心根因**：

1. **图/表目录分类逻辑缺陷** (影响问题1,3,4,5,6)
2. **VLM/Text路径子章节提取不足** (影响问题2)
3. **页码分配机制粗糙** (影响问题2,3,4)

---

## 问题1: AI_Agent - 无中生有图目录和表目录

**文档**: 2026年AI Agent智能体技术发展报告.pdf
**路径**: fast → bookmarks
**现象**: 生成了图目录(4条)和表目录(1条)，但原文没有

### 根因分析

**代码位置**: `post_processing.py:620-632` (classify_node_type函数)

```python
def classify_node_type(node):
    title = str(node.get("title", "")).lower()
    number = str(node.get("number", "")).lower()
    text = f"{number} {title}"
    
    if any(k in text for k in ['图', 'figure', 'fig.']):
        return "figure"
    if any(k in text for k in ['表', 'table']):
        return "table"
    return "chapter"
```

**问题**: 该函数仅基于关键词匹配，无法区分：
- **章节标题**: "四层产业生态图谱"、"一张图看懂主流工具"、"决策流程图"
- **真实图表条目**: "图1 产业生态图"、"表1 对比数据"

**验证结果**:
```
AI_Agent 图目录中的节点:
  1. "四层产业生态图谱" (structure: 1.3.2) ← 子章节，有上下文
  2. "综合对比：一张图看懂主流工具" (structure: 3.4.1) ← 子章节
  3. "决策流程图" (structure: 3.4.3) ← 子章节
  4. "AI Agent 的未来技术图景" (structure: 6.1) ← 子章节

AI_Agent 表目录中的节点:
  1. "多模态信息的统一表征" (structure: 2.2.1) ← 子章节
```

**关键发现**: 这些被误分类的节点都有**完整的structure编号**（如1.3.2, 3.4.1），说明它们是正文中的章节标题，而非独立的图表条目。

### 正确vs错误分类的特征

| 特征 | 章节标题（错误） | 图表条目（正确） |
|------|----------------|----------------|
| structure | "1.3.2", "3.4.1"（有层级） | "" 或 "1", "2"（简单编号） |
| 标题格式 | "xx图谱"、"xx图"、"流程图" | "图1 xxx"、"Figure 1" |
| 在TOC中的位置 | 混杂在章节中 | 集中在"图目录"节点后 |
| 子节点 | 可能有 | 无 |

### 根因1: 缺乏上下文感知

系统应该检查：
1. 是否有独立的"图目录"/"表目录"节点
2. 该节点后是否有连续的"图1"/"表1"条目
3. 节点structure是否为简单编号（非层级）

---

## 问题2: AI_Applications - 只有一级目录且不准确

**文档**: 2026AI应用专题：各大厂新模型持续迭代，重视AI应用板块投资机会.pdf
**路径**: balanced → visual → vlm_toc
**现象**: 只有5个一级节点，无子章节，页码不准确

### 根因分析

**提取结果**:
```
structure: 01, "国外大厂AI应用落地" (p.4-7)
structure: 02, "国内大厂AI应用落地" (p.8-12)
structure: 03, "产业链梳理" (p.13-17)
structure: 04, "风险提示" (p.18-21)
```

**问题1: VLM只提取了一级标题**
- VLM的prompt没有明确要求提取子章节
- VLM倾向于只输出主要章节，忽略子章节

**问题2: structure格式异常**
- VLM输出"01", "02"而不是"1", "1.1"
- build_tree函数按"01"处理为顶级节点

**问题3: 页码不准确**
- 第1个节点"国外大厂AI应用落地"只占4页(p.4-7)
- 但实际章节可能更长，VLM只捕获了标题页

### 根因2: VLM路径缺乏子章节提取

与hierarchical_extractor.py的设计对比：
- **hierarchical_extractor**: Phase 1提取框架 → Phase 2逐章展开子章节
- **visual路径**: 一次性VLM调用，只提取可见的主要标题

---

## 问题3: Compliance_Guide - 表目录抽取错误

**文档**: 生成式人工智能服务合规备案指南（2026年）.pdf
**路径**: fast → bookmarks
**现象**: 表目录包含5个明显错误的条目

### 根因分析

**表目录中的节点**:
```
1. "（一）生成式人工智能服务上线备案申请表" (structure: 3.2.1)
2. "（五）拦截关键词列表" (structure: 3.2.5)
3. "生成式人工智能服务备案由网信部门通知..." (structure: 3.3.3, 长文本)
4. "全国人民代表大会常务委员会" (structure: 5.48)
5. "全国人民代表大会常务委员会" (structure: 5.52, 重复)
```

**问题**: 节点1-2包含"表"/"列表"字样被误分类，节点3-5更奇怪...

**深入分析**: 
- 节点1-2确实是章节标题（structure: 3.2.1, 3.2.5），包含"表"字
- 节点3-5的structure是5.48, 5.52，说明是第五章的子章节
- 这些节点的原始数据中可能有`number`字段包含"表"字

### 根因1续: 关键词匹配过于粗暴

"申请表"、"关键词列表"、"常务委员会"（可能OCR误识别）都被匹配到了"表"字。

---

## 问题4: FMCG_AI_Marketing - 不应有图目录

**文档**: 2026年快消行业AI营销增长白皮书.pdf
**路径**: balanced → visual → vlm_toc
**现象**: 生成了图目录(2条)，但原文没有

### 根因分析

**图目录中的节点**:
```
1. "小红书 | 不仅是内容种草..." (structure: "")
2. "AI时代·企业全链路数据资产图谱..." (structure: "")
```

**问题**: 
- 节点1标题不含"图"字，为什么被分类？→ 可能原始VLM数据中有其他字段
- 节点2含"图谱"二字

**关键**: 这两个节点的structure都是空字符串""。在build_tree中，空structure的节点被提升为根节点。

### 根因1续: 空structure节点被误分类

空structure的节点（通常是图表条目）被classify_node_type分类后，由于structure为空，在build_tree中被作为独立根节点处理，然后被归入图目录组。

---

## 问题5: AI_Glasses - 有图目录和表目录但没抽取

**文档**: AI眼镜关键技术与产业生态研究报告（2025年）.pdf
**路径**: balanced → text → llm_text
**现象**: 无图目录/表目录组

### 根因分析

**提取结果**: 只有目录组(6个节点)，无图/表组

**可能原因**:
1. LLM提取的TOC中没有包含图表条目
2. 或者图表条目被filter_figure_catalogs过滤了

**关键**: 
- filter_figure_catalogs只过滤标题为"图目录"/"表目录"的节点
- 如果LLM没有提取"图1 xxx"这样的具体条目，就不会有图目录组

### 根因: LLM未提取图表条目

Text路径的LLM prompt可能没有要求提取图表信息，或者LLM认为图表不重要而省略了。

---

## 问题6: AI_Safety - 有图目录但没抽取

**文档**: 人工智能安全治理研究报告（2025年）.pdf
**路径**: fast → bookmarks
**现象**: 无图目录组

### 根因分析

**提取结果**: 只有目录组(8个节点)

**可能原因**: 同问题5 - 书签中没有包含图表条目，只有"图目录"节点被filter_figure_catalogs过滤掉了。

---

## 根因总结

### 根因A: 图/表目录分类逻辑缺陷 (影响问题1,3,4,5,6)

**位置**: `post_processing.py:620-632`

```python
def classify_node_type(node):
    # 致命缺陷: 仅基于关键词，无上下文感知
    if any(k in text for k in ['图', 'figure', 'fig.']):
        return "figure"
    if any(k in text for k in ['表', 'table']):
        return "table"
```

**应该做的检查**:
1. ✅ 节点structure是否为简单编号（非层级）
2. ✅ 标题是否匹配"图N"或"表N"格式
3. ✅ 是否有明确的"图目录"/"表目录"前置节点
4. ✅ 节点是否集中在文档特定区域

### 根因B: VLM路径缺乏子章节提取 (影响问题2)

**位置**: `balanced_toc.py:visual路径`

VLM路径只提取一级标题，没有：
1. 逐章展开子章节的机制
2. 对structure格式的标准化（"01" → "1"）
3. 页码验证和修正

### 根因C: 页码分配机制粗糙 (影响问题2,3,4)

**位置**: `post_processing.py:147-158`

```python
def assign_page_ranges(toc_items, page_count):
    for i, item in enumerate(toc_items):
        item["start_index"] = item["physical_index"]
        if i < len(toc_items) - 1:
            next_start = toc_items[i + 1]["physical_index"]
            item["end_index"] = max(next_start - 1, item["start_index"])
```

问题：
- 简单使用下一个节点的start作为当前节点的end
- 没有考虑子章节穿插的情况
- 导致页码范围不准确（如35-35只有1页）

---

## 修复建议（不修改代码）

### 短期修复

1. **提高分类阈值**: 图目录/表目录最少需要3-5个条目才创建组
2. **structure验证**: 只有structure为空或简单数字的节点才分类为图表
3. **格式检查**: 标题必须匹配"图N"或"Figure N"格式

### 中期修复

1. **上下文感知分类**: 
   - 检测是否有"图目录"节点
   - 只分类该节点之后的连续条目
   
2. **VLM prompt优化**:
   - 要求VLM提取所有级别的标题
   - 标准化structure格式
   - 包含图表条目

3. **页码分配改进**:
   - 使用子节点的end_index计算父节点范围
   - 处理穿插结构

### 长期修复

1. **分层提取架构**: 对visual路径也实现Phase 1/2/3分层提取
2. **智能检测**: 使用LLM判断文档是否有图/表目录
3. **后处理增强**: 基于文档结构而非关键词进行分类
