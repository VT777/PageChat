"""
Integration Test: Compare Official vs Hook-Enhanced Pipeline
Test hook effects on real PDFs
"""
import sys
sys.path.insert(0, 'backend')

import os
import glob
import asyncio
from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.enhancement_hooks import MultimodalEnhancementHooks

# Find target document
doc_dir = 'backend/data/documents'
target_files = glob.glob(os.path.join(doc_dir, 'f9a2f07e*.pdf'))

if not target_files:
    print("Target document not found")
    sys.exit(1)

target_file = target_files[0]
print("="*80)
print("Integration Test: Hook Enhancement Validation")
print("="*80)
print(f"Target: {os.path.basename(target_file)}")
print()

# Analyze document
analysis = analyze_pdf_structure(target_file)
print(f"Total pages: {analysis['page_count']}")
print(f"Dividers: {analysis.get('chapter_dividers', [])}")
print()

# Test 1: Structure generation from dividers
print("Test 1: Divider-based Structure Generation")
print("-"*80)

hooks = MultimodalEnhancementHooks(enable_hooks=['on_structure_generated'])
page_list = [(text, len(text)) for text in analysis['page_texts']]

async def test_structure_hook():
    analysis_info = {"chapter_dividers": analysis.get('chapter_dividers', [])}
    result = await hooks.on_structure_generated([], page_list, analysis_info)
    
    if result:
        print(f"[OK] Generated {len(result)} chapters:")
        for item in result:
            print(f"  - {item['title']} (p.{item['physical_index']})")
        return True
    else:
        print("[FAIL] No structure generated")
        return False

success1 = asyncio.run(test_structure_hook())
print()

# Test 2: TOC detection enhancement
print("Test 2: TOC Detection Enhancement")
print("-"*80)

async def test_toc_detection_hook():
    hooks = MultimodalEnhancementHooks(enable_hooks=['on_check_toc'])
    check_toc_result = {"toc_content": ""}
    result = await hooks.on_check_toc(page_list, check_toc_result)
    
    if result and result.get('has_dividers'):
        print(f"[OK] Detected implicit TOC (dividers): {result.get('divider_pages', [])}")
        return True
    else:
        print("[FAIL] No dividers detected")
        return False

success2 = asyncio.run(test_toc_detection_hook())
print()

# Test 3: Verification enhancement
print("Test 3: Verification Enhancement (Fuzzy Matching)")
print("-"*80)

async def test_verify_hook():
    hooks = MultimodalEnhancementHooks(enable_hooks=['on_verify'])
    incorrect_items = [{"title": "百花齐放的大模型时代", "physical_index": 4}]
    result = await hooks.on_verify(0.3, incorrect_items, page_list)
    
    if result:
        accuracy, items = result
        print(f"[OK] Accuracy improved: 30% -> {accuracy:.0%}")
        print(f"  Remaining errors: {len(items)}")
        return accuracy > 0.3
    else:
        print("[FAIL] Verification not enhanced")
        return False

success3 = asyncio.run(test_verify_hook())
print()

# Test 4: Compare official vs enhanced
print("Test 4: Structure Comparison")
print("-"*80)

code_toc = analysis.get('code_toc', {})
toc_items = code_toc.get('items', [])

print("Official TOC:")
if toc_items:
    for i, item in enumerate(toc_items[:5]):
        title = item.get('title', '')
        page = item.get('physical_index', 'N/A')
        print(f"  {i+1}. {title} (p.{page})")
    if len(toc_items) > 5:
        print(f"  ... {len(toc_items)-5} more items")
else:
    print("  No TOC")

print("\nEnhanced TOC:")
async def get_enhanced_structure():
    hooks = MultimodalEnhancementHooks(enable_hooks=['on_structure_generated'])
    analysis_info = {"chapter_dividers": analysis.get('chapter_dividers', [])}
    return await hooks.on_structure_generated([], page_list, analysis_info)

enhanced = asyncio.run(get_enhanced_structure())
if enhanced:
    for i, item in enumerate(enhanced):
        print(f"  {i+1}. {item['title']} (p.{item['physical_index']})")
else:
    print("  No enhancement")

print()

# Summary
print("="*80)
print("Test Results Summary")
print("="*80)
print(f"[OK] Divider structure generation: {'PASS' if success1 else 'FAIL'}")
print(f"[OK] TOC detection enhancement: {'PASS' if success2 else 'FAIL'}")
print(f"[OK] Verification enhancement: {'PASS' if success3 else 'FAIL'}")
print()

if success1 and success2 and success3:
    print("[SUCCESS] All integration tests passed!")
    print("\nHook architecture can:")
    print("  1. Detect dividers and generate correct chapter structure")
    print("  2. Enhance TOC detection (recognize implicit TOC)")
    print("  3. Improve verification accuracy (fuzzy matching)")
else:
    print("[WARNING] Some tests failed, needs investigation")
