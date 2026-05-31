import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/fa82c969.json', encoding='utf-8'))
items = d.get('structure', [])
print('Top-level:', len(items), '  Page count:', d.get('page_count'))
print('Route:', json.dumps(d.get('route_decision', {}), ensure_ascii=False, indent=2))
print()

for it in items:
    s = it.get('start_index', 0)
    e = it.get('end_index', 0)
    nc = len(it.get('nodes', []))
    st = str(it.get('structure', '?'))
    title = it.get('title', '')[:60]
    print(f'  {st:8s}  start={s:3d}  end={e:3d}  children={nc}  {title}')

    # Show sub-nodes if any
    for sub in it.get('nodes', []):
        ss = sub.get('start_index', 0)
        se = sub.get('end_index', 0)
        sst = str(sub.get('structure', '?'))
        stitle = sub.get('title', '')[:50]
        print(f'    {sst:8s}  start={ss:3d}  end={se:3d}  {stitle}')

# Also show the raw index text to trace VLM output
print('\n=== First node raw text (first 1000 chars) ===')
if items:
    print(items[0].get('text', '')[:1000])
