import sqlite3
import os

db_path = r'D:\projects\page_chat\backend\data\knowclaw.db.backup3'
new_db = r'D:\projects\page_chat\backend\data\knowclaw.db'

# Connect to backup
conn_src = sqlite3.connect(db_path)
conn_src.row_factory = sqlite3.Row

# Connect to new db
conn_dst = sqlite3.connect(new_db)

tables_to_recover = ['documents', 'users', 'login_logs']

for table in tables_to_recover:
    try:
        cursor = conn_src.cursor()
        cursor.execute(f'SELECT * FROM {table}')
        rows = cursor.fetchall()
        
        if rows:
            columns = [description[0] for description in cursor.description]
            placeholders = ','.join(['?' for _ in columns])
            
            conn_dst.executemany(
                f'INSERT OR REPLACE INTO {table} ({",".join(columns)}) VALUES ({placeholders})',
                rows
            )
            print(f'{table}: recovered {len(rows)} rows')
        else:
            print(f'{table}: no data')
    except Exception as e:
        print(f'{table}: failed - {e}')

conn_dst.commit()

# Verify
for table in ['conversations', 'documents', 'folders', 'users', 'messages', 'login_attempts', 'login_logs']:
    try:
        cursor = conn_dst.cursor()
        cursor.execute(f'SELECT COUNT(*) FROM {table}')
        print(f'{table}: {cursor.fetchone()[0]} rows')
    except Exception as e:
        print(f'{table}: error - {e}')

conn_src.close()
conn_dst.close()

print('\nRecovery complete!')
