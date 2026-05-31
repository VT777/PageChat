"""
UNIFORM DISTRIBUTION STRATEGY ANALYSIS
=====================================

Current State:
- _map_toc_physical_pages has 3 strategies:
  1. OCR verification (most accurate)
  2. Standard offset (page numbers trustworthy)
  3. Uniform distribution (no page numbers or unreliable)

- _map_uniformly is called when:
  a) No logical pages found (items_with_page is empty)
  b) After dividers attempt fails
  c) Fallback from proportional mapping

Problems Identified:
1. Fabricates positions that don't reflect reality
2. Hides real chapter spans, preventing large node detection
3. Creates false confidence (positions look precise but are wrong)
4. Adds complexity without value in most cases
5. Never corrects itself - fake positions persist

When is uniform distribution used?
- TOC items extracted from VLM don't have "page" field
- This happens when the TOC page doesn't show page numbers
- Or when VLM fails to extract page numbers

Better alternatives:
1. If dividers exist → use dividers (already partially implemented but bypassed)
2. If no dividers → full document scan (more accurate)
3. If no dividers and can't scan → leave positions empty, let post-processing handle it

Key insight: NEVER fabricate positions. It's better to admit uncertainty than to lie.

Proposed change:
- Remove _map_uniformly entirely
- When no page numbers and no dividers match → trigger full scan
- When page numbers exist but unreliable → use proportional mapping (already implemented)
- Let post-processing handle gaps

Let's verify this won't break other documents...
"""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os
from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Analyze all test files
files_to_test = [
    "*097e50d9*",  # 技术应用洞察
    "*d9b2b5ea*",  # AI眼镜
    "*8cefa13e*",  # 重庆案例集
    "*90e75e6f*",  # 第五范式
    "*a1ed6276*",  # AI治理
    "*9cf5b5be*",  # AI Agent
]

print("=== UNIFORM DISTRIBUTION IMPACT ANALYSIS ===\n")

for pattern in files_to_test:
    files = glob.glob(f"{doc_dir}/{pattern}")
    if not files:
        continue
    
    file_path = files[0]
    analysis = analyze_pdf_structure(file_path)
    
    print(f"File: {os.path.basename(file_path)}")
    print(f"  Text coverage: {analysis['text_coverage']:.2f}")
    print(f"  Is garbled: {analysis['is_garbled_pdf']}")
    print(f"  Code TOC items: {len(analysis['code_toc']['items'] or [])}")
    print(f"  Code TOC source: {analysis['code_toc']['source'] or 'None'}")
    
    # Check if code TOC has page numbers
    if analysis['code_toc']['items']:
        items = analysis['code_toc']['items']
        has_pages = sum(1 for it in items if it.get('physical_index'))
        print(f"  Items with pages: {has_pages}/{len(items)}")
        
        # Check first few items
        for i, it in enumerate(items[:5]):
            print(f"    [{i}] s={it.get('structure','')} pi={it.get('physical_index','null')} {it.get('title','')[:40]}")
    
    print()

print("=== CONCLUSION ===")
print("""
For documents with code TOC (bookmarks/links/regex):
- Page numbers are usually present (from PDF metadata)
- Uniform distribution is NOT needed

For documents without code TOC:
- Visual path is used
- TOC is extracted by VLM from TOC page images
- If TOC page shows page numbers → standard offset works
- If TOC page doesn't show page numbers → uniform distribution kicks in

The problem: When TOC page doesn't show page numbers AND we have dividers,
we should use dividers instead of uniform distribution.

Current code attempts this but the logic is flawed:
1. _map_toc_physical_pages checks for dividers
2. But only when items_with_page is empty
3. And the dividers check is before _map_uniformly
4. BUT: if items have page=null (not missing), items_with_page is still empty
5. So it should work... let me check why it doesn't

Wait, let me re-read the code...
""")
