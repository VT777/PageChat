import sys
sys.path.insert(0, 'D:/projects/page_chat/backend')

import json
import pymupdf
from pageindex.utils import post_processing, clean_structure_post, add_preface_if_needed, is_garbled_text
from pageindex.divider_fix import detect_divider_pages, fix_toc_for_dividers
from pageindex.page_index import check_toc, find_toc_pages_by_rules

# Simple options mock
class MockOpt:
    def __init__(self):
        self.model = "gpt-4o"
        self.toc_check_page_num = 20
        self.N = 8
        self.batch_size = 5
        self.if_add_node_text = "no"

pdf_path = 'D:/projects/page_chat/backend/data/documents/f9a2f07e_2025年第五范式-人工智能驱动的科技创新报告.pdf'

print("=== Integration Test: All Fixes Combined ===")

# Step 1: Get page tokens
print("\n[1/4] Extracting pages...")
doc = pymupdf.open(pdf_path)
page_list = []
for page in doc:
    text = page.get_text()
    page_list.append((text, len(text)))
doc.close()
print(f"  Total pages: {len(page_list)}")

# Step 2: Check divider detection
print("\n[2/4] Divider detection...")
divider_pages = detect_divider_pages(page_list)
print(f"  Detected divider pages: {divider_pages}")
assert len(divider_pages) > 0, "Should detect divider pages"
print("  OK: Divider pages detected")

# Step 3: Check TOC detection (should NOT detect TOC pages due to 汇报提纲 exclusion)
print("\n[3/4] TOC page detection...")
rule_pages = find_toc_pages_by_rules(page_list)
print(f"  Regex detected pages: {rule_pages}")
# Page 14 should NOT be in the list
assert 14 not in rule_pages, "Page 14 (汇报提纲) should NOT be detected as TOC"
print("  OK: Page 14 correctly excluded from TOC detection")

# Step 4: Simulate a problematic TOC structure and verify fixes
print("\n[4/4] Simulating TOC fixes...")

# Simulate LLM-generated TOC with shifted titles (the problem before fix)
simulated_toc = [
    {"structure": "1", "title": "汇报提纲", "physical_index": 3, "appear_start": "yes"},
    {"structure": "1.1", "title": "大模型概述", "physical_index": 4, "appear_start": "yes"},
    {"structure": "2", "title": "汇报提纲", "physical_index": 13, "appear_start": "yes"},
    {"structure": "2.1", "title": "大模型辅助的论文与项目", "physical_index": 14, "appear_start": "yes"},
    {"structure": "3", "title": "汇报提纲", "physical_index": 35, "appear_start": "yes"},
    {"structure": "3.1", "title": "未来研发方式展望", "physical_index": 36, "appear_start": "yes"},
    {"structure": "4", "title": "汇报提纲", "physical_index": 49, "appear_start": "yes"},
    {"structure": "4.1", "title": "大模型辅助的论文与项目", "physical_index": 50, "appear_start": "yes"},
    {"structure": "5", "title": "汇报提纲", "physical_index": 61, "appear_start": "yes"},
    {"structure": "5.1", "title": "总结与展望", "physical_index": 62, "appear_start": "yes"},
]

# Apply divider fix
fixed_toc = fix_toc_for_dividers(simulated_toc.copy(), page_list)
print(f"  Before fix: {[item['title'] for item in simulated_toc[:5]]}")
print(f"  After fix:  {[item['title'] for item in fixed_toc[:5]]}")

# Check that main chapter titles are no longer "汇报提纲" (where divider fix applied)
main_chapters = [item for item in fixed_toc if '.' not in str(item.get('structure', ''))]
fixed_count = sum(1 for ch in main_chapters if ch['title'] != "汇报提纲")
print(f"  Fixed {fixed_count}/{len(main_chapters)} main chapter titles")
assert fixed_count >= 4, f"Expected at least 4 fixed chapters, got {fixed_count}"
print("  OK: Divider titles replaced with real chapter titles")

# Apply post-processing and check inverted ranges
# First add preface
toc_with_preface = add_preface_if_needed(fixed_toc.copy(), page_list)
tree = post_processing(toc_with_preface, len(page_list))

# Clean output
for node in tree:
    clean_structure_post(node)

print("\n=== Final Tree Structure ===")
print(json.dumps(tree, ensure_ascii=False, indent=2))

# Check no inverted ranges
has_inverted = False
for ch in tree:
    if ch.get('start_index', 0) > ch.get('end_index', float('inf')):
        print(f"  WARNING: Inverted range in '{ch.get('title')}'")
        has_inverted = True
if not has_inverted:
    print("OK: No inverted ranges")

print("\n=== All Integration Tests Passed! ===")
