"""Deep analysis: Visual path TOC extraction quality for 技术应用洞察报告."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os, asyncio, json
from pathlib import Path

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual,
    _vlm_detect_anchors,
    decide_balanced_path,
)
from pageindex.post_processing import post_process_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Find the file
files = glob.glob(f"{doc_dir}/*097e50d9*")
if not files:
    print("File not found")
    sys.exit(1)

file_path = files[0]

# 1. Analyze PDF
analysis = analyze_pdf_structure(file_path)
print(f"File: {os.path.basename(file_path)}")
print(f"Pages: {analysis['page_count']}")
print(f"Text coverage: {analysis['text_coverage']:.2f}")
print(f"Is garbled: {analysis['is_garbled_pdf']}")
print(f"Balanced path: {decide_balanced_path(analysis)}")
print()

# 2. Detect anchors
async def analyze_visual_path():
    print("=== VISUAL PATH ANALYSIS ===\n")
    
    anchors = await _vlm_detect_anchors(file_path, model="qwen3.6-flash")
    print(f"Anchors:")
    print(f"  TOC pages: {anchors.get('toc_pages', [])}")
    print(f"  Dividers: {anchors.get('chapter_dividers', [])}")
    print(f"  First content: {anchors.get('first_content_page', 1)}")
    print()
    
    # 3. Build TOC with visual path
    print("=== BUILDING TOC (Visual Path) ===")
    result = await build_balanced_toc_visual(
        file_path, 
        analysis, 
        model="qwen3.6-flash",
        anchors=anchors
    )
    
    toc_items = result.get("toc_items", [])
    print(f"Raw TOC items: {len(toc_items)}")
    for i, item in enumerate(toc_items[:20]):
        print(f"  [{i}] structure='{item.get('structure', '')}' title='{item.get('title', '')[:60]}' pi={item.get('physical_index')}")
    print()
    
    # 4. Structure analysis
    print("=== STRUCTURE ANALYSIS ===")
    main_chapters = [it for it in toc_items if '.' not in str(it.get('structure', ''))]
    sub_chapters = [it for it in toc_items if '.' in str(it.get('structure', ''))]
    print(f"Main chapters: {len(main_chapters)}")
    for it in main_chapters:
        print(f"  - [{it.get('structure', '')}] p.{it.get('physical_index')} {it.get('title', '')[:60]}")
    print(f"Sub chapters: {len(sub_chapters)}")
    for it in sub_chapters[:15]:
        print(f"  - [{it.get('structure', '')}] p.{it.get('physical_index')} {it.get('title', '')[:60]}")
    print()
    
    # 5. Post-processing result
    print("=== POST-PROCESSING ===")
    tree, completeness = post_process_toc(toc_items, analysis['page_count'])
    print(f"Top-level nodes: {len(tree)}")
    print(f"Coverage: {completeness.get('coverage', 0):.0%}")
    print(f"Quality: {completeness.get('quality', 'unknown')}")
    
    # 6. Large nodes analysis
    print(f"\n=== LARGE NODE ANALYSIS ===")
    for i, item in enumerate(toc_items):
        start = item.get('physical_index', 0)
        if i < len(toc_items) - 1:
            end = toc_items[i+1].get('physical_index', start + 1) - 1
        else:
            end = analysis['page_count']
        span = end - start + 1
        if span >= 5:
            print(f"  p.{start}-{end} span={span}: {item.get('title', '')[:50]}")
    
    # 7. Compare with expected structure (based on dividers)
    print(f"\n=== DIVIDER vs ACTUAL ===")
    dividers = anchors.get('chapter_dividers', [])
    for d in dividers:
        closest = min(toc_items, key=lambda x: abs(x.get('physical_index', 999) - d))
        dist = abs(closest.get('physical_index', 999) - d)
        print(f"  Divider p.{d} -> matched: p.{closest.get('physical_index')} '{closest.get('title', '')[:40]}' (dist={dist})")
    
    # 8. Check VLM extraction details
    print(f"\n=== VLM EXTRACTION DETAILS ===")
    print(f"Source: {result.get('source', 'unknown')}")
    if 'vlm_response' in result:
        print(f"VLM response (first 1000 chars):")
        print(result['vlm_response'][:1000])

asyncio.run(analyze_visual_path())

print(f"\n{'='*60}")
print("ANALYSIS COMPLETE")
print(f"{'='*60}")
