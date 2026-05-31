import sqlite3

db_path = r'D:\projects\page_chat\backend\data\knowclaw.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check login_logs table schema
cursor.execute("PRAGMA table_info(login_logs)")
print("login_logs schema:")
for row in cursor.fetchall():
    print(f"  {row}")

# Check if there are any records
cursor.execute("SELECT * FROM login_logs ORDER BY id DESC LIMIT 3")
print("\nRecent login_logs:")
for row in cursor.fetchall():
    print(f"  {row}")

conn.close()
