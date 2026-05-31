import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/6de931ad.json', encoding='utf-8'))
items = d.get('structure', [])
print('Top-level nodes:', len(items))
print('\nFirst 10 items:')
for it in items[:10]:
    print(f"  {it.get('structure', '?'):4s}  start={it['start_index']:3d}  end={it['end_index']:3d}")
print('\nLast 10 items:')
for it in items[-10:]:
    print(f"  {it.get('structure', '?'):4s}  start={it['start_index']:3d}  end={it['end_index']:3d}")
print('\nRoute decision:', json.dumps(d.get('route_decision', {}), ensure_ascii=False))
