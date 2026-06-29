import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.migrations import run_migrations  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from app.services.model_settings_service import ModelSettingsService  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema, sse_frame  # noqa: E402


async def _open_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_chat_history_schema(db)
    await run_migrations(db)
    return db


def test_resolved_route_includes_provider_id_for_auditing() -> None:
    async def run() -> None:
        db = await _open_db()
        try:
            service = ModelSettingsService(db)
            provider = await service.save_provider_config(
                user_id="user-route",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-123456",
            )
            await service.save_route_mapping(
                user_id="user-route",
                route_slot="document_qa",
                provider_id=provider["provider_id"],
                model="audited-model",
            )

            resolved = await service.resolve_route("user-route", "document_qa")

            assert resolved["provider_id"] == provider["provider_id"]
            assert resolved["provider"] == "openai_compatible"
            assert resolved["model"] == "audited-model"
            assert resolved["source"] == "user"
            assert "api_key" in resolved
        finally:
            await db.close()

    asyncio.run(run())


def test_chat_run_records_selected_document_qa_route() -> None:
    async def run() -> None:
        db = await _open_db()
        try:
            settings = ModelSettingsService(db)
            provider = await settings.save_provider_config(
                user_id="user-chat",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret-abcdef",
            )
            await settings.save_route_mapping(
                user_id="user-chat",
                route_slot="document_qa",
                provider_id=provider["provider_id"],
                model="qa-audited-model",
            )

            service = ChatService(db)

            class FakeAgent:
                async def run_agent_stream(self, **kwargs):
                    yield sse_frame("answer_delta", {"content": "hello"})
                    yield sse_frame("run_completed", {"status": "completed"})

            service.agent_service = FakeAgent()

            async for _frame in service.stream_chat(
                question="hello",
                user_id="user-chat",
            ):
                pass

            cursor = await db.execute(
                """
                SELECT provider_id, model, protocol
                FROM agent_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()

            assert row["provider_id"] == provider["provider_id"]
            assert row["model"] == "qa-audited-model"
            assert row["protocol"] == "chat_completions"
        finally:
            await db.close()

    asyncio.run(run())
