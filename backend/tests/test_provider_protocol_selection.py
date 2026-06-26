import asyncio
from pathlib import Path
import sys

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.provider_adapter import (  # noqa: E402
    ProviderCapabilityError,
    select_provider_protocol,
)
from app.core.llm import async_chat_completion  # noqa: E402
from app.models.migrations import run_migrations  # noqa: E402
from app.services.chat_run_repository import ChatRunRepository  # noqa: E402
from app.services.model_gateway import ModelGateway  # noqa: E402
from app.services.model_settings_service import ModelSettingsService  # noqa: E402
from phase0_chat_helpers import create_chat_history_schema  # noqa: E402


class FakeSettingsService:
    def __init__(self, routes: dict[str, dict]):
        self.routes = routes

    async def resolve_route(self, user_id: str, route_slot: str) -> dict:
        route = dict(self.routes[route_slot])
        route["route_slot"] = route_slot
        return route


def test_dashscope_uses_chat_completions_even_when_responses_requested() -> None:
    selection = select_provider_protocol(
        {
            "provider": "dashscope",
            "model": "qwen-plus",
            "supports_responses_api": True,
            "supports_tool_calling": True,
        },
        prefer_responses=True,
        requires_tool_calling=True,
    )

    assert selection.protocol == "chat_completions"
    assert selection.provider == "dashscope"
    assert selection.tool_strategy == "function_calling"
    assert selection.fallback_protocol is None


def test_provider_selection_fails_fast_when_required_capability_is_missing() -> None:
    try:
        select_provider_protocol(
            {
                "provider": "openai_compatible",
                "model": "text-only",
                "supports_vision": False,
            },
            requires_vision=True,
        )
        assert False, "Expected missing vision capability to fail"
    except ProviderCapabilityError as exc:
        message = str(exc).lower()
        assert "vision" in message
        assert "text-only" in message


def test_model_gateway_attaches_single_chat_completions_protocol() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        gateway = ModelGateway(
            completion_fn=fake_completion,
            model_settings_service=FakeSettingsService(
                {
                    "document_qa": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "api_key": "sk-secret",
                        "model": "custom-qa",
                        "source": "user",
                        "route_version": "qa-v1",
                        "supports_vision": False,
                        "supports_tool_calling": True,
                    }
                }
            ),
            user_id="user-a",
        )

        await gateway.stream_answer([{"role": "user", "content": "question"}])

        provider_config = calls[0]["provider_config"]
        assert provider_config["protocol"] == "chat_completions"
        assert provider_config["provider_capabilities"]["supports_streaming"] is True
        assert provider_config.get("fallback_protocol") is None

    asyncio.run(run())


def test_model_gateway_uses_deterministic_strategy_without_forwarding_tools() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        gateway = ModelGateway(
            completion_fn=fake_completion,
            model_settings_service=FakeSettingsService(
                {
                    "general_chat": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "api_key": "sk-secret",
                        "model": "no-tools",
                        "source": "user",
                        "route_version": "chat-v1",
                        "supports_tool_calling": False,
                    }
                }
            ),
            user_id="user-a",
        )

        try:
            await gateway.plan_with_tools(
                [{"role": "user", "content": "question"}],
                tools=[{"type": "function", "function": {"name": "search"}}],
            )
            assert False, "Expected deterministic gateway tool planning to fail fast"
        except ProviderCapabilityError as exc:
            message = str(exc).lower()
            assert "deterministic" in message
            assert "tool" in message

        assert calls == []

    asyncio.run(run())


def test_model_gateway_uses_persisted_capability_flags_for_tool_strategy() -> None:
    async def run() -> None:
        calls = []

        async def fake_completion(**kwargs):
            calls.append(kwargs)
            return {"ok": True}

        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await create_chat_history_schema(db)
            await run_migrations(db)
            settings = ModelSettingsService(db)
            provider = await settings.save_provider_config(
                user_id="user-a",
                provider="openai_compatible",
                base_url="https://example.test/v1",
                api_key="sk-secret",
            )
            await settings.save_route_mapping(
                user_id="user-a",
                route_slot="general_chat",
                provider_id=provider["provider_id"],
                model="custom-no-tools",
                supports_streaming=True,
                supports_tool_calling=False,
                supports_vision=False,
                supports_structured_output=False,
                supports_responses_api=False,
            )

            gateway = ModelGateway(
                completion_fn=fake_completion,
                model_settings_service=settings,
                user_id="user-a",
            )
            try:
                await gateway.plan_with_tools(
                    [{"role": "user", "content": "question"}],
                    tools=[{"type": "function", "function": {"name": "search"}}],
                )
                assert False, "Expected persisted deterministic tool route to fail fast"
            except ProviderCapabilityError as exc:
                message = str(exc).lower()
                assert "deterministic" in message
                assert "custom-no-tools" in message

        assert calls == []

    asyncio.run(run())


def test_model_gateway_fails_fast_when_streaming_is_required_but_missing() -> None:
    async def run() -> None:
        async def fake_completion(**_kwargs):
            return {"ok": True}

        gateway = ModelGateway(
            completion_fn=fake_completion,
            model_settings_service=FakeSettingsService(
                {
                    "document_qa": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "api_key": "sk-secret",
                        "model": "batch-only",
                        "source": "user",
                        "route_version": "qa-v1",
                        "supports_streaming": False,
                    }
                }
            ),
            user_id="user-a",
        )

        try:
            await gateway.stream_answer([{"role": "user", "content": "question"}])
            assert False, "Expected missing streaming capability to fail"
        except ProviderCapabilityError as exc:
            assert "streaming" in str(exc).lower()

    asyncio.run(run())


def test_async_chat_completion_fails_fast_on_implicit_deterministic_tools(
    monkeypatch,
) -> None:
    calls = []

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    monkeypatch.setattr("app.core.llm.LiteLLMAdapter", lambda: FakeAdapter())

    async def run() -> None:
        try:
            await async_chat_completion(
                messages=[{"role": "user", "content": "question"}],
                provider_config={
                    "provider": "openai_compatible",
                    "base_url": "https://example.test/v1",
                    "api_key": "sk-secret",
                    "model": "custom-no-tools",
                    "supports_tool_calling": False,
                },
                tools=[{"type": "function", "function": {"name": "search"}}],
                tool_choice="auto",
            )
            assert False, "Expected implicit deterministic tools to fail fast"
        except ProviderCapabilityError as exc:
            message = str(exc).lower()
            assert "deterministic" in message
            assert "custom-no-tools" in message

    asyncio.run(run())
    assert calls == []


def test_async_chat_completion_allows_explicit_deterministic_answer_generation(
    monkeypatch,
) -> None:
    calls = []

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    monkeypatch.setattr("app.core.llm.LiteLLMAdapter", lambda: FakeAdapter())

    async def run() -> None:
        result = await async_chat_completion(
            messages=[{"role": "user", "content": "answer from deterministic evidence"}],
            provider_config={
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "sk-secret",
                "model": "custom-no-tools",
                "supports_tool_calling": False,
            },
            tools=[{"type": "function", "function": {"name": "search"}}],
            tool_choice="auto",
            allow_deterministic_tools=True,
        )

        assert result == {"ok": True}

    asyncio.run(run())
    assert "tools" not in calls[0]
    assert "tool_choice" not in calls[0]
    assert calls[0]["provider_config"]["tool_strategy"] == "pagechat_deterministic_tools"


def test_agent_run_records_exactly_one_selected_protocol() -> None:
    async def run() -> None:
        async with aiosqlite.connect(":memory:") as db:
            await create_chat_history_schema(db)
            await run_migrations(db)
            await db.execute(
                """
                INSERT INTO conversations (id, title, user_id)
                VALUES ('conv-protocol', 'Protocol test', 'user-a')
                """
            )
            await db.commit()
            repo = ChatRunRepository(db)
            user_id = await repo.create_user_message("conv-protocol", "Question")
            assistant_id = await repo.create_assistant_placeholder(
                "conv-protocol",
                "run-protocol",
            )
            selection = select_provider_protocol(
                {"provider": "openai_compatible", "model": "custom-qa"}
            )

            await repo.create_run(
                run_id="run-protocol",
                conversation_id="conv-protocol",
                user_message_id=user_id,
                assistant_message_id=assistant_id,
                protocol=selection.protocol,
            )
            cursor = await db.execute(
                "SELECT protocol FROM agent_runs WHERE id = 'run-protocol'"
            )
            row = await cursor.fetchone()

        assert row[0] == "chat_completions"
        assert "->" not in row[0]
        assert "," not in row[0]

    asyncio.run(run())
