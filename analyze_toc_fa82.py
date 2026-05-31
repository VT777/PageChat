import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/fa82c969.json', encoding='utf-8'))
items = d.get('structure', [])
print('Top-level nodes:', len(items))
print('Page count:', d.get('page_count', '?'))
print('Route:', json.dumps(d.get('route_decision', {}), ensure_ascii=False, indent=2))
print()

for it in items:
    s = it.get('start_index', 0)
    e = it.get('end_index', 0)
    title = it.get('title', '')[:60]
    nodes = len(it.get('nodes', []))
    struct = it.get('structure', '?')
    print(f'  {struct:6s}  start={s:3d}  end={e:3d}  children={nodes}  {title}')

# Also check the index text to see the original TOC
if items:
    first = items[0]
    text = first.get('text', '')
    print('\n=== First node text (first 2000 chars) ===')
    print(text[:2000])
