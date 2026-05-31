"""
测试不同锚点检测 Prompt 的效果
对比 4 种改进方案 + 原始方案
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.vlm_utils import render_thumbnail_grids, vlm_call_with_images, parse_vlm_json

doc_dir = os.path.join(os.path.dirname(__file__), '..', 'backend', 'data', 'documents')
target_file = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target_file = os.path.join(doc_dir, f)
        break

# 渲染缩略图网格
print("Rendering thumbnail grids...")
grids = render_thumbnail_grids(target_file, pages_per_grid=12, cols=4)
grid_images = [{"page_index": 0, "image_base64": g["image_base64"]} for g in grids]
print(f"Rendered {len(grids)} grids ({len(grids)*12} pages)")

# Ground truth
ground_truth = {
    'toc_pages': [2, 3],  # 汇报提纲页
    'dividers': [2, 3, 13, 25, 50, 61],  # 每个大章节的开始
    'first_content_page': 4  # 1.1 开始
}

# 定义多个 prompt 方案
prompts = {
    "原始": """你是文档分析专家。这些是一份 PDF 文档所有页面的缩略图网格。
每个缩略图左上角标注了页码（如 p.1, p.2...）。

请识别以下两类特殊页面：

1. 目录页（Table of Contents）：页面上有结构化的章节标题列表，通常有"目录"或"CONTENTS"字样
2. 章节分隔页（Chapter Divider）：整页是一个大标题，通常有色块背景，正文文字很少

另外，请判断第一个章节内容（非封面、非目录、非前言）实际从哪一页开始。

回答 JSON（不要 markdown code fence）:
{{
  "toc_pages": [4],
  "chapter_dividers": [5, 13, 25, 35, 41],
  "first_content_page": 5
}}

如果没有找到目录页或分隔页，对应数组返回空 []。""",

    "方案1-扩展关键词": """你是文档分析专家。这些是一份 PDF 文档所有页面的缩略图网格。
每个缩略图左上角标注了页码（如 p.1, p.2...）。

请识别以下两类特殊页面：

1. 目录页（Table of Contents）：页面上有结构化的章节标题列表，关键词包括"目录"、"CONTENTS"、"提纲"、"大纲"、"Outline"、"Summary"
2. 章节分隔页（Chapter Divider）：整页是一个章节大标题，可能有"第X章"、"一、"、"1."等编号，正文较少

另外，请判断第一个实质性章节内容（非封面、非目录、非前言）实际从哪一页开始。

回答 JSON（不要 markdown code fence）:
{{
  "toc_pages": [4],
  "chapter_dividers": [5, 13, 25, 35, 41],
  "first_content_page": 5
}}

如果没有找到目录页或分隔页，对应数组返回空 []。""",

    "方案2-增加过渡页识别": """你是文档分析专家。这些是一份 PDF 文档所有页面的缩略图网格。
每个缩略图左上角标注了页码（如 p.1, p.2...）。

请识别以下三类特殊页面：

1. 目录页（Table of Contents）：页面上有结构化的章节标题列表，关键词包括"目录"、"CONTENTS"、"提纲"、"大纲"
2. 章节分隔页（Chapter Divider）：整页是章节大标题，有明显的视觉分隔（色块、大字体）
3. 章节过渡页（Transition Page）：有章节标题列表或总结，作为章节之间的过渡

另外，请判断第一个实质性章节内容（非封面、非目录、非前言）实际从哪一页开始。

回答 JSON（不要 markdown code fence）:
{{
  "toc_pages": [2, 3],
  "chapter_dividers": [2, 3, 13, 25, 50, 61],
  "first_content_page": 4,
  "reasoning": "简要说明判断依据"
}}

如果没有找到目录页或分隔页，对应数组返回空 []。""",

    "方案3-科技报告专用": """你是文档分析专家，专门分析科技报告/白皮书类PDF。这些是一份 PDF 文档所有页面的缩略图网格。
每个缩略图左上角标注了页码（如 p.1, p.2...）。

科技报告的典型结构：
- 封面（通常有标题、机构logo）
- 目录/提纲页（可能有"目录"、"提纲"、"CONTENTS"、"Outline"等字样）
- 章节内容（可能有"第X章"、"一、"、"1."等编号）
- 附录/参考文献

请识别：
1. 目录页：包含"目录"、"提纲"、"CONTENTS"、"Outline"、"Summary"的页面
2. 章节起始页：每个主要章节的第一页（通常是"第X章"或"X."开头）
3. 正文开始页：第一个实质性内容页（不是封面、不是目录）

回答 JSON（不要 markdown code fence）:
{{
  "toc_pages": [2, 3],
  "chapter_dividers": [2, 13, 25, 50, 61],
  "first_content_page": 4,
  "reasoning": "简要说明"
}}

注意：
- 科技报告可能没有明显的"目录"页，但会有"提纲"页
- 章节可能没有"第X章"字样，而是用"一、"、"1."等编号
- 如果没有找到某类页面，返回空数组 []""",

    "方案4-详细特征描述": """你是文档分析专家。这些是一份 PDF 文档所有页面的缩略图网格。
每个缩略图左上角标注了页码（如 p.1, p.2...）。

请仔细分析每个缩略图，识别以下页面：

**目录页特征**：
- 有"目录"、"提纲"、"大纲"、"CONTENTS"、"Outline"等标题
- 有多个章节标题的列表
- 可能有页码数字

**章节分隔页特征**：
- 页面顶部或中间有大标题
- 标题可能是"第X章 XXX"、"一、XXX"、"1. XXX"格式
- 页面其余部分文字较少或有装饰

**正文开始页特征**：
- 有段落文字
- 不是封面、不是目录、不是纯标题页

请输出：
{{
  "toc_pages": [页码列表],
  "chapter_dividers": [每个主要章节的开始页码],
  "first_content_page": 第一个正文页码,
  "analysis": {{
    "p2": "描述第2页的内容",
    "p3": "描述第3页的内容",
    "p13": "描述第13页的内容"
  }}
}}

如果没有找到某类页面，对应数组返回空 []。"""
}

async def test_prompt(name, prompt_text):
    """测试单个 prompt"""
    print(f"\n{'='*80}")
    print(f"测试: {name}")
    print(f"{'='*80}")
    
    try:
        raw = await vlm_call_with_images(grid_images, prompt_text, max_tokens=3000)
        result = parse_vlm_json(raw)
        
        if not isinstance(result, dict):
            print(f"[ERROR] 返回格式错误: {type(result)}")
            return None
        
        toc_pages = result.get('toc_pages', [])
        dividers = result.get('chapter_dividers', [])
        first_content = result.get('first_content_page')
        reasoning = result.get('reasoning', '')
        
        print(f"toc_pages: {toc_pages}")
        print(f"chapter_dividers: {dividers}")
        print(f"first_content_page: {first_content}")
        if reasoning:
            print(f"reasoning: {reasoning}")
        
        # 评估准确性
        def evaluate():
            issues = []
            score = 100
            
            # 检查 toc_pages
            if not toc_pages:
                issues.append("未检测到目录页")
                score -= 20
            elif 2 not in toc_pages and 3 not in toc_pages:
                issues.append("未检测到P2/P3提纲页")
                score -= 15
            
            # 检查 dividers
            if not dividers:
                issues.append("未检测到章节分隔")
                score -= 30
            elif len(dividers) < 5:
                issues.append(f"分隔页太少({len(dividers)}个，应约5-6个)")
                score -= 10
            
            # 检查 first_content_page
            if first_content != 4:
                issues.append(f"正文开始页错误(应为4，实际{first_content})")
                score -= 10
            
            return score, issues
        
        score, issues = evaluate()
        print(f"\n评分: {score}/100")
        if issues:
            print("问题:")
            for issue in issues:
                print(f"  - {issue}")
        
        return {
            'name': name,
            'toc_pages': toc_pages,
            'dividers': dividers,
            'first_content': first_content,
            'score': score,
            'issues': issues,
            'reasoning': reasoning
        }
        
    except Exception as e:
        print(f"[ERROR] {e}")
        return None

async def main():
    print("="*80)
    print("锚点检测 Prompt 对比测试")
    print("="*80)
    print(f"\n文档: {os.path.basename(target_file)}")
    print(f"期望结果:")
    print(f"  toc_pages: {ground_truth['toc_pages']}")
    print(f"  dividers: {ground_truth['dividers']}")
    print(f"  first_content_page: {ground_truth['first_content_page']}")
    
    results = []
    
    for name, prompt_text in prompts.items():
        result = await test_prompt(name, prompt_text)
        if result:
            results.append(result)
    
    # 总结
    print(f"\n{'='*80}")
    print("测试总结")
    print(f"{'='*80}")
    print(f"{'方案':<20} {'评分':<8} {'目录页':<15} {'分隔页':<20} {'正文开始':<10}")
    print("-" * 80)
    
    for r in sorted(results, key=lambda x: x['score'], reverse=True):
        print(f"{r['name']:<20} {r['score']:<8} {str(r['toc_pages']):<15} {str(r['dividers']):<20} {str(r['first_content']):<10}")
    
    best = max(results, key=lambda x: x['score'])
    print(f"\n最佳方案: {best['name']} (评分: {best['score']})")
    
    return results

results = asyncio.run(main())
