import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio, json

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json

# 新 prompt：更健壮，包含正例/反例
PAGE_TITLE_PROMPT_V2 = """这是文档的第 {page} 页截图。

请识别这一页的**章节标题**（即这一页属于哪个章节/主题）。

【识别规则】
- 标题通常是页面上方最醒目的文字（字号最大、粗体、特殊颜色）
- 如果页面有多个标题，只返回最大的那个（主标题）
- 标题不等于页码、logo、版权信息

【必须返回 null 的情况】
- 封面页：有 logo、副标题、出版信息、"白皮书""报告"等字样
- 目录页：有大量章节名 + 页码列表（如"第一章...15"格式）
- 空白页或纯图片页（无文字）
- 广告页、版权页

【返回格式】
如果有标题：{{"title": "标题文字"}}
如果没有标题：{{"title": null}}

注意：只返回 JSON，不要其他文字。"""


async def test_improved_prompt():
    """Test the improved prompt on key pages: cover, TOC, chapter start, content."""
    test_pages = [
        (0, "封面"),
        (1, "目录左页"),
        (2, "目录右页"),
        (3, "目录CONTENTS"),
        (4, "Part01章节标题页"),
        (5, "Part01内容页1"),
        (6, "Part01内容页2"),
        (12, "Part02章节标题页"),
        (13, "Part02内容页1"),
        (34, "Part04章节标题页"),
        (39, "Part04内容页"),
    ]
    
    print("Testing improved prompt on key pages:\n")
    for page_idx, desc in test_pages:
        images = render_pages_to_images(file_path, [page_idx], dpi=150)
        if not images:
            continue
        
        prompt = PAGE_TITLE_PROMPT_V2.format(page=page_idx + 1)
        
        try:
            raw = await vlm_call_with_images(images, prompt, model="qwen3.6-flash", max_tokens=100)
            result = parse_vlm_json(raw)
            title = result.get("title") if isinstance(result, dict) else None
            status = f"'{title}'" if title else "null"
            print(f"  p.{page_idx+1:2d} ({desc:15s}): {status}")
        except Exception as e:
            print(f"  p.{page_idx+1:2d} ({desc:15s}): ERROR {e}")

asyncio.run(test_improved_prompt())
