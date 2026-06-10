import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.litellm_adapter import LiteLLMAdapter, ModelProviderError


def _resolved_config() -> dict:
    return {
        "provider": "openai_compatible",
        "base_url": "https://example.test/v1",
        "api_key": "sk-secret-123456",
        "model": "custom-model",
    }


def test_sync_completion_calls_litellm_with_resolved_provider(monkeypatch) -> None:
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr("app.services.litellm_adapter.litellm.completion", fake_completion)

    result = LiteLLMAdapter().completion(
        provider_config=_resolved_config(),
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        timeout=3,
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert calls[0]["model"] == "custom-model"
    assert calls[0]["api_key"] == "sk-secret-123456"
    assert calls[0]["api_base"] == "https://example.test/v1"
    assert calls[0]["timeout"] == 3


def test_async_completion_calls_litellm(monkeypatch) -> None:
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "async-ok"}}]}

    monkeypatch.setattr(
        "app.services.litellm_adapter.litellm.acompletion", fake_acompletion
    )

    async def run() -> None:
        result = await LiteLLMAdapter().acompletion(
            provider_config=_resolved_config(),
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )

        assert result["choices"][0]["message"]["content"] == "async-ok"
        assert calls[0]["stream"] is True

    asyncio.run(run())


def test_provider_errors_do_not_leak_raw_api_keys(monkeypatch) -> None:
    def fake_completion(**_kwargs):
        raise RuntimeError("provider rejected sk-secret-123456")

    monkeypatch.setattr("app.services.litellm_adapter.litellm.completion", fake_completion)

    try:
        LiteLLMAdapter().completion(
            provider_config=_resolved_config(),
            messages=[{"role": "user", "content": "hi"}],
        )
        assert False, "Expected provider error"
    except ModelProviderError as exc:
        assert "sk-secret-123456" not in str(exc)
        assert "provider rejected" in str(exc)


def test_timeout_is_forwarded_to_async_completion(monkeypatch) -> None:
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "app.services.litellm_adapter.litellm.acompletion", fake_acompletion
    )

    async def run() -> None:
        await LiteLLMAdapter().acompletion(
            provider_config=_resolved_config(),
            messages=[{"role": "user", "content": "hi"}],
            timeout=9,
        )

    asyncio.run(run())

    assert calls[0]["timeout"] == 9
