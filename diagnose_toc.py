import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

# 读取两份文档的索引并分析 TOC 结构
doc_ids = ['6de931ad', 'fa82c969']
names = ['重庆案例集', '快消白皮书']

for doc_id, name in zip(doc_ids, names):
    index_path = 'D:/projects/page_chat/backend/data/indexes/' + doc_id + '.json'
    print('\n========================================')
    print('文档:', name, '(', doc_id, ')')
    print('========================================')
    
    with open(index_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 1. 分析 route_decision
    rd = data.get('route_decision', {})
    print('\n--- 路由决策 ---')
    print('requested_mode:', rd.get('requested_mode'))
    print('execution_mode:', rd.get('execution_mode'))
    print('balanced_path:', rd.get('balanced_path'))
    print('toc_source:', rd.get('toc_source'))
    print('is_image_only_pdf:', rd.get('is_image_only_pdf'))
    
    # 2. 分析 pre_analysis
    pa = data.get('pre_analysis', {})
    if isinstance(pa, dict):
        print('\n--- 预分析 ---')
        print('text_coverage:', pa.get('text_coverage'))
        print('image_pages:', pa.get('image_pages'))
        print('preferred_parser:', pa.get('preferred_parser'))
        print('has_toc:', pa.get('has_toc'))
        print('toc_pages:', pa.get('toc_pages'))
    
    # 3. 分析目录结构
    structure = data.get('structure', [])
    print('\n--- 目录结构 ---')
    print('顶层节点数:', len(structure))
    
    # 检查是否有层级
    has_hierarchy = False
    for node in structure:
        if node.get('nodes'):
            has_hierarchy = True
            break
    print('有层级结构:', has_hierarchy)
    
    # 打印所有标题
    print('\n所有节点标题:')
    for i, node in enumerate(structure):
        title = node.get('title', 'N/A')
        start = node.get('start_index', 'N/A')
        end = node.get('end_index', 'N/A')
        text_len = len(node.get('text', '') or '')
        print('  [' + str(i) + '] 页' + str(start) + '-' + str(end) + ': ' + title)
        print('      文本长度:', text_len)

print('\n\n========================================')
print('诊断结论')
print('========================================')
