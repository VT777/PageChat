import sqlite3

db_path = r'D:\projects\page_chat\backend\data\knowclaw.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check login_attempts table schema
cursor.execute("PRAGMA table_info(login_attempts)")
print("login_attempts schema:")
for row in cursor.fetchall():
    print(f"  {row[1]} {row[2]}")

# Check login_attempts data
cursor.execute("SELECT * FROM login_attempts LIMIT 5")
print("\nlogin_attempts data:")
for row in cursor.fetchall():
    print(f"  {row}")

# Check login_logs table schema
cursor.execute("PRAGMA table_info(login_logs)")
print("\nlogin_logs schema:")
for row in cursor.fetchall():
    print(f"  {row[1]} {row[2]}")

conn.close()
