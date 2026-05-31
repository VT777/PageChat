"""
分析误报文档特征
"""
import sys, os, glob
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re

doc_dir = 'backend/data/documents'

# 通过glob找到误报文档
pattern = os.path.join(doc_dir, 'e7b28a07*.pdf')
files = glob.glob(pattern)

if not files:
    print("未找到文件")
    exit(1)

pdf_path = files[0]
print(f"找到文件: {os.path.basename(pdf_path)}")

analysis = analyze_pdf_structure(pdf_path)
page_texts = analysis['page_texts']

print(f"总页数: {len(page_texts)}")
print()

# 显示被检测到的页面内容
print("被检测到的分隔页内容:")
for page_num in [3, 9, 16, 18]:
    text = page_texts[page_num-1].strip()
    print(f"\n--- 第{page_num}页 ---")
    print(f"长度: {len(text)}")
    print(f"内容:")
    for i, line in enumerate(text.split('\n')[:15]):
        if line.strip():
            print(f"  {i}: {line.strip()[:100]}")

# 检查这些页面的指纹
print("\n" + "="*80)
print("指纹分析:")

def extract_fp(text):
    return re.sub(r'[^\u4e00-\u9fa5a-zA-Z]', '', text[:100])

fps = {}
for page_num in [3, 9, 16, 18]:
    text = page_texts[page_num-1].strip()
    fp = extract_fp(text)
    fps[page_num] = fp
    print(f"第{page_num}页指纹长度: {len(fp)}")

# 检查指纹是否完全相同
unique_fps = set(fps.values())
print(f"\n唯一指纹数: {len(unique_fps)}")
if len(unique_fps) == 1:
    print("所有页面指纹相同!")
    print(f"指纹内容: {list(unique_fps)[0][:50]}")
else:
    print("指纹不同:")
    for page, fp in fps.items():
        print(f"  第{page}页: {fp[:50]}")

# 检查页面间的间隔
pages = [3, 9, 16, 18]
gaps = [pages[i+1] - pages[i] for i in range(len(pages)-1)]
print(f"\n页面间隔: {gaps}")
print(f"最大间隔: {max(gaps)}")

# 分析整篇文档的短页面
print("\n" + "="*80)
print("所有短页面（<300字符）分析:")
for i, text in enumerate(page_texts):
    text_stripped = text.strip()
    text_len = len(text_stripped)
    if 0 < text_len < 300:
        fp = extract_fp(text_stripped)
        print(f"第{i+1:2d}页: 长度={text_len:3d}, 指纹长度={len(fp):2d}")
