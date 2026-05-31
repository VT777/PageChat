"""Deep diagnosis for 技术应用洞察报告 - Phase 1: Evidence Gathering"""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, json, asyncio, os
from pathlib import Path

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual, 
    build_balanced_toc_text,
    _vlm_detect_anchors,
    decide_balanced_path,
    _refine_toc_with_dividers
)
from pageindex.post_processing import post_process_toc
from pageindex.page_index import meta_processor, JsonLogger
from types import SimpleNamespace

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Find the file
files = glob.glob(f"{doc_dir}/*097e50d9*")
if not files:
    print("File not found")
    sys.exit(1)

file_path = files[0]
print(f"File: {os.path.basename(file_path)}")

# 1. PDF Analysis
analysis = analyze_pdf_structure(file_path)
page_count = analysis.get('page_count', 0)
print(f"\n1. PDF Structure:")
print(f"   Pages: {page_count}")
print(f"   Text coverage: {analysis.get('text_coverage', 0):.2f}")
print(f"   Is image only: {analysis.get('is_image_only_pdf', False)}")
print(f"   Is garbled: {analysis.get('is_garbled_pdf', False)}")

# 2. Anchor detection
anchors = asyncio.run(_vlm_detect_anchors(file_path))
toc_pages = anchors.get('toc_pages', [])
dividers = anchors.get('chapter_dividers', [])
first_content = anchors.get('first_content_page', 1)
print(f"\n2. Anchors:")
print(f"   TOC pages: {toc_pages}")
print(f"   Dividers: {dividers}")
print(f"   First content: {first_content}")

# 3. Page list analysis
page_list = analysis.get('page_list', [])
print(f"\n3. Page List Analysis:")
print(f"   Total pages in list: {len(page_list)}")
if page_list:
    print(f"   First page: {page_list[0][:80]}...")
    print(f"   Last page: {page_list[-1][:80]}...")

# 4. Balanced path decision
balanced_path = decide_balanced_path(analysis)
print(f"\n4. Balanced Path: {balanced_path}")

# 5. Try text path first
print(f"\n5. TEXT PATH ANALYSIS:")
opt = SimpleNamespace(
    model="qwen3.6-flash",
    toc_check_page_num=15,
    max_page_num_each_node=6,
    max_token_num_each_node=15000,
    if_add_node_id="no",
    if_add_node_summary="no",
    if_add_doc_description="no",
    if_add_node_text="no",
    index_mode="balanced",
)
logger = JsonLogger(file_path)

toc_items = asyncio.run(meta_processor(
    page_list,
    mode="process_no_toc",
    start_index=1,
    opt=opt,
    logger=logger,
    doc_type="general",
    doc_type_confidence=0.0,
))

print(f"   Raw TOC items: {len(toc_items)}")
for i, item in enumerate(toc_items[:20]):
    print(f"   [{i}] structure='{item.get('structure', '')}' title='{item.get('title', '')[:50]}' pi={item.get('physical_index')}")

# 6. Structure analysis
print(f"\n6. STRUCTURE ANALYSIS:")
main_chapters = [it for it in toc_items if '.' not in str(it.get('structure', ''))]
sub_chapters = [it for it in toc_items if '.' in str(it.get('structure', ''))]
print(f"   Main chapters: {len(main_chapters)}")
for it in main_chapters:
    print(f"     - [{it.get('structure', '')}] p.{it.get('physical_index')} {it.get('title', '')[:50]}")
print(f"   Sub chapters: {len(sub_chapters)}")
for it in sub_chapters[:10]:
    print(f"     - [{it.get('structure', '')}] p.{it.get('physical_index')} {it.get('title', '')[:50]}")

# 7. Divider analysis
print(f"\n7. DIVIDER vs TOC MAPPING:")
for d in dividers:
    # Find closest TOC item
    closest = min(toc_items, key=lambda x: abs(x.get('physical_index', 999) - d))
    dist = abs(closest.get('physical_index', 999) - d)
    print(f"   Divider p.{d} -> closest TOC p.{closest.get('physical_index')} '{closest.get('title', '')[:40]}' (dist={dist})")

# 8. Large node analysis
print(f"\n8. LARGE NODE ANALYSIS (span >= 5):")
for i, item in enumerate(toc_items):
    start = item.get('physical_index', 0)
    if i < len(toc_items) - 1:
        end = toc_items[i+1].get('physical_index', start + 1) - 1
    else:
        end = page_count
    span = end - start + 1
    if span >= 5:
        print(f"   p.{start}-{end} span={span}: {item.get('title', '')[:50]}")

# 9. Visual path comparison
print(f"\n9. VISUAL PATH COMPARISON:")
print(f"   (This would take longer, but let's check TOC page content)")
if toc_pages:
    from pageindex.vlm_utils import render_pages_to_images
    images = render_pages_to_images(file_path, [p - 1 for p in toc_pages], dpi=150)
    print(f"   Rendered {len(images)} TOC pages")
    for i, (page_num, img) in enumerate(zip(toc_pages, images)):
        print(f"   TOC page {page_num}: {img[:50]}...")

# 10. Manual divider check - what pages are dividers?
print(f"\n10. DIVIDER PAGE CONTENT CHECK:")
for d in dividers:
    if d <= len(page_list):
        content = page_list[d-1][:150]
        print(f"   p.{d}: {content}...")

print(f"\n{'='*60}")
print("DIAGNOSIS COMPLETE")
print(f"{'='*60}")
