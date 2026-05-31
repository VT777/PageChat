"""Structural validation using diagnose_all.py infrastructure."""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from backend.app.services.pageindex_service import PageIndexService
from backend.pageindex.fast_toc import try_fast_toc
from backend.pageindex.balanced_toc import (
    decide_balanced_path,
    build_balanced_toc_visual,
    build_balanced_toc_text,
    _vlm_detect_anchors,
)
from backend.pageindex.post_processing import post_process_toc, refine_toc_with_dividers
from backend.pageindex.pdf_analyzer import analyze_pdf_structure as analyze_pdf

TARGET_FILES = [
    ("9cf5b5be", "AI_Agent_2026"),
    ("90e75e6f", "第五范式_2025"),
    ("d9b2b5ea", "AI眼镜_2025"),
    ("097e50d9", "技术应用洞察_2025"),
    ("a1ed6276", "AI治理_2025"),
    ("8cefa13e", "重庆案例集_2025"),
]

DATA_DIR = Path(r"D:\projects\page_chat\backend\data\documents")
MODEL = "qwen3.6-flash"


def validate_structure(tree, page_count, dividers=None, name=""):
    """Validate tree structure and return errors/warnings."""
    errors = []
    warnings = []
    
    # 1. Collect all nodes
    all_nodes = []
    def collect(nodes, depth=0):
        for node in nodes:
            all_nodes.append((node, depth))
            collect(node.get("nodes", []), depth + 1)
    collect(tree)
    
    # 2. Check for duplicate start_index
    seen = set()
    for node, depth in all_nodes:
        start = node.get("start_index")
        if start in seen:
            errors.append(f"Duplicate start_index: p.{start} in {node.get('title', '')}")
        seen.add(start)
    
    # 3. Check parent-child ranges
    def check_ranges(nodes, parent_start=1, parent_end=page_count):
        for node in nodes:
            start = node.get("start_index", 0)
            end = node.get("end_index", 0)
            if start < parent_start:
                errors.append(f"Child p.{start} < parent p.{parent_start}: {node.get('title', '')}")
            if end > parent_end:
                errors.append(f"Child p.{end} > parent p.{parent_end}: {node.get('title', '')}")
            check_ranges(node.get("nodes", []), start, end)
    check_ranges(tree)
    
    # 4. Check divider alignment
    if dividers:
        top_starts = [node.get("start_index") for node in tree]
        for d in dividers:
            matched = any(abs(s - d) <= 1 for s in top_starts if s)
            if not matched:
                warnings.append(f"Divider p.{d} not matched by top-level node")
    
    # 5. Check coverage
    covered = set()
    for node, depth in all_nodes:
        start = node.get("start_index", 0)
        end = node.get("end_index", 0)
        for p in range(start, end + 1):
            covered.add(p)
    
    coverage = len(covered) / page_count if page_count else 0
    if coverage < 0.95:
        errors.append(f"Coverage too low: {coverage:.1%}")
    
    # 6. Check for nodes without children that should have them
    for node, depth in all_nodes:
        children = node.get("nodes", [])
        span = node.get("end_index", 0) - node.get("start_index", 0) + 1
        if span > 10 and not children:
            warnings.append(f"Large node without children: {node.get('title', '')} ({span} pages)")
    
    return errors, warnings, coverage


def print_tree(nodes, indent=0):
    for node in nodes:
        prefix = "  " * indent
        start = node.get("start_index", "?")
        end = node.get("end_index", "?")
        title = node.get("title", "")[:40]
        struct = node.get("structure", "")
        children = len(node.get("nodes", []))
        try:
            print(f"{prefix}[{struct}] p.{start}-{end} {title} ({children} children)")
        except UnicodeEncodeError:
            print(f"{prefix}[{struct}] p.{start}-{end} <unicode> ({children} children)")
        if node.get("nodes"):
            print_tree(node["nodes"], indent + 1)


async def test_file(file_id, name):
    print(f"\n{'='*70}")
    print(f"Testing: {name} ({file_id})")
    print(f"{'='*70}")
    
    files = list(DATA_DIR.glob(f"{file_id}*.pdf"))
    if not files:
        print(f"  [ERROR] File not found")
        return False
    
    file_path = files[0]
    
    # Analyze PDF
    analysis = analyze_pdf(str(file_path))
    page_count = analysis["page_count"]
    print(f"  Pages: {page_count}, text_coverage: {analysis['text_coverage']:.2f}")
    
    # Detect anchors
    anchors = await _vlm_detect_anchors(str(file_path), MODEL)
    dividers = anchors.get("chapter_dividers", [])
    toc_pages = anchors.get("toc_pages", [])
    first_content = anchors.get("first_content_page", 1)
    print(f"  Anchors: toc={toc_pages}, dividers={dividers}, first_content={first_content}")
    
    # Build TOC
    balanced_path = decide_balanced_path(analysis)
    print(f"  Path: {balanced_path}")
    
    if balanced_path == "visual":
        result = await build_balanced_toc_visual(str(file_path), analysis, model=MODEL, anchors=anchors)
    else:
        result = await build_balanced_toc_text(analysis, model=MODEL, dividers=dividers)
    
    toc_items = result.get("toc_items", [])
    print(f"  TOC items: {len(toc_items)}")
    
    # Post-process with dividers
    tree, completeness = post_process_toc(toc_items, page_count, dividers=dividers)
    
    print(f"\n  Tree structure:")
    print_tree(tree)
    
    # Validate
    errors, warnings, coverage = validate_structure(tree, page_count, dividers, name)
    
    print(f"\n  Validation:")
    print(f"    Top-level: {len(tree)}")
    print(f"    Coverage: {coverage:.0%}")
    print(f"    Quality: {completeness.get('quality', 'unknown')}")
    print(f"    Errors: {len(errors)}")
    print(f"    Warnings: {len(warnings)}")
    
    if errors:
        print(f"    [FAIL] ERRORS:")
        for e in errors:
            print(f"      - {e}")
    if warnings:
        print(f"    [WARN] WARNINGS:")
        for w in warnings:
            print(f"      - {w}")
    
    success = len(errors) == 0
    if success:
        print(f"    [PASS] PASSED")
    else:
        print(f"    [FAIL] FAILED")
    
    return success


async def main():
    print("="*70)
    print("STRUCTURAL VALIDATION TESTS")
    print("="*70)
    
    results = {}
    for file_id, name in TARGET_FILES:
        try:
            results[name] = await test_file(file_id, name)
        except Exception as e:
            print(f"  [ERROR] {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
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
