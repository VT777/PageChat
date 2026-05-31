"""
全面鲁棒性测试框架 v4
目标：找到最通用的"多个相似短页面作为章节分隔"检测逻辑
测试多种策略组合，评估准确率、召回率、误判率
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re
from collections import defaultdict, Counter

doc_dir = 'backend/data/documents'

def analyze_page_features(page_texts):
    """分析所有页面的特征"""
    features = []
    for i, text in enumerate(page_texts):
        page_num = i + 1
        text_len = len(text.strip())
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        # 特征1：文本长度
        is_short = 20 <= text_len <= 400
        
        # 特征2：行数
        line_count = len(lines)
        
        # 特征3：是否有编号列表（多种格式）
        numbered_lines = 0
        for line in lines:
            if re.match(r'^[\d一二三四五六七八九十①②③④⑤⑥⑦⑧⑨⑩][\.、\.\)\】\]\s]', line):
                numbered_lines += 1
            elif re.match(r'^（[一二三四五六七八九十\d]+）', line):
                numbered_lines += 1
            elif re.match(r'^[\-\*•・]', line):
                numbered_lines += 1
        
        # 特征4：是否包含章节关键词
        has_chapter_kw = bool(re.search(r'(?:第[一二三四五六七八九十\d]+章|第[一二三四五六七八九十\d]+节|Chapter\s+\d+|Section\s+\d+)', text[:300]))
        
        # 特征5：是否包含目录/提纲关键词
        has_toc_kw = bool(re.search(r'(?:目录|提纲|大纲|CONTENTS|Outline|Summary|汇报)', text[:300], re.I))
        
        # 特征6：平均行长度（短行比例）
        short_lines = sum(1 for l in lines if len(l) < 30)
        short_line_ratio = short_lines / len(lines) if lines else 0
        
        # 特征7：内容指纹（去除所有空格和数字后的前60字符）
        content_fp = re.sub(r'[\s\d]', '', text[:80])
        
        features.append({
            'page': page_num,
            'len': text_len,
            'line_count': line_count,
            'is_short': is_short,
            'numbered_lines': numbered_lines,
            'has_chapter_kw': has_chapter_kw,
            'has_toc_kw': has_toc_kw,
            'short_line_ratio': short_line_ratio,
            'content_fp': content_fp,
            'first_line': lines[0] if lines else ''
        })
    
    return features

def strategy_1_keyword_based(features):
    """策略1：基于关键词（汇报提纲/目录）"""
    candidates = [f for f in features if f['has_toc_kw'] and f['is_short']]
    return len(candidates) >= 3, candidates

def strategy_2_pattern_based(features):
    """策略2：基于编号列表模式"""
    candidates = [f for f in features if f['numbered_lines'] >= 2 and f['is_short']]
    return len(candidates) >= 3, candidates

def strategy_3_similarity_based(features):
    """策略3：基于内容相似度（指纹识别）"""
    # 找出重复的内容指纹
    fp_groups = defaultdict(list)
    for f in features:
        if f['is_short'] and len(f['content_fp']) > 10:
            fp_groups[f['content_fp']].append(f['page'])
    
    # 查找分散的重复组
    dispersed_groups = []
    for fp, pages in fp_groups.items():
        if len(pages) >= 2:
            pages_sorted = sorted(pages)
            max_gap = max(pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1))
            if max_gap >= 5:
                dispersed_groups.extend(pages)
    
    candidates = [f for f in features if f['page'] in dispersed_groups]
    return len(dispersed_groups) >= 3, candidates

def strategy_4_combined(features):
    """策略4：组合策略（关键词 OR 编号列表）+ 分散性检查"""
    # 条件1：有目录关键词或编号列表
    candidates = [f for f in features if 
                  (f['has_toc_kw'] or f['numbered_lines'] >= 2) and f['is_short']]
    
    if len(candidates) < 3:
        return False, candidates
    
    # 条件2：分散性检查
    pages = [f['page'] for f in candidates]
    pages_sorted = sorted(pages)
    if len(pages_sorted) >= 2:
        max_gap = max(pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1))
        if max_gap < 5:
            return False, candidates
    
    # 条件3：内容相似度检查（至少2个页面内容高度相似）
    fp_groups = defaultdict(int)
    for f in candidates:
        fp_groups[f['content_fp']] += 1
    
    has_similar = any(count >= 2 for count in fp_groups.values())
    
    return has_similar, candidates

def strategy_5_relaxed_pattern(features):
    """策略5：放宽的列表检测（中文数字+空格也匹配）"""
    relaxed_numbered = 0
    for f in features:
        text = [l.strip() for l in open(target_file, 'rb').read().decode('utf-8', errors='ignore').split('\n') if l.strip()][f['page']-1]
        # 这里需要重新获取文本...简化处理
        pass
    
    # 简化：使用已有的numbered_lines但放宽阈值
    candidates = [f for f in features if f['numbered_lines'] >= 1 and f['is_short']]
    
    # 额外检查：是否有多个页面具有相同的短行比例
    short_page_groups = defaultdict(list)
    for f in candidates:
        if f['short_line_ratio'] > 0.5:
            short_page_groups[round(f['short_line_ratio'], 1)].append(f['page'])
    
    dispersed = False
    for ratio, pages in short_page_groups.items():
        if len(pages) >= 2:
            pages_sorted = sorted(pages)
            if max(pages_sorted) - min(pages_sorted) > 5:
                dispersed = True
    
    return len(candidates) >= 3 and dispersed, candidates

def test_document(file_path, strategy_funcs):
    """测试单个文档的所有策略"""
    try:
        analysis = analyze_pdf_structure(file_path)
        page_texts = analysis.get('page_texts', [])
        features = analyze_page_features(page_texts)
        
        code_toc = analysis.get('code_toc', {})
        toc_items = code_toc.get('items', []) if code_toc else []
        
        results = {
            'file': os.path.basename(file_path),
            'pages': analysis.get('page_count', 0),
            'toc_source': code_toc.get('source') if code_toc else None,
            'toc_items': len(toc_items)
        }
        
        for name, func in strategy_funcs.items():
            is_special, candidates = func(features)
            results[name] = {
                'is_special': is_special,
                'candidates': [c['page'] for c in candidates]
            }
        
        return results
    except Exception as e:
        import traceback
        return {
            'file': os.path.basename(file_path), 
            'error': str(e),
            'traceback': traceback.format_exc()
        }

def main():
    """主测试函数"""
    print("="*100)
    print("全面鲁棒性测试：5种检测策略对比")
    print("="*100)
    
    strategies = {
        '关键词检测': strategy_1_keyword_based,
        '编号列表检测': strategy_2_pattern_based,
        '相似度检测': strategy_3_similarity_based,
        '组合策略': strategy_4_combined,
        '放宽模式检测': strategy_5_relaxed_pattern
    }
    
    pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
    print(f"\n测试 {len(pdf_files)} 个PDF文件，{len(strategies)} 种策略\n")
    
    all_results = []
    for f in sorted(pdf_files):
        file_path = os.path.join(doc_dir, f)
        result = test_document(file_path, strategies)
        all_results.append(result)
    
    # 汇总统计
    print("="*100)
    print("各策略检测结果统计")
    print("="*100)
    
    for strategy_name in strategies.keys():
        special_count = sum(1 for r in all_results if strategy_name in r and r[strategy_name]['is_special'])
        print(f"\n{strategy_name.encode('ascii', 'replace').decode()}:")
        print(f"  Detected: {special_count}/{len(all_results)}")
        
        # 列出被识别的文档
        if special_count > 0:
            print("  Documents:")
            for r in all_results:
                if strategy_name in r and r[strategy_name]['is_special']:
                    candidates = r[strategy_name]['candidates']
                    file_name = r['file'][:50].encode('ascii', 'replace').decode()
                    print(f"    - {file_name}: {candidates}")
    
    # 目标文档检查
    print("\n" + "="*100)
    print("目标文档检查 (f9a2f07e)")
    print("="*100)
    
    for r in all_results:
        if 'f9a2f07e' in r.get('file', ''):
            print(f"\n文件: {r.get('file', 'N/A')}")
            print(f"总页数: {r.get('pages', 'N/A')}")
            print(f"Code TOC: {r.get('toc_source', 'N/A')} ({r.get('toc_items', 0)} items)")
            print("\n各策略检测结果:")
            for strategy_name in strategies.keys():
                if strategy_name in r:
                    is_special = r[strategy_name]['is_special']
                    candidates = r[strategy_name]['candidates']
                    status = "[OK] 识别" if is_special else "[FAIL] 未识别"
                    print(f"  {strategy_name:15s}: {status} (候选页: {candidates})")
    
    # 误判分析
    print("\n" + "="*100)
    print("误判风险分析")
    print("="*100)
    
    for strategy_name in strategies.keys():
        false_positives = []
        for r in all_results:
            if strategy_name in r and r[strategy_name]['is_special']:
                # 如果文档有有效的bookmarks TOC，但被识别为特殊，可能是误判
                if r.get('toc_source') == 'bookmarks' and r.get('toc_items', 0) > 5:
                    false_positives.append(r['file'])
        
        if false_positives:
            print(f"\n{strategy_name} - 潜在误判 ({len(false_positives)}个):")
            for fp in false_positives:
                print(f"  - {fp}")
        else:
            print(f"\n{strategy_name} - 无潜在误判")
    
    print("\n" + "="*100)
    print("测试完成")
    print("="*100)

if __name__ == "__main__":
    main()
