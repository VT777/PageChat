"""
验证 balanced_toc.py 能正确读取 chapter_dividers
"""
import sys, os
sys.path.insert(0, 'backend')

import asyncio
from pageindex.pdf_analyzer import analyze_pdf_structure

# 找到目标文档
doc_dir = 'backend/data/documents'
import glob
target_files = glob.glob(os.path.join(doc_dir, 'f9a2f07e*.pdf'))

if not target_files:
    print("未找到目标文档")
    exit(1)

target_path = target_files[0]
analysis = analyze_pdf_structure(target_path)

print("="*80)
print("验证 balanced_toc.py 读取 chapter_dividers")
print("="*80)
print(f"文件: {os.path.basename(target_path)}")
print(f"chapter_dividers in analysis: {analysis.get('chapter_dividers', [])}")

# 模拟 build_balanced_toc_visual 中的逻辑
# 只测试 dividers 的合并逻辑，不涉及 VLM 调用
toc_pages = []
dividers = []
first_content = None

# P0-6: 合并代码检测的章节分隔页
code_dividers = analysis.get("chapter_dividers", [])
print(f"code_dividers: {code_dividers}")

if code_dividers and not dividers:
    print("[模拟] VLM dividers为空，使用代码检测的 dividers")
    dividers = code_dividers
    if not first_content and dividers:
        first_content = dividers[0]
elif code_dividers and dividers:
    merged = sorted(set(dividers + code_dividers))
    print(f"[模拟] 合并 dividers: {dividers} + {code_dividers} = {merged}")
    dividers = merged

print(f"\n最终 dividers: {dividers}")
print(f"first_content: {first_content}")

# 验证分支逻辑
page_count = analysis['page_count']
divider_density = len(dividers) / page_count if page_count > 0 else 0
print(f"divider_density: {divider_density:.2%}")

if toc_pages:
    print("\n将进入分支 A: 有目录页")
elif dividers:
    if divider_density > 0.4:
        print("\n将进入分支 B-密集: dividers 当 TOC")
    else:
        print("\n将进入分支 B-正常: 按 divider 分组")
else:
    print("\n将进入分支 C: 全文分析")

# 验证 dividers 是否正确
expected = [2, 3, 13, 35, 49, 61]
if dividers == expected:
    print(f"\n[PASS] dividers 正确: {dividers}")
else:
    print(f"\n[FAIL] dividers 不匹配: 期望 {expected}, 实际 {dividers}")

print("\n测试完成!")
