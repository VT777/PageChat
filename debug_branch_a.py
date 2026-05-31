"""Debug: Check why full scan is not triggered."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os, asyncio
from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    _branch_a_toc_page,
    _vlm_detect_anchors,
)

doc_dir = "D:/projects/page_chat/backend/data/documents"
files = glob.glob(f"{doc_dir}/*097e50d9*")
file_path = files[0]

analysis = analyze_pdf_structure(file_path)

async def debug_branch_a():
    anchors = await _vlm_detect_anchors(file_path, model="qwen3.6-flash")
    toc_pages = anchors.get('toc_pages', [])
    dividers = anchors.get('chapter_dividers', [])
    first_content = anchors.get('first_content_page')
    
    print("=== CALLING _branch_a_toc_page ===\n")
    
    result = await _branch_a_toc_page(
        file_path, 
        analysis['page_count'], 
        toc_pages, 
        dividers, 
        model="qwen3.6-flash",
        first_content_page=first_content,
        ocr_text_map=None,
    )
    
    if result:
        toc_items = result.get("toc_items", [])
        print(f"\n=== RESULT ===")
        print(f"Total items: {len(toc_items)}")
        for i, item in enumerate(toc_items[:20]):
            print(f"  [{i}] s='{item.get('structure', '')}' pi={item.get('physical_index')} t='{item.get('title', '')[:50]}'")
        
        # Check large nodes
        print(f"\n=== SPAN ANALYSIS ===")
        LARGE_NODE_THRESHOLD = 8
        large_count = 0
        for i, item in enumerate(toc_items):
            start = item.get('physical_index', 0)
            if not start or start < 1:
                continue
            if i < len(toc_items) - 1:
                next_start = toc_items[i + 1].get('physical_index', start + 1)
                estimated_end = max(next_start - 1, start)
            else:
                estimated_end = analysis['page_count']
            span = estimated_end - start + 1
            if span >= LARGE_NODE_THRESHOLD:
                large_count += 1
                print(f"  LARGE: p.{start}-{estimated_end} span={span}: {item.get('title', '')[:40]}")
            else:
                print(f"  small: p.{start}-{estimated_end} span={span}: {item.get('title', '')[:40]}")
        
        print(f"\nLarge nodes: {large_count}")
        print(f"Need full scan: {len(toc_items) < 10 and large_count > 0}")
    else:
        print("Result is None!")

asyncio.run(debug_branch_a())
