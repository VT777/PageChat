import sqlite3
import os
import shutil

# Use the backup that has most data
db_path = r'D:\projects\page_chat\backend\data\knowclaw.db.backup3'
new_db = r'D:\projects\page_chat\backend\data\knowclaw.db'

# Create fresh database
if os.path.exists(new_db):
    os.remove(new_db)

# Connect to corrupted backup
conn_src = sqlite3.connect(db_path)
conn_src.row_factory = sqlite3.Row

# Create new database  
conn_dst = sqlite3.connect(new_db)

# Get schemas
cursor = conn_src.cursor()
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")
tables = cursor.fetchall()

# Create all tables in new db
for table_name, schema in tables:
    try:
        conn_dst.execute(schema)
        print(f'Created table: {table_name}')
    except Exception as e:
        print(f'Failed to create {table_name}: {e}')

conn_dst.commit()

# Now try to copy data table by table
for table_name, _ in tables:
    try:
        cursor.execute(f'SELECT * FROM {table_name}')
        rows = cursor.fetchall()
        
        if rows:
            columns = [description[0] for description in cursor.description]
            placeholders = ','.join(['?' for _ in columns])
            
            conn_dst.executemany(
                f'INSERT INTO {table_name} ({",".join(columns)}) VALUES ({placeholders})',
                rows
            )
            print(f'{table_name}: copied {len(rows)} rows')
        else:
            print(f'{table_name}: empty')
    except Exception as e:
        print(f'{table_name}: copy failed - {e}')

conn_dst.commit()

# Verify integrity
cursor_dst = conn_dst.cursor()
cursor_dst.execute('PRAGMA integrity_check')
result = cursor_dst.fetchone()
print(f'\nIntegrity check: {result[0]}')

conn_src.close()
conn_dst.close()

print('\nDatabase rebuild complete!')
