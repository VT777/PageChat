import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, os

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import decide_balanced_path

doc_dir = "D:/projects/page_chat/backend/data/documents"

test_files = {
    "AI_Agent_2026": "*9cf5b5be*",
    "第五范式_2025": "*90e75e6f*",
    "AI眼镜_2025": "*d9b2b5ea*",
    "技术应用洞察_2025": "*097e50d9*",
    "AI治理_2025": "*a1ed6276*",
}

print("Routing Analysis")
print("=" * 80)

for name, pattern in test_files.items():
    files = glob.glob(f"{doc_dir}/{pattern}")
    if not files:
        print(f"{name}: FILE NOT FOUND")
        continue
    
    file_path = files[0]
    analysis = analyze_pdf_structure(file_path)
    
    tc = analysis.get("text_coverage", 0)
    garbled = analysis.get("is_garbled_pdf", False)
    image_only = analysis.get("is_image_only_pdf", False)
    code_toc = analysis.get("code_toc", {})
    has_code_toc = code_toc.get("items") is not None
    
    path = decide_balanced_path(analysis)
    
    print(f"\n{name}:")
    print(f"  text_coverage={tc:.2f}, is_garbled={garbled}, is_image_only={image_only}")
    print(f"  has_code_toc={has_code_toc}, source={code_toc.get('source', 'none')}")
    print(f"  decide_balanced_path -> '{path}'")
    print(f"  garbled_pages={len(analysis.get('garbled_pages', []))}, image_only_pages={len(analysis.get('image_only_pages', []))}")
