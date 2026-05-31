"""Deep analysis: Why is page_list content garbled?"""

import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import glob, os
from pathlib import Path
import fitz  # PyMuPDF

# Find file
doc_dir = "D:/projects/page_chat/backend/data/documents"
files = glob.glob(f"{doc_dir}/*097e50d9*")
file_path = files[0]

print("=== DIRECT PDF TEXT EXTRACTION ===\n")

# Extract text directly with PyMuPDF
doc = fitz.open(file_path)
print(f"Total pages: {len(doc)}")

for page_num in [4, 5, 11, 12, 24, 25]:
    page = doc[page_num - 1]  # 0-indexed
    text = page.get_text()
    print(f"\n--- Page {page_num} (PyMuPDF direct) ---")
    print(f"Length: {len(text)} chars")
    print(f"First 300 chars (ascii safe):")
    safe_text = text[:300].encode('ascii', 'replace').decode('ascii')
    print(safe_text)

doc.close()

print("\n\n=== CHECK PDF ANALYZER METHOD ===")
from pageindex.pdf_analyzer import analyze_pdf_structure

analysis = analyze_pdf_structure(file_path)
print(f"Text coverage: {analysis['text_coverage']}")
print(f"Page count: {analysis['page_count']}")
print(f"Is image only: {analysis.get('is_image_only_pdf', False)}")
print(f"Is garbled: {analysis.get('is_garbled_pdf', False)}")

# Check if analyze_pdf_structure uses OCR
print(f"\nImage only pages: {len(analysis.get('image_only_pages', []))}")
print(f"Garbled pages: {len(analysis.get('garbled_pages', []))}")

# Show what page_list actually contains
page_list = analysis['page_list']
print(f"\nPage list length: {len(page_list)}")
print(f"Page list[0] type: {type(page_list[0])}")
print(f"Page list[0] length: {len(page_list[0])}")
if isinstance(page_list[0], tuple):
    print(f"Page list[0][0] length: {len(page_list[0][0])}")
    print(f"Page list[0][0] first 200 chars:")
    try:
            safe = page_list[0][0][:200].encode('ascii', 'replace').decode('ascii')
            print(safe)
    except Exception as e:
        print(f"Error: {e}")

# Check if there's any readable text
print(f"\n=== CHECKING FOR READABLE TEXT ===")
has_readable = False
for i, page_data in enumerate(page_list):
    if isinstance(page_data, tuple):
        text = page_data[0]
    else:
        text = page_data
    
    # Check if text contains Chinese characters
    import re
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', text)
    if chinese_chars:
        has_readable = True
        print(f"Page {i+1}: Found {len(chinese_chars)} Chinese chars")
        # Show first few
        print(f"  Sample: {''.join(chinese_chars[:20])}")

if not has_readable:
    print("WARNING: No readable Chinese text found in page_list!")
    print("This PDF may need OCR processing.")
