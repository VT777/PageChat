import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio, os, sqlite3

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors
from pageindex.post_processing import post_process_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"
db_path = "D:/projects/page_chat/backend/data/knowclaw.db"

test_files = {
    "AI_Agent_2026": "*9cf5b5be*",
    "第五范式_2025": "*90e75e6f*", 
    "技术应用洞察_2025": "*097e50d9*",
    "AI治理_2025": "*a1ed6276*",
}

async def diagnose_detailed(name, pattern):
    print(f"\n{'='*80}")
    print(f"DETAILED DIAGNOSIS: {name}")
    print(f"{'='*80}")
    
    files = glob.glob(f"{doc_dir}/{pattern}")
    if not files:
        print(f"  FILE NOT FOUND: {pattern}")
        return
    
    file_path = files[0]
    print(f"  File: {os.path.basename(file_path)}")
    
    # 1. PDF Analysis
    analysis = analyze_pdf_structure(file_path)
    print(f"\n  1. PDF Structure:")
    print(f"     pages={analysis.get('page_count')}")
    print(f"     text_coverage={analysis.get('text_coverage', 0):.2f}")
    print(f"     has_code_toc={analysis['code_toc']['items'] is not None}")
    print(f"     code_toc_source={analysis['code_toc'].get('source')}")
    
    # 2. Check DB status
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, status, error_message FROM documents WHERE file_path LIKE ?", (f"%{os.path.basename(file_path)}",))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        print(f"\n  2. DB Status:")
        print(f"     id={row[0]}")
        print(f"     status={row[1]}")
        print(f"     error={row[2]}")
    
    # 3. Anchor detection
    anchors = await _vlm_detect_anchors(file_path)
    print(f"\n  3. Anchors:")
    print(f"     toc_pages={anchors.get('toc_pages')}")
    print(f"     dividers={anchors.get('chapter_dividers')}")
    print(f"     first_content={anchors.get('first_content_page')}")
    
    # 4. Full TOC extraction
    result = await build_balanced_toc_visual(file_path, analysis, model="qwen3.6-flash", anchors=anchors)
    toc_items = result.get("toc_items", [])
    
    print(f"\n  4. TOC Extraction:")
    print(f"     total_items={len(toc_items)}")
    
    # Show ALL items with structure analysis
    print(f"\n     All items (structure analysis):")
    for i, item in enumerate(toc_items):
        struct = item.get('structure', 'NONE')
        title = item.get('title', '')[:50]
        pi = item.get('physical_index', 'NONE')
        has_dot = '.' in str(struct)
        is_empty = not struct
        print(f"       [{i}] struct={struct:10} | pi={pi:4} | empty={is_empty} | dot={has_dot} | {title}")
    
    # 5. Post-processing
    tree, completeness = post_process_toc(toc_items, analysis.get("page_count", 0))
    print(f"\n  5. Post-Processing:")
    print(f"     top_level_nodes={len(tree)}")
    
    # Show tree structure
    print(f"\n     Tree structure:")
    for node in tree:
        s = node.get('start_index', '?')
        e = node.get('end_index', '?')
        st = node.get('structure', '?')
        title = node.get('title', '')[:50]
        children = node.get('nodes', [])
        print(f"       [{st}] p.{s}-{e} {title} (children={len(children)})")
        for child in children:
            cs = child.get('start_index', '?')
            ce = child.get('end_index', '?')
            cst = child.get('structure', '?')
            ctitle = child.get('title', '')[:40]
            print(f"         [{cst}] p.{cs}-{ce} {ctitle}")
    
    # 6. Smart Grouping Check
    print(f"\n  6. Smart Grouping Check:")
    dividers = anchors.get("chapter_dividers", [])
    top_items = [it for it in toc_items if "." not in str(it.get("structure", ""))]
    print(f"     dividers_count={len(dividers)}")
    print(f"     top_items_count={len(top_items)}")
    print(f"     total_items_count={len(toc_items)}")
    if dividers and len(top_items) != len(dividers):
        print(f"     MISMATCH: dividers({len(dividers)}) != top_items({len(top_items)})")
        print(f"     Smart grouping SHOULD have triggered!")
    else:
        print(f"     Match or no dividers")

async def main():
    print("SYSTEMATIC DEBUGGING - Phase 1: Evidence Gathering")
    print("=" * 80)
    
    for name, pattern in test_files.items():
        await diagnose_detailed(name, pattern)
    
    print(f"\n{'='*80}")
    print("Phase 1 Complete")
    print(f"{'='*80}")

asyncio.run(main())
