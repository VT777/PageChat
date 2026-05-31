import sqlite3
import os

conn = sqlite3.connect(r'D:\projects\page_chat\backend\data\knowclaw.db')
cursor = conn.cursor()

# 检查 index_path 分布
cursor.execute("SELECT index_path, COUNT(*) FROM documents WHERE index_path IS NOT NULL GROUP BY SUBSTR(index_path, 1, 2)")
print('Index path prefixes:')
for row in cursor.fetchall():
    print(f'  {row[0][:20]}... : {row[1]} docs')

# 检查 data/indexes 目录是否存在
print(f'\nCurrent project indexes dir exists: {os.path.exists(r"D:\projects\page_chat\backend\data\indexes")}')

# 检查 E 盘路径
print(f'E drive path exists: {os.path.exists(r"E:\projects\knowclaw_v2_mvp_refactor\backend\data\indexes")}')

# 统计
conn.close()
