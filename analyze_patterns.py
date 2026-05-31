import sys
import os
sys.path.insert(0, 'backend')

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = 'backend/data/documents'
results = []
for f in os.listdir(doc_dir)[:8]:
    if f.endswith('.pdf'):
        path = os.path.join(doc_dir, f)
        try:
            analysis = analyze_pdf_structure(path)
            has_bookmarks = analysis['code_toc']['source'] == 'bookmarks' if analysis['code_toc']['items'] else False
            results.append({
                'file': f[:50],
                'pages': analysis['page_count'],
                'text_coverage': analysis['text_coverage'],
                'code_toc_source': analysis['code_toc']['source'],
                'code_toc_items': len(analysis['code_toc']['items']) if analysis['code_toc']['items'] else 0,
            })
        except Exception as e:
            pass

print("PDF Analysis Results:")
print("-" * 100)
for r in results:
    try:
        print(r['file'].encode('ascii', 'replace').decode() + ": " + str(r['pages']) + "p, text=" + str(int(r['text_coverage']*100)) + "%, source=" + str(r['code_toc_source']) + ", items=" + str(r['code_toc_items']))
    except:
        print("FILE_ERROR: " + str(r.get('pages', 0)) + "p")
