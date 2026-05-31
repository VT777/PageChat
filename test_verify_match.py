import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.fast_toc import try_fast_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Test verify_content_match details
file_path = glob.glob(f"{doc_dir}/*90e75e6f*")[0]
analysis = analyze_pdf_structure(file_path)

# Check code TOC items
code_toc = analysis["code_toc"]
items = code_toc.get("items", [])

print(f"Total code TOC items: {len(items)}")
print("\nFirst 10 items:")
for i, item in enumerate(items[:10]):
    print(f"  {i}: structure={item.get('structure')}, title={item.get('title', '')[:40]}, physical_index={item.get('physical_index')}")

# Check page list sample
page_list = analysis.get("page_list", [])
print(f"\nTotal pages: {len(page_list)}")
print("\nFirst 3 pages text (first 200 chars):")
for i in range(min(3, len(page_list))):
    text = page_list[i][0][:200]
    print(f"  Page {i+1}: {text}")
