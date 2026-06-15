import asyncio
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ocr_engines.openai_compatible_adapter import (  # noqa: E402
    OpenAICompatibleOCRAdapter,
)


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Completion:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class FakeCompletions:
    def __init__(self, client) -> None:
        self.client = client

    async def create(self, **kwargs):
        self.client.calls.append(kwargs)
        if isinstance(self.client.response, Exception):
            raise self.client.response
        return _Completion(self.client.response)


class FakeChat:
    def __init__(self, client) -> None:
        self.completions = FakeCompletions(client)


class FakeClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls = []
        self.chat = FakeChat(self)


def test_toc_page_prompt_requests_strict_json_and_parses_items() -> None:
    async def run() -> None:
        client = FakeClient(
            '{"items":[{"title":"Intro","page":1,"level":1}],"confidence":0.88}'
        )
        adapter = OpenAICompatibleOCRAdapter(
            api_key="dash-secret",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-vl-ocr-2025-11-20",
            client=client,
        )

        result = await adapter.recognize("https://example.test/toc.png", task="toc_page")

        call = client.calls[0]
        prompt = call["messages"][0]["content"][1]["text"]
        assert "strict JSON" in prompt
        assert "items" in prompt
        assert result.pages[0].evidence_level == "model_inferred"
        assert result.pages[0].structured_items == [{"title": "Intro", "page": 1, "level": 1}]
        assert result.pages[0].raw["confidence"] == 0.88

    asyncio.run(run())


def test_page_text_prompt_requests_markdown_and_returns_text_only() -> None:
    async def run() -> None:
        client = FakeClient("# Title\n\nBody text")
        adapter = OpenAICompatibleOCRAdapter(
            api_key="dash-secret",
            model="qwen-vl-ocr-2025-11-20",
            client=client,
        )

        result = await adapter.recognize("data:image/png;base64,abc", task="page_text")

        prompt = client.calls[0]["messages"][0]["content"][1]["text"]
        assert "Markdown" in prompt
        assert result.pages[0].evidence_level == "text_only"
        assert result.pages[0].markdown == "# Title\n\nBody text"

    asyncio.run(run())


def test_toc_page_markdown_fallback_when_json_parse_fails() -> None:
    async def run() -> None:
        client = FakeClient("# Contents\n\n- Intro 1")
        adapter = OpenAICompatibleOCRAdapter(
            api_key="dash-secret",
            model="qwen-vl-ocr-2025-11-20",
            client=client,
        )

        result = await adapter.recognize("https://example.test/toc.png", task="toc_page")

        assert result.pages[0].evidence_level == "text_only"
        assert result.pages[0].markdown == "# Contents\n\n- Intro 1"
        assert result.pages[0].raw["parse_error"]

    asyncio.run(run())


def test_api_key_is_redacted_from_adapter_errors() -> None:
    async def run() -> None:
        client = FakeClient(RuntimeError("provider rejected dash-secret"))
        adapter = OpenAICompatibleOCRAdapter(
            api_key="dash-secret",
            model="qwen-vl-ocr-2025-11-20",
            client=client,
        )

        try:
            await adapter.recognize("https://example.test/toc.png", task="page_text")
            assert False, "Expected provider failure"
        except RuntimeError as exc:
            assert "dash-secret" not in str(exc)
            assert "[redacted-api-key]" in str(exc)

    asyncio.run(run())
