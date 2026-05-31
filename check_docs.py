import sys, sqlite3
sys.path.insert(0, 'D:/projects/page_chat/backend')

conn = sqlite3.connect('D:/projects/page_chat/backend/data/knowclaw.db')
conn.row_factory = sqlite3.Row
cursor = conn.execute(
    "SELECT id, original_name, status, page_count, index_path FROM documents WHERE original_name LIKE '%快消%' OR original_name LIKE '%重庆%'"
)
for row in cursor.fetchall():
    print('ID:', row['id'])
    print('Name:', row['original_name'])
    print('Status:', row['status'])
    print('Pages:', row['page_count'])
    print('Index:', row['index_path'])
    print('---')
conn.close()
