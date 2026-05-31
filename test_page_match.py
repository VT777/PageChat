import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = "D:/projects/page_chat/backend/data/documents"

# Check if page text contains the bookmark titles
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]
analysis = analyze_pdf_structure(file_path)

items = analysis["code_toc"].get("items", [])
page_list = analysis.get("page_list", [])

# Check first few items
for item in items[:3]:
    title = item.get("title", "")
    claimed_page = item.get("physical_index", 1)
    
    print(f"\nTitle: '{title}'")
    print(f"Claimed page: {claimed_page}")
    
    # Check actual page content
    if claimed_page <= len(page_list):
        page_text = page_list[claimed_page - 1][0]
        print(f"Actual page {claimed_page} text (first 200 chars):")
        print(f"  {page_text[:200]}")
        
        # Check if title appears
        if title in page_text:
            print("  -> Title FOUND in page")
        else:
            print("  -> Title NOT found in page")
