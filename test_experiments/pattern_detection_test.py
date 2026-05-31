"""
通用模式检测：识别"多个相似短页面作为章节分隔"的文档
不依赖"汇报提纲"关键词，而是检测页面特征模式
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re
from collections import defaultdict

doc_dir = 'backend/data/documents'

def detect_similar_short_pages(analysis):
    """
    通用检测：查找多个相似的短页面（作为章节分隔）
    
    特征：
    1. 文本长度短（<300字符）
    2. 包含列表结构（多个行开头有编号/项目符号）
    3. 多个页面满足以上条件
    4. 这些页面分散在文档不同位置（不是连续的）
    """
    page_texts = analysis.get('page_texts', [])
    page_count = analysis['page_count']
    
    if not page_texts or page_count < 10:
        return False, []
    
    # 步骤1：找出所有短页面（<300字符）且有列表结构的页面
    short_list_pages = []
    
    for i, text in enumerate(page_texts):
        page_num = i + 1
        text_len = len(text.strip())
        
        if 20 <= text_len <= 300:
            # 检查是否有列表结构
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            list_items = 0
            
            for line in lines:
                # 匹配列表项：编号、项目符号、中文数字等
                if re.match(r'^[\d一二三四五六七八九十①②③④⑤⑥⑦⑧⑨⑩][\.、\.\)\】\]]', line):
                    list_items += 1
                elif re.match(r'^[\-\*•・]', line):
                    list_items += 1
                elif re.match(r'^（[一二三四五六七八九十\d]+）', line):
                    list_items += 1
            
            # 如果有至少2个列表项，认为是列表页
            if list_items >= 2:
                short_list_pages.append({
                    'page': page_num,
                    'text': text[:100],
                    'len': text_len,
                    'list_items': list_items,
                    'line_count': len(lines)
                })
    
    if len(short_list_pages) < 2:
        return False, short_list_pages
    
    # 步骤2：检查这些页面是否分散（不是连续的目录页）
    pages = [p['page'] for p in short_list_pages]
    pages_sorted = sorted(pages)
    
    # 计算页面间隔
    gaps = [pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1)]
    max_gap = max(gaps) if gaps else 0
    
    # 如果有间隔>5页，说明分散在文档不同位置
    is_dispersed = max_gap >= 5
    
    # 步骤3：检查内容模式相似度
    # 提取每个页面的"结构指纹"（列表项的模式，而非具体内容）
    structure_fps = []
    for p in short_list_pages:
        text = page_texts[p['page']-1]
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        # 记录行首模式
        patterns = []
        for line in lines[:10]:  # 只看前10行
            if re.match(r'^第[一二三四五六七八九十]', line):
                patterns.append('CH')
            elif re.match(r'^[一二三四五六七八九十][、\.]', line):
                patterns.append('CN_NUM')
            elif re.match(r'^\d+[\.、]', line):
                patterns.append('NUM')
            elif re.match(r'^[\-\*•]', line):
                patterns.append('BULLET')
            elif len(line) < 20:
                patterns.append('SHORT')
            else:
                patterns.append('TEXT')
        
        structure_fps.append(tuple(patterns))
    
    # 检查是否有相同的结构模式
    fp_counts = defaultdict(int)
    for fp in structure_fps:
        fp_counts[fp] += 1
    
    # 如果最常见的模式出现>=2次，说明有重复的结构
    most_common = max(fp_counts.values()) if fp_counts else 0
    has_repeated_structure = most_common >= 2
    
    # 最终判断
    should_use_special_handling = (
        len(short_list_pages) >= 3 and  # 至少3个页面
        is_dispersed and  # 分散在不同位置
        has_repeated_structure  # 有重复的结构模式
    )
    
    return should_use_special_handling, short_list_pages

def test_all_documents():
    """测试所有文档"""
    print("="*100)
    print("通用模式检测：相似短页面作为章节分隔")
    print("="*100)
    print("\n不依赖'汇报提纲'关键词")
    print("检测特征：短文本 + 列表结构 + 分散位置 + 重复模式")
    
    results = []
    pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
    
    print(f"\nTesting {len(pdf_files)} PDF files...\n")
    
    for f in sorted(pdf_files):
        file_path = os.path.join(doc_dir, f)
        try:
            analysis = analyze_pdf_structure(file_path)
            is_special, pages = detect_similar_short_pages(analysis)
            
            results.append({
                'file': os.path.basename(file_path),
                'pages': analysis['page_count'],
                'is_special': is_special,
                'special_pages': pages,
                'toc_source': analysis['code_toc']['source'],
                'toc_items': len(analysis['code_toc']['items']) if analysis['code_toc']['items'] else 0
            })
        except Exception as e:
            results.append({'file': os.path.basename(file_path), 'error': str(e)})
    
    # 统计
    special_docs = [r for r in results if r.get('is_special', False)]
    normal_docs = [r for r in results if not r.get('is_special', False) and 'error' not in r]
    
    print("="*100)
    print("Results")
    print("="*100)
    print(f"\nTotal: {len(results)}")
    print(f"  Special handling needed: {len(special_docs)}")
    print(f"  Normal: {len(normal_docs)}")
    
    # 详细信息
    print("\n" + "="*100)
    print("All Documents")
    print("="*100)
    
    for r in results:
        if 'error' in r:
            print(f"\n{r['file'].encode('ascii', 'replace').decode()}: ERROR")
        else:
            status = "SPECIAL" if r['is_special'] else "normal"
            page_list = [p['page'] for p in r['special_pages']]
            print(f"\n{r['file'][:60].encode('ascii', 'replace').decode()}: {status}")
            if r['is_special']:
                print(f"  Special pages: {page_list}")
                print(f"  TOC: {r['toc_source']} ({r['toc_items']} items)")
    
    # 目标文档检查
    print("\n" + "="*100)
    print("Target Document Check")
    print("="*100)
    for r in results:
        if 'f9a2f07e' in r['file']:
            print(f"\nFile: {r['file']}")
            print(f"  Is special: {r['is_special']}")
            if r['special_pages']:
                print(f"  Detected pages:")
                for p in r['special_pages']:
                    print(f"    P{p['page']}: {p['list_items']} list items, len={p['len']}")
            if r['is_special']:
                print(f"  [OK] Correctly identified as special document!")
            else:
                print(f"  [FAIL] Not identified")
    
    # 误判检查
    print("\n" + "="*100)
    print("False Positive Analysis")
    print("="*100)
    
    # 检查是否有正常文档被误判
    false_positives = []
    for r in special_docs:
        # 如果有有效的bookmarks TOC，却被识别为special，可能是误判
        if r['toc_source'] == 'bookmarks' and r['toc_items'] > 5:
            false_positives.append(r)
    
    print(f"\nPotential false positives: {len(false_positives)}")
    for r in false_positives:
        print(f"  - {r['file']}")
        print(f"    Has bookmarks TOC ({r['toc_items']} items) but classified as special")
    
    if not false_positives:
        print("\nNo false positives detected!")
    
    return results

results = test_all_documents()
