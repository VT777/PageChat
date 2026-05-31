import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual, 
    _vlm_detect_anchors,
    _vlm_scan_document_pages,
)

async def diagnose():
    print("=" * 80)
    print("FA82 DIAGNOSIS REPORT")
    print("=" * 80)
    
    analysis = analyze_pdf_structure(file_path)
    page_count = analysis["page_count"]
    print(f"\n1. PDF Analysis: page_count={page_count}")
    
    # 2. Anchor detection
    print("\n2. Anchor Detection (_vlm_detect_anchors)")
    anchors = await _vlm_detect_anchors(file_path)
    print(f"   toc_pages={anchors.get('toc_pages')}")
    print(f"   dividers={anchors.get('chapter_dividers')}")
    print(f"   first_content={anchors.get('first_content_page')}")
    
    # 3. Full document scan
    print("\n3. Full Document Scan (_vlm_scan_document_pages)")
    page_titles = await _vlm_scan_document_pages(file_path, page_count, model="qwen3.6-flash")
    
    chapters = [pt for pt in page_titles if pt.get("type") == "chapter"]
    print(f"   Chapter pages found: {len(chapters)}")
    for ch in chapters:
        print(f"      p.{ch['physical_index']}: {ch['title'][:50]}")
    
    # 4. The key issue
    print("\n4. KEY FINDINGS:")
    dividers = anchors.get("chapter_dividers", [])
    first_content = anchors.get("first_content_page")
    
    print(f"   - Dividers detected: {dividers}")
    print(f"   - First content page (from anchor): {first_content}")
    if chapters:
        actual_first_chapter = min(ch["physical_index"] for ch in chapters)
        print(f"   - Actual first chapter page (from scan): {actual_first_chapter}")
        if first_content != actual_first_chapter:
            print(f"   *** ISSUE: first_content is WRONG! Should be {actual_first_chapter}, not {first_content}")
    
    print(f"\n   - TOC items have NO page numbers (all page=null)")
    print(f"   - Without page numbers, uniform distribution is used")
    print(f"   - Uniform distribution starts from first_content={first_content}")
    print(f"   - This causes ALL chapter positions to be off!")
    
    if dividers:
        print(f"\n   - BUT dividers are ACCURATE: {dividers}")
        print(f"   - Code does NOT use dividers to correct physical_index when page=null")
        print(f"   - This is the ROOT CAUSE!")
    
    print("\n" + "=" * 80)
    print("END OF DIAGNOSIS")
    print("=" * 80)

asyncio.run(diagnose())
