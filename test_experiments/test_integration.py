"""集成测试：验证改进后的Branch B在项目代码中正常工作"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from pageindex.balanced_toc import _branch_b_normal_dividers
from pageindex.post_processing import post_process_toc


async def test_integration():
    """测试改进后的Branch B集成"""
    
    file_path = "backend/data/documents/275d4c02_2026年快消行业AI营销增长白皮书.pdf"
    dividers = [5, 13, 25, 35, 41]
    page_count = 62
    model = "qwen3.6-flash"
    
    print("="*70)
    print("INTEGRATION TEST: 改进版Branch B")
    print("="*70)
    
    # Step 1: 调用改进后的Branch B
    print("\n[Step 1] 调用 _branch_b_normal_dividers (improved)")
    result = await _branch_b_normal_dividers(
        file_path=file_path,
        page_count=page_count,
        dividers=dividers,
        model=model
    )
    
    if not result:
        print("[ERROR] Branch B返回None")
        return False
    
    toc_items = result["toc_items"]
    print(f"[OK] 提取到 {len(toc_items)} 个条目")
    
    # 显示前10个
    print("\n前10个条目:")
    for item in toc_items[:10]:
        print(f"  [{item.get('structure', 'N/A')}] p.{item.get('physical_index')} {item.get('title', 'N/A')[:40]}")
    
    # Step 2: 后处理
    print("\n[Step 2] 后处理")
    tree, completeness = post_process_toc(
        toc_items=toc_items,
        page_count=page_count,
        dividers=dividers,
    )
    
    print(f"[OK] 后处理完成: {len(tree)} 个顶级节点, 覆盖率 {completeness['coverage']:.0%}")
    
    # Step 3: 验证
    print("\n[Step 3] 验证")
    success = True
    
    # 验证1：页码准确性
    expected = {
        5: ["市场", "Part01"],
        6: ["行业", "现状"],
        7: ["竞争", "态势"],
        13: ["Part02"],
    }
    
    print("\n页码验证:")
    for page, keywords in expected.items():
        found = [it for it in toc_items if it.get("physical_index") == page]
        if found:
            title = found[0].get("title", "")
            matches = any(kw in title for kw in keywords)
            status = "OK" if matches else "FAIL"
            print(f"  p.{page}: {status} '{title[:30]}' (期望含{keywords})")
            if not matches:
                success = False
        else:
            print(f"  p.{page}: FAIL 未找到")
            success = False
    
    # 验证2：层级结构
    main_count = len([it for it in toc_items if '.' not in str(it.get('structure', ''))])
    sub_count = len([it for it in toc_items if '.' in str(it.get('structure', ''))])
    
    print(f"\n层级结构:")
    print(f"  主章节: {main_count} (期望: 5)")
    print(f"  子章节: {sub_count} (期望: >0)")
    
    if main_count == 5:
        print("  [OK] 主章节数量正确")
    else:
        print("  [FAIL] 主章节数量不正确")
        success = False
    
    if sub_count > 0:
        print("  [OK] 有子章节")
    else:
        print("  [FAIL] 无子章节")
        success = False
    
    # 验证3：树结构
    print(f"\n树结构验证:")
    print(f"  顶级节点: {len(tree)}")
    for i, node in enumerate(tree):
        struct = node.get('structure', 'N/A')
        title = node.get('title', 'N/A')[:30]
        children = len(node.get('nodes', []))
        print(f"  节点{i+1}: [{struct}] {title} (子节点:{children})")
    
    if success:
        print("\n*** ALL CHECKS PASSED ***")
    else:
        print("\n*** SOME CHECKS FAILED ***")
    
    return success


if __name__ == "__main__":
    success = asyncio.run(test_integration())
    sys.exit(0 if success else 1)
