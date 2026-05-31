import sqlite3
import os
import shutil

# Create a completely fresh database
old_db = r'D:\projects\page_chat\backend\data\knowclaw.db'
backup_db = r'D:\projects\page_chat\backend\data\knowclaw.db.backup3'
new_db = r'D:\projects\page_chat\backend\data\knowclaw.db.new'

# Backup
shutil.copy2(old_db, backup_db)
print(f'Backed up to: {backup_db}')

# Connect to corrupted db
conn_src = sqlite3.connect(old_db)
conn_src.row_factory = sqlite3.Row

# Create new database
if os.path.exists(new_db):
    os.remove(new_db)
conn_dst = sqlite3.connect(new_db)

# Get all tables except sqlite_sequence
cursor = conn_src.cursor()
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")
tables = cursor.fetchall()

for table_name, schema in tables:
    try:
        # Create table
        conn_dst.execute(schema)
        
        # Try to get data from corrupted db
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
                print(f'{table_name}: migrated {len(rows)} rows')
            else:
                print(f'{table_name}: empty')
        except Exception as e:
            print(f'{table_name}: data export failed - {e}')
    except Exception as e:
        print(f'{table_name}: schema creation failed - {e}')

conn_dst.commit()
conn_src.close()
conn_dst.close()

# Verify new database
conn_verify = sqlite3.connect(new_db)
cursor = conn_verify.cursor()
cursor.execute('PRAGMA integrity_check')
result = cursor.fetchone()
print(f'\nNew DB Integrity check: {result[0]}')
conn_verify.close()

# Replace old with new
os.replace(new_db, old_db)
print('Database replaced successfully!')
