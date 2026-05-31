import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import os
import base64
from pathlib import Path

# Find the actual file
base_dir = Path("D:/projects/page_chat/backend/data/documents")
for f in base_dir.iterdir():
    if "6de931ad" in f.name:
        file_path = str(f)
        print(f"Found: {f.name}")
        print(f"Full path: {file_path}")
        break
else:
    print("File not found")
    sys.exit(1)

# Generate thumbnail grids for first 24 pages (to cover TOC)
from pageindex.vlm_utils import render_thumbnail_grids

grids = render_thumbnail_grids(file_path, pages_per_grid=12, cols=4)
print(f"Generated {len(grids)} grids")

# Save the first grid as image
import io
from PIL import Image

for i, grid in enumerate(grids[:2]):
    img_data = base64.b64decode(grid["image_base64"])
    img = Image.open(io.BytesIO(img_data))
    out_path = f"D:/projects/page_chat/thumbnail_grid_{i}.png"
    img.save(out_path)
    print(f"Saved grid {i}: pages {grid['start_page']}-{grid['end_page']} -> {out_path}")
    print(f"  Image size: {img.size}")
