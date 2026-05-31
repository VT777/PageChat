import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import base64
import io
from pathlib import Path
from PIL import Image
from pageindex.vlm_utils import render_pages_to_images

# Find the actual file
base_dir = Path("D:/projects/page_chat/backend/data/documents")
for f in base_dir.iterdir():
    if "6de931ad" in f.name:
        file_path = str(f)
        print(f"Found: {f.name}")
        break

# Find "企业碳账户" case index
import json
d = json.load(open('D:/projects/page_chat/backend/data/indexes/6de931ad.json', encoding='utf-8'))
items = d.get('structure', [])

# Find the case with "碳账户" or "企业碳"
target_idx = None
for i, it in enumerate(items):
    title = it.get('title', '')
    if '碳' in title or '账户' in title:
        target_idx = i
        print(f"Found '{title}' at index {i}, structure={it.get('structure')}, start={it.get('start_index')}, end={it.get('end_index')}")
        # Also show surrounding cases
        print("\nSurrounding cases:")
        for j in range(max(0, i-2), min(len(items), i+3)):
            t = items[j]
            print(f"  {t.get('structure', '?'):4s}  start={t.get('start_index', 0):3d}  end={t.get('end_index', 0):3d}  {t['title'][:40]}")
        break

if target_idx is None:
    print("Target case not found")
    sys.exit(1)

# Render the pages around this case
target_item = items[target_idx]
start_page = target_item.get('start_index', 1) - 1  # 0-indexed
end_page = target_item.get('end_index', start_page + 1)

# Also render a few cases before and after
pages_to_render = list(range(max(0, start_page - 2), min(44, end_page + 3)))
print(f"\nRendering pages: {[p+1 for p in pages_to_render]}")

images = render_pages_to_images(file_path, pages_to_render, dpi=150)
for img_info in images:
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/case_page_{idx+1}.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: size={img.size}")
