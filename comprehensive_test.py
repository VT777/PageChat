"""
Comprehensive Test Framework for TOC Extraction Strategies
Tests 3 approaches and evaluates against user requirements:
1. 一级目录符合"汇报提纲"
2. 内容划分正确，页码对应正确
"""
import sys, os, asyncio
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import (
    build_balanced_toc_visual,
    _vlm_detect_anchors,
    _branch_a_toc_page,
    _branch_c_fulltext
)

doc_dir = 'backend/data/documents'
target = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target = os.path.join(doc_dir, f)
        break

# Ground truth based on user's description
ground_truth = {
    'title': '2025年第五范式-人工智能驱动的科技创新报告',
    'chapters': [
        {'name': '一 百花齐放大模型时代', 'page': 2, 'subsections': [
            {'name': '1.1 第五范式与科学范式变迁', 'page': 4},
            {'name': '1.2 行业案例', 'page': 7},
        ]},
        {'name': '二 大模型重塑科学研究范式', 'page': 13, 'subsections': [
            {'name': '2.1 人工智能发展史', 'page': 14},
            {'name': '2.2 千问等大模型协同创新', 'page': 20},
        ]},
        {'name': '三 未来创新范式展望', 'page': 25, 'subsections': [
            {'name': '3.1 科学研究复现的原因', 'page': 26},
            {'name': '3.2 科学研究复现的方法', 'page': 27},
            {'name': '3.3 大模型重塑科学研究范式（LLM for Science）', 'page': 28},
            {'name': '3.4 科学研究复现的案例', 'page': 47},
            {'name': '3.5 科学研究复现的工具', 'page': 48},
        ]},
        {'name': '四 大模型重塑全球创新生态', 'page': 50, 'subsections': [
            {'name': '4.1 论文撰写', 'page': 51},
            {'name': '4.2 项目申报-强化学习', 'page': 53},
            {'name': '4.3 高水平论文撰写', 'page': 56},
            {'name': '4.4 学位论文撰写', 'page': 58},
            {'name': '4.5 开源生态', 'page': 60},
        ]},
        {'name': '五 AI驱动的科技创新方式', 'page': 61, 'subsections': [
            {'name': '5.1 AI研究新方式的挑战', 'page': 62},
            {'name': '5.2 AI研究新方式展望', 'page': 63},
            {'name': '5.3 新范式促进学科交叉的AI研究', 'page': 64},
            {'name': '5.4 新范式促进学科交叉的基础研究', 'page': 65},
            {'name': '5.5 AI研究新方式下的潜在风险', 'page': 66},
            {'name': '5.6 AI研究新方式下的潜在风险', 'page': 67},
        ]}
    ]
}

def evaluate_toc(items, ground_truth):
    """Evaluate TOC quality against ground truth."""
    if not items:
        return {'score': 0, 'issues': ['No items generated']}
    
    issues = []
    
    # Check 1: Do we have top-level chapters?
    top_level = [i for i in items if '.' not in str(i.get('structure', ''))]
    if len(top_level) < 3:
        issues.append(f"Too few top-level chapters: {len(top_level)} (expected 5)")
    
    # Check 2: Do we have subsections?
    has_subsections = any('.' in str(i.get('structure', '')) for i in items)
    if not has_subsections:
        issues.append("No subsections found")
    
    # Check 3: Are major chapters present?
    chapter_titles = [c['name'] for c in ground_truth['chapters']]
    found_titles = [i.get('title', '') for i in items]
    
    # Check 4: Page alignment
    page_errors = []
    for chapter in ground_truth['chapters']:
        # Find matching item
        matches = [i for i in items if chapter['name'] in i.get('title', '')]
        if not matches:
            issues.append(f"Missing chapter: {chapter['name']}")
        else:
            actual_page = matches[0].get('physical_index', 0)
            expected_page = chapter['page']
            if abs(actual_page - expected_page) > 2:
                page_errors.append(
                    f"{chapter['name']}: expected p.{expected_page}, got p.{actual_page}"
                )
    
    if page_errors:
        issues.extend(page_errors[:3])  # Show first 3
    
    # Score
    score = max(0, 100 - len(issues) * 15)
    
    return {
        'score': score,
        'items': len(items),
        'top_level': len(top_level),
        'has_subsections': has_subsections,
        'issues': issues
    }

async def test_strategy(name, strategy_func, **kwargs):
    """Test a strategy."""
    print(f"\n{'='*80}")
    print(f"STRATEGY: {name}")
    print(f"{'='*80}")
    
    analysis = analyze_pdf_structure(target)
    start = asyncio.get_event_loop().time()
    
    try:
        result = await strategy_func(target, analysis, **kwargs)
        elapsed = asyncio.get_event_loop().time() - start
        
        items = result.get('toc_items', [])
        source = result.get('source', 'unknown')
        
        print(f"  Source: {source}")
        print(f"  Time: {elapsed:.1f}s")
        print(f"  Items: {len(items)}")
        
        # Show items
        for i, item in enumerate(items[:15]):
            print(f"    [{item.get('structure', '?')}] {item.get('title', '')[:50]} -> p.{item.get('physical_index', '?')}")
        if len(items) > 15:
            print(f"    ... and {len(items)-15} more")
        
        # Evaluate
        eval_result = evaluate_toc(items, ground_truth)
        print(f"\n  Evaluation:")
        print(f"    Score: {eval_result['score']}/100")
        print(f"    Top-level: {eval_result['top_level']}")
        print(f"    Has subsections: {eval_result['has_subsections']}")
        if eval_result['issues']:
            print(f"    Issues:")
            for issue in eval_result['issues']:
                print(f"      - {issue}")
        
        return {
            'name': name,
            'source': source,
            'time': elapsed,
            'items': len(items),
            'score': eval_result['score'],
            'top_level': eval_result['top_level'],
            'has_subsections': eval_result['has_subsections'],
            'issues': eval_result['issues'],
            'toc': items
        }
        
    except Exception as e:
        print(f"  ERROR: {e}")
        return {'name': name, 'error': str(e)}

async def main():
    print("="*80)
    print("TOC EXTRACTION STRATEGY COMPARISON")
    print("="*80)
    print(f"File: {os.path.basename(target)}")
    
    analysis = analyze_pdf_structure(target)
    print(f"Pages: {analysis['page_count']}")
    print(f"Text coverage: {analysis['text_coverage']:.1%}")
    print(f"\nExpected structure:")
    for ch in ground_truth['chapters']:
        print(f"  [{ch['name']}] -> p.{ch['page']}")
        for sub in ch['subsections'][:2]:
            print(f"    {sub['name']} -> p.{sub['page']}")
        if len(ch['subsections']) > 2:
            print(f"    ... and {len(ch['subsections'])-2} more")
    
    results = []
    
    # Test 1: Current behavior
    anchors = await _vlm_detect_anchors(target)
    r1 = await test_strategy("Current (Branch B with dividers)", 
                             build_balanced_toc_visual, anchors=anchors)
    results.append(r1)
    
    # Test 2: Full document scan
    print(f"\n{'='*80}")
    print("STRATEGY: Branch C (Full Document Scan)")
    print(f"{'='*80}")
    start = asyncio.get_event_loop().time()
    result_c = await _branch_c_fulltext(target, analysis['page_count'])
    elapsed = asyncio.get_event_loop().time() - start
    items_c = result_c.get('toc_items', [])
    
    print(f"  Source: {result_c.get('source')}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Items: {len(items_c)}")
    for i, item in enumerate(items_c[:15]):
        print(f"    [{item.get('structure', '?')}] {item.get('title', '')[:50]} -> p.{item.get('physical_index', '?')}")
    if len(items_c) > 15:
        print(f"    ... and {len(items_c)-15} more")
    
    eval_c = evaluate_toc(items_c, ground_truth)
    print(f"\n  Evaluation:")
    print(f"    Score: {eval_c['score']}/100")
    print(f"    Top-level: {eval_c['top_level']}")
    print(f"    Has subsections: {eval_c['has_subsections']}")
    if eval_c['issues']:
        print(f"    Issues:")
        for issue in eval_c['issues']:
            print(f"      - {issue}")
    
    results.append({
        'name': 'Branch C (Full Scan)',
        'source': result_c.get('source'),
        'time': elapsed,
        'items': len(items_c),
        'score': eval_c['score'],
        'top_level': eval_c['top_level'],
        'has_subsections': eval_c['has_subsections'],
        'issues': eval_c['issues'],
        'toc': items_c
    })
    
    # Summary
    print(f"\n{'='*80}")
    print("FINAL COMPARISON")
    print(f"{'='*80}")
    print(f"{'Strategy':<30} {'Score':<8} {'Time':<8} {'Items':<8} {'Top':<6} {'Subs':<6}")
    print("-" * 80)
    for r in sorted(results, key=lambda x: x.get('score', 0), reverse=True):
        if 'error' in r:
            print(f"{r['name']:<30} ERROR: {r['error']}")
        else:
            print(f"{r['name']:<30} {r['score']:<8} {r['time']:.1f}s   {r['items']:<8} {r['top_level']:<6} {str(r['has_subsections']):<6}")
    
    # Recommendation
    best = max(results, key=lambda x: x.get('score', 0) if 'error' not in x else -1)
    print(f"\nRECOMMENDATION: {best['name']} (Score: {best['score']})")
    
    return results

results = asyncio.run(main())
