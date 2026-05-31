import json

# 深入分析两份文档的索引结构
doc_ids = ['6de931ad', 'fa82c969']
names = ['2025年度重庆市人工智能应用场景典型案例集（压缩版）.pdf', '2026年快消行业AI营销增长白皮书.pdf']

for doc_id, name in zip(doc_ids, names):
    index_path = 'D:/projects/page_chat/backend/data/indexes/' + doc_id + '.json'
    print('\n========================================')
    print('Document:', name)
    print('ID:', doc_id)
    print('========================================')
    
    with open(index_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 1. Route Decision Analysis
    print('\n--- Route Decision ---')
    rd = data.get('route_decision', {})
    print('requested_mode:', rd.get('requested_mode'))
    print('execution_mode:', rd.get('execution_mode'))
    print('reasons:', rd.get('reasons', []))
    
    # 2. TOC Quality Analysis
    print('\n--- TOC Quality ---')
    tq = data.get('toc_quality', {})
    if isinstance(tq, dict):
        for k, v in tq.items():
            print(k + ':', v)
    else:
        print('toc_quality:', tq)
    
    # 3. Structure Analysis
    print('\n--- Structure Analysis ---')
    structure = data.get('structure', [])
    print('Total top-level nodes:', len(structure))
    
    stats = {'total_nodes': 0, 'max_depth': 0, 'nodes_with_children': 0, 'empty_text_nodes': 0, 'short_title_nodes': 0}
    
    def analyze_depth(nodes, depth=0):
        stats['max_depth'] = max(stats['max_depth'], depth)
        for n in nodes:
            stats['total_nodes'] += 1
            title = n.get('title', '') or ''
            text = n.get('text', '') or ''
            children = n.get('nodes', [])
            
            if children:
                stats['nodes_with_children'] += 1
            if not text or len(text) < 30:
                stats['empty_text_nodes'] += 1
            if len(title) < 5:
                stats['short_title_nodes'] += 1
            
            if children:
                analyze_depth(children, depth + 1)
    
    analyze_depth(structure)
    
    total_nodes = stats['total_nodes']
    max_depth = stats['max_depth']
    nodes_with_children = stats['nodes_with_children']
    empty_text_nodes = stats['empty_text_nodes']
    short_title_nodes = stats['short_title_nodes']
    
    print('Total nodes (all levels):', total_nodes)
    print('Max depth:', max_depth)
    print('Nodes with children:', nodes_with_children)
    print('Nodes with empty/short text (<30 chars):', empty_text_nodes)
    print('Nodes with short title (<5 chars):', short_title_nodes)
    print('Flat structure (max_depth=0):', max_depth == 0)
    
    # 4. Print all top-level node titles
    print('\n--- All Top-Level Nodes ---')
    for i, node in enumerate(structure):
        title = node.get('title', 'N/A')
        text_len = len(node.get('text', '') or '')
        child_count = len(node.get('nodes', []))
        print('  [' + str(i) + '] ' + title)
        print('      text=' + str(text_len) + ' chars, children=' + str(child_count))
    
    # 5. Completeness
    print('\n--- Completeness ---')
    comp = data.get('completeness', {})
    if isinstance(comp, dict):
        for k, v in comp.items():
            print(k + ':', v)
    else:
        print('completeness:', comp)
    
    # 6. OCR used
    print('\n--- OCR ---')
    print('ocr_used:', data.get('ocr_used', 'N/A'))

print('\n\n========================================')
print('SUMMARY')
print('========================================')
print('Both documents show:')
print('1. requested_mode=smart but execution_mode=balanced (downgraded)')
print('2. Completely FLAT structure (max_depth=0, no children)')
print('3. All nodes are top-level, no hierarchy')
print('4. This means TOC extraction failed to identify document hierarchy')
