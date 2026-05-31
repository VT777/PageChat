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
        break

# Render pages 11-14 (0-indexed: 10, 11, 12, 13)
print("Rendering pages 11-14 (around case 10):")
images = render_pages_to_images(file_path, [10, 11, 12, 13], dpi=150)
for img_info in images:
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/check_case10_page_{idx+1}.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: size={img.size}")
