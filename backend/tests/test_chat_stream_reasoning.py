import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema, parse_sse_frames, sse_frame  # noqa: E402


def test_chat_service_persists_native_reasoning_without_processing_as_thinking() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_chat_history_schema(db)
            await run_migrations(db)

            class FakeAgent:
                async def run_agent_stream(self, **_kwargs):
                    yield sse_frame("reasoning_delta", {"content": "Inspect evidence."})
                    yield sse_frame("processing_delta", {"content": "Backend status."})
                    yield sse_frame("answer_delta", {"content": "Final answer."})

            service = ChatService(db)
            service.agent_service = FakeAgent()

            frames = [
                frame
                async for frame in service.stream_chat(
                    question="hello",
                    user_id="user-a",
                )
            ]

            cursor = await db.execute(
                """
                SELECT thinking_content, content
                FROM messages
                WHERE role = 'assistant'
                ORDER BY sequence DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()

        events = parse_sse_frames(frames)
        assert [event["event"] for event in events] == [
            "run_started",
            "reasoning_delta",
            "processing_delta",
            "answer_delta",
            "run_completed",
        ]
        assert row["thinking_content"] == "Inspect evidence."
        assert row["content"] == "Final answer."

    asyncio.run(run())
