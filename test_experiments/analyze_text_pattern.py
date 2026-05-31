"""
分析目标文档的文本特征，找出为什么没被识别
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

print("="*80)
print("目标文档文本特征分析")
print("="*80)

# 检查关键页面的文本结构和列表项
key_pages = [2, 3, 13, 35, 49, 61]

for p in key_pages:
    if p <= len(analysis['page_texts']):
        text = analysis['page_texts'][p-1]
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        
        print(f"\n--- Page {p} (len={len(text)}) ---")
        print("Lines:")
        for i, line in enumerate(lines):
            print(f"  {i}: '{line}'")
        
        # 检查列表项匹配
        list_items = 0
        for line in lines:
            if re.match(r'^[\d一二三四五六七八九十①②③④⑤⑥⑦⑧⑨⑩][\.、\.\)\】\]]', line):
                list_items += 1
                print(f"  [LIST] '{line}'")
            elif re.match(r'^[\-\*•・]', line):
                list_items += 1
                print(f"  [LIST] '{line}'")
            elif re.match(r'^（[一二三四五六七八九十\d]+）', line):
                list_items += 1
                print(f"  [LIST] '{line}'")
        
        print(f"\n  Total list items detected: {list_items}")
        print(f"  Text length: {len(text)}")
        print(f"  Would be detected: {'YES' if (20 <= len(text) <= 300 and list_items >= 2) else 'NO'}")

print("\n" + "="*80)
print("问题分析")
print("="*80)
print("""
原因：汇报提纲页面的文本格式不符合列表项的正则匹配
例如：
  "一 百花齐放大模型时代"  ← 不匹配 (没有标点符号)
  "二 大模型重塑科学研究范式"  ← 不匹配 (没有标点符号)

这些行没有顿号"、"或点号"."，所以正则表达式匹配失败。
""")
