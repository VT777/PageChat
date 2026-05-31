import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, base64, io
from PIL import Image
from pageindex.vlm_utils import render_pages_to_images

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]
print(f"File: {file_path}")

# Render first 12 pages to see document structure
images = render_pages_to_images(file_path, list(range(12)), dpi=100)

for img_info in images:
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/fa82_page_{idx+1}.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: {img.size}")
