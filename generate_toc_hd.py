import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import os
import base64
from pathlib import Path
import io
from PIL import Image

# Find the actual file
base_dir = Path("D:/projects/page_chat/backend/data/documents")
for f in base_dir.iterdir():
    if "6de931ad" in f.name:
        file_path = str(f)
        print(f"Found: {f.name}")
        break

from pageindex.vlm_utils import render_pages_to_images

# Render TOC pages in high DPI (150)
# p.2 and p.3 are the TOC pages (0-indexed: 1, 2)
images = render_pages_to_images(file_path, [1, 2], dpi=150)
print(f"Rendered {len(images)} pages in DPI 150")

for img_info in images:
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/toc_page_{idx+1}_dpi150.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: size={img.size}, path={out_path}")
