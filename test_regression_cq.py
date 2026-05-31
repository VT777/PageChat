import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*8cefa13e*")[0]
print(f"Testing: {file_path}")

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors

async def main():
    analysis = analyze_pdf_structure(file_path)
    print(f"Pages: {analysis['page_count']}")
    
    anchors = await _vlm_detect_anchors(file_path)
    print(f"toc_pages: {anchors.get('toc_pages')}, first_content: {anchors.get('first_content_page')}")
    
    result = await build_balanced_toc_visual(
        file_path, analysis, model="qwen3.6-flash", anchors=anchors
    )
    
    items = result.get('toc_items', [])
    total = len(items)
    with_children = 0
    for it in items:
        nc = len(it.get('nodes', []))
        total += nc
        if nc > 0:
            with_children += 1
        print(f"  children={nc}  span={it.get('physical_index','?')}-{it.get('end_index', it.get('physical_index','?'))}")
    
    # Each case is ~1 page, so span should be small, no large nodes
    large_nodes = sum(1 for it in items if (it.get('end_index', it.get('physical_index', 0)) or 0) - it.get('physical_index', 0) >= 8)
    
    print(f"\nRegression check:")
    print(f"  Total items: {total}")
    print(f"  Items with children: {with_children}")
    print(f"  Large nodes (>8p): {large_nodes}")
    print(f"  Should NOT trigger sub-extraction: {large_nodes == 0}")

asyncio.run(main())
