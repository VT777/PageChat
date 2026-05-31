import sqlite3
import sys

db_path = "D:/projects/page_chat/backend/data/knowclaw.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 查找 AI 治理报告
cursor.execute("SELECT id, original_name, status, index_path, error_message FROM documents WHERE original_name LIKE '%AI治理%'")
rows = cursor.fetchall()

print("AI Governance Report Status:")
for row in rows:
    print(f"  ID: {row[0]}")
    print(f"  Name: {row[1]}")
    print(f"  Status: {row[2]}")
    print(f"  Index Path: {row[3]}")
    print(f"  Error: {row[4]}")
    print()

# 检查最近上传的文档状态
cursor.execute("SELECT id, original_name, status, created_at FROM documents ORDER BY created_at DESC LIMIT 10")
rows = cursor.fetchall()

print("\nRecent Documents:")
for row in rows:
    print(f"  {row[0][:8]}... | {row[1][:40]:40} | {row[2]:20} | {row[3]}")

conn.close()
