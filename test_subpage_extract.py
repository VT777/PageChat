import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.balanced_toc import _vlm_extract_page_titles

async def main():
    # Test extracting page titles from pages 6-12 (should be Part 1 content)
    pages = list(range(5, 12))  # 0-indexed: p.6-p.12
    print(f"Testing page titles from pages {[p+1 for p in pages]}...")
    
    items = await _vlm_extract_page_titles(file_path, pages)
    print(f"\nExtracted {len(items)} titles:")
    for it in items:
        print(f"  p.{it.get('physical_index','?')}  {it.get('title','')[:60]}")

asyncio.run(main())
