"""Analyze the final tree structure for 技术应用洞察报告."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os, asyncio
from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual,
    _vlm_detect_anchors,
    decide_balanced_path,
)
from pageindex.post_processing import post_process_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"
files = glob.glob(f"{doc_dir}/*097e50d9*")
file_path = files[0]

analysis = analyze_pdf_structure(file_path)

async def analyze_final_tree():
    anchors = await _vlm_detect_anchors(file_path, model="qwen3.6-flash")
    dividers = anchors.get('chapter_dividers', [])
    
    result = await build_balanced_toc_visual(
        file_path, 
        analysis, 
        model="qwen3.6-flash",
        anchors=anchors
    )
    
    toc_items = result.get("toc_items", [])
    print(f"Raw TOC items: {len(toc_items)}\n")
    
    # Post-process
    tree, completeness = post_process_toc(toc_items, analysis['page_count'], dividers=dividers)
    
    print(f"Final tree: {len(tree)} top-level nodes")
    print(f"Coverage: {completeness.get('coverage', 0):.0%}")
    print()
    
    # Print tree structure
    def print_tree(nodes, indent=0):
        for node in nodes:
            prefix = "  " * indent
            start = node.get("start_index", "?")
            end = node.get("end_index", "?")
            title = node.get("title", "")[:60]
            struct = node.get("structure", "")
            children = len(node.get("nodes", []))
            try:
                print(f"{prefix}[{struct}] p.{start}-{end} {title} ({children} children)")
            except:
                print(f"{prefix}[{struct}] p.{start}-{end} <unicode> ({children} children)")
            if node.get("nodes"):
                print_tree(node["nodes"], indent + 1)
    
    print("=== FINAL TREE STRUCTURE ===")
    print_tree(tree)
    
    # Check for issues
    print(f"\n=== ISSUE ANALYSIS ===")
    
    # 1. Check main chapters
    main_chapters = [n for n in tree if n.get('structure') and '.' not in n.get('structure', '')]
    print(f"Main chapters: {len(main_chapters)}")
    for ch in main_chapters:
        children = ch.get("nodes", [])
        span = ch.get("end_index", 0) - ch.get("start_index", 0) + 1
        print(f"  - {ch.get('title', '')[:40]}: {len(children)} children, span={span} pages")
    
    # 2. Check for empty structure
    empty_struct = [n for n in tree if not n.get('structure')]
    if empty_struct:
        print(f"\nWARNING: {len(empty_struct)} nodes with empty structure:")
        for n in empty_struct:
            print(f"  p.{n.get('start_index')} {n.get('title', '')[:40]}")
    
    # 3. Check coverage gaps
    covered = set()
    def collect_ranges(nodes):
        for node in nodes:
            start = node.get("start_index", 0)
            end = node.get("end_index", 0)
            for p in range(start, end + 1):
                covered.add(p)
            collect_ranges(node.get("nodes", []))
    collect_ranges(tree)
    
    all_pages = set(range(1, analysis['page_count'] + 1))
    missing = sorted(all_pages - covered)
    if missing:
        print(f"\nWARNING: Missing pages: {missing}")
    else:
        print(f"\nAll pages covered ✓")
    
    # 4. Compare with dividers
    print(f"\n=== DIVIDER ALIGNMENT ===")
    top_pages = [n.get("start_index") for n in tree]
    for d in dividers:
        matched = any(abs(p - d) <= 1 for p in top_pages if p)
        status = "✓" if matched else "✗"
        print(f"  Divider p.{d}: {status}")

asyncio.run(analyze_final_tree())
