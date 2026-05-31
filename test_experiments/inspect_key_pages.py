import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = 'backend/data/documents'
target = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target = os.path.join(doc_dir, f)
        break

analysis = analyze_pdf_structure(target)

# 检查用户提到的关键页面
key_pages = [2, 3, 13, 35, 49, 61]

print("="*80)
print("关键页面内容分析")
print("="*80)

for p in key_pages:
    if p <= len(analysis['page_texts']):
        text = analysis['page_texts'][p-1]
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        print(f"\n--- Page {p} (len={len(text)}) ---")
        for i, line in enumerate(lines[:15]):
            print(f"  {i+1}: {line[:80]}")
        if len(lines) > 15:
            print(f"  ... ({len(lines)-15} more lines)")
        
        # 判断特征
        has_toc_keyword = any(kw in text[:300] for kw in ['汇报提纲', '目录', '提纲', '大纲'])
        has_chapter_number = bool(__import__('re').search(r'^[一二三四五六七八九十]、|^第[一二三四五六七八九十]', text[:300]))
        is_short = len(text) < 200
        
        print(f"  [特征] toc_keyword={has_toc_keyword}, chapter_num={has_chapter_number}, short={is_short}")

print("\n" + "="*80)
print("相邻页面对比")
print("="*80)

# 查看每个关键页面前后的页面
for p in key_pages:
    print(f"\n--- 上下文: P{p-1} - P{p} - P{p+1} ---")
    for offset in [-1, 0, 1]:
        page = p + offset
        if 1 <= page <= len(analysis['page_texts']):
            text = analysis['page_texts'][page-1]
            first_line = text.split('\n')[0].strip()[:60] if text else "(empty)"
            print(f"  P{page:2d} (len={len(text):4d}): {first_line}")
