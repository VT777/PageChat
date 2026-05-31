import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob

# Find the actual file
files = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")
if files:
    file_path = files[0]
    print(f"File found: {file_path}")
else:
    print("File not found")
    sys.exit(1)

from pageindex.pdf_analyzer import analyze_pdf_structure

analysis = analyze_pdf_structure(file_path)
print(f"Page count: {analysis['page_count']}")
print(f"Text coverage: {analysis['text_coverage']:.2f}")
print(f"Is image only: {analysis['is_image_only_pdf']}")
print(f"Is garbled: {analysis['is_garbled_pdf']}")
print(f"Text pages: {len(analysis['text_pages'])}")
print(f"Image only pages: {len(analysis['image_only_pages'])}")
print(f"Garbled pages: {len(analysis['garbled_pages'])}")

# Check text of first few pages
for idx in list(analysis['text_pages'])[:8]:
    text = analysis['page_texts'][idx]
    headings = []
    for line in text.split('\n'):
        if any(p in line for p in ['章', '节', '部分', '目录', '前言', '结语', 'CONTENTS']):
            headings.append(line[:80])
    if headings:
        print(f"\np.{idx+1}: {', '.join(headings)}")
        print(f"  Text len: {len(text)}")

# Check code TOC
code_toc = analysis.get('code_toc', {})
print(f"\nCode TOC source: {code_toc.get('source')}")
if code_toc.get('items'):
    for it in code_toc['items'][:10]:
        print(f"  structure={it.get('structure')} title={it.get('title')} pi={it.get('physical_index')}")
