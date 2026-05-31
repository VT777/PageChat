import sqlite3

# Check database connections and locks
db_path = r'D:\projects\page_chat\backend\data\knowclaw.db'

try:
    conn = sqlite3.connect(db_path, timeout=5)
    cursor = conn.cursor()
    
    # Check journal mode
    cursor.execute("PRAGMA journal_mode")
    journal_mode = cursor.fetchone()
    print(f"Journal mode: {journal_mode[0] if journal_mode else 'unknown'}")
    
    # Check WAL size
    cursor.execute("PRAGMA wal_checkpoint")
    wal_checkpoint = cursor.fetchone()
    print(f"WAL checkpoint: {wal_checkpoint}")
    
    # Check if any table has issues
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"Tables: {[t[0] for t in tables]}")
    
    # Check login_attempts table
    try:
        cursor.execute("SELECT COUNT(*) FROM login_attempts")
        count = cursor.fetchone()[0]
        print(f"login_attempts count: {count}")
    except Exception as e:
        print(f"login_attempts error: {e}")
    
    # Check login_logs table
    try:
        cursor.execute("SELECT COUNT(*) FROM login_logs")
        count = cursor.fetchone()[0]
        print(f"login_logs count: {count}")
    except Exception as e:
        print(f"login_logs error: {e}")
    
    # Check users table
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        count = cursor.fetchone()[0]
        print(f"users count: {count}")
    except Exception as e:
        print(f"users error: {e}")
    
    conn.close()
    print("\nDatabase check completed successfully")
    
except Exception as e:
    print(f"Database error: {e}")
