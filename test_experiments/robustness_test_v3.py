"""
改进的鲁棒性测试 v3：平衡误判率和召回率
关键洞察：目标文档虽然有regex TOC，但TOC质量很差（页码是年份）
需要判断：TOC质量差 + 有汇报提纲特征 => 进入Branch D
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re

doc_dir = 'backend/data/documents'

def is_toc_valid(items, page_count):
    """判断TOC是否有效：页码是否在合理范围内"""
    if not items or len(items) < 2:
        return False
    
    # 检查页码是否合理
    valid_pages = 0
    total_pages = 0
    for item in items:
        pi = item.get('physical_index', 0)
        if isinstance(pi, int) and 1 <= pi <= page_count:
            valid_pages += 1
        total_pages += 1
    
    # 如果<50%的页码合理，认为TOC无效
    if total_pages > 0 and valid_pages / total_pages < 0.5:
        return False
    
    # 检查页码是否单调递增
    pages = [item.get('physical_index', 0) for item in items if isinstance(item.get('physical_index'), int)]
    if len(pages) >= 2:
        is_monotonic = all(pages[i] <= pages[i+1] for i in range(len(pages)-1))
        if not is_monotonic:
            return False
    
    return True

def detect_outline_pages_v3(analysis):
    """
    v3改进：
    1. 如果TOC有效（页码合理），不进入Branch D
    2. 如果TOC无效（页码是年份等），但有多处"汇报提纲"，进入Branch D
    3. 没有TOC但有"汇报提纲"特征，进入Branch D
    """
    page_texts = analysis.get('page_texts', [])
    page_count = analysis['page_count']
    code_toc = analysis.get('code_toc', {})
    
    if not page_texts or page_count < 10:
        return False, []
    
    # 检查TOC有效性
    toc_items = code_toc.get('items', [])
    toc_valid = is_toc_valid(toc_items, page_count) if toc_items else False
    
    # 如果TOC有效，不需要Branch D
    if toc_valid:
        return False, []
    
    # 查找"汇报提纲"特征
    outline_candidates = []
    for i, text in enumerate(page_texts):
        page_num = i + 1
        text_len = len(text.strip())
        
        # 查找"汇报提纲"关键词
        if '汇报提纲' in text[:500] and text_len < 300 and text_len > 10:
            outline_candidates.append({
                'page': page_num,
                'len': text_len
            })
    
    if len(outline_candidates) < 2:
        return False, outline_candidates
    
    # 检查内容相似度
    fingerprints = {}
    for cand in outline_candidates:
        page_idx = cand['page'] - 1
        text = page_texts[page_idx]
        fp = re.sub(r'[\s\d]', '', text[:80])
        if fp in fingerprints:
            fingerprints[fp].append(cand['page'])
        else:
            fingerprints[fp] = [cand['page']]
    
    # 检查分散的重复页面
    has_dispersed_duplicates = False
    for fp, pages in fingerprints.items():
        if len(pages) >= 2:
            pages_sorted = sorted(pages)
            max_gap = max(pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1))
            if max_gap >= 5:
                has_dispersed_duplicates = True
    
    if not has_dispersed_duplicates:
        return False, outline_candidates
    
    return True, outline_candidates

def test_all_documents():
    """测试所有文档"""
    print("="*100)
    print("Robustness Test v3: Balanced Detection")
    print("="*100)
    print("\nKey insight: Target doc has regex TOC but it's invalid (years as page numbers)")
    print("Strategy: Check TOC validity, not just existence")
    
    results = []
    pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
    
    print(f"\nTesting {len(pdf_files)} PDF files...\n")
    
    for f in sorted(pdf_files):
        file_path = os.path.join(doc_dir, f)
        try:
            analysis = analyze_pdf_structure(file_path)
            toc_items = analysis['code_toc']['items'] if analysis['code_toc']['items'] else []
            toc_valid = is_toc_valid(toc_items, analysis['page_count'])
            
            is_outline, candidates = detect_outline_pages_v3(analysis)
            
            results.append({
                'file': os.path.basename(file_path),
                'pages': analysis['page_count'],
                'toc_source': analysis['code_toc']['source'],
                'toc_items': len(toc_items),
                'toc_valid': toc_valid,
                'is_outline': is_outline,
                'candidates': candidates
            })
        except Exception as e:
            results.append({'file': os.path.basename(file_path), 'error': str(e)})
    
    # 统计
    outline_docs = [r for r in results if r.get('is_outline', False)]
    normal_docs = [r for r in results if not r.get('is_outline', False) and 'error' not in r]
    
    print("="*100)
    print("Results")
    print("="*100)
    print(f"\nTotal: {len(results)}")
    print(f"  Outline: {len(outline_docs)}")
    print(f"  Normal: {len(normal_docs)}")
    
    # 详细信息
    print("\n" + "="*100)
    print("All Documents")
    print("="*100)
    print(f"{'File':<50} {'TOC':<10} {'Valid':<8} {'Outline':<10} {'Candidates'}")
    print("-" * 100)
    
    for r in results:
        if 'error' in r:
            print(f"{r['file'][:48]:<50} ERROR")
        else:
            cand_str = str([c['page'] for c in r['candidates']]) if r['candidates'] else '[]'
            toc_src = r['toc_source'] or 'None'
            file_name = r['file'][:48].encode('ascii', 'replace').decode()
            print(f"{file_name:<50} {toc_src:<10} {str(r['toc_valid']):<8} {str(r['is_outline']):<10} {cand_str}")
    
    # 目标文档检查
    print("\n" + "="*100)
    print("Target Document")
    print("="*100)
    for r in results:
        if 'f9a2f07e' in r['file']:
            print(f"\nFile: {r['file']}")
            print(f"  TOC source: {r['toc_source']} ({r['toc_items']} items)")
            print(f"  TOC valid: {r['toc_valid']}")
            print(f"  Is outline: {r['is_outline']}")
            print(f"  Candidates: {[c['page'] for c in r['candidates']]}")
            if r['is_outline']:
                print(f"  [OK] Correctly identified!")
            else:
                print(f"  [FAIL] Not identified")
    
    # 误判检查
    print("\n" + "="*100)
    print("False Positive Check")
    print("="*100)
    false_pos = [r for r in outline_docs if r['toc_valid']]
    print(f"\nDocuments with valid TOC but classified as outline: {len(false_pos)}")
    for r in false_pos:
        print(f"  - {r['file']} (TOC: {r['toc_source']}, {r['toc_items']} items)")
    
    missed = [r for r in results if 'f9a2f07e' in r['file'] and not r.get('is_outline', False)]
    if missed:
        print(f"\n[WARNING] Target document missed!")
    else:
        print(f"\n[OK] Target document correctly detected")
    
    return results

results = test_all_documents()
