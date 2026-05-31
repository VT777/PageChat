import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = "D:/projects/page_chat/backend/data/documents"

file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]
analysis = analyze_pdf_structure(file_path)

items = analysis["code_toc"].get("items", [])

print("Testing encoding issue:")
for i, item in enumerate(items[:5]):
    title = item.get("title", "")
    # Try different decodings
    try:
        # If title is already str, encode to bytes first
        if isinstance(title, str):
            # Try to see if it's UTF-8 bytes misinterpreted as latin-1
            bytes_title = title.encode('latin-1')
            decoded = bytes_title.decode('utf-8', errors='replace')
            print(f"  Item {i}: original='{title[:30]}', re-decoded='{decoded[:30]}', pi={item.get('physical_index')}")
    except Exception as e:
        print(f"  Item {i}: '{title[:30]}', error={e}")
