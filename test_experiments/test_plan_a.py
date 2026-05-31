"""
方案A测试：目录页优先提取
思路：先找到目录页（汇报提纲），从中提取完整结构
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import _vlm_detect_anchors
from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json
import pymupdf

doc_dir = os.path.join(os.path.dirname(__file__), '..', 'backend', 'data', 'documents')
target_file = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target_file = os.path.join(doc_dir, f)
        break

async def test_plan_a():
    """方案A：目录页优先提取"""
    print("="*80)
    print("方案A：目录页优先提取")
    print("="*80)
    
    analysis = analyze_pdf_structure(target_file)
    page_count = analysis['page_count']
    
    # Step 1: 检测可能的目录页
    # P2-P3 有 "汇报提纲" 文本
    candidate_toc_pages = []
    for i in range(min(10, page_count)):
        text = analysis['page_texts'][i] if i < len(analysis['page_texts']) else ""
        if '汇报提纲' in text or '目录' in text or '提纲' in text:
            candidate_toc_pages.append(i + 1)  # 1-indexed
    
    print(f"\nStep 1: 候选目录页: {candidate_toc_pages}")
    
    if not candidate_toc_pages:
        print("未找到目录页，方案A无法执行")
        return None
    
    # Step 2: 渲染目录页高清图
    print(f"\nStep 2: 渲染目录页 {candidate_toc_pages}")
    toc_images = render_pages_to_images(target_file, [p-1 for p in candidate_toc_pages])
    print(f"  渲染了 {len(toc_images)} 页")
    
    # Step 3: VLM 提取目录结构
    prompt = """你是文档目录提取专家。
这些是 PDF 的目录/提纲页图片。

任务：
1. 提取所有章节的层级结构（一级、二级等）
2. 保留完整的章节标题
3. 如果有页码，也提取出来

输出格式（JSON）：
{
  "toc_items": [
    {"structure": "1", "title": "第一章标题", "page": 1},
    {"structure": "1.1", "title": "子节标题", "page": 3},
    {"structure": "2", "title": "第二章标题", "page": 10}
  ]
}

重要：
- 保留标题中的序号（如"一"、"1.1"等）
- 如果没有页码，page设为null
- 输出必须是JSON格式，不要markdown代码块"""

    print(f"\nStep 3: VLM提取目录结构")
    raw = await vlm_call_with_images(toc_images, prompt, max_tokens=8000)
    result = parse_vlm_json(raw)
    
    if not isinstance(result, dict) or 'toc_items' not in result:
        print(f"VLM返回格式错误: {type(result)}")
        return None
    
    toc_items = result['toc_items']
    print(f"  提取到 {len(toc_items)} 个条目")
    
    # Step 4: 页码映射
    # 如果没有页码，使用锚点或均匀分布
    has_pages = any(i.get('page') for i in toc_items)
    
    if not has_pages:
        print("\nStep 4: 无页码，进行页码映射")
        # 获取 dividers 作为参考
        anchors = await _vlm_detect_anchors(target_file)
        dividers = anchors.get('chapter_dividers', [])
        first_content = anchors.get('first_content_page', 2)
        
        print(f"  使用 dividers: {dividers}")
        print(f"  first_content_page: {first_content}")
        
        # 简单映射：一级章节用 divider，二级均匀分布
        top_items = [i for i in toc_items if '.' not in str(i.get('structure', ''))]
        
        if dividers and len(top_items) == len(dividers):
            # 完美匹配
            for item, div in zip(top_items, dividers):
                item['physical_index'] = div
        else:
            # 均匀分布
            n = len(toc_items)
            for i, item in enumerate(toc_items):
                item['physical_index'] = min(page_count, first_content + i * (page_count - first_content) // max(n-1, 1))
    else:
        # 有页码，直接使用
        for item in toc_items:
            item['physical_index'] = item.get('page') or item.get('physical_index', 1)
    
    # Step 5: 验证和输出
    print(f"\nStep 5: 最终TOC（{len(toc_items)}条）")
    for item in toc_items:
        print(f"  [{item.get('structure', '?')}] {item.get('title', '')} -> p.{item.get('physical_index', '?')}")
    
    return {
        'source': 'plan_a_toc_first',
        'toc_items': toc_items,
        'time': 0  # 稍后计算
    }

# 运行测试
result = asyncio.run(test_plan_a())

if result:
    print(f"\n{'='*80}")
    print("方案A测试完成")
    print(f"条目数: {len(result['toc_items'])}")
    print(f"来源: {result['source']}")
