import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.responses_adapter import OpenAIResponsesAdapter, response_provider_capabilities


def test_known_openai_compatible_providers_can_use_responses_reasoning_summary() -> None:
    dashscope = response_provider_capabilities(
        provider="dashscope",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    openai = response_provider_capabilities(
        provider="openai_compatible",
        base_url="https://api.openai.com/v1",
    )
    unknown = response_provider_capabilities(
        provider="openai_compatible",
        base_url="https://example.test/v1",
    )

    assert dashscope == {
        "supports_responses_api": True,
        "supports_reasoning_effort": True,
        "supports_reasoning_summary": False,
    }
    assert openai["supports_reasoning_summary"] is True
    assert unknown["supports_responses_api"] is False


def test_responses_adapter_builds_reasoning_summary_request(monkeypatch) -> None:
    calls = []

    class FakeResponses:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return object()

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.responses = FakeResponses()

    monkeypatch.setattr("app.services.responses_adapter.AsyncOpenAI", FakeClient)

    async def run() -> None:
        result = await OpenAIResponsesAdapter().create(
            provider_config={
                "api_key": "sk-secret",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5-mini",
                "supports_responses_api": True,
                "supports_reasoning_effort": True,
                "supports_reasoning_summary": True,
            },
            instructions="You are PageChat.",
            input_items=[{"role": "user", "content": "hi"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "search_within_document",
                        "description": "Search",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            stream=True,
            temperature=0.3,
            timeout=12,
        )

        assert result is not None

    asyncio.run(run())

    assert calls[0]["model"] == "gpt-5-mini"
    assert calls[0]["instructions"] == "You are PageChat."
    assert calls[0]["input"] == [{"role": "user", "content": "hi"}]
    assert calls[0]["reasoning"] == {"effort": "low", "summary": "auto"}
    assert calls[0]["tools"][0]["type"] == "function"
    assert calls[0]["tools"][0]["name"] == "search_within_document"
    assert calls[0]["stream"] is True
