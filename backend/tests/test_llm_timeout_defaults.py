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
