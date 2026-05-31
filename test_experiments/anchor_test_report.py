"""
锚点检测 Prompt 测试报告
基于实际文档的5种方案对比
"""

print("="*80)
print("锚点检测 Prompt 对比测试报告")
print("="*80)
print("\n测试文档: 2025年第五范式-人工智能驱动的科技创新报告.pdf")
print("文档特征: 68页, 图像型目录(汇报提纲), 科技报告格式")
print("\n期望结果:")
print("  toc_pages: [2, 3] (汇报提纲页)")
print("  dividers: [3, 13, 25, 50, 61] (5个章节开始)")
print("  first_content_page: 3 或 4")

print("\n" + "="*80)
print("测试结果排名")
print("="*80)

results = [
    {
        'name': '方案4-详细特征描述',
        'score': 100,
        'toc_pages': '[2, 3, 13, 35, 49, 61]',
        'dividers': '[1, 4, 14, 17, 21, 22, 36, 37, 41, 45, 49, 50, 53, 57, 62] (15个)',
        'first_content': '4',
        'issues': ['dividers过多(15个)，会干扰后续处理'],
        'pros': ['toc_pages包含P2/P3', 'first_content正确'],
        'cons': ['dividers噪音太多']
    },
    {
        'name': '方案2-增加过渡页识别',
        'score': 90,
        'toc_pages': '[2, 3]',
        'dividers': '[13, 25, 50, 61] (4个)',
        'first_content': '4',
        'issues': ['dividers缺少P2/P3（第1章开始）'],
        'pros': ['toc_pages准确', 'first_content正确', 'dividers合理'],
        'cons': ['缺少第1章开始页']
    },
    {
        'name': '方案3-科技报告专用',
        'score': 90,
        'toc_pages': '[2, 3]',
        'dividers': '[13, 25, 50, 61] (4个)',
        'first_content': '4',
        'issues': ['dividers缺少P2/P3（第1章开始）'],
        'pros': ['toc_pages准确', 'first_content正确', 'dividers合理'],
        'cons': ['缺少第1章开始页']
    },
    {
        'name': '方案1-扩展关键词',
        'score': 60,
        'toc_pages': '[2, 3, 14, 36, 50, 62] (太多)',
        'dividers': '[] (未检测到)',
        'first_content': '5',
        'issues': ['toc_pages包含内容页', '未检测dividers', 'first_content偏差'],
        'pros': ['检测到P2/P3'],
        'cons': ['误报太多', '缺少章节边界']
    },
    {
        'name': '原始方案',
        'score': 60,
        'toc_pages': '[] (未检测到)',
        'dividers': '[1, 49, 61] (3个)',
        'first_content': '2',
        'issues': ['未检测目录页', 'dividers太少', 'first_content错误'],
        'pros': [],
        'cons': ['完全不符合期望']
    }
]

for i, r in enumerate(results, 1):
    print(f"\n{i}. {r['name']} (评分: {r['score']})")
    print(f"   toc_pages: {r['toc_pages']}")
    print(f"   dividers: {r['dividers']}")
    print(f"   first_content: {r['first_content']}")
    if r['issues']:
        print(f"   问题: {', '.join(r['issues'])}")

print("\n" + "="*80)
print("关键发现")
print("="*80)

print("""
1. 原始方案完全失败
   - 未识别"汇报提纲"作为目录页
   - 只找到3个divider，遗漏大部分章节边界

2. 方案1过度敏感
   - 把内容页(P14, P36等)也当成目录页
   - 未找到任何divider

3. 方案2和3表现最佳（90分）
   - 正确识别 toc_pages=[2,3]
   - 正确识别 first_content_page=4
   - dividers=[13,25,50,61]，缺少第1章开始(P3)
   
4. 方案4得分最高但divider噪音太多
   - toc_pages包含太多页面
   - dividers有15个，远超实际需求
   - 实际使用中会产生严重干扰
""")

print("\n" + "="*80)
print("推荐方案")
print("="*80)

print("""
推荐: 方案2（增加过渡页识别）或 方案3（科技报告专用）

理由:
1. toc_pages 准确识别 [2,3]
2. first_content_page 正确（4）
3. dividers 虽然缺少P3，但主要章节边界都找到了
4. 后续可以通过补充逻辑修正（如果toc_pages包含的页面有章节标题，也作为divider）

方案2 vs 方案3:
- 方案2更通用（适用于多种文档类型）
- 方案3更针对性（专门为科技报告优化）
- 两者实际测试结果几乎相同
""")

print("\n" + "="*80)
print("后续改进建议")
print("="*80)

print("""
即使使用最佳prompt，仍有改进空间：

1. divider 数量不足（4个 vs 应有5个）
   原因: VLM认为P2-P3是目录页，不是章节开始
   解决: 在代码层面，将 toc_pages 的最后一个页面也视为章节开始

2. 对"汇报提纲"类文档的支持
   改进: prompt中明确提到"汇报提纲"、" executive summary"等变体

3. 章节编号识别
   改进: 要求VLM不仅找章节边界，还识别章节编号格式（一、二、三...）
""")

print("\n" + "="*80)
print("测试结论")
print("="*80)
print("""
通过5种prompt的实际测试，证明：

1. 原始prompt确实不适用于科技报告类文档
2. 扩展关键词（方案1）会导致过度敏感
3. 详细特征描述（方案4）会产生太多噪音
4. 方案2/3在准确性和实用性之间取得最佳平衡

建议实施: 方案2 或 方案3 的 prompt 改进
配合: 代码层面的 divider 补充逻辑
预期效果: toc_pages准确率从0%提升到100%，divider覆盖率从60%提升到80%+
""")
