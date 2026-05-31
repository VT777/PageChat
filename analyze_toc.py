import json

# 检查两份文档的索引结构
doc_ids = ['6de931ad', 'fa82c969']

for doc_id in doc_ids:
    index_path = 'D:/projects/page_chat/backend/data/indexes/' + doc_id + '.json'
    print('\n=== Document: ' + doc_id + ' ===')
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print('Top-level keys:', list(data.keys()))
        
        if 'route_decision' in data:
            rd = data['route_decision']
            print('Route decision: mode=' + str(rd.get('execution_mode')) + ', requested=' + str(rd.get('requested_mode')))
        
        if 'structure' in data and isinstance(data['structure'], list):
            print('Top-level nodes:', len(data['structure']))
            
            def analyze_nodes(nodes, depth=0):
                stats = {'total': 0, 'empty_title': 0, 'no_text': 0, 'short_text': 0, 'deep_levels': 0}
                for n in nodes:
                    stats['total'] += 1
                    title = n.get('title', '')
                    if not title or title == '':
                        stats['empty_title'] += 1
                    text = n.get('text', '') or ''
                    if not text:
                        stats['no_text'] += 1
                    elif len(text) < 50:
                        stats['short_text'] += 1
                    if depth > 2:
                        stats['deep_levels'] += 1
                    if n.get('nodes'):
                        child_stats = analyze_nodes(n['nodes'], depth+1)
                        for k in stats:
                            stats[k] += child_stats[k]
                return stats
            
            stats = analyze_nodes(data['structure'])
            print('Node stats:', stats)
            
            # 打印前5个节点的标题
            print('First 5 nodes:')
            for i, node in enumerate(data['structure'][:5]):
                title = node.get('title', 'N/A')
                text_len = len(node.get('text', '') or '')
                child_count = len(node.get('nodes', []))
                print('  [' + str(i) + '] ' + title + ' (text=' + str(text_len) + ' chars, children=' + str(child_count) + ')')
        
        if 'toc_quality' in data:
            print('TOC quality keys:', list(data['toc_quality'].keys()) if isinstance(data['toc_quality'], dict) else data['toc_quality'])
        
        if 'pre_analysis' in data:
            pa = data['pre_analysis']
            if isinstance(pa, dict):
                print('Pre-analysis keys:', list(pa.keys()))
        
    except Exception as e:
        print('Error:', e)
