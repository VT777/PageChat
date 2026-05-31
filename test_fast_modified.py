"""Test modified fast path for tech insight report."""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os, asyncio
from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.fast_toc import try_fast_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Test the problematic file
files = glob.glob(f"{doc_dir}/*097e50d9*")
if not files:
    print("File not found")
    sys.exit(1)

file_path = files[0]
print(f"Testing: {os.path.basename(file_path)}\n")

# Analyze PDF
analysis = analyze_pdf_structure(file_path)
print(f"PDF Analysis:")
print(f"  Pages: {analysis['page_count']}")
print(f"  Text coverage: {analysis['text_coverage']:.2f}")
print(f"  Is garbled: {analysis['is_garbled_pdf']}")
print(f"  Code TOC source: {analysis['code_toc']['source']}")
print(f"  Code TOC items: {len(analysis['code_toc']['items'] or [])}")
print()

# Test fast path
async def test_fast():
    print("=== Testing Fast Path ===\n")
    
    result = await try_fast_toc(analysis, model="qwen3.6-flash")
    
    if result:
        toc_items = result.get("toc_items", [])
        source = result.get("source", "unknown")
        quality_failed = result.get("quality_check_failed", False)
        
        print(f"Fast path result:")
        print(f"  Source: {source}")
        print(f"  Items: {len(toc_items)}")
        print(f"  Quality check failed: {quality_failed}")
        print()
        
        # Show first 20 items
        print("First 20 items:")
        for i, item in enumerate(toc_items[:20]):
            struct = item.get("structure", "")
            title = item.get("title", "")[:50]
            pi = item.get("physical_index", 0)
            print(f"  [{i}] s={struct:6s} pi={pi:2d} {title}")
        
        if len(toc_items) > 20:
            print(f"  ... and {len(toc_items) - 20} more")
        
        # Check structure
        main_chapters = [it for it in toc_items if "." not in str(it.get("structure", ""))]
        sub_chapters = [it for it in toc_items if "." in str(it.get("structure", ""))]
        print(f"\nStructure:")
        print(f"  Main chapters: {len(main_chapters)}")
        print(f"  Sub chapters: {len(sub_chapters)}")
        
        # Check if fast path succeeded (not quality_check_failed)
        if not quality_failed:
            print(f"\n✓ Fast path SUCCEEDED")
        else:
            print(f"\n✗ Fast path returned with quality_check_failed=True")
    else:
        print("✗ Fast path FAILED (returned None)")
        print("This means it was rejected by fast path")

asyncio.run(test_fast())
