"""
Test Framework: Compare different TOC extraction strategies
for the problematic PDF (2025年第五范式报告)
"""
import sys
import os
import asyncio
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual, 
    _vlm_detect_anchors,
    _branch_a_toc_page,
    _branch_c_fulltext
)

# Find the file
doc_dir = 'backend/data/documents'
target_file = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target_file = os.path.join(doc_dir, f)
        break

async def test_strategy(name, strategy_func, **kwargs):
    """Test a single strategy and return metrics."""
    print(f"\n{'='*80}")
    print(f"TESTING: {name}")
    print(f"{'='*80}")
    
    analysis = analyze_pdf_structure(target_file)
    start_time = asyncio.get_event_loop().time()
    
    try:
        result = await strategy_func(target_file, analysis, **kwargs)
        elapsed = asyncio.get_event_loop().time() - start_time
        
        items = result.get('toc_items', [])
        source = result.get('source', 'unknown')
        
        # Metrics
        metrics = {
            'strategy': name,
            'elapsed': elapsed,
            'source': source,
            'item_count': len(items),
            'has_subsections': any('.' in str(i.get('structure', '')) for i in items),
            'page_range': f"{items[0].get('physical_index', '?')}-{items[-1].get('physical_index', '?')}" if items else 'N/A',
            'items': items
        }
        
        print(f"  Time: {elapsed:.1f}s")
        print(f"  Source: {source}")
        print(f"  Items: {len(items)}")
        print(f"  Has subsections: {metrics['has_subsections']}")
        print(f"  Page range: {metrics['page_range']}")
        
        return metrics
        
    except Exception as e:
        print(f"  ERROR: {e}")
        return {'strategy': name, 'error': str(e)}

async def run_all_tests():
    """Run all strategies and compare."""
    print("TOC Extraction Strategy Comparison")
    print(f"File: {target_file}")
    
    analysis = analyze_pdf_structure(target_file)
    print(f"Pages: {analysis['page_count']}")
    print(f"Text coverage: {analysis['text_coverage']:.1%}")
    
    results = []
    
    # Strategy 1: Current behavior (Branch A with buggy logic)
    anchors = await _vlm_detect_anchors(target_file)
    r1 = await test_strategy(
        "Current: Branch A (original)",
        build_balanced_toc_visual,
        anchors=anchors
    )
    results.append(r1)
    
    # Strategy 2: Branch C (full document scan)
    # We simulate this by calling _branch_c_fulltext directly
    print(f"\n{'='*80}")
    print("TESTING: Branch C (Full Document Scan)")
    print(f"{'='*80}")
    start_time = asyncio.get_event_loop().time()
    result_c = await _branch_c_fulltext(target_file, analysis['page_count'])
    elapsed = asyncio.get_event_loop().time() - start_time
    items_c = result_c.get('toc_items', [])
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Source: {result_c.get('source')}")
    print(f"  Items: {len(items_c)}")
    print(f"  Has subsections: {any('.' in str(i.get('structure', '')) for i in items_c)}")
    results.append({
        'strategy': 'Branch C (Full Scan)',
        'elapsed': elapsed,
        'source': result_c.get('source'),
        'item_count': len(items_c),
        'has_subsections': any('.' in str(i.get('structure', '')) for i in items_c),
        'items': items_c
    })
    
    # Strategy 3: Branch A with fixed empty-list handling
    # This would require code modification, so we simulate the logic
    print(f"\n{'='*80}")
    print("SIMULATION: Branch A with empty-list fix")
    print(f"{'='*80}")
    print("  This would clear toc_pages when all pages are filtered,")
    print("  causing fallback to Branch B/C")
    
    # Summary
    print(f"\n{'='*80}")
    print("COMPARISON SUMMARY")
    print(f"{'='*80}")
    for r in results:
        if 'error' in r:
            print(f"  {r['strategy']}: ERROR - {r['error']}")
        else:
            print(f"  {r['strategy']}: {r['item_count']} items, {r['elapsed']:.1f}s, subs={r['has_subsections']}")
    
    return results

# Run tests
results = asyncio.run(run_all_tests())
print("\nDone. Results available in 'results' variable.")
