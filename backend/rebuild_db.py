import sqlite3
import shutil
from pathlib import Path

db_path = Path(r'D:\projects\page_chat\backend\data\knowclaw.db')
backup_path = db_path.with_suffix('.db.backup')

# Backup corrupted database
shutil.copy2(db_path, backup_path)
print(f'Backed up to: {backup_path}')

# Connect to corrupted db and export data
conn_src = sqlite3.connect(str(db_path))
conn_src.row_factory = sqlite3.Row

# Create new database
new_db_path = db_path
temp_db_path = db_path.with_suffix('.db.new')
if temp_db_path.exists():
    temp_db_path.unlink()
conn_dst = sqlite3.connect(str(temp_db_path))

# Get all tables
cursor = conn_src.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print(f'Tables to migrate: {tables}')

for table in tables:
    try:
        # Get schema
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        schema = cursor.fetchone()[0]
        
        # Create table in new db
        conn_dst.execute(schema)
        
        # Get data
        cursor.execute(f'SELECT * FROM {table}')
        rows = cursor.fetchall()
        
        if rows:
            # Get column names
            columns = [description[0] for description in cursor.description]
            placeholders = ','.join(['?' for _ in columns])
            
            # Insert data
            conn_dst.executemany(
                f'INSERT INTO {table} ({",".join(columns)}) VALUES ({placeholders})',
                rows
            )
        
        print(f'{table}: migrated {len(rows)} rows')
    except Exception as e:
        print(f'{table}: ERROR - {e}')

conn_dst.commit()
conn_src.close()
conn_dst.close()

# Replace old db with new one
shutil.move(str(temp_db_path), str(new_db_path))
print('\nDatabase rebuilt successfully!')
