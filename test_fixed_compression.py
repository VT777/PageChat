import sys
sys.path.insert(0, "D:\\projects\\page_chat\\backend")

from pageindex.balanced_toc import _map_toc_physical_pages

# 模拟重庆案例集的 TOC 条目
toc_items = []
for i in range(41):
    logical = 1 + i * 2  # 1, 3, 5, ..., 81
    toc_items.append({
        "structure": f"{i+1:02d}",
        "title": f"案例{i+1}",
        "page": logical,
    })

# 测试 fixed compression 检测
_map_toc_physical_pages(
    toc_items,
    page_count=44,
    first_content_page=3,
    last_toc_page=2,
    ocr_text_map=None,
)

print("Fixed compression test (41 cases, step=2):")
print(f"case 01 (logical=1):  physical={toc_items[0]['physical_index']}")
print(f"case 02 (logical=3):  physical={toc_items[1]['physical_index']}")
print(f"case 10 (logical=19): physical={toc_items[9]['physical_index']}")
print(f"case 11 (logical=21): physical={toc_items[10]['physical_index']}")
print(f"case 41 (logical=81): physical={toc_items[40]['physical_index']}")

# 检查是否有重复或跳过
dupes = [it['physical_index'] for it in toc_items]
print(f"\nAll physical indices: {dupes[:15]}...")
print(f"Unique count: {len(set(dupes))}")

# 测试非固定压缩（差值不同）
print("\n\nNon-fixed compression test:")
toc_items2 = [
    {"structure": "1", "title": "A", "page": 1},
    {"structure": "2", "title": "B", "page": 5},   # diff=4
    {"structure": "3", "title": "C", "page": 10},  # diff=5
    {"structure": "4", "title": "D", "page": 20},  # diff=10
]
_map_toc_physical_pages(
    toc_items2,
    page_count=10,
    first_content_page=2,
    last_toc_page=1,
    ocr_text_map=None,
)
print(f"case 1 (logical=1): physical={toc_items2[0]['physical_index']}")
print(f"case 2 (logical=5): physical={toc_items2[1]['physical_index']}")
print(f"case 3 (logical=10): physical={toc_items2[2]['physical_index']}")
print(f"case 4 (logical=20): physical={toc_items2[3]['physical_index']}")
