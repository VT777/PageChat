import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, base64, io
from PIL import Image
from pageindex.vlm_utils import render_pages_to_images

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

# Render key pages to verify chapter starts
# Index says: Part01 p.6, Part02 p.17, Part03 p.29, Part04 p.40, Part05 p.52
check_pages = [5, 6, 7, 16, 17, 28, 29, 39, 40, 51, 52]  # 0-indexed

for idx in check_pages:
    if idx >= 62:
        continue
    images = render_pages_to_images(file_path, [idx], dpi=120)
    img = images[0]
    img_data = base64.b64decode(img["image_base64"])
    pil_img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/fa82_verify_{idx+1}.png"
    pil_img.save(out_path)
    print(f"Saved page {idx+1}")
