"""
重新设计：在官方流程关键节点增强
不替换官方流程，而是在每个环节提供多模态增强检查点
"""
import sys, os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure
import re
import glob

doc_dir = 'backend/data/documents'
pdf_files = [f for f in os.listdir(doc_dir) if f.endswith('.pdf')]
pdf_files.sort()

output_lines = []
output_lines.append("="*80)
output_lines.append("Official Pipeline Enhancement Points Analysis")
output_lines.append("="*80)
output_lines.append("")

# Analyze each document for potential failure points in official pipeline
analysis_results = []

for pdf_file in pdf_files[:23]:
    pdf_path = os.path.join(doc_dir, pdf_file)
    try:
        analysis = analyze_pdf_structure(pdf_path)
        
        page_count = analysis['page_count']
        page_texts = analysis['page_texts']
        text_quality = analysis.get('text_quality', {})
        is_low_quality = text_quality.get('is_low_quality', False)
        
        code_toc = analysis.get('code_toc', {})
        has_code_toc = code_toc.get('items') is not None
        toc_source = code_toc.get('source', 'none')
        toc_items = code_toc.get('items', [])
        
        # Checkpoint 1: TOC Detection Analysis
        toc_detected = False
        toc_pages = []
        for i in range(min(20, page_count)):
            text = page_texts[i].strip()
            toc_line_count = 0
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if re.match(r'^(?:第[一二三四五六七八九十\d]+[章节]|[\d一二三四五六七八九十]+[\.、\)）\s])', line):
                    if re.search(r'\d{1,4}$', line) or re.search(r'[.…·\s]+\d{1,4}$', line):
                        toc_line_count += 1
            if toc_line_count >= 3:
                toc_pages.append(i+1)
                toc_detected = True
        
        # Checkpoint 2: TOC Quality Analysis
        toc_quality_issues = []
        if toc_items:
            for item in toc_items:
                page = item.get('physical_index', 0)
                if page > page_count + 50:
                    toc_quality_issues.append(f"Page {page} > doc pages ({page_count})")
                if page < 1:
                    toc_quality_issues.append(f"Invalid page {page}")
            
            titles = [item.get('title', '') for item in toc_items]
            if len(titles) != len(set(titles)):
                toc_quality_issues.append("Duplicate titles")
            
            for item in toc_items:
                title = item.get('title', '')
                if len(title) < 3:
                    toc_quality_issues.append(f"Title too short: '{title}'")
                if len(title) > 100:
                    toc_quality_issues.append(f"Title too long: '{title[:50]}...'")
        
        # Checkpoint 3: Structure Generation Difficulty
        structure_difficulty = "Easy"
        chapter_patterns = 0
        for text in page_texts[:30]:
            if re.search(r'^(?:第[一二三四五六七八九十\d]+[章节]|Chapter\s+\d+|\d+\.\d+\s+\S{5,})', text, re.M):
                chapter_patterns += 1
        
        has_dividers = len(analysis.get('chapter_dividers', [])) > 0
        
        if has_dividers:
            structure_difficulty = "Hard (dividers)"
        elif chapter_patterns < 3:
            structure_difficulty = "Hard (no clear structure)"
        elif chapter_patterns < 8:
            structure_difficulty = "Medium"
        
        # Checkpoint 4: Verification Risk
        verification_risk = "Low"
        if is_low_quality:
            verification_risk = "High (low text quality)"
        elif len(toc_items) > 50 if toc_items else False:
            verification_risk = "High (too many items)"
        elif toc_quality_issues:
            verification_risk = "Medium (TOC quality issues)"
        
        doc_result = {
            'file': pdf_file,
            'pages': page_count,
            'toc_detected': toc_detected,
            'toc_pages': toc_pages,
            'toc_source': toc_source,
            'toc_items_count': len(toc_items) if toc_items else 0,
            'toc_quality_issues': toc_quality_issues,
            'structure_difficulty': structure_difficulty,
            'verification_risk': verification_risk,
            'has_dividers': has_dividers,
            'dividers': analysis.get('chapter_dividers', []),
        }
        analysis_results.append(doc_result)
        
    except Exception as e:
        output_lines.append(f"ERROR - {pdf_file}: {e}")

# Output analysis results
output_lines.append(f"Analyzed {len(analysis_results)} documents")
output_lines.append("")

# Statistics by checkpoint
output_lines.append("="*80)
output_lines.append("Checkpoint 1: TOC Detection Risk")
output_lines.append("="*80)
output_lines.append("")

high_risk_toc = [r for r in analysis_results if not r['toc_detected'] and r['toc_source'] == 'none']
medium_risk_toc = [r for r in analysis_results if not r['toc_detected'] and r['toc_source'] != 'none']

output_lines.append(f"High risk (no TOC detected, none exists): {len(high_risk_toc)} docs")
for r in high_risk_toc[:5]:
    output_lines.append(f"  - {r['file'][:50]}: {r['pages']}p")

output_lines.append(f"\nMedium risk (no TOC detected, but code found one): {len(medium_risk_toc)} docs")
for r in medium_risk_toc[:5]:
    output_lines.append(f"  - {r['file'][:50]}: {r['pages']}p, source={r['toc_source']}")

output_lines.append("")
output_lines.append("="*80)
output_lines.append("Checkpoint 2: TOC Quality Risk")
output_lines.append("="*80)
output_lines.append("")

docs_with_toc_issues = [r for r in analysis_results if r['toc_quality_issues']]
output_lines.append(f"Documents with TOC quality issues: {len(docs_with_toc_issues)}")
for r in docs_with_toc_issues:
    output_lines.append(f"\n  {r['file'][:50]}:")
    for issue in r['toc_quality_issues'][:5]:
        output_lines.append(f"    - {issue}")

output_lines.append("")
output_lines.append("="*80)
output_lines.append("Checkpoint 3: Structure Generation Difficulty")
output_lines.append("="*80)
output_lines.append("")

hard_docs = [r for r in analysis_results if 'Hard' in r['structure_difficulty']]
medium_docs = [r for r in analysis_results if 'Medium' in r['structure_difficulty']]
easy_docs = [r for r in analysis_results if r['structure_difficulty'] == 'Easy']

output_lines.append(f"Hard: {len(hard_docs)} docs")
for r in hard_docs:
    output_lines.append(f"  - {r['file'][:50]}: {r['structure_difficulty']}")
    if r['has_dividers']:
        output_lines.append(f"    Dividers: {r['dividers']}")

output_lines.append(f"\nMedium: {len(medium_docs)} docs")
for r in medium_docs[:3]:
    output_lines.append(f"  - {r['file'][:50]}")

output_lines.append(f"\nEasy: {len(easy_docs)} docs")
for r in easy_docs[:3]:
    output_lines.append(f"  - {r['file'][:50]}")

output_lines.append("")
output_lines.append("="*80)
output_lines.append("Checkpoint 4: Verification Risk")
output_lines.append("="*80)
output_lines.append("")

high_risk_verif = [r for r in analysis_results if 'High' in r['verification_risk']]
medium_risk_verif = [r for r in analysis_results if 'Medium' in r['verification_risk']]

output_lines.append(f"High risk: {len(high_risk_verif)} docs")
for r in high_risk_verif:
    output_lines.append(f"  - {r['file'][:50]}: {r['verification_risk']}")

output_lines.append(f"\nMedium risk: {len(medium_risk_verif)} docs")
for r in medium_risk_verif:
    output_lines.append(f"  - {r['file'][:50]}: {r['verification_risk']}")

# Design enhancement checkpoints
output_lines.append("")
output_lines.append("="*80)
output_lines.append("Enhancement Checkpoint Design")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("Based on analysis, design these enhancement checkpoints:")
output_lines.append("")

output_lines.append("Checkpoint 1: TOC Detection Enhancement")
output_lines.append("-"*60)
output_lines.append("Trigger: Text scan didn't detect TOC, but document might have one")
output_lines.append("Enhancement: VLM thumbnail grid analysis of first 20 pages")
output_lines.append("Expected benefit: Catch unusual TOC formats (e.g., 'hui bao ti gang')")
output_lines.append(f"Expected trigger: {len(high_risk_toc)} docs")
output_lines.append("")

output_lines.append("Checkpoint 2: TOC Quality Enhancement")
output_lines.append("-"*60)
output_lines.append("Trigger: TOC extracted but quality metrics abnormal")
output_lines.append("Enhancement: VLM verification of TOC page content vs extracted results")
output_lines.append("Expected benefit: Catch bad TOC extraction (e.g., wrong page numbers)")
output_lines.append(f"Expected trigger: {len(docs_with_toc_issues)} docs")
output_lines.append("")

output_lines.append("Checkpoint 3: Structure Generation Enhancement")
output_lines.append("-"*60)
output_lines.append("Trigger: High difficulty in structure generation (dividers/no clear headings)")
output_lines.append("Enhancement: VLM analysis of overall document structure")
output_lines.append("Expected benefit: Correctly handle divider-type documents")
output_lines.append(f"Expected trigger: {len(hard_docs)} docs")
output_lines.append("")

output_lines.append("Checkpoint 4: Verification Enhancement")
output_lines.append("-"*60)
output_lines.append("Trigger: High verification risk (low quality text/many items)")
output_lines.append("Enhancement: VLM visual verification instead of text verification")
output_lines.append("Expected benefit: Improve verification accuracy")
output_lines.append(f"Expected trigger: {len(high_risk_verif)} docs")
output_lines.append("")

# Unified enhancement interface
output_lines.append("="*80)
output_lines.append("Unified Enhancement Interface Design")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("Core idea: Decorator Pattern")
output_lines.append("  - Keep official API unchanged")
output_lines.append("  - Insert optional enhancement checks at each step")
output_lines.append("  - Fall back to official implementation if enhancement fails")
output_lines.append("")

output_lines.append("Key advantages:")
output_lines.append("  1. Official pipeline remains the primary path")
output_lines.append("  2. Enhancements are additive, not replacement")
output_lines.append("  3. Each checkpoint can be enabled/disabled independently")
output_lines.append("  4. Easy to test and measure impact of each enhancement")
output_lines.append("  5. Backward compatible - can disable all enhancements")
output_lines.append("")

output_lines.append("Implementation approach:")
output_lines.append("  1. Create EnhancementProvider interface")
output_lines.append("  2. Official pipeline accepts optional EnhancementProvider")
output_lines.append("  3. Each checkpoint calls provider if available")
output_lines.append("  4. Provider returns enhanced result or None (use official)")
output_lines.append("")

output_lines.append("Example:")
output_lines.append("  # Without enhancement")
output_lines.append("  result = official_pipeline.process(doc)")
output_lines.append("")
output_lines.append("  # With enhancement")
output_lines.append("  provider = MultimodalEnhancementProvider()")
output_lines.append("  result = official_pipeline.process(doc, enhancer=provider)")
output_lines.append("")

output_lines.append("="*80)
output_lines.append("Comparison")
output_lines.append("="*80)
output_lines.append("")

output_lines.append("vs Simple Trigger Approach:")
output_lines.append("  [OK] Keeps official API unchanged")
output_lines.append("  [OK] Modular design, each checkpoint independent")
output_lines.append("  [OK] Auto-fallback to official implementation")
output_lines.append("  [OK] Easy to test and maintain")
output_lines.append("  [OK] Can enable/disable checkpoints individually")
output_lines.append("")

output_lines.append("vs Official Original:")
output_lines.append("  [OK] Provides multimodal enhancement at key points")
output_lines.append("  [OK] Catches edge cases official pipeline misses")
output_lines.append("  [OK] Keeps official core logic unchanged")
output_lines.append("  [OK] Gradual enhancement, controllable risk")
output_lines.append("")

output_lines.append("="*80)
output_lines.append("NEXT STEPS")
output_lines.append("="*80)
output_lines.append("")
output_lines.append("1. Implement EnhancementProvider interface")
output_lines.append("2. Implement each checkpoint one by one")
output_lines.append("3. Test each checkpoint on 24 documents")
output_lines.append("4. Measure accuracy improvement per checkpoint")
output_lines.append("5. Create configuration to enable/disable checkpoints")
output_lines.append("")

# Write to file
output_text = "\n".join(output_lines)
with open('test_experiments/enhancement_checkpoint_design.txt', 'w', encoding='utf-8') as f:
    f.write(output_text)

print("="*80)
print("Enhancement Checkpoint Design Complete")
print("="*80)
print()
print(f"Analyzed: {len(analysis_results)} documents")
print(f"High risk TOC detection: {len(high_risk_toc)}")
print(f"TOC quality issues: {len(docs_with_toc_issues)}")
print(f"Hard structure: {len(hard_docs)}")
print(f"High risk verification: {len(high_risk_verif)}")
print()
print("Core idea: Insert enhancement checkpoints in official pipeline")
print("Keep official API unchanged, internal modular enhancement")
print()
print("Report: test_experiments/enhancement_checkpoint_design.txt")
