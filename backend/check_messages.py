import sqlite3

db_path = r'D:\projects\page_chat\backend\data\knowclaw.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if messages table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
if cursor.fetchone():
    print('messages table exists')
    cursor.execute('SELECT COUNT(*) FROM messages')
    print(f'messages count: {cursor.fetchone()[0]}')
else:
    print('messages table missing - creating...')
    cursor.execute('''
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            sources TEXT,
            agent_steps TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            thinking_content TEXT,
            status TEXT DEFAULT 'completed',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    ''')
    conn.commit()
    print('messages table created')

# Verify integrity
cursor.execute('PRAGMA integrity_check')
result = cursor.fetchone()
print(f'Integrity check: {result[0]}')

conn.close()
