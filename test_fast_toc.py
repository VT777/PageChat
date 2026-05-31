import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.fast_toc import try_fast_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"

test_files = {
    "第五范式_2025": "*90e75e6f*",
    "AI眼镜_2025": "*d9b2b5ea*",
    "技术应用洞察_2025": "*097e50d9*",
}

async def test_fast():
    for name, pattern in test_files.items():
        files = glob.glob(f"{doc_dir}/{pattern}")
        if not files:
            print(f"{name}: NOT FOUND")
            continue
        
        file_path = files[0]
        analysis = analyze_pdf_structure(file_path)
        
        print(f"\n{'='*60}")
        print(f"Testing: {name}")
        print(f"{'='*60}")
        print(f"  has_code_toc: {analysis['code_toc']['items'] is not None}")
        print(f"  source: {analysis['code_toc'].get('source')}")
        print(f"  text_coverage: {analysis['text_coverage']:.2f}")
        
        result = await try_fast_toc(analysis, model="qwen3.6-flash")
        
        if result:
            print(f"  FAST SUCCESS: {len(result['toc_items'])} items")
        else:
            print(f"  FAST FAILED: returned None")

asyncio.run(test_fast())
