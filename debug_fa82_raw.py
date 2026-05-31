import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio, re

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json
from pageindex.balanced_toc import _vlm_detect_anchors
from app.prompts.pageindex_prompts import VLM_TOC_EXTRACT_PROMPT

async def main():
    # Detect anchors
    anchors = await _vlm_detect_anchors(file_path)
    toc_pages = anchors.get("toc_pages", [])
    print(f"TOC pages: {toc_pages}")
    
    last_toc = max(toc_pages) if toc_pages else 8
    pages_to_render = sorted(set(
        [p - 1 for p in toc_pages] + list(range(last_toc, min(last_toc + 3, 62)))
    ))
    print(f"Rendering: {pages_to_render}")
    
    images = render_pages_to_images(file_path, pages_to_render, dpi=150)
    
    # Build prompt with page annotations
    page_annotation_lines = []
    for img in images:
        p = img["page_index"] + 1
        label = "TOC" if p in toc_pages else "content"
        page_annotation_lines.append(f"- Image {len(page_annotation_lines)+1}: physical page p.{p} ({label})")
    annotations = "Image sequence:\n" + "\n".join(page_annotation_lines)
    
    prompt = VLM_TOC_EXTRACT_PROMPT.format(page_annotations=annotations)
    
    # Call VLM
    print("Calling VLM...")
    raw = await vlm_call_with_images(images, prompt, max_tokens=3000)
    
    # Parse and show raw
    print("\n=== RAW VLM OUTPUT (first 2000 chars) ===")
    print(raw[:2000])
    print()
    
    result = parse_vlm_json(raw)
    if isinstance(result, dict):
        items = result.get("toc_items", [])
        print(f"Items: {len(items)}")
        for it in items[:10]:
            num = it.get("number", "?")
            title = it.get("title", "?")[:40]
            page = it.get("page")
            print(f"  number={num:10s}  page={page:5s}  title={title}")
    else:
        print(f"Unexpected result type: {type(result)}")

asyncio.run(main())
