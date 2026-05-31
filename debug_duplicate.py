import sqlite3
db = sqlite3.connect('D:/projects/page_chat/backend/data/app.db')
db.row_factory = sqlite3.Row

# Find all messages with '中机' content
rows = db.execute("""
    SELECT m.id, m.role, m.status, m.content, m.created_at, m.conversation_id
    FROM messages m
    WHERE m.content LIKE '%中机%'
    ORDER BY m.created_at DESC
""").fetchall()

print(f"Found {len(rows)} messages containing '中机':")
for r in rows:
    print(f"  msg_id={r['id'][:16]}  role={r['role']}  status={r['status']}  conv_id={r['conversation_id'][:16]}")
    print(f"    content={r['content'][:100]}")

# Also check conversations
print("\nRecent conversations:")
convs = db.execute("""
    SELECT c.id, c.title, c.created_at,
           (SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) as msg_count
    FROM conversations c
    ORDER BY c.created_at DESC
    LIMIT 5
""").fetchall()

for c in convs:
    print(f"  conv_id={c['id'][:16]}  title={c['title'][:30]}  msgs={c['msg_count']}  created={c['created_at']}")

db.close()
