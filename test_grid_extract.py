import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio, json, math

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json

async def test_grid_extract():
    """Test 2x2 grid extraction with new prompt that uses page_indices for physical_index."""
    # Test on Part01 pages (p.6-p.16, 0-indexed 5-15)
    page_indices = list(range(5, 16))
    chapter_title = "市场概述与M型消费、新增长挑战"
    
    # Build 2x2 grids
    images = render_pages_to_images(file_path, page_indices, dpi=150)
    
    # Batch into 2x2 grids
    cols = 2
    pages_per_grid = 4
    all_items = []
    
    for batch_start in range(0, len(images), pages_per_grid):
        batch = images[batch_start:batch_start + pages_per_grid]
        batch_page_indices = [img["page_index"] for img in batch]
        
        prompt = f"""这些是"{chapter_title}"章节的连续页面截图（2x2 网格）。
每页左上角标注了页码 p.N。

请从左到右、从上到下，按顺序提取每一页的标题。
- 标题通常是页面上方最醒目的文字（字号最大、粗体、特殊颜色）
- 如果某页没有标题（纯图片、正文内容、空白），跳过该页
- 封面页、目录页、广告页跳过

只返回标题列表，按顺序排列，不要返回页码：
["标题1", "标题2", ...]"""

        try:
            raw = await vlm_call_with_images(batch, prompt, model="qwen3.6-flash", max_tokens=500)
            titles = parse_vlm_json(raw)
            if isinstance(titles, list):
                for idx, title in zip(batch_page_indices, titles):
                    if title and title != "null":
                        all_items.append({"physical_index": idx + 1, "title": title})
                        print(f"  p.{idx+1}: {title[:50]}")
        except Exception as e:
            print(f"  Batch error: {e}")
    
    print(f"\nTotal: {len(all_items)} titles from {len(page_indices)} pages")

asyncio.run(test_grid_extract())
