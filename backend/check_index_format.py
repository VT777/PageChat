import json
import os

# 读取一个索引文件查看结构
index_file = r'D:\projects\page_chat\backend\data\indexes\fea96c94.json'
with open(index_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

print('Keys:', list(data.keys()))

if 'structure' in data:
    structure = data['structure']
    print(f'\nStructure type: {type(structure)}')
    
    if isinstance(structure, list) and len(structure) > 0:
        print(f'Root nodes: {len(structure)}')
        print('\nFirst node keys:', list(structure[0].keys()))
        
        def print_tree(nodes, indent=0):
            for node in nodes:
                title = node.get('title', 'N/A')
                summary = node.get('summary', '')
                start = node.get('start_index', node.get('start_page', 'N/A'))
                end = node.get('end_index', node.get('end_page', 'N/A'))
                print('  ' * indent + f'- {title} [pages {start}-{end}]')
                if summary:
                    print('  ' * (indent + 1) + f'Summary: {summary[:100]}...')
                children = node.get('nodes', [])
                if children:
                    print_tree(children, indent + 1)
        
        print('\nTree structure:')
        print_tree(structure)

if 'route_decision' in data:
    print('\nRoute decision:', data['route_decision'])
