import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors
from pageindex.post_processing import post_process_toc

doc_dir = "D:/projects/page_chat/backend/data/documents"
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]

async def test():
    analysis = analyze_pdf_structure(file_path)
    anchors = await _vlm_detect_anchors(file_path)
    
    print("=== 测试技术应用洞察 ===")
    print(f"Dividers: {anchors.get('chapter_dividers')}")
    print(f"TOC pages: {anchors.get('toc_pages')}")
    print(f"First content: {anchors.get('first_content_page')}")
    
    result = await build_balanced_toc_visual(
        file_path, analysis, model="qwen3.6-flash", anchors=anchors
    )
    
    toc_items = result["toc_items"]
    print(f"\nTOC items: {len(toc_items)}")
    
    # Check if smart grouping triggered
    for item in toc_items:
        print(f"  {item.get('structure')}: p.{item.get('physical_index')} - {item.get('title', '')[:40]}")
    
    # Check spans
    print("\nSpan calculation:")
    page_count = analysis["page_count"]
    for i, item in enumerate(toc_items):
        start = item.get("physical_index", 0)
        if i < len(toc_items) - 1:
            end = toc_items[i + 1].get("physical_index", start + 1) - 1
        else:
            end = page_count
        span = end - start + 1
        print(f"  {item.get('structure')}: p.{start}-p.{end} (span={span}) {'LARGE!' if span >= 8 else ''}")

asyncio.run(test())
