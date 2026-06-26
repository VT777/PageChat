import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_service import ChatService  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema, parse_sse_frames  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402


def test_stream_chat_persists_messages_across_reopened_connections(tmp_path: Path) -> None:
    db_path = tmp_path / "stream-chat.db"

    async def run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await create_chat_history_schema(db)
            await run_migrations(db)

            service = ChatService(db)
            frames = [
                frame
                async for frame in service.stream_chat(
                    question="有哪些工具",
                    conversation_id=None,
                    user_id="user-a",
                )
            ]

        events = parse_sse_frames(frames)
        conversation_id = next(
            event["data"]["conversation_id"]
            for event in events
            if event["event"] == "run_started"
        )
        assistant_content = "".join(
            event["data"].get("content", "")
            for event in events
            if event["event"] == "answer_delta"
        )

        assert conversation_id is not None

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                """
                SELECT content, sequence, run_id, status
                FROM messages
                WHERE conversation_id = (
                    SELECT id FROM conversations ORDER BY created_at DESC LIMIT 1
                )
                ORDER BY sequence
                """
            )
            rows = await cursor.fetchall()

        assert rows[0][0] == "有哪些工具"
        assert rows[0][1] == 1
        assert rows[1][3] == "completed"
        assert "当前可用工具如下" in assistant_content

    asyncio.run(run())
