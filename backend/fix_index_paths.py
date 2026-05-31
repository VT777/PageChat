import sqlite3
import os

conn = sqlite3.connect(r'D:\projects\page_chat\backend\data\knowclaw.db')
cursor = conn.cursor()

# 修复 index_path
cursor.execute("""
    UPDATE documents 
    SET index_path = REPLACE(index_path, 'E:\\projects\\knowclaw_v2_mvp_refactor', 'D:\\projects\\page_chat')
    WHERE index_path LIKE 'E:\\projects\\knowclaw_v2_mvp_refactor%'
""")
conn.commit()
print(f'Updated {cursor.rowcount} documents')

# 验证
cursor.execute("SELECT id, original_name, index_path FROM documents WHERE index_path IS NOT NULL LIMIT 3")
for row in cursor.fetchall():
    print(f'  {row[0]}: exists={os.path.exists(row[2])} - {row[2][:60]}...')

conn.close()
