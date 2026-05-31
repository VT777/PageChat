"""
分析：如果"汇报提纲"被识别为 divider，代码路径会如何执行？
"""
import sys, os
sys.path.insert(0, 'backend')

print("="*80)
print("代码路径分析：汇报提纲作为 divider 的影响")
print("="*80)

print("""
当前代码逻辑（build_balanced_toc_visual）：

if toc_pages:           # 如果[2,3,13,35,49,61]是toc_pages，进入Branch A
    -> Branch A: 提取目录结构 + 页码映射
    
elif dividers:         # 如果[2,3,13,35,49,61]是dividers，进入Branch B
    if density > 0.4:
        -> Branch B-dense: 直接看divider页缩略图提取标题
    else:
        -> Branch B-normal: 按divider分组，每组分析子章节
        
else:                   # 如果都没有，进入Branch C
    -> Branch C: 全文扫描

问题分析：
"""
)

scenarios = [
    {
        'name': '场景1: 汇报提纲作为 toc_pages',
        'toc_pages': '[2,3,13,35,49,61]',
        'dividers': '[]',
        'path': 'Branch A',
        'issues': [
            'Branch A期望目录页有页码，但汇报提纲没有页码',
            'VLM从汇报提纲提取结构后，无法映射页码',
            '会触发uniform distribution，页码不准'
        ]
    },
    {
        'name': '场景2: 汇报提纲作为 dividers',
        'toc_pages': '[]',
        'dividers': '[2,3,13,35,49,61]',
        'path': 'Branch B',
        'issues': [
            'Branch B-dense: 看汇报提纲缩略图，提取的标题都是"汇报提纲"',
            'Branch B-normal: 从汇报提纲页开始分析，把提纲当正文',
            '章节标题丢失，子章节结构混乱'
        ]
    },
    {
        'name': '场景3: 混合策略（推荐）',
        'toc_pages': '[2,3]（仅文档开头）',
        'dividers': '[3,13,35,49,61]（含第1章开始）',
        'path': 'Branch A + 修正',
        'issues': [
            '需要识别P2-P3是总提纲，P13等是章节分隔',
            '需要从汇报提纲提取章节标题和结构'
        ]
    }
]

for s in scenarios:
    print(f"\n{s['name']}:")
    print(f"  toc_pages: {s['toc_pages']}")
    print(f"  dividers: {s['dividers']}")
    print(f"  进入路径: {s['path']}")
    print(f"  潜在问题:")
    for issue in s['issues']:
        print(f"    - {issue}")

print("\n" + "="*80)
print("鲁棒方案设计")
print("="*80)

print("""
核心洞察：
"汇报提纲"类页面是特殊的——它们既是章节边界（divider）又是结构信息来源（toc）

方案设计：

1. 识别阶段（Anchor Detection）
   - 检测所有"汇报提纲"类页面
   - 第一个/前两个标记为 toc_pages（总提纲）
   - 所有标记为 special_dividers（特殊分隔页）

2. 处理阶段（Branch处理）
   
   如果存在 special_dividers:
     a) 提取 special_dividers 的章节结构（类似Branch A）
     b) 用 special_dividers 作为章节边界
     c) 合并结构和边界生成完整TOC
   
   否则:
     走原有Branch A/B/C逻辑

3. 页码映射
   - special_dividers 的位置就是章节开始页码
   - 子章节页码用均匀分布或正文扫描补充

优势：
- 兼容传统目录页文档（不受影响）
- 兼容汇报提纲类文档（正确处理）
- 不增加额外的VLM调用（复用divider页图片）
""")
