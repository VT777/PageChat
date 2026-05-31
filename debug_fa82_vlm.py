import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json

# Read the index to get the VLM-extracted data
d = json.load(open('D:/projects/page_chat/backend/data/indexes/fa82c969.json', encoding='utf-8'))

# The index file stores the final tree, not the raw VLM output.
# Let me write a test script that calls ONLY the TOC extraction part and logs VLM output
# to see what number field values VLM actually returns.

# Alternative: render the suspected TOC pages and read them visually
file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.vlm_utils import render_pages_to_images
import base64, io
from PIL import Image

# Render pages 1-10 (likely contains TOC)
for img_info in render_pages_to_images(file_path, list(range(10)), dpi=120):
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/fa82_detail_{idx+1}.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: {img.size}")

# Also render a page from the middle to verify chapter start pages
for img_info in render_pages_to_images(file_path, [15, 16, 17], dpi=120):
    idx = img_info["page_index"]
    img_data = base64.b64decode(img_info["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/fa82_detail_{idx+1}.png"
    img.save(out_path)
    print(f"Saved page {idx+1}: {img.size}")
