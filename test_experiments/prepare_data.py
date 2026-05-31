import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Test framework for comparing two approaches
from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import _vlm_detect_anchors, build_balanced_toc_visual
from pageindex.vlm_utils import render_pages_to_images, vlm_call_with_images, parse_vlm_json
from app.prompts.pageindex_prompts import VLM_FULLTEXT_SECTION_PROMPT

doc_dir = os.path.join(os.path.dirname(__file__), '..', 'backend', 'data', 'documents')
target_file = None
for f in os.listdir(doc_dir):
    if 'f9a2f07e' in f:
        target_file = os.path.join(doc_dir, f)
        break

print(f"Target file: {os.path.basename(target_file)}")
print(f"File exists: {os.path.exists(target_file)}")

# Load analysis
analysis = analyze_pdf_structure(target_file)
print(f"\nDocument info:")
print(f"  Pages: {analysis['page_count']}")
print(f"  Text coverage: {analysis['text_coverage']:.1%}")
print(f"  Code TOC items: {len(analysis['code_toc']['items']) if analysis['code_toc']['items'] else 0}")

# Get anchors
async def get_anchors():
    anchors = await _vlm_detect_anchors(target_file)
    print(f"\nAnchors detected:")
    print(f"  toc_pages: {anchors.get('toc_pages', [])}")
    print(f"  dividers: {anchors.get('chapter_dividers', [])}")
    print(f"  first_content_page: {anchors.get('first_content_page')}")
    return anchors

anchors = asyncio.run(get_anchors())
