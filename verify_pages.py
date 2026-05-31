import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import base64
import io
from pathlib import Path
from PIL import Image

# Find the actual file
base_dir = Path("D:/projects/page_chat/backend/data/documents")
for f in base_dir.iterdir():
    if "6de931ad" in f.name:
        file_path = str(f)
        print(f"Found: {f.name}")
        break

from pageindex.vlm_utils import render_pages_to_images

# Render pages 1-6 (p.1 to p.6) to verify content
print("\n=== Rendering pages 1-6 ===")
images = render_pages_to_images(file_path, [0, 1, 2, 3, 4, 5], dpi=150)

for img_info in images:
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/verify_page_{idx+1}.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: size={img.size}")

# Also OCR these pages to see text content
from app.services.ocr_service import OCRService
import asyncio

async def ocr_pages():
    ocr_service = OCRService()
    print("\n=== OCR pages 1-6 ===")
    for img_info in images:
        page_num = img_info["page_index"] + 1
        result = await ocr_service.ocr_image_base64(img_info["image_base64"], page_num)
        if result.ok:
            text_preview = result.text[:200].replace('\n', ' ')
            print(f"p.{page_num}: {text_preview}...")
        else:
            print(f"p.{page_num}: OCR failed - {result.error}")

asyncio.run(ocr_pages())
