import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, json, asyncio

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]
print(f"Testing: {file_path}")

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors

async def main():
    print("\n=== Phase 0: Analysis ===")
    analysis = analyze_pdf_structure(file_path)
    print(f"Pages: {analysis['page_count']}, text_coverage: {analysis['text_coverage']:.0%}")
    
    print("\n=== Phase 0.5: Anchors ===")
    anchors = await _vlm_detect_anchors(file_path)
    print(f"toc_pages: {anchors.get('toc_pages')}, first_content: {anchors.get('first_content_page')}")
    
    print("\n=== Phase 1: TOC Building ===")
    result = await build_balanced_toc_visual(
        file_path, analysis, model="qwen3.6-flash", anchors=anchors
    )
    
    items = result.get('toc_items', [])
    print(f"\nTop-level nodes: {len(items)}")
    total_nodes = len(items)
    for it in items:
        s = it.get('physical_index', 0)
        e = it.get('end_index', s)
        span = (e or s) - s + 1
        children = len(it.get('nodes', []))
        total_nodes += children
        title = it.get('title', '')[:50]
        print(f"  p.{s}-{e}  span={span}p  children={children}  {title}")
        for sub in it.get('nodes', [])[:3]:
            st = sub.get('title', '')[:40]
            spi = sub.get('physical_index', '?')
            print(f"    -> p.{spi}  {st}")
        if len(it.get('nodes', [])) > 3:
            print(f"    ... and {len(it.get('nodes', []))-3} more")
    
    print(f"\n=== Summary ===")
    print(f"Total nodes (top-level + children): {total_nodes}")
    print(f"Documents with sub-nodes (>0 children): {sum(1 for it in items if len(it.get('nodes',[])) > 0)}")
    print(f"Success: {total_nodes > 10}")

asyncio.run(main())
