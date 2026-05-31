import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob

from pageindex.pdf_analyzer import analyze_pdf_structure

doc_dir = "D:/projects/page_chat/backend/data/documents"

test_files = {
    "AI眼镜_2025": "*d9b2b5ea*",
    "技术应用洞察_2025": "*097e50d9*",
    "AI_Agent_2026": "*9cf5b5be*",
}

for name, pattern in test_files.items():
    file_path = glob.glob(f"{doc_dir}/{pattern}")[0]
    analysis = analyze_pdf_structure(file_path)
    
    code_toc = analysis["code_toc"]
    items = code_toc.get("items", [])
    source = code_toc.get("source", "none")
    
    print(f"\n{'='*60}")
    print(f"{name} (source={source}, pages={analysis['page_count']})")
    print(f"{'='*60}")
    print(f"Total items: {len(items)}")
    
    # Check for out-of-range physical_index
    out_of_range = [it for it in items if it.get("physical_index", 0) > analysis["page_count"]]
    print(f"Out of range: {len(out_of_range)} / {len(items)}")
    
    for i, item in enumerate(items[:5]):
        print(f"  {i}: structure={item.get('structure')}, pi={item.get('physical_index')}, title={item.get('title', '')[:40]}")
    
    if out_of_range:
        print("  Out of range examples:")
        for item in out_of_range[:3]:
            print(f"    structure={item.get('structure')}, pi={item.get('physical_index')}, title={item.get('title', '')[:40]}")
