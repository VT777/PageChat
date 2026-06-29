import json

import aiosqlite


async def create_chat_history_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE documents (
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
        """
    )
    await db.execute(
        """
        CREATE TABLE conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        )
        """
    )
    await db.execute(
        """
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
            sequence INTEGER,
            run_id TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE message_citations (
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
        """
    )
    await db.execute(
        """
        CREATE TABLE folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT,
            path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT
        )
        """
    )
    await db.commit()


def sse_frame(event_type: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"


def parse_sse_frames(frames: list[str]) -> list[dict]:
    parsed = []
    for frame in frames:
        event_type = None
        payload = {}
        for line in frame.strip().splitlines():
            if line.startswith("event: "):
                event_type = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        parsed.append({"event": event_type, "data": payload})
    return parsed
