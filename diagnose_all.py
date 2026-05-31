import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio, os

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors
from pageindex.post_processing import post_process_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"

test_files = {
    "AI_Agent_2026": "*9cf5b5be*",
    "第五范式_2025": "*90e75e6f*",
    "AI眼镜_2025": "*d9b2b5ea*",
    "技术应用洞察_2025": "*097e50d9*",
    "AI治理_2025": "*a1ed6276*",
}

async def diagnose_single(name, pattern):
    print(f"\n{'='*80}")
    print(f"DIAGNOSIS: {name}")
    print(f"{'='*80}")
    
    files = glob.glob(f"{doc_dir}/{pattern}")
    if not files:
        print(f"  FILE NOT FOUND: {pattern}")
        return
    
    file_path = files[0]
    print(f"  File: {os.path.basename(file_path)}")
    
    # 1. PDF Analysis
    analysis = analyze_pdf_structure(file_path)
    print(f"\n  1. PDF Structure: pages={analysis.get('page_count')}, text_coverage={analysis.get('text_coverage', 0):.2f}")
    
    # 2. Anchor detection
    anchors = await _vlm_detect_anchors(file_path)
    print(f"\n  2. Anchors: toc_pages={anchors.get('toc_pages')}, dividers={anchors.get('chapter_dividers')}, first_content={anchors.get('first_content_page')}")
    
    # 3. TOC extraction
    result = await build_balanced_toc_visual(file_path, analysis, model="qwen3.6-flash", anchors=anchors)
    toc_items = result.get("toc_items", [])
    print(f"\n  3. TOC Items: {len(toc_items)} items")
    
    # 4. Structure analysis
    top_level = [it for it in toc_items if "." not in it.get("structure", "")]
    print(f"     Top-level nodes: {len(top_level)}")
    for i, item in enumerate(top_level[:10]):
        print(f"       [{item.get('structure')}] p.{item.get('physical_index')}  {item.get('title', '')[:50]}")
    if len(top_level) > 10:
        print(f"       ... and {len(top_level)-10} more")
    
    # 5. Check for page issues
    pis = [it.get("physical_index", 0) for it in toc_items if it.get("physical_index")]
    if pis:
        print(f"\n  4. Physical Index Range: {min(pis)}-{max(pis)}")
        # Check for duplicates
        dupes = [pi for pi in set(pis) if pis.count(pi) > 1]
        if dupes:
            print(f"     WARNING: Duplicate physical_index: {dupes}")
    
    # 6. Large nodes
    large_nodes = []
    for i, item in enumerate(toc_items):
        start = item.get("physical_index", 0)
        if not start:
            continue
        if i < len(toc_items) - 1:
            end = toc_items[i+1].get("physical_index", start + 1) - 1
        else:
            end = analysis.get("page_count", start)
        span = end - start + 1
        if span >= 8:
            large_nodes.append((item.get("title", "")[:40], span, start, end))
    if large_nodes:
        print(f"\n  5. Large Nodes (span >= 8):")
        for title, span, start, end in large_nodes:
            print(f"     '{title}' span={span} (p.{start}-p.{end})")
    
    # 7. Post-processing
    tree, completeness = post_process_toc(toc_items, analysis.get("page_count", 0))
    print(f"\n  6. Post-Processing: {len(tree)} top-level nodes, completeness={completeness}")

async def main():
    print("SYSTEMATIC DEBUGGING - Phase 1: Evidence Gathering")
    print("=" * 80)
    
    for name, pattern in test_files.items():
        await diagnose_single(name, pattern)
    
    print(f"\n{'='*80}")
    print("Phase 1 Complete")
    print(f"{'='*80}")

asyncio.run(main())
