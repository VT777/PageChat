import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, json, asyncio

file_path = glob.glob("D:/projects/page_chat/backend/data/documents/*fa82c969*")[0]

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors
from pageindex.post_processing import post_process_toc

async def main():
    analysis = analyze_pdf_structure(file_path)
    anchors = await _vlm_detect_anchors(file_path)
    
    result = await build_balanced_toc_visual(
        file_path, analysis, model="qwen3.6-flash", anchors=anchors
    )
    
    toc_items = result["toc_items"]
    
    # Run full post-processing to verify build_tree works
    tree, completeness = post_process_toc(toc_items, analysis["page_count"])
    
    print(f"=== Post-processed tree ({len(tree)} top-level nodes) ===\n")
    for node in tree:
        s = node.get('start_index', '?')
        e = node.get('end_index', '?')
        st = node.get('structure', '?')
        title = node.get('title', '')[:40]
        children = node.get('nodes', [])
        print(f"  [{st}] p.{s}-{e}  {title}")
        for sub in children[:3]:
            ss = sub.get('start_index', '?')
            se = sub.get('end_index', '?')
            sst = sub.get('structure', '?')
            stitle = sub.get('title', '')[:40]
            print(f"    [{sst}] p.{ss}-{se}  {stitle}")
        if len(children) > 3:
            print(f"    ... +{len(children)-3} more sub-nodes")
        print()
    
    total = len(tree) + sum(len(n.get('nodes', [])) for n in tree)
    print(f"Total nodes: {total}")

asyncio.run(main())
