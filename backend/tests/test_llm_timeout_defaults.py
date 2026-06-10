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
