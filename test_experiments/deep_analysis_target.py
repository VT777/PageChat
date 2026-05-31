"""
深入分析：第五范式报告的正则TOC提取质量
以及官方Mode 2/Mode 3的处理方式
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import glob

doc_dir = 'backend/data/documents'
target_files = glob.glob(os.path.join(doc_dir, 'f9a2f07e*.pdf'))

if not target_files:
    print("Target file not found")
    exit(1)

analysis = analyze_pdf_structure(target_files[0])

output_lines = []
output_lines.append("="*80)
output_lines.append("Target Document Deep Analysis")
output_lines.append("="*80)
output_lines.append(f"File: {os.path.basename(target_files[0])}")
output_lines.append(f"Pages: {analysis['page_count']}")
output_lines.append("")

# 1. 代码提取的TOC
output_lines.append("-"*80)
output_lines.append("1. Code-Extracted TOC (Regex)")
output_lines.append("-"*80)

code_toc = analysis.get('code_toc', {})
toc_items = code_toc.get('items', [])
toc_source = code_toc.get('source', 'none')

output_lines.append(f"Source: {toc_source}")
output_lines.append(f"Item count: {len(toc_items) if toc_items else 0}")

if toc_items:
    for i, item in enumerate(toc_items[:20]):  # 只显示前20个
        title = item.get('title', '')
        page = item.get('physical_index', 'N/A')
        structure = item.get('_num', '')
        output_lines.append(f"  {i+1}. [{structure}] {title} (p.{page})")
else:
    output_lines.append("  No TOC items extracted")

output_lines.append("")

# 2. 前20页文本分析（官方会扫描这些页面找TOC）
output_lines.append("-"*80)
output_lines.append("2. First 20 Pages Text Analysis (Official TOC Detection Range)")
output_lines.append("-"*80)

page_texts = analysis['page_texts']
for i in range(min(20, len(page_texts))):
    text = page_texts[i].strip()
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    output_lines.append(f"\nPage {i+1}: {len(text)} chars, {len(lines)} lines")
    
    # 显示前10行
    for j, line in enumerate(lines[:10]):
        output_lines.append(f"  {j+1}: {line[:80]}")
    if len(lines) > 10:
        output_lines.append(f"  ... ({len(lines)-10} more lines)")

output_lines.append("")

# 3. 文本质量详细分析
output_lines.append("-"*80)
output_lines.append("3. Text Quality Analysis")
output_lines.append("-"*80)

text_quality = analysis.get('text_quality', {})
output_lines.append(f"Meaningful ratio: {text_quality.get('meaningful_ratio', 0):.2%}")
output_lines.append(f"Duplicate ratio: {text_quality.get('duplicate_ratio', 0):.2%}")
output_lines.append(f"Fragment ratio: {text_quality.get('fragment_ratio', 0):.2%}")
output_lines.append(f"Is low quality: {text_quality.get('is_low_quality', False)}")

# 分析重复页面
output_lines.append("\nDuplicate page analysis:")
from collections import defaultdict
import re

fingerprints = []
for text in page_texts:
    fp = re.sub(r'[\d\s]', '', text[:100])
    fingerprints.append(fp)

duplicate_groups = defaultdict(list)
for i, fp in enumerate(fingerprints):
    if len(fp) >= 10:
        duplicate_groups[fp].append(i+1)

for fp, pages in duplicate_groups.items():
    if len(pages) > 1:
        output_lines.append(f"  Pages {pages} have identical fingerprint (len={len(fp)})")
        output_lines.append(f"    Content: {fp[:60]}")

output_lines.append("")

# 4. 模拟官方Mode 2处理：TOC无页码时的定位
output_lines.append("-"*80)
output_lines.append("4. Official Mode 2 Simulation: TOC without Page Numbers")
output_lines.append("-"*80)

if toc_items:
    output_lines.append("If official uses Mode 2 (TOC exists but no page numbers):")
    output_lines.append("  Step 1: Extract TOC structure from text")
    output_lines.append(f"  Step 2: Found {len(toc_items)} items")
    output_lines.append("  Step 3: Search document text to find physical locations")
    output_lines.append("  Step 4: Use neighbor-bounded correction for errors")
    output_lines.append("")
    output_lines.append("Challenge for this document:")
    output_lines.append("  - TOC entries may not have clear page numbers")
    output_lines.append("  - Text-based search may fail if TOC is just 'hui bao ti gang'")
    output_lines.append("  - LLM needs to recognize chapter boundaries from content")
else:
    output_lines.append("If official uses Mode 3 (No TOC):")
    output_lines.append("  Step 1: Group pages into chunks (e.g., 20k tokens each)")
    output_lines.append("  Step 2: Ask LLM to generate structure from first chunk")
    output_lines.append("  Step 3: Continue with subsequent chunks")
    output_lines.append("")
    output_lines.append("Challenge for this document:")
    output_lines.append("  - 68 pages need to be processed in chunks")
    output_lines.append("  - LLM may miss 'hui bao ti gang' chapter dividers")
    output_lines.append("  - Without clear headings, structure generation is hard")

output_lines.append("")

# 5. 多模态增强点分析
output_lines.append("-"*80)
output_lines.append("5. Multimodal Enhancement Opportunities")
output_lines.append("-"*80)

output_lines.append("Where VLM/Vision can help:")
output_lines.append("")

if toc_items:
    output_lines.append("A. TOC Page Detection (Current: text scanning)")
    output_lines.append("   - VLM can visually identify TOC pages vs content pages")
    output_lines.append("   - Useful when text extraction confuses TOC with content")
    output_lines.append("   - Cost: 1 VLM call for thumbnail grid")
    output_lines.append("")
    
    output_lines.append("B. Page Number Verification (Current: text search)")
    output_lines.append("   - VLM can read page numbers from images")
    output_lines.append("   - More reliable than text extraction for complex layouts")
    output_lines.append("   - Cost: 1 VLM call per page")
    output_lines.append("")

output_lines.append("C. Structure Generation for No-TOC Documents (Current: LLM from text)")
output_lines.append("   - VLM can see page layout, headers, visual separators")
output_lines.append("   - Can identify chapter dividers like 'hui bao ti gang'")
output_lines.append("   - More accurate than text-only for layout-based documents")
output_lines.append("   - Cost: 1 VLM call per 12-page grid")
output_lines.append("")

output_lines.append("D. Quality Verification (Current: text-based sampling)")
output_lines.append("   - VLM can verify if a section title actually appears on a page")
output_lines.append("   - Visual verification is more reliable than text matching")
output_lines.append("   - Cost: 1 VLM call per verification sample")
output_lines.append("")

# 6. 成本效益分析
output_lines.append("-"*80)
output_lines.append("6. Cost-Benefit Analysis")
output_lines.append("-"*80)

output_lines.append("Document distribution:")
output_lines.append("  Mode 1 (TOC + pages):     9 docs - Official handles well, minimal VLM needed")
output_lines.append("  Mode 2 (TOC no pages):    7 docs - VLM can help with page number mapping")
output_lines.append("  Mode 3 (No TOC):          6 docs - VLM can help with structure generation")
output_lines.append("")

output_lines.append("Recommended VLM integration points (in order of impact):")
output_lines.append("  1. Structure generation for Mode 3 docs (highest impact)")
output_lines.append("  2. TOC verification for Mode 2 docs (medium impact)")
output_lines.append("  3. Quality verification for all modes (safety net)")
output_lines.append("  4. TOC page detection enhancement (low impact, Mode 1/2)")

output_lines.append("")
output_lines.append("="*80)
output_lines.append("Analysis Complete")
output_lines.append("="*80)

# Write to file
output_text = "\n".join(output_lines)
with open('test_experiments/target_document_deep_analysis.txt', 'w', encoding='utf-8') as f:
    f.write(output_text)

print("Deep analysis complete. Results written to: test_experiments/target_document_deep_analysis.txt")
