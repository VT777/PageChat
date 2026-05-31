import sqlite3

# Try knowclaw.db
db = sqlite3.connect('D:/projects/page_chat/backend/data/knowclaw.db')
db.row_factory = sqlite3.Row

# List tables
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("Tables:", [t['name'] for t in tables])

# Find '中机' in messages
if 'messages' in [t['name'] for t in tables]:
    rows = db.execute("""
        SELECT m.id, m.role, m.status, m.content, m.created_at, m.conversation_id
        FROM messages m
        WHERE m.content LIKE '%中机%'
        ORDER BY m.created_at DESC
    """).fetchall()
    
    print(f"\nFound {len(rows)} messages containing '中机':")
    for r in rows:
        cid = r['conversation_id'][:16] if r['conversation_id'] else 'N/A'
        mid = r['id'][:16] if r['id'] else 'N/A'
        print(f"  msg_id={mid}  role={r['role']}  status={r['status']}  conv_id={cid}")
        print(f"    content={r['content'][:200]}")

# Find recent conversations
if 'conversations' in [t['name'] for t in tables]:
    convs = db.execute("""
        SELECT id, title, created_at
        FROM conversations
        ORDER BY created_at DESC
        LIMIT 5
    """).fetchall()
    
    print(f"\nRecent conversations:")
    for c in convs:
        print(f"  id={c['id'][:16]}  title={c['title'][:40]}  created={c['created_at']}")
        
    # Count messages per conversation
    for c in convs:
        count = db.execute("SELECT COUNT(*) as cnt FROM messages WHERE conversation_id = ?", (c['id'],)).fetchone()['cnt']
        print(f"    messages: {count}")

db.close()
