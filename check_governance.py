import sqlite3
db = sqlite3.connect('D:/projects/page_chat/backend/data/knowclaw.db')
cursor = db.cursor()
cursor.execute("SELECT id, original_name, status, error_message FROM documents WHERE original_name LIKE '%治理%'")
for row in cursor.fetchall():
    print(f'ID: {row[0]}')
    print(f'Name: {row[1]}')
    print(f'Status: {row[2]}')
    print(f'Error: {row[3]}')
    print()
db.close()
