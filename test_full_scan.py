import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio, json

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json

async def test_full_scan():
    """逐页扫描整个文档，提取每页标题。"""
    page_count = 62
    print(f"Scanning {page_count} pages one by one...")
    
    all_titles = []
    for page_idx in range(page_count):
        images = render_pages_to_images(file_path, [page_idx], dpi=150)
        if not images:
            continue
        
        prompt = """这是一份文档的单页截图（物理页码 p.{page}）。

请识别这页的标题。标题通常位于页面左上角，可能是更大的字号或特殊颜色。

如果该页有明确的标题 → 返回标题
如果该页是空白页、过渡页或封面 → 返回 null

回答 JSON（不要 markdown code fence）:
{{"physical_index": {page}, "title": "标题或null"}}""".format(page=page_idx + 1)
        
        try:
            raw = await vlm_call_with_images(images, prompt, model="qwen3.6-flash", max_tokens=200)
            result = parse_vlm_json(raw)
            if isinstance(result, dict):
                title = result.get("title")
                if title and title != "null":
                    all_titles.append({"physical_index": page_idx + 1, "title": title})
        except Exception as e:
            print(f"  p.{page_idx+1}: ERROR {e}")
    
    print(f"\n=== Results: {len(all_titles)} titles from {page_count} pages ===\n")
    for item in all_titles:
        print(f"  p.{item['physical_index']:2d}  {item['title'][:60]}")
    
    return all_titles

asyncio.run(test_full_scan())
