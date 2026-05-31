import sqlite3
conn=sqlite3.connect('data/knowclaw.db')
cursor=conn.cursor()

tables = ['documents', 'conversations', 'messages', 'folders', 'users', 'login_attempts', 'login_logs']

for table in tables:
    print(f"\n=== {table} ===")
    cursor.execute(f"PRAGMA table_info({table})")
    for row in cursor.fetchall():
        print(f"  {row[1]} {row[2]}")

conn.close()
