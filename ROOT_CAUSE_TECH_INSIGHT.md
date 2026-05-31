"""ROOT CAUSE ANALYSIS: 技术应用洞察报告 TOC 不准确

问题: TOC 只有大标题，缺少子章节
根本原因: Branch A 的均匀分布策略导致章节边界错误，阻止了完整扫描触发
"""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

print("="*70)
print("ROOT CAUSE ANALYSIS: 技术应用洞察报告")
print("="*70)

print("""
## 现象

用户反馈: "2025全球人工智能技术应用洞察报告.pdf还是只有大标题"

实际测试结果:
- Visual 路径被触发 ✓
- 但 TOC 只有 8 个 items，且大多数没有子章节
- 覆盖率为 100%，但结构不完整

## 诊断过程

### Step 1: 检查 Visual 路径提取的原始 TOC

Branch A 提取结果:
```
[0] structure='第一章' physical_index=5   title='全球人工智能技术发展现状'
[1] structure='2'      physical_index=10  title='全球数据算力算法变化对产业影响'
[2] structure='第二章' physical_index=15  title='AI十大行业应用洞察'
[3] structure='4'      physical_index=20  title='AI在各行各业应用价值...'
[4] structure='第三章' physical_index=24  title='全球人工智能应用突破'
[5] structure='6'      physical_index=29  title='人工智能应用关键价值...'
[6] structure='第四章' physical_index=34  title='全球人工智能应用未来趋势'
[7] structure='8'      physical_index=39  title='技术趋势、市场趋势...'
```

### Step 2: 分析章节跨度

计算每个 item 的跨度（到下一个 item 的距离）:
```
p.5-9   span=5: 全球人工智能技术发展现状
p.10-14 span=5: 全球数据算力算法变化对产业影响
p.15-19 span=5: AI十大行业应用洞察
p.20-23 span=4: AI在各行各业应用价值...
p.24-28 span=5: 全球人工智能应用突破
p.29-33 span=5: 人工智能应用关键价值...
p.34-38 span=5: 全球人工智能应用未来趋势
p.39-43 span=5: 技术趋势、市场趋势...
```

**关键发现**: 所有跨度都是 4-5 页，没有一个 >= 8 页！

### Step 3: 为什么均匀分布？

查看 `_map_toc_physical_pages` 的日志:
```
[TOC-MAP] No logical pages found, using uniform distribution
```

这意味着:
1. 目录页（TOC page）上没有可识别的页码
2. 系统退而求其次，使用均匀分布策略
3. 8 个 items 被均匀分布在 43 页中

### Step 4: 为什么完整扫描没有触发？

完整扫描触发条件:
```python
need_full_scan = len(toc_items) < 10 and large_count > 0 and model
```

由于均匀分布导致所有跨度都是 5 页:
- large_count = 0（没有节点跨度 >= 8）
- need_full_scan = False

**完整扫描被阻止了！**

### Step 5: 完整扫描能提取什么？

手动运行完整扫描测试:
- 提取了 40 个页面标题
- 包括 11 个 chapter 类型页面
- 29 个 content 类型页面
- 每个章节都有丰富的子章节

例如 Chapter 2 (p.11-23) 有 9 个子项:
- AI智能计算行业应用价值概述
- 全球重点行业人工智能渗透率
- 智能制造
- 智慧金融
- 医疗健康
- 智慧交通
- ...

### Step 6: 为什么之前测试显示 32 个 items？

之前的 `debug_full_scan.py` 测试直接调用了 `_vlm_scan_document_pages`，
绕过了 `build_balanced_toc_visual` 的完整流程。

而实际流程中，由于 `need_full_scan = False`，完整扫描不会执行。

## 根本原因总结

```
┌─────────────────────────────────────────────────────────────┐
│  目录页无页码 → 均匀分布 → 所有跨度≈5页 → large_count=0  │
│                                              ↓              │
│  完整扫描不触发 ← need_full_scan=False ← 没有大节点      │
│                                              ↓              │
│                    TOC 只有 8 个大标题，缺少子章节         │
└─────────────────────────────────────────────────────────────┘
```

## 正确预期 vs 实际结果

预期结构（基于 dividers [5,13,25,38]）:
```
第一章: p.5-12  (8页)  - 应该有 6 个子章节
第二章: p.13-24 (12页) - 应该有 9 个子章节
第三章: p.25-37 (13页) - 应该有 9 个子章节
第四章: p.38-43 (6页)  - 应该有 4 个子章节
```

实际结果:
```
第一章: p.5-9   (5页)  - 0 个子章节
第二章: p.15-19 (5页)  - 0 个子章节  ← 位置错误！
第三章: p.24-28 (5页)  - 0 个子章节  ← 位置错误！
第四章: p.34-38 (5页)  - 0 个子章节  ← 位置错误！
```

## 关键问题

1. **均匀分布策略不适合这种文档**
   - 章节长度不均匀（8页、12页、13页、6页）
   - 均匀分布将长章节拆分成了多个假章节

2. **大节点检测阈值过高**
   - LARGE_NODE_THRESHOLD = 8
   - 均匀分布后最大跨度只有 5 页
   - 即使章节实际跨度 13 页，也被均匀分布掩盖了

3. **未使用 dividers 修正分布**
   - 有 4 个 dividers: [5, 13, 25, 38]
   - 这些 dividers 已经知道章节边界
   - 但没有用于修正均匀分布的结果

## 修复方案

### 方案 A: 当使用均匀分布时，强制使用 dividers 修正
- 如果 `_map_toc_physical_pages` 使用了均匀分布
- 且存在 dividers
- 则用 dividers 重新分配主章节的位置

### 方案 B: 降低大节点检测阈值或改变触发条件
- 当使用均匀分布时，降低 LARGE_NODE_THRESHOLD
- 或者改为：如果 items < 10 且 text_coverage < 0.5，强制完整扫描

### 方案 C: 后处理阶段使用 dividers 修正
- 在 `post_process_toc` 中
- 如果顶级节点数量与 dividers 不匹配
- 用 dividers 重新对齐章节边界

## 推荐方案: A + B

1. **在 Branch A 中**：如果使用均匀分布 + 有 dividers → 用 dividers 修正
2. **在 Branch A 中**：如果使用均匀分布 → 降低 large_count 阈值到 5
3. **作为兜底**：如果文本质量低（is_garbled）→ 强制完整扫描
""")

print("="*70)
print("ANALYSIS COMPLETE")
print("="*70)
