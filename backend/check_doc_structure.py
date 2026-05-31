import sqlite3
import os
import json

conn = sqlite3.connect(r'D:\projects\page_chat\backend\data\knowclaw.db')
cursor = conn.cursor()

# 查看文档数据
cursor.execute("SELECT id, original_name, file_type, status, page_count, index_path, description FROM documents WHERE status='completed' LIMIT 1")
doc = cursor.fetchone()
if doc:
    print(f'Doc: {doc[0]} - {doc[1]}')
    print(f'Index path: {doc[5]}')
    
    # 检查索引文件是否存在
    if doc[5] and os.path.exists(doc[5]):
        print(f'Index file exists: {os.path.getsize(doc[5])} bytes')
        with open(doc[5], 'r', encoding='utf-8') as f:
            data = json.load(f)
            print(f'Keys: {list(data.keys())}')
            if 'structure' in data:
                print(f'Structure type: {type(data["structure"])}')
                if isinstance(data['structure'], list):
                    print(f'  Nodes: {len(data["structure"])}')
                elif isinstance(data['structure'], dict):
                    print(f'  Structure keys: {list(data["structure"].keys())}')
    else:
        print('Index file NOT exists')
conn.close()
