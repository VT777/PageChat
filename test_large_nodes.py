import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors

doc_dir = "D:/projects/page_chat/backend/data/documents"
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]

async def test():
    analysis = analyze_pdf_structure(file_path)
    anchors = await _vlm_detect_anchors(file_path)
    
    print(f"Dividers: {anchors.get('chapter_dividers')}")
    print(f"TOC pages: {anchors.get('toc_pages')}")
    print(f"First content: {anchors.get('first_content_page')}")
    print(f"Page count: {analysis['page_count']}")
    
    # Simulate what happens in _branch_a_toc_page
    toc_items = [
        {"structure": "一", "title": "第一章", "page": None},
        {"structure": "2", "title": "第二章", "page": None},
        {"structure": "二", "title": "第三章", "page": None},
        {"structure": "4", "title": "第四章", "page": None},
        {"structure": "三", "title": "第五章", "page": None},
        {"structure": "6", "title": "第六章", "page": None},
        {"structure": "四", "title": "第七章", "page": None},
        {"structure": "8", "title": "第八章", "page": None},
    ]
    
    dividers = anchors.get("chapter_dividers", [])
    page_count = analysis["page_count"]
    first_content = anchors.get("first_content_page")
    
    # Step 1: _map_toc_physical_pages (uniform distribution since page=null)
    from pageindex.balanced_toc import _map_toc_physical_pages
    _map_toc_physical_pages(toc_items, page_count, first_content, max(anchors.get("toc_pages", [0])), dividers=dividers)
    
    print("\nAfter _map_toc_physical_pages:")
    for item in toc_items:
        print(f"  {item['structure']}: p.{item.get('physical_index')} - {item['title']}")
    
    # Step 2: Check spans
    print("\nSpan calculation:")
    for i, item in enumerate(toc_items):
        start = item.get("physical_index", 0)
        if i < len(toc_items) - 1:
            next_start = toc_items[i + 1].get("physical_index", start + 1)
            end = max(next_start - 1, start)
        else:
            end = page_count
        span = end - start + 1
        print(f"  {item['structure']}: p.{start}-p.{end} (span={span}) {'LARGE!' if span >= 8 else ''}")

asyncio.run(test())
