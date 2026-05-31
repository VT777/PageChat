import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import os
import re
import asyncio
from pathlib import Path

# Find the actual file
base_dir = Path("D:/projects/page_chat/backend/data/documents")
for f in base_dir.iterdir():
    if "6de931ad" in f.name:
        file_path = str(f)
        print(f"Found: {f.name}")
        break
else:
    print("File not found")
    sys.exit(1)

# Test Phase 0: analyze_pdf_structure
from pageindex.pdf_analyzer import analyze_pdf_structure

print("\n=== Phase 0: Document Analysis ===")
analysis = analyze_pdf_structure(file_path)
print(f"Page count: {analysis['page_count']}")
print(f"Text coverage: {analysis['text_coverage']:.0%}")
print(f"Is image only: {analysis['is_image_only_pdf']}")

# Test Phase 0.5: Anchor detection
from pageindex.balanced_toc import _vlm_detect_anchors

async def test_anchors():
    print("\n=== Phase 0.5: Anchor Detection ===")
    anchors = await _vlm_detect_anchors(file_path)
    print(f"TOC pages: {anchors.get('toc_pages', [])}")
    print(f"First content page: {anchors.get('first_content_page')}")
    return anchors

# Test Phase 0.5: OCR
from app.services.pageindex_service import PageIndexService

async def test_ocr(anchors):
    print("\n=== Phase 0.5: OCR Validation ===")
    service = PageIndexService()
    toc_pages = anchors.get("toc_pages", [])
    if toc_pages:
        pages_to_ocr = sorted(set(
            [p - 1 for p in toc_pages] +
            list(range(max(toc_pages), min(max(toc_pages) + 6, analysis["page_count"])))
        ))
        ocr_map = await service._ocr_pages_for_toc_validation(
            Path(file_path), pages_to_ocr
        )
        print(f"OCR result: {len(ocr_map)} pages with text")
        return ocr_map
    return {}

# Test Phase 1: TOC building with new mapping
from pageindex.balanced_toc import build_balanced_toc_visual

async def test_toc_building(anchors, ocr_map):
    print("\n=== Phase 1: TOC Building ===")
    result = await build_balanced_toc_visual(
        file_path, analysis,
        anchors=anchors,
        ocr_text_map=ocr_map,
    )
    toc_items = result.get("toc_items", [])
    print(f"Source: {result.get('source')}")
    print(f"Items count: {len(toc_items)}")
    
    if toc_items:
        # Check physical indices
        pis = [item.get('physical_index', 0) for item in toc_items]
        min_pi = min(pis)
        max_pi = max(pis)
        out_of_range = sum(1 for pi in pis if pi > analysis['page_count'])
        
        print(f"\nPhysical indices range: {min_pi} - {max_pi}")
        print(f"Page count: {analysis['page_count']}")
        print(f"Out of range items: {out_of_range}")
        
        # Check monotonicity
        non_monotonic = sum(1 for i in range(1, len(pis)) if pis[i] <= pis[i-1])
        print(f"Non-monotonic items: {non_monotonic}")
        
        # Show first and last items
        print(f"\nFirst 3 items:")
        for item in toc_items[:3]:
            print(f"  logical={item.get('page', '?')} -> physical={item.get('physical_index', '?')}")
        print(f"\nLast 3 items:")
        for item in toc_items[-3:]:
            print(f"  logical={item.get('page', '?')} -> physical={item.get('physical_index', '?')}")
        
        # Check case 41 mapping
        case_41 = toc_items[-1]
        print(f"\nCase 41 (last item):")
        print(f"  logical page: {case_41.get('page', '?')}")
        print(f"  physical page: {case_41.get('physical_index', '?')}")
        print(f"  expected for 44-page PDF: ~44")
        
    return result

async def main():
    anchors = await test_anchors()
    ocr_map = await test_ocr(anchors)
    result = await test_toc_building(anchors, ocr_map)
    
    print("\n=== Summary ===")
    toc_items = result.get('toc_items', [])
    print(f"Total TOC items: {len(toc_items)}")
    print(f"Expected: 41")
    if toc_items:
        pis = [item.get('physical_index', 0) for item in toc_items]
        out_of_range = sum(1 for pi in pis if pi > analysis['page_count'])
        print(f"Items out of range (> {analysis['page_count']}): {out_of_range}")
        print(f"Status: {'PASS' if out_of_range == 0 and len(toc_items) == 41 else 'FAIL'}")

if __name__ == "__main__":
    asyncio.run(main())
