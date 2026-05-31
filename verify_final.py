import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/6de931ad.json', encoding='utf-8'))
items = d.get('structure', [])

# Find case 10 and surrounding
print("Cases around case 10:")
for i, it in enumerate(items):
    s = it.get('structure', '')
    if s in ['09', '10', '11', '12', '13']:
        print(f"  {s:4s}  start={it.get('start_index', 0):3d}  end={it.get('end_index', 0):3d}  {it['title'][:40]}")

# Check all spans
print("\nAll cases with span > 1:")
for i, it in enumerate(items):
    s = it.get('start_index', 0)
    e = it.get('end_index', 0)
    span = e - s + 1
    if span > 1:
        print(f"  {it.get('structure', '?'):4s}  span={span}  start={s}  end={e}  {it['title'][:40]}")

# Physical page distribution
print("\nPhysical page distribution (first 20 cases):")
for i, it in enumerate(items[:20]):
    print(f"  {it.get('structure', '?'):4s}  p.{it.get('start_index', 0):2d}")
