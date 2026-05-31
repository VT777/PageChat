import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio, json

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json

async def test_single_page():
    """Test extracting titles one page at a time for pages 40-51 (Part04)."""
    pages = list(range(39, 51))  # 0-indexed, p.40-p.51
    print(f"Testing single-page extraction for p.40-p.51...")
    
    results = []
    for page_idx in pages:
        images = render_pages_to_images(file_path, [page_idx], dpi=150)
        if not images:
            continue
        
        prompt = """这是一份文档的单页截图（物理页码 p.{page}）。

请识别这页的标题。标题通常位于页面左上角，可能是更大的字号或特殊颜色。

如果该页有明确的标题 → 返回标题
如果该页是空白页或过渡页 → 返回 null

回答 JSON（不要 markdown code fence）:
{{"physical_index": {page}, "title": "标题或null"}}

注意：physical_index 必须是 {page}。""".format(page=page_idx + 1)
        
        try:
            raw = await vlm_call_with_images(images, prompt, model="qwen3.6-flash", max_tokens=200)
            result = parse_vlm_json(raw)
            if isinstance(result, dict):
                title = result.get("title")
                pi = result.get("physical_index")
                if title and title != "null":
                    results.append({"physical_index": pi, "title": title})
                    print(f"  p.{pi}: {title[:50]}")
                else:
                    print(f"  p.{page_idx+1}: (no title)")
        except Exception as e:
            print(f"  p.{page_idx+1}: ERROR {e}")
    
    print(f"\nTotal: {len(results)} titles from {len(pages)} pages")
    return results

asyncio.run(test_single_page())
