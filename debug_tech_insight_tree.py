import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
import glob, asyncio

from pageindex.pdf_analyzer import analyze_pdf_structure
from pageindex.balanced_toc import build_balanced_toc_visual, _vlm_detect_anchors
from pageindex.post_processing import post_process_toc, build_tree, _get_depth

doc_dir = "D:/projects/page_chat/backend/data/documents"
file_path = glob.glob(f"{doc_dir}/*097e50d9*")[0]

async def test():
    analysis = analyze_pdf_structure(file_path)
    anchors = await _vlm_detect_anchors(file_path)
    
    result = await build_balanced_toc_visual(
        file_path, analysis, model="qwen3.6-flash", anchors=anchors
    )
    
    toc_items = result["toc_items"]
    
    print("=== 技术应用洞察 - 详细结构分析 ===\n")
    print(f"Total items: {len(toc_items)}\n")
    
    # 显示所有 items 的 structure 和 depth
    print("Items with depth calculation:")
    for i, item in enumerate(toc_items):
        struct = item.get('structure', 'EMPTY')
        depth = _get_depth(struct)
        title = item.get('title', '')[:40]
        pi = item.get('physical_index', 'NONE')
        print(f"  [{i:2}] struct={struct:8} | depth={depth} | pi={pi:2} | {title}")
    
    # 手动调用 build_tree 看结果
    print("\n=== 调用 build_tree ===\n")
    tree = build_tree(toc_items)
    
    print(f"Top-level nodes: {len(tree)}\n")
    for node in tree:
        s = node.get('start_index', '?')
        e = node.get('end_index', '?')
        st = node.get('structure', '?')
        title = node.get('title', '')[:50]
        children = node.get('nodes', [])
        print(f"  [{st}] p.{s}-{e} struct={st} | {title}")
        print(f"       children={len(children)}")
        for child in children:
            cs = child.get('start_index', '?')
            ce = child.get('end_index', '?')
            cst = child.get('structure', '?')
            ctitle = child.get('title', '')[:40]
            print(f"         [{cst}] p.{cs}-{ce} {ctitle}")
        print()

asyncio.run(test())
