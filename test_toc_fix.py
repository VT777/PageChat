import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import os
import json
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
print(f"Code TOC source: {analysis['code_toc']['source']}")
print(f"Code TOC items: {len(analysis['code_toc']['items']) if analysis['code_toc']['items'] else 0}")

# Test Phase 0.5: Anchor detection
from pageindex.balanced_toc import _vlm_detect_anchors

async def test_anchors():
    print("\n=== Phase 0.5: Anchor Detection ===")
    anchors = await _vlm_detect_anchors(file_path)
    print(f"TOC pages: {anchors.get('toc_pages', [])}")
    print(f"First content page: {anchors.get('first_content_page')}")
    print(f"Dividers: {len(anchors.get('chapter_dividers', []))}")
    return anchors

# Test Phase 0.5: OCR (if needed)
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
        print(f"OCR pages: {pages_to_ocr}")
        ocr_map = await service._ocr_pages_for_toc_validation(
            Path(file_path), pages_to_ocr
        )
        print(f"OCR result: {len(ocr_map)} pages with text")
        for page_num, text in list(ocr_map.items())[:3]:
            print(f"  p.{page_num}: {text[:100]}...")
        return ocr_map
    return {}

# Test Phase 1: TOC building
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
        print("\nFirst 5 items:")
        for item in toc_items[:5]:
            print(f"  {item.get('structure', '?')}: {item['title'][:50]} -> p.{item.get('physical_index', '?')}")
        print("\nLast 5 items:")
        for item in toc_items[-5:]:
            print(f"  {item.get('structure', '?')}: {item['title'][:50]} -> p.{item.get('physical_index', '?')}")
        
        # Check physical_index correctness
        pis = [item.get('physical_index', 0) for item in toc_items]
        print(f"\nPhysical indices range: {min(pis)} - {max(pis)}")
        
        # Check if all 41 items are present
        # Extract case numbers from titles
        case_count = sum(1 for item in toc_items if re.search(r'\d+', item.get('title', '')))
        print(f"Items with numbers in title: {case_count}")
        
    return result

async def main():
    anchors = await test_anchors()
    ocr_map = await test_ocr(anchors)
    result = await test_toc_building(anchors, ocr_map)
    
    print("\n=== Summary ===")
    print(f"Total TOC items: {len(result.get('toc_items', []))}")
    print(f"Expected: 41 (for Chongqing case collection)")

if __name__ == "__main__":
    asyncio.run(main())
