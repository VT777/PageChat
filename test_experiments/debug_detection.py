"""
简化测试：直接分析目标文档的页面特征
找出为什么检测失败
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re

doc_dir = 'backend/data/documents'
target = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target = os.path.join(doc_dir, f)
        break

analysis = analyze_pdf_structure(target)
page_texts = analysis['page_texts']

print("="*80)
print("目标文档页面特征分析")
print("="*80)

# 分析所有页面的特征
features = []
for i, text in enumerate(page_texts):
    page_num = i + 1
    text_len = len(text.strip())
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # 检查是否有编号列表
    numbered_lines = 0
    for line in lines:
        if re.match(r'^[\d一二三四五六七八九十①②③④⑤⑥⑦⑧⑨⑩][\.、\.\)\】\]\s]', line):
            numbered_lines += 1
        elif re.match(r'^（[一二三四五六七八九十\d]+）', line):
            numbered_lines += 1
        elif re.match(r'^[\-\*•・]', line):
            numbered_lines += 1
    
    # 更宽松的匹配：中文数字+空格
    relaxed_numbered = 0
    for line in lines:
        if re.match(r'^[一二三四五六七八九十]\s+', line):
            relaxed_numbered += 1
    
    # 目录关键词
    has_toc_kw = bool(re.search(r'(?:目录|提纲|大纲|CONTENTS|Outline|Summary|汇报)', text[:300], re.I))
    
    # 内容指纹
    content_fp = re.sub(r'[\s\d]', '', text[:80])
    
    features.append({
        'page': page_num,
        'len': text_len,
        'line_count': len(lines),
        'numbered_lines': numbered_lines,
        'relaxed_numbered': relaxed_numbered,
        'has_toc_kw': has_toc_kw,
        'content_fp': content_fp
    })

# 打印短页面（<300字符）
print("\n短页面（<300字符）:")
short_pages = [f for f in features if f['len'] < 300]
for f in short_pages:
    print(f"  P{f['page']:2d}: len={f['len']:3d}, lines={f['line_count']:2d}, "
          f"numbered={f['numbered_lines']}, relaxed={f['relaxed_numbered']}, "
          f"toc_kw={f['has_toc_kw']}, fp_len={len(f['content_fp'])}")

# 检查策略1：关键词检测
toc_kw_pages = [f for f in features if f['has_toc_kw'] and f['len'] < 300]
print(f"\n策略1-关键词检测：{len(toc_kw_pages)} 个页面")
print(f"  需要 >=3: {'PASS' if len(toc_kw_pages) >= 3 else 'FAIL'}")

# 检查策略2：编号列表检测
numbered_pages = [f for f in features if f['numbered_lines'] >= 2 and f['len'] < 300]
print(f"\n策略2-编号列表检测（严格）：{len(numbered_pages)} 个页面")
print(f"  需要 >=3: {'PASS' if len(numbered_pages) >= 3 else 'FAIL'}")

# 检查策略2b：放宽的编号检测
relaxed_pages = [f for f in features if f['relaxed_numbered'] >= 2 and f['len'] < 300]
print(f"\n策略2b-放宽编号检测：{len(relaxed_pages)} 个页面")
print(f"  需要 >=3: {'PASS' if len(relaxed_pages) >= 3 else 'FAIL'}")
if relaxed_pages:
    print("  页面列表:", [f['page'] for f in relaxed_pages])

# 检查策略3：相似度检测
print(f"\n策略3-相似度检测:")
fp_groups = {}
for f in features:
    if f['len'] < 300 and len(f['content_fp']) > 10:
        if f['content_fp'] in fp_groups:
            fp_groups[f['content_fp']].append(f['page'])
        else:
            fp_groups[f['content_fp']] = [f['page']]

for fp, pages in fp_groups.items():
    if len(pages) >= 2:
        pages_sorted = sorted(pages)
        max_gap = max(pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1))
        print(f"  FP重复: {len(pages)} 次, 页面: {pages}, 最大间隔: {max_gap}")
        if max_gap >= 5:
            print(f"    -> 分散!")

# 最终推荐策略
print("\n" + "="*80)
print("推荐策略")
print("="*80)

# 组合策略：放宽编号 + 分散性检查
if len(relaxed_pages) >= 3:
    pages = [f['page'] for f in relaxed_pages]
    pages_sorted = sorted(pages)
    if len(pages_sorted) >= 2:
        max_gap = max(pages_sorted[i+1] - pages_sorted[i] for i in range(len(pages_sorted)-1))
        is_dispersed = max_gap >= 5
        
        print(f"放宽编号检测: {len(relaxed_pages)} 个页面")
        print(f"分散性: max_gap={max_gap}, {'分散' if is_dispersed else '集中'}")
        
        if is_dispersed:
            print("\n✓ 目标文档应该被识别为特殊文档！")
            print("  使用策略：放宽编号检测 + 分散性检查")
