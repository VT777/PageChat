import sys, os, asyncio
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors

doc_dir = 'backend/data/documents'
target = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target = os.path.join(doc_dir, f)
        break

async def test():
    analysis = analyze_pdf_structure(target)
    anchors = await _vlm_detect_anchors(target)
    result = await build_balanced_toc_visual(target, analysis, anchors=anchors)
    
    items = result.get('toc_items', [])
    print(f"Source: {result.get('source')}")
    print(f"Items: {len(items)}")
    print()
    print("TOC:")
    for i, item in enumerate(items[:25]):  # Show first 25
        print(f"  [{item.get('structure', '?')}] {item.get('title', '')} -> p.{item.get('physical_index', '?')}")
    
    if len(items) > 25:
        print(f"  ... and {len(items)-25} more")

asyncio.run(test())
