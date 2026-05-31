"""
调试：检查目标文档的特征提取结果
"""
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

print("文档基本信息:")
print(f"  页数: {analysis.get('page_count', 'N/A')}")
print(f"  TOC source: {analysis.get('code_toc', {}).get('source', 'N/A')}")
print(f"  TOC items: {len(analysis.get('code_toc', {}).get('items', []))}")

print("\n前10页文本长度:")
for i in range(min(10, len(analysis['page_texts']))):
    text = analysis['page_texts'][i]
    print(f"  P{i+1}: {len(text)} chars")
    if len(text) < 300:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        print(f"    Lines: {len(lines)}")
        for j, line in enumerate(lines[:5]):
            print(f"      {j}: {line[:60]}")
