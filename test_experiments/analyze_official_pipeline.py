"""
深度分析：PageIndex官方级联流程在我们文档上的表现
将结果写入文件避免编码问题
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = 'backend/data/documents'
pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
pdf_files.sort()

output_lines = []

output_lines.append("="*80)
output_lines.append("PageIndex Official Pipeline Analysis")
output_lines.append("="*80)
output_lines.append(f"Total documents: {len(pdf_files)}")
output_lines.append("")

# Statistics
results = {
    'has_toc': 0,
    'text_quality_ok': 0,
    'code_toc_success': 0,
}

doc_details = []

for pdf_file in pdf_files[:23]:
    pdf_path = os.path.join(doc_dir, pdf_file)
    try:
        analysis = analyze_pdf_structure(pdf_path)
        
        code_toc = analysis.get('code_toc', {})
        has_code_toc = code_toc.get('items') is not None
        toc_source = code_toc.get('source', 'none')
        
        text_quality = analysis.get('text_quality', {})
        is_low_quality = text_quality.get('is_low_quality', False)
        meaningful_ratio = text_quality.get('meaningful_ratio', 0)
        
        page_count = analysis['page_count']
        text_coverage = analysis['text_coverage']
        
        has_toc = has_code_toc and toc_source in ['bookmarks', 'links']
        
        doc_info = {
            'file': pdf_file,
            'pages': page_count,
            'text_coverage': text_coverage,
            'has_code_toc': has_code_toc,
            'toc_source': toc_source,
            'is_low_quality': is_low_quality,
            'meaningful_ratio': meaningful_ratio,
            'has_toc': has_toc,
        }
        doc_details.append(doc_info)
        
        if has_toc:
            results['has_toc'] += 1
        if not is_low_quality:
            results['text_quality_ok'] += 1
        if has_code_toc:
            results['code_toc_success'] += 1
            
    except Exception as e:
        output_lines.append(f"ERROR - {pdf_file}: {e}")

# Print statistics
output_lines.append("="*80)
output_lines.append("Overall Statistics")
output_lines.append("="*80)
output_lines.append(f"Has TOC (bookmarks/links): {results['has_toc']}/{len(doc_details)}")
output_lines.append(f"Good text quality:         {results['text_quality_ok']}/{len(doc_details)}")
output_lines.append(f"Code TOC extraction OK:    {results['code_toc_success']}/{len(doc_details)}")
output_lines.append("")

# Predict which path each doc would take
output_lines.append("="*80)
output_lines.append("Predicted Official Pipeline Path")
output_lines.append("="*80)

for doc in doc_details:
    file_short = doc['file'][:50]
    
    if doc['has_toc']:
        path = "Mode 1: TOC + Page Numbers"
    elif doc['has_code_toc'] and doc['toc_source'] == 'regex':
        path = "Mode 2: TOC (no page numbers)"
    else:
        if doc['is_low_quality']:
            path = "Mode 3: No TOC (LOW QUALITY)"
        else:
            path = "Mode 3: No TOC (text ok)"
    
    output_lines.append(f"{file_short:50s} | {doc['pages']:3d}p | {path}")

output_lines.append("")

# Problem documents
output_lines.append("="*80)
output_lines.append("Problem Documents (Need Multimodal Enhancement)")
output_lines.append("="*80)

problem_docs = [d for d in doc_details if d['is_low_quality'] or not d['has_code_toc']]
for doc in problem_docs:
    file_short = doc['file'][:50]
    issues = []
    if doc['is_low_quality']:
        issues.append(f"low_quality({doc['meaningful_ratio']:.0%})")
    if not doc['has_code_toc']:
        issues.append("no_toc")
    
    output_lines.append(f"{file_short:50s} | Issues: {', '.join(issues)}")

output_lines.append(f"\nTotal problem docs: {len(problem_docs)}/{len(doc_details)}")
output_lines.append("")

# Target document analysis
output_lines.append("="*80)
output_lines.append("Target Document Analysis (5th Paradigm Report)")
output_lines.append("="*80)
target = [d for d in doc_details if 'f9a2f07e' in d['file']]
if target:
    t = target[0]
    output_lines.append(f"File: {t['file']}")
    output_lines.append(f"Pages: {t['pages']}")
    output_lines.append(f"Text coverage: {t['text_coverage']:.2%}")
    output_lines.append(f"Code TOC: {t['has_code_toc']} (source: {t['toc_source']})")
    output_lines.append(f"Text quality: {'LOW' if t['is_low_quality'] else 'OK'} (meaningful: {t['meaningful_ratio']:.0%})")
    output_lines.append("")
    output_lines.append("Official pipeline prediction:")
    if t['has_toc']:
        output_lines.append("  -> Mode 1: TOC + Page Numbers")
        output_lines.append("  -> Issue: TOC page numbers may be inaccurate")
    else:
        output_lines.append("  -> Mode 3: No TOC")
        if t['is_low_quality']:
            output_lines.append("  -> CRITICAL: Low text quality, LLM cannot generate structure")
        else:
            output_lines.append("  -> Text quality OK, but LLM must generate structure from 68 pages")
            output_lines.append("  -> Challenge: No clear chapter markers")

output_lines.append("")
output_lines.append("="*80)
output_lines.append("Analysis Complete")
output_lines.append("="*80)

# Write to file
output_text = "\n".join(output_lines)
with open('test_experiments/official_pipeline_analysis.txt', 'w', encoding='utf-8') as f:
    f.write(output_text)

print("Analysis complete. Results written to: test_experiments/official_pipeline_analysis.txt")
print(f"Total documents analyzed: {len(doc_details)}")
print(f"Problem documents: {len(problem_docs)}")
