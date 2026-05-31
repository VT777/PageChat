"""
方案B测试：章节起始页标题识别
思路：用divider定位章节边界，识别每个章节的大标题
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import _vlm_detect_anchors, build_balanced_toc_visual
from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json

doc_dir = os.path.join(os.path.dirname(__file__), '..', 'backend', 'data', 'documents')
target_file = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target_file = os.path.join(doc_dir, f)
        break

async def test_plan_b():
    """方案B：章节起始页标题识别"""
    print("="*80)
    print("方案B：章节起始页标题识别")
    print("="*80)
    
    analysis = analyze_pdf_structure(target_file)
    page_count = analysis['page_count']
    
    # Step 1: 获取现有结果（Branch B）作为子章节基础
    print(f"\nStep 1: 获取现有子章节结构")
    anchors = await _vlm_detect_anchors(target_file)
    existing_result = await build_balanced_toc_visual(
        target_file, analysis, anchors=anchors
    )
    
    existing_items = existing_result.get('toc_items', [])
    print(f"  现有 {len(existing_items)} 个条目")
    
    # 提取一级和二级结构
    top_level_existing = [i for i in existing_items if '.' not in str(i.get('structure', ''))]
    sub_level_existing = [i for i in existing_items if '.' in str(i.get('structure', ''))]
    
    print(f"  其中一级: {len(top_level_existing)} 个")
    print(f"  其中二级: {len(sub_level_existing)} 个")
    
    # Step 2: 获取 dividers
    print(f"\nStep 2: 分析章节边界")
    dividers = anchors.get('chapter_dividers', [])
    first_content = anchors.get('first_content_page', 2)
    
    print(f"  dividers: {dividers}")
    print(f"  first_content: {first_content}")
    
    # Step 3: 确定每个章节的起始页
    # 构建章节范围
    chapter_ranges = []
    if dividers:
        for i, div in enumerate(dividers):
            if i + 1 < len(dividers):
                end = dividers[i + 1] - 1
            else:
                end = page_count
            chapter_ranges.append((div, end))
    
    print(f"\nStep 3: 章节范围")
    for i, (start, end) in enumerate(chapter_ranges):
        print(f"  章节{i+1}: p.{start} - p.{end}")
    
    # Step 4: 对每个章节起始页，识别大标题
    print(f"\nStep 4: 识别章节大标题")
    chapter_titles = []
    
    for i, (start, end) in enumerate(chapter_ranges):
        # 渲染起始页
        images = render_pages_to_images(target_file, [start - 1])  # 0-indexed
        if not images:
            continue
            
        prompt = f"""你是文档章节标题识别专家。
这是PDF的第{start}页图片。

任务：
1. 找出这一页最醒目的大标题（通常是章节标题）
2. 只返回标题文本，不要解释

输出格式（JSON）：
{{
  "chapter_title": "标题文本",
  "confidence": "high|medium|low"
}}

注意：
- 如果这是封面/前言，标题可能是"前言"、"摘要"等
- 如果是正文章节，标题格式可能是"第一章 XXX"、"一、XXX"等
- 只返回最主要的一个标题"""

        print(f"  识别章节 {i+1} (p.{start})...")
        raw = await vlm_call_with_images(images, prompt, max_tokens=1000)
        result = parse_vlm_json(raw)
        
        if isinstance(result, dict) and 'chapter_title' in result:
            title = result['chapter_title']
            print(f"    -> {title}")
            chapter_titles.append({
                'structure': str(i + 1),
                'title': title,
                'physical_index': start
            })
        else:
            print(f"    -> 无法识别")
    
    # Step 5: 合并结果
    print(f"\nStep 5: 合并章节标题和子章节")
    
    # 将子章节映射到正确的章节下
    final_items = []
    
    # 添加一级章节
    for ch in chapter_titles:
        final_items.append(ch)
        
        # 找到属于这个章节的子章节
        ch_start = ch['physical_index']
        ch_num = int(ch['structure'])
        
        # 确定章节结束页
        ch_idx = chapter_titles.index(ch)
        if ch_idx + 1 < len(chapter_titles):
            ch_end = chapter_titles[ch_idx + 1]['physical_index']
        else:
            ch_end = page_count
        
        # 添加属于这个范围的子章节
        for sub in sub_level_existing:
            sub_page = sub.get('physical_index', 0)
            if ch_start <= sub_page < ch_end:
                # 调整 structure
                sub_structure = sub.get('structure', '')
                if sub_structure.startswith(str(ch_num) + '.'):
                    final_items.append(sub)
                elif '.' in sub_structure:
                    # 重新编号
                    parts = sub_structure.split('.')
                    if len(parts) >= 2:
                        new_structure = f"{ch_num}.{'.'.join(parts[1:])}"
                        sub['structure'] = new_structure
                        final_items.append(sub)
    
    # Step 6: 输出结果
    print(f"\nStep 6: 最终TOC（{len(final_items)}条）")
    for item in final_items:
        print(f"  [{item.get('structure', '?')}] {item.get('title', '')} -> p.{item.get('physical_index', '?')}")
    
    return {
        'source': 'plan_b_chapter_titles',
        'toc_items': final_items,
        'chapter_titles': chapter_titles,
        'sub_chapters': sub_level_existing
    }

# 运行测试
result = asyncio.run(test_plan_b())

if result:
    print(f"\n{'='*80}")
    print("方案B测试完成")
    print(f"识别到 {len(result['chapter_titles'])} 个章节标题")
    print(f"总条目数: {len(result['toc_items'])}")
    print(f"来源: {result['source']}")
