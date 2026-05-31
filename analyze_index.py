import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/6de931ad.json', encoding='utf-8'))
items = d.get('structure', [])

print('=== 前20个条目 ===')
for it in items[:20]:
    print(f"  {it.get('structure', '?'):4s}  start={it['start_index']:3d}  end={it['end_index']:3d}  {it['title'][:30]}")

print('\n=== 后10个条目 ===')
for it in items[-10:]:
    print(f"  {it.get('structure', '?'):4s}  start={it['start_index']:3d}  end={it['end_index']:3d}  {it['title'][:30]}")

# 分析物理页码分布
starts = [it['start_index'] for it in items if it.get('start_index')]
print(f"\n物理页码范围: {min(starts)} - {max(starts)}")
print(f"PDF总页数: {d.get('page_count', '?')}")
print(f"超出范围的条目: {sum(1 for s in starts if s > 44)}")

# 统计每个physical_index出现次数
from collections import Counter
counts = Counter(starts)
dupes = {k: v for k, v in counts.items() if v > 1}
print(f"\n重复的物理页码: {len(dupes)} 个")
print(f"重复最多的页码: {counts.most_common(5)}")

# 分析目录原始页码
# 从 route_decision 看 offset
toc_items = d.get('structure', [])
# Preface 是自动添加的，从第二个开始是实际目录
real_items = [it for it in toc_items if it.get('structure') != '0']
print(f"\n实际目录条目数: {len(real_items)}")
print(f"目录条目 logical pages (从title提取): ...")

# 分析 route_decision
rd = d.get('route_decision', {})
print(f"\nRoute: {rd}")
