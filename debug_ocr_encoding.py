import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

import asyncio
from pathlib import Path
from app.services.pageindex_service import PageIndexService
from pageindex.vlm_utils import render_pages_to_images

# Find the actual file
base_dir = Path("D:/projects/page_chat/backend/data/documents")
for f in base_dir.iterdir():
    if "6de931ad" in f.name:
        file_path = str(f)
        print(f"Found: {f.name}")
        break

async def debug_ocr():
    service = PageIndexService()
    
    # OCR p.2 and p.3 (0-indexed: 1, 2)
    images = render_pages_to_images(file_path, [1, 2], dpi=150)
    
    from app.services.ocr_service import OCRService
    ocr_service = OCRService()
    
    for img in images:
        page_num = img["page_index"] + 1
        result = await ocr_service.ocr_image_base64(img["image_base64"], page_num)
        
        print(f"\n=== Page {page_num} ===")
        print(f"OK: {result.ok}")
        if result.ok:
            # Print raw bytes info
            text = result.text
            print(f"Text length: {len(text)}")
            print(f"First 300 chars (repr): {repr(text[:300])}")
            
            # Try to detect if it's a known encoding issue
            if '' in text or '\ufffd' in text:
                print("WARNING: Contains replacement characters (encoding issue)")
                
                # Try GBK decode
                try:
                    # The text might be UTF-8 that was originally GBK
                    gbk_bytes = text.encode('latin-1', errors='ignore')
                    decoded = gbk_bytes.decode('gbk', errors='ignore')
                    print(f"GBK decode attempt: {decoded[:200]}")
                except Exception as e:
                    print(f"GBK decode failed: {e}")

asyncio.run(debug_ocr())
