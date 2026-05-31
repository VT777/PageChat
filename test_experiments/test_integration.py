"""
验证章节分隔符检测集成效果
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = 'backend/data/documents'

# 测试目标文档
print("="*80)
print("测试1: 目标文档（第五范式报告）")
print("="*80)

# 找到目标文档
import glob
target_files = glob.glob(os.path.join(doc_dir, 'f9a2f07e*.pdf'))
if target_files:
    target_path = target_files[0]
    analysis = analyze_pdf_structure(target_path)
    
    print(f"文件: {os.path.basename(target_path)}")
    print(f"总页数: {analysis['page_count']}")
    print(f"文本覆盖率: {analysis['text_coverage']:.2%}")
    print(f"代码TOC来源: {analysis['code_toc']['source']}")
    print(f"章节分隔页: {analysis.get('chapter_dividers', [])}")
    
    if analysis.get('chapter_dividers'):
        print("\n[PASS] 章节分隔符检测成功！")
        dividers = analysis['chapter_dividers']
        print(f"   检测到 {len(dividers)} 个分隔页: {dividers}")
    else:
        print("\n[FAIL] 未检测到章节分隔符")
else:
    print("未找到目标文档")

print("\n" + "="*80)
print("测试2: 快速检查所有文档的 chapter_dividers 字段")
print("="*80)

pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
pdf_files.sort()

special_count = 0
for pdf_file in pdf_files:
    pdf_path = os.path.join(doc_dir, pdf_file)
    try:
        analysis = analyze_pdf_structure(pdf_path)
        dividers = analysis.get('chapter_dividers', [])
        if dividers:
            special_count += 1
            print(f"  {pdf_file[:50]}...: {len(dividers)} dividers at {dividers}")
    except Exception as e:
        print(f"  错误 - {pdf_file}: {e}")

print(f"\n总计: {len(pdf_files)} 个文档, {special_count} 个检测到章节分隔符")

# 测试3: 验证 balanced_toc 路径（模拟）
print("\n" + "="*80)
print("测试3: 验证分析结果结构")
print("="*80)

if target_files:
    analysis = analyze_pdf_structure(target_files[0])
    required_keys = ['file_path', 'page_count', 'pages', 'text_coverage', 
                     'text_pages', 'image_only_pages', 'garbled_pages',
                     'is_image_only_pdf', 'is_garbled_pdf', 'code_toc',
                     'page_list', 'page_texts', 'text_quality', 'chapter_dividers']
    
    print("检查必需字段:")
    for key in required_keys:
        present = key in analysis
        print(f"  {key}: {'[OK]' if present else '[MISSING]'}")
    
    all_present = all(k in analysis for k in required_keys)
    print(f"\n{'[PASS] 所有字段都存在' if all_present else '[FAIL] 缺少字段'}")

print("\n测试完成!")
