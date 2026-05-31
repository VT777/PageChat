import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, re

from pageindex.pdf_analyzer import analyze_pdf_structure, _normalize_for_search
from pageindex.fast_toc import verify_content_match

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Test 技术应用洞察 - why match_rate=0%
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]
analysis = analyze_pdf_structure(file_path)

code_toc = analysis["code_toc"]
items = code_toc.get("items", [])
page_list = analysis.get("page_list", [])

print("Testing: 技术应用洞察_2025")
print(f"Total items: {len(items)}")
print(f"Total pages: {len(page_list)}")

# Sample first item
item = items[0]
title = item.get("title", "").strip()
claimed_page = item.get("physical_index")

print(f"\nFirst item: title='{title}', claimed_page={claimed_page}")

# Search in claimed_page ±5
search_key = _normalize_for_search(title[:30])
print(f"Search key: '{search_key}'")

for delta in range(-5, 6):
    page_idx = claimed_page - 1 + delta
    if 0 <= page_idx < len(page_list):
        normalized_page = _normalize_for_search(page_list[page_idx][0][:3000])
        found = search_key in normalized_page
        if found or delta == 0:
            print(f"  Page {page_idx+1}: found={found}, text_preview={page_list[page_idx][0][:100]}")

# Run full verify
result = verify_content_match(items, page_list)
print(f"\nFull verify: match_rate={result['match_rate']:.0%}, total_checked={result['total_checked']}")
print(f"Mismatches: {len(result['mismatches'])}")
for m in result['mismatches'][:3]:
    print(f"  {m}")
