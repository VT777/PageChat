from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import llm


class FakeCompletions:
    def __init__(self):
        self.params = None

    def create(self, **params):
        self.params = params
        return object()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions()


def test_chat_completion_sets_default_timeout(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "get_llm_client", lambda: client)

    llm.chat_completion(messages=[{"role": "user", "content": "hi"}], model="qwen3.6-flash")

    assert client.chat.completions.params["timeout"] == float(llm.MODEL_FLASH_TIMEOUT_SECONDS)


def test_chat_completion_preserves_explicit_timeout(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "get_llm_client", lambda: client)

    llm.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model="qwen-plus",
        timeout=3.5,
    )

    assert client.chat.completions.params["timeout"] == 3.5


def test_chat_completion_disables_thinking_when_requested(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(llm, "get_llm_client", lambda: client)

    llm.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model="qwen-plus",
        disable_thinking=True,
    )

    assert client.chat.completions.params["extra_body"]["enable_thinking"] is False
    assert "disable_thinking" not in client.chat.completions.params


def test_chat_completion_uses_litellm_adapter_when_provider_config_is_supplied(monkeypatch):
    calls = []

    class FakeAdapter:
        def completion(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    monkeypatch.setattr(llm, "LiteLLMAdapter", lambda: FakeAdapter())

    result = llm.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        provider_config={
            "base_url": "https://example.test/v1",
            "api_key": "sk-secret",
            "model": "custom-model",
        },
        timeout=7,
    )

    assert result == {"ok": True}
    assert calls[0]["provider_config"]["model"] == "custom-model"
    assert calls[0]["timeout"] == 7


def test_chat_by_scenario_resolves_user_model_settings(monkeypatch):
    calls = []

    class FakeClient:
        chat = None

    async def fake_resolve(user_id, route_slot):
        return {
            "route_version": "qa-v1",
            "provider_config": {
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "sk-secret",
                "model": "custom-qa",
                "route_version": "qa-v1",
            },
            "model": "custom-qa",
        }

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    monkeypatch.setattr(llm, "_resolve_user_route", fake_resolve)
    monkeypatch.setattr(llm, "LiteLLMAdapter", lambda: FakeAdapter())

    import asyncio

    result = asyncio.run(
        llm.chat_by_scenario(
            "qa",
            [{"role": "user", "content": "hi"}],
            user_id="user-a",
        )
    )

    assert result == {"ok": True}
    assert calls[0]["provider_config"]["model"] == "custom-qa"


def test_chat_by_scenario_forwards_disable_thinking_to_user_route(monkeypatch):
    calls = []

    async def fake_resolve(user_id, route_slot):
        return {
            "route_version": "qa-v1",
            "provider_config": {
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "sk-secret",
                "model": "custom-qa",
                "route_version": "qa-v1",
            },
            "model": "custom-qa",
        }

    class FakeAdapter:
        async def acompletion(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    monkeypatch.setattr(llm, "_resolve_user_route", fake_resolve)
    monkeypatch.setattr(llm, "LiteLLMAdapter", lambda: FakeAdapter())

    import asyncio

    result = asyncio.run(
        llm.chat_by_scenario(
            "qa",
            [{"role": "user", "content": "hi"}],
            user_id="user-a",
            disable_thinking=True,
        )
    )

    assert result == {"ok": True}
    assert calls[0]["extra_body"]["enable_thinking"] is False
    assert "disable_thinking" not in calls[0]


def test_resolve_scenario_route_prefers_user_route(monkeypatch):
    async def fake_resolve(user_id, route_slot):
        return {
            "route_version": "qa-v1",
            "provider_config": {
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "sk-secret",
                "model": "custom-qa",
                "supports_responses_api": True,
                "supports_reasoning_effort": True,
                "supports_reasoning_summary": True,
            },
            "model": "custom-qa",
        }

    monkeypatch.setattr(llm, "_resolve_user_route", fake_resolve)

    import asyncio

    result = asyncio.run(llm.resolve_scenario_route("qa", user_id="user-a"))

    assert result["model"] == "custom-qa"
    assert result["provider_config"]["model"] == "custom-qa"


def test_resolve_user_route_loads_user_model_settings(monkeypatch):
    import asyncio
    import aiosqlite
    from app.services import model_settings_service

    class FakeConnection:
        row_factory = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    class FakeModelSettingsService:
        def __init__(self, db):
            self.db = db

        async def resolve_route(self, user_id, route_slot):
            return {
                "source": "user",
                "route_version": "qa-v1",
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "sk-secret",
                "model": "custom-qa",
                "supports_responses_api": True,
                "supports_reasoning_effort": True,
                "supports_reasoning_summary": True,
            }

    monkeypatch.setattr(aiosqlite, "connect", lambda *_args, **_kwargs: FakeConnection())
    monkeypatch.setattr(model_settings_service, "ModelSettingsService", FakeModelSettingsService)

    result = asyncio.run(llm._resolve_user_route("user-a", "document_qa"))

    assert result["model"] == "custom-qa"
    assert result["provider_config"]["supports_responses_api"] is True
