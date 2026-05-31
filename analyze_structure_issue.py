import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import _vlm_detect_anchors, _vlm_scan_document_pages

doc_dir = "D:/projects/page_chat/backend/data/documents"
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]

async def analyze():
    analysis = analyze_pdf_structure(file_path)
    anchors = await _vlm_detect_anchors(file_path)
    
    # Simulate TOC items for 技术应用洞察
    toc_items = [
        {"structure": "一", "title": "全球人工智能技术概览与发展趋势", "page": None},
        {"structure": "2", "title": "全球人工智能技术应用全景图谱", "page": None},
        {"structure": "二", "title": "AI十大行业应用洞察", "page": None},
        {"structure": "4", "title": "AI赋能行业应用价值、重点与十大行业应用", "page": None},
        {"structure": "三", "title": "全球人工智能技术应用趋势", "page": None},
        {"structure": "6", "title": "人工智能技术应用关键价值、模型、十大趋势", "page": None},
        {"structure": "四", "title": "全球人工智能技术应用未来发展", "page": None},
        {"structure": "8", "title": "全球人工智能应用十大趋势", "page": None},
    ]
    
    dividers = anchors.get("chapter_dividers", [])
    page_count = analysis["page_count"]
    
    print("=== 问题分析 ===")
    print(f"Dividers: {dividers} (count={len(dividers)})")
    print(f"TOC items: {len(toc_items)}")
    print(f"Page count: {page_count}")
    
    # Analyze structure patterns
    print("\n=== Structure 分析 ===")
    chinese_nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
    arabic_nums = [str(i) for i in range(1, 20)]
    
    for item in toc_items:
        struct = item.get("structure", "")
        is_chinese = struct in chinese_nums
        is_arabic = struct in arabic_nums
        print(f"  structure='{struct}' -> chinese={is_chinese}, arabic={is_arabic}, title={item['title'][:30]}")
    
    # What should happen
    print("\n=== 理想分配 ===")
    print("章节 (分配 dividers):")
    for i, div in enumerate(dividers):
        print(f"  第{i+1}章: p.{div}")
    
    print("\n子章节 (应归入对应章节):")
    # Based on title analysis
    print("  '2' -> 第一章的子章节")
    print("  '4' -> 第二章的子章节") 
    print("  '6' -> 第三章的子章节")
    print("  '8' -> 第四章的子章节")
    
    # Why current code fails
    print("\n=== 现有代码问题 ===")
    print("1. _assign_divider_positions 只认 '无 . 的 structure' 为 top_items")
    print("2. 所有 8 个 items 都无 '.' -> 都是 top_items")
    print("3. zip(top_items, dividers) 只分配前 4 个")
    print("4. 后 4 个 items 无 physical_index -> uniform distribution")
    print("5. 结果: 8 个 items 均匀分布，每个 span 4-5 页")
    print("6. Large node threshold=8 -> 没有任何节点触发")

asyncio.run(analyze())
