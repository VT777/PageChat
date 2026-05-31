import sqlite3
import os

conn = sqlite3.connect(r'D:\projects\page_chat\backend\data\knowclaw.db')
cursor = conn.cursor()

# 修复 file_path
cursor.execute("""
    UPDATE documents 
    SET file_path = REPLACE(file_path, 'E:\\projects\\knowclaw_v2_mvp_refactor', 'D:\\projects\\page_chat')
    WHERE file_path LIKE 'E:\\projects\\knowclaw_v2_mvp_refactor%'
""")
conn.commit()
print(f'Updated {cursor.rowcount} file paths')

# 验证
cursor.execute("SELECT id, original_name, file_path FROM documents LIMIT 5")
for row in cursor.fetchall():
    print(f'  {row[0]}: exists={os.path.exists(row[2])} - {row[2][:60]}...')

conn.close()
