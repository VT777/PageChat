import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual, 
    _vlm_detect_anchors,
    _smart_identify_chapters,
    _assign_divider_positions,
)

doc_dir = "D:/projects/page_chat/backend/data/documents"
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]

async def test():
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
    
    print("=== 测试 _smart_identify_chapters ===")
    chapters, subsections = _smart_identify_chapters(toc_items, dividers)
    
    if chapters is not None:
        print(f"Chapters: {len(chapters)}")
        for ch in chapters:
            print(f"  {ch['structure']}: {ch['title'][:40]}")
        
        print(f"Subsections: {len(subsections)}")
        for sub in subsections:
            print(f"  {sub['structure']}: {sub['title'][:40]}")
    else:
        print("无法识别，返回 None")
    
    # Test _assign_divider_positions
    print("\n=== 测试 _assign_divider_positions ===")
    _assign_divider_positions(toc_items, dividers)
    
    for item in toc_items:
        print(f"  {item['structure']}: p.{item.get('physical_index')} - {item['title'][:40]}")

asyncio.run(test())
