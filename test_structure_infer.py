import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")
from pageindex.balanced_toc import _infer_structure_from_numbers

# Test 1: Dot numbering (快消白皮书 style)
print("=== Test 1: Dot numbering ===")
items1 = [
    {"number": "1", "title": "市场概述"},
    {"number": "1.1", "title": "消费趋势"},
    {"number": "1.2", "title": "增长瓶颈"},
    {"number": "1.3", "title": "新机遇"},
    {"number": "2", "title": "AI重构定位"},
    {"number": "2.1", "title": "占位策略"},
    {"number": "2.2", "title": "投放实践"},
    {"number": "", "title": "结语"},
]
_infer_structure_from_numbers(items1)
for it in items1:
    print(f"  {it['number']:6s} → structure={it['structure']:6s}  {it['title']}")

# Test 2: Chinese numbering
print("\n=== Test 2: Chinese numbering ===")
items2 = [
    {"number": "一", "title": "概述"},
    {"number": "（一）", "title": "背景"},
    {"number": "（二）", "title": "方法论"},
    {"number": "二", "title": "实践"},
    {"number": "1", "title": "案例一"},
    {"number": "2", "title": "案例二"},
]
_infer_structure_from_numbers(items2)
for it in items2:
    print(f"  {it['number']:6s} → structure={it['structure']:6s}  {it['title']}")

# Test 3: All empty (重庆案例集 style)
print("\n=== Test 3: All empty (flat) ===")
items3 = [
    {"number": "", "title": "案例一"},
    {"number": "", "title": "案例二"},
    {"number": "", "title": "案例三"},
]
_infer_structure_from_numbers(items3)
for it in items3:
    print(f"  {it['number']:6s} → structure={it['structure']:6s}  {it['title']}")

# Test 4: Mixed
print("\n=== Test 4: Mixed ===")
items4 = [
    {"number": "第一章", "title": "背景"},
    {"number": "1.1", "title": "市场分析"},
    {"number": "", "title": "小结"},
    {"number": "第二章", "title": "方案"},
]
_infer_structure_from_numbers(items4)
for it in items4:
    print(f"  {it['number']:6s} → structure={it['structure']:6s}  {it['title']}")

print("\nAll tests passed!")
