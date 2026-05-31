"""
鲁棒性测试：验证"汇报提纲"检测逻辑是否会误判其他文档类型
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re

doc_dir = 'backend/data/documents'

# 定义检测逻辑（模拟Branch D的入口条件）
def detect_outline_pages(analysis):
    """检测是否为"汇报提纲"类文档"""
    page_texts = analysis.get('page_texts', [])
    page_count = analysis['page_count']
    
    if not page_texts or page_count < 10:
        return False, []
    
    # 条件1：查找包含提纲关键词的短文本页
    outline_candidates = []
    outline_keywords = ['汇报提纲', '目录', '大纲', 'CONTENTS', 'Outline', 'Summary']
    
    for i, text in enumerate(page_texts):
        page_num = i + 1
        text_len = len(text.strip())
        
        # 短文本页（<300字符）且包含关键词
        if text_len < 300 and text_len > 10:
            has_keyword = any(kw in text[:500] for kw in outline_keywords)
            if has_keyword:
                outline_candidates.append({
                    'page': page_num,
                    'len': text_len,
                    'keyword': [kw for kw in outline_keywords if kw in text[:500]][0]
                })
    
    if len(outline_candidates) < 2:
        return False, outline_candidates
    
    # 条件2：检查是否有重复内容的页面（分散在文档不同位置）
    fingerprints = {}
    for i, text in enumerate(page_texts):
        page_num = i + 1
        text_len = len(text.strip())
        if text_len < 300 and text_len > 10:
            fp = re.sub(r'\s+', '', text[:50])
            if fp in fingerprints:
                fingerprints[fp].append(page_num)
            else:
                fingerprints[fp] = [page_num]
    
    # 如果有相同内容的页面分散在不同位置
    duplicate_pages = []
    for fp, pages in fingerprints.items():
        if len(pages) >= 2:
            if max(pages) - min(pages) > 5:
                duplicate_pages.extend(pages)
    
    if duplicate_pages:
        return True, outline_candidates
    
    # 条件3：即使没有重复内容，如果有多个目录页也可能触发
    if len(outline_candidates) >= 3:
        return True, outline_candidates
    
    return False, outline_candidates

def analyze_document(file_path):
    """分析单个文档"""
    try:
        analysis = analyze_pdf_structure(file_path)
        is_outline, candidates = detect_outline_pages(analysis)
        
        return {
            'file': os.path.basename(file_path),
            'pages': analysis['page_count'],
            'text_coverage': analysis['text_coverage'],
            'is_outline': is_outline,
            'candidates': candidates,
            'code_toc_source': analysis['code_toc']['source'],
            'code_toc_items': len(analysis['code_toc']['items']) if analysis['code_toc']['items'] else 0
        }
    except Exception as e:
        return {
            'file': os.path.basename(file_path),
            'error': str(e)
        }

# 测试所有PDF文档
print("="*100)
print("Robustness Test: Branch D Detection Logic")
print("="*100)

results = []
pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]

print(f"\nTesting {len(pdf_files)} PDF files...\n")

for f in sorted(pdf_files):
    file_path = os.path.join(doc_dir, f)
    result = analyze_document(file_path)
    results.append(result)

# 分类统计
outline_docs = [r for r in results if r.get('is_outline', False)]
normal_docs = [r for r in results if not r.get('is_outline', False) and 'error' not in r]
error_docs = [r for r in results if 'error' in r]

print("="*100)
print("Test Results Summary")
print("="*100)
print(f"\nTotal documents: {len(results)}")
print(f"  - Classified as 'outline': {len(outline_docs)}")
print(f"  - Normal documents: {len(normal_docs)}")
print(f"  - Processing errors: {len(error_docs)}")

print("\n" + "="*100)
print("Documents classified as 'outline' (need manual review)")
print("="*100)

if outline_docs:
    for r in outline_docs:
        print(f"\nFile: {r['file'].encode('ascii', 'replace').decode()}")
        print(f"  Pages: {r['pages']}, Text coverage: {int(r['text_coverage']*100)}%")
        print(f"  Code TOC: {r['code_toc_source']} ({r['code_toc_items']} items)")
        print(f"  Detected candidate pages:")
        for cand in r['candidates'][:5]:
            print(f"    P{cand['page']}: {cand['keyword']} (len={cand['len']})")
else:
    print("\nNone")

print("\n" + "="*100)
print("False Positive Risk Analysis")
print("="*100)

false_positives = []
for r in outline_docs:
    # 如果文档有传统书签或目录，却被识别为outline，可能是误判
    if r['code_toc_source'] in ['bookmarks', 'regex'] and r['code_toc_items'] > 5:
        false_positives.append(r)

print(f"\nPotential false positives (has standard TOC but classified as outline): {len(false_positives)}")

if false_positives:
    for r in false_positives:
        print(f"  - {r['file'].encode('ascii', 'replace').decode()}")
        print(f"    Reason: Has {r['code_toc_source']} TOC ({r['code_toc_items']} items), but classified as outline")
        print(f"    Risk: HIGH - would incorrectly enter Branch D")

print("\n" + "="*100)
print("Conclusion")
print("="*100)

print(f"""
1. Detection Logic Evaluation
   - Documents classified as outline: {len(outline_docs)}
   - Potential false positives: {len(false_positives)}
   - False positive rate: {len(false_positives)/len(results)*100:.1f}%

2. Recommended Improvements
   - Add constraint: exclude documents with bookmarks TOC
   - Add constraint: require >=3 duplicate pages for outline detection
   - Add constraint: check if duplicate pages have identical content

3. Safety Strategy
   - Branch D as fallback when Branch A/B/C fail
   - Add manual confirmation mechanism
""")
