import aiosqlite
from pathlib import Path
from app.core.config import DATA_DIR
from app.models.migrations import run_migrations

DB_PATH = DATA_DIR / "knowclaw.db"

async def get_db():
    """获取数据库连接（FastAPI 依赖）"""
    db = await aiosqlite.connect(str(DB_PATH))
    await db.execute("PRAGMA foreign_keys=ON")
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()

async def init_db():
    """初始化数据库，创建所有表"""
    async with aiosqlite.connect(str(DB_PATH)) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        # 文档表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                original_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                index_path TEXT,
                file_size INTEGER,
                file_type TEXT,
                status TEXT DEFAULT 'uploaded',
                page_count INTEGER,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_pages INTEGER DEFAULT 0,
                folder_id TEXT,
                folder_path TEXT,
                description TEXT,
                user_id TEXT
            )
        """)

        # 会话表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT
            )
        """)

        # 消息表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
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
                sequence INTEGER,
                run_id TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_message_id TEXT NOT NULL,
                assistant_message_id TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_id TEXT,
                model TEXT,
                protocol TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                error TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                FOREIGN KEY (user_message_id) REFERENCES messages(id),
                FOREIGN KEY (assistant_message_id) REFERENCES messages(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS agent_run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_id, seq),
                FOREIGN KEY (run_id) REFERENCES agent_runs(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS message_citations (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                citation_key TEXT NOT NULL,
                document_id TEXT,
                document_name TEXT NOT NULL,
                source_anchor_json TEXT NOT NULL,
                display_label TEXT NOT NULL,
                preview_kind TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (message_id) REFERENCES messages(id)
            )
        """)

        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_conversation_sequence
            ON messages(conversation_id, sequence)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_started
            ON agent_runs(conversation_id, started_at)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_run_events_run_seq
            ON agent_run_events(run_id, seq)
        """)

        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_citations_message
            ON message_citations(message_id)
        """)

        # 文件夹表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS folders (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                parent_id TEXT,
                path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT
            )
        """)

        # 用户表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                avatar TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 登录尝试表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                email TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                locked_until TIMESTAMP,
                last_attempt TIMESTAMP
            )
        """)

        # 登录日志表
        await db.execute("""
            CREATE TABLE IF NOT EXISTS login_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                email TEXT,
                ip_address TEXT,
                user_agent TEXT,
                success BOOLEAN DEFAULT 0,
                fail_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()
        await run_migrations(db)
