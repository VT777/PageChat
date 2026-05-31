"""Analyze the full document scan output for 技术应用洞察报告."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os, asyncio
from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual,
    _vlm_detect_anchors,
    _vlm_scan_document_pages,
    decide_balanced_path,
)

doc_dir = "D:/projects/page_chat/backend/data/documents"
files = glob.glob(f"{doc_dir}/*097e50d9*")
file_path = files[0]

analysis = analyze_pdf_structure(file_path)

async def debug_scan():
    print("=== FULL DOCUMENT SCAN DEBUG ===\n")
    
    # Get page titles from full scan
    page_titles = await _vlm_scan_document_pages(
        file_path, 
        analysis['page_count'], 
        model="qwen3.6-flash"
    )
    
    print(f"Total page titles extracted: {len(page_titles)}\n")
    
    # Group by type
    chapters = [pt for pt in page_titles if pt.get('type') == 'chapter']
    contents = [pt for pt in page_titles if pt.get('type') == 'content']
    skips = [pt for pt in page_titles if pt.get('type') == 'skip']
    
    print(f"Chapters: {len(chapters)}")
    for pt in chapters:
        print(f"  p.{pt['physical_index']:2d}: {pt['title']}")
    
    print(f"\nContents: {len(contents)}")
    for pt in contents[:30]:
        print(f"  p.{pt['physical_index']:2d}: {pt['title']}")
    
    print(f"\nSkips: {len(skips)}")
    for pt in skips:
        print(f"  p.{pt['physical_index']:2d}: {pt['title']}")
    
    # Now check dividers
    anchors = await _vlm_detect_anchors(file_path, model="qwen3.6-flash")
    dividers = anchors.get('chapter_dividers', [])
    print(f"\n=== DIVIDERS: {dividers} ===")
    
    # Check what pages are around dividers
    for d in dividers:
        print(f"\nAround divider p.{d}:")
        for pt in page_titles:
            if abs(pt['physical_index'] - d) <= 1:
                print(f"  p.{pt['physical_index']:2d} [{pt.get('type', '?')}] {pt['title']}")
    
    # Check chapter boundaries detection
    print(f"\n=== CHAPTER BOUNDARY DETECTION ===")
    
    # Get TOC items
    toc_items = [
        {"structure": "1", "title": "第一章", "physical_index": 5},
        {"structure": "2", "title": "第二章", "physical_index": 13},
        {"structure": "3", "title": "第三章", "physical_index": 25},
        {"structure": "4", "title": "第四章", "physical_index": 38},
    ]
    
    # Simulate chapter boundary matching
    chapter_boundaries = []
    for item in toc_items:
        toc_title = item.get("title", "")
        toc_prefix = toc_title[:10].strip()
        for pt in page_titles:
            page_title = pt.get("title", "")
            if toc_prefix and toc_prefix in page_title and pt.get("physical_index", 0) > 2:
                chapter_boundaries.append({
                    "structure": item.get("structure", ""),
                    "title": toc_title,
                    "start_page": pt["physical_index"],
                })
                break
    
    print(f"Matched chapter boundaries: {len(chapter_boundaries)}")
    for cb in chapter_boundaries:
        print(f"  {cb['structure']}: p.{cb['start_page']} - {cb['title']}")
    
    # Check what happens with sub-items
    print(f"\n=== SUB-ITEMS ANALYSIS ===")
    for cb_idx, cb in enumerate(chapter_boundaries):
        start = cb["start_page"]
        if cb_idx < len(chapter_boundaries) - 1:
            end = chapter_boundaries[cb_idx + 1]["start_page"] - 1
        else:
            end = analysis['page_count']
        
        sub_items = [
            pt for pt in page_titles
            if start <= pt["physical_index"] <= end
            and pt.get("type") != "chapter"
        ]
        
        print(f"\nChapter '{cb['title']}' (p.{start}-{end}):")
        print(f"  Total pages in range: {end - start + 1}")
        print(f"  Sub-items found: {len(sub_items)}")
        for si in sub_items[:15]:
            print(f"    p.{si['physical_index']:2d}: {si['title']}")

asyncio.run(debug_scan())
