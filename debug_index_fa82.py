import json

d = json.load(open('D:/projects/page_chat/backend/data/indexes/fa82c969.json', encoding='utf-8'))
items = d.get('structure', [])
print(f"Top-level nodes: {len(items)}, Page count: {d.get('page_count')}")

def show_node(node, indent=0):
    s = node.get('start_index', 0)
    e = node.get('end_index', 0)
    st = node.get('structure', '?')
    title = node.get('title', '')[:55]
    children = len(node.get('nodes', []))
    prefix = '  ' * indent
    print(f"{prefix}[{st}] p.{s}-{e} ({e-s+1}p)  {title}")
    for sub in node.get('nodes', []):
        show_node(sub, indent + 1)

for node in items:
    show_node(node)

# Also check: are all top-level items in the expected range?
print("\n=== Physical index analysis ===")
for i, it in enumerate(items):
    pi = it.get('physical_index', 0)
    st = it.get('structure', '?')
    title = it.get('title', '')[:30]
    print(f"  item {i}: structure={st}  pi={pi}  {title}")

# Check: how many total items?
all_nodes = items.copy()
for it in items:
    all_nodes.extend(it.get('nodes', []))
print(f"\nTotal items: {len(all_nodes)}")
