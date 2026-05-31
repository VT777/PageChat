"""
改进的鲁棒性测试：更精确的"汇报提纲"检测逻辑
目标：降低误判率，确保只有真正的"汇报提纲"类文档才进入Branch D
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re

doc_dir = 'backend/data/documents'

def detect_outline_pages_v2(analysis):
    """
    改进的检测逻辑：
    1. 优先检查文档是否已有标准TOC（有则直接返回False）
    2. 检测"汇报提纲"关键词（比"目录"更精确）
    3. 要求重复页面内容高度相似（不仅仅是关键词）
    4. 重复页面分散在文档不同章节位置
    """
    page_texts = analysis.get('page_texts', [])
    page_count = analysis['page_count']
    code_toc = analysis.get('code_toc', {})
    
    if not page_texts or page_count < 10:
        return False, []
    
    # 条件1：如果文档已有标准TOC（书签或正则提取到>3项），不进入Branch D
    if code_toc.get('source') == 'bookmarks' and code_toc.get('items'):
        return False, []
    
    if code_toc.get('source') == 'regex' and len(code_toc.get('items', [])) > 3:
        # 如果正则提取的TOC质量较高（有页码信息），也不进入Branch D
        items = code_toc['items']
        has_pages = sum(1 for i in items if i.get('physical_index')) > len(items) * 0.5
        if has_pages:
            return False, []
    
    # 条件2：查找"汇报提纲"关键词（比"目录"更精确）
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
    
    # 条件3：检查内容相似度（不只是关键词匹配）
    # 提取候选页面的内容指纹
    fingerprints = {}
    for cand in outline_candidates:
        page_idx = cand['page'] - 1
        text = page_texts[page_idx]
        # 提取前80字符作为指纹（去掉空格和数字）
        fp = re.sub(r'[\s\d]', '', text[:80])
        if fp in fingerprints:
            fingerprints[fp].append(cand['page'])
        else:
            fingerprints[fp] = [cand['page']]
    
    # 检查是否有高度相似的内容分布在不同位置
    duplicate_groups = []
    for fp, pages in fingerprints.items():
        if len(pages) >= 2:
            # 检查是否分散（至少间隔5页）
            pages_sorted = sorted(pages)
            max_gap = max(pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1))
            if max_gap >= 5:
                duplicate_groups.append(pages)
    
    if not duplicate_groups:
        return False, outline_candidates
    
    # 条件4：要求至少3个重复页面（确保不是偶然的页眉/页脚）
    total_duplicate_pages = sum(len(g) for g in duplicate_groups)
    if total_duplicate_pages < 3:
        return False, outline_candidates
    
    return True, outline_candidates

def test_all_documents():
    """测试所有文档"""
    print("="*100)
    print("Improved Robustness Test: Branch D Detection Logic v2")
    print("="*100)
    print("\nImprovements:")
    print("  1. Exclude documents with standard TOC (bookmarks/regex)")
    print("  2. Focus on '汇报提纲' keyword (more specific)")
    print("  3. Require content similarity (not just keyword)")
    print("  4. Require dispersed duplicate pages (>=5 page gap)")
    print("  5. Require >=3 duplicate pages total")
    
    results = []
    pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
    
    print(f"\nTesting {len(pdf_files)} PDF files...\n")
    
    for f in sorted(pdf_files):
        file_path = os.path.join(doc_dir, f)
        try:
            analysis = analyze_pdf_structure(file_path)
            is_outline, candidates = detect_outline_pages_v2(analysis)
            
            results.append({
                'file': os.path.basename(file_path),
                'pages': analysis['page_count'],
                'text_coverage': analysis['text_coverage'],
                'is_outline': is_outline,
                'candidates': candidates,
                'code_toc_source': analysis['code_toc']['source'],
                'code_toc_items': len(analysis['code_toc']['items']) if analysis['code_toc']['items'] else 0
            })
        except Exception as e:
            results.append({
                'file': os.path.basename(file_path),
                'error': str(e)
            })
    
    # 统计
    outline_docs = [r for r in results if r.get('is_outline', False)]
    normal_docs = [r for r in results if not r.get('is_outline', False) and 'error' not in r]
    error_docs = [r for r in results if 'error' in r]
    
    print("="*100)
    print("Results Summary")
    print("="*100)
    print(f"\nTotal: {len(results)}")
    print(f"  Classified as outline: {len(outline_docs)}")
    print(f"  Normal: {len(normal_docs)}")
    print(f"  Errors: {len(error_docs)}")
    
    # 检查误判
    print("\n" + "="*100)
    print("Documents classified as 'outline'")
    print("="*100)
    
    if outline_docs:
        for r in outline_docs:
            print(f"\nFile: {r['file'].encode('ascii', 'replace').decode()}")
            print(f"  Pages: {r['pages']}, Text: {int(r['text_coverage']*100)}%")
            print(f"  Code TOC: {r['code_toc_source']} ({r['code_toc_items']} items)")
            print(f"  Candidate pages: {[c['page'] for c in r['candidates']]}")
            
            # 判断是否为误判
            if r['code_toc_source'] in ['bookmarks', 'regex'] and r['code_toc_items'] > 3:
                print(f"  [WARNING] Has standard TOC - potential false positive!")
    else:
        print("\nNone - good!")
    
    # 验证目标文档是否被正确识别
    print("\n" + "="*100)
    print("Target Document Check")
    print("="*100)
    target_found = False
    for r in results:
        if 'f9a2f07e' in r['file']:
            target_found = True
            print(f"\nTarget: {r['file'].encode('ascii', 'replace').decode()}")
            print(f"  Classified as outline: {r['is_outline']}")
            print(f"  Candidates: {[c['page'] for c in r['candidates']]}")
            if r['is_outline']:
                print(f"  [OK] Correctly identified as outline document")
            else:
                print(f"  [FAIL] Not identified - need to adjust logic")
    
    if not target_found:
        print("[ERROR] Target document not found in test set")
    
    # 计算误判率
    false_positives = [r for r in outline_docs 
                      if r['code_toc_source'] in ['bookmarks', 'regex'] and r['code_toc_items'] > 3]
    
    print("\n" + "="*100)
    print("Final Statistics")
    print("="*100)
    print(f"\nFalse positive rate: {len(false_positives)}/{len(results)} = {len(false_positives)/len(results)*100:.1f}%")
    print(f"Target document detected: {target_found}")
    print(f"Documents needing Branch D: {len(outline_docs)}")
    
    return results

# 运行测试
results = test_all_documents()
