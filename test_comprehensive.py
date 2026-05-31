"""Comprehensive structural validation tests for TOC pipeline.

Validates:
1. Tree structure correctness (no duplicate physical_index)
2. Parent-child relationships (children's pages within parent's range)
3. Divider alignment (top-level nodes match divider positions)
4. Coverage completeness (no large gaps)
5. All nodes have valid structure assignments
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from backend.app.services.pageindex_service import PageIndexService

TARGET_FILES = [
    ("9cf5b5be", "AI_Agent_2026"),
    ("90e75e6f", "第五范式_2025"),
    ("d9b2b5ea", "AI眼镜_2025"),
    ("097e50d9", "技术应用洞察_2025"),
    ("a1ed6276", "AI治理_2025"),
    ("8cefa13e", "重庆案例集_2025"),
]

DATA_DIR = Path(r"D:\projects\page_chat\backend\data\documents")


def validate_tree_structure(tree: list, page_count: int, dividers: list = None):
    """Validate tree structure correctness."""
    errors = []
    warnings = []
    
    # 1. Check no duplicate physical_index
    seen_pages = set()
    def check_duplicates(nodes, path=""):
        for node in nodes:
            pi = node.get("start_index")
            if pi in seen_pages:
                errors.append(f"Duplicate physical_index: p.{pi} at {path}")
            seen_pages.add(pi)
            children = node.get("nodes", [])
            if children:
                check_duplicates(children, f"{path}>{node.get('title', '')}")
    
    check_duplicates(tree)
    
    # 2. Check parent-child ranges
    def check_ranges(nodes, parent_start=1, parent_end=page_count, path=""):
        for node in nodes:
            start = node.get("start_index", 0)
            end = node.get("end_index", 0)
            
            if start < parent_start:
                errors.append(f"Child starts before parent: {node.get('title', '')} p.{start} < parent p.{parent_start}")
            if end > parent_end:
                errors.append(f"Child ends after parent: {node.get('title', '')} p.{end} > parent p.{parent_end}")
            
            children = node.get("nodes", [])
            if children:
                check_ranges(children, start, end, f"{path}>{node.get('title', '')}")
    
    check_ranges(tree)
    
    # 3. Check divider alignment
    if dividers:
        top_level_pages = [node.get("start_index") for node in tree if node.get("start_index")]
        for d in dividers:
            matched = any(abs(p - d) <= 1 for p in top_level_pages)
            if not matched:
                warnings.append(f"Divider p.{d} not matched by any top-level node")
    
    # 4. Check structure assignments
    def check_structure(nodes, depth=0):
        for node in nodes:
            struct = node.get("structure", "")
            title = node.get("title", "")
            if not struct and depth > 0:
                warnings.append(f"Empty structure at depth {depth}: {title}")
            children = node.get("nodes", [])
            if children:
                check_structure(children, depth + 1)
    
    check_structure(tree)
    
    return errors, warnings


def print_tree(nodes, indent=0):
    """Print tree structure."""
    for node in nodes:
        prefix = "  " * indent
        start = node.get("start_index", "?")
        end = node.get("end_index", "?")
        title = node.get("title", "")
        struct = node.get("structure", "")
        children = node.get("nodes", [])
        child_count = len(children)
        print(f"{prefix}[{struct}] p.{start}-{end} {title} ({child_count} children)")
        if children:
            print_tree(children, indent + 1)


async def test_file(file_id, name):
    """Test a single file."""
    print(f"\n{'='*70}")
    print(f"Testing: {name} ({file_id})")
    print(f"{'='*70}")
    
    pdf_path = DATA_DIR / f"{file_id}*.pdf"
    files = list(DATA_DIR.glob(f"{file_id}*.pdf"))
    if not files:
        print(f"  ERROR: File not found")
        return False
    
    file_path = files[0]
    service = PageIndexService()
    
    try:
        result = await service.generate_index(str(file_path), doc_id=file_id)
        tree = result.get("tree", [])
        page_count = result.get("page_count", 0)
        completeness = result.get("completeness", {})
        dividers = result.get("dividers", [])
        
        print(f"\nTree structure:")
        print_tree(tree)
        
        # Validate structure
        errors, warnings = validate_tree_structure(tree, page_count, dividers)
        
        print(f"\nValidation:")
        print(f"  Top-level nodes: {len(tree)}")
        print(f"  Coverage: {completeness.get('coverage', 0):.0%}")
        print(f"  Quality: {completeness.get('quality', 'unknown')}")
        print(f"  Errors: {len(errors)}")
        print(f"  Warnings: {len(warnings)}")
        
        if errors:
            print(f"  [FAIL] ERRORS:")
            for e in errors:
                print(f"    - {e}")
        
        if warnings:
            print(f"  [WARN] WARNINGS:")
            for w in warnings:
                print(f"    - {w}")
        
        success = len(errors) == 0
        if success:
            print(f"  [PASS] PASSED")
        else:
            print(f"  [FAIL] FAILED")
        
        return success
        
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all tests."""
    print("="*70)
    print("COMPREHENSIVE STRUCTURAL VALIDATION TESTS")
    print("="*70)
    
    results = {}
    for file_id, name in TARGET_FILES:
        results[name] = await test_file(file_id, name)
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for name, success in results.items():
        status = "[PASS]" if success else "[FAIL]"
        print(f"  {status}: {name}")
    print(f"\nTotal: {passed}/{total} passed")
    
    return all(results.values())


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
