import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/6de931ad.json', encoding='utf-8'))
items = d.get('structure', [])

print("All cases with '碳' or '账户' in title:")
for i, it in enumerate(items):
    title = it.get('title', '')
    if '碳' in title or '账户' in title:
        print(f"  idx={i:2d}  structure={it.get('structure', '?'):4s}  start={it.get('start_index', 0):3d}  end={it.get('end_index', 0):3d}  {title[:50]}")

print("\nAll cases (showing start/end):")
for i, it in enumerate(items):
    s = it.get('start_index', 0)
    e = it.get('end_index', 0)
    span = e - s + 1
    if span > 1:
        print(f"  WARNING: idx={i:2d}  structure={it.get('structure', '?'):4s}  span={span}  start={s}  end={e}  {it['title'][:40]}")
