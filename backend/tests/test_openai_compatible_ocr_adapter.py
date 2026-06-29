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


def test_page_text_task_uses_unified_prompt_and_returns_markdown() -> None:
    async def run() -> None:
        client = FakeClient("# Contents\n\n- Intro 1")
        adapter = OpenAICompatibleOCRAdapter(
            api_key="dash-secret",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-vl-ocr-2025-11-20",
            client=client,
        )

        result = await adapter.recognize("https://example.test/toc.png", task="page_text")

        call = client.calls[0]
        prompt = call["messages"][0]["content"][1]["text"]
        assert prompt == "完整、准确地抽取内容，用markdown输出"
        assert result.pages[0].evidence_level == "text_only"
        assert result.pages[0].markdown == "# Contents\n\n- Intro 1"
        assert result.pages[0].structured_items == []

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
        assert prompt == "完整、准确地抽取内容，用markdown输出"
        assert result.pages[0].evidence_level == "text_only"
        assert result.pages[0].markdown == "# Title\n\nBody text"

    asyncio.run(run())


def test_page_text_markdown_is_not_json_parsed() -> None:
    async def run() -> None:
        client = FakeClient("# Contents\n\n- Intro 1")
        adapter = OpenAICompatibleOCRAdapter(
            api_key="dash-secret",
            model="qwen-vl-ocr-2025-11-20",
            client=client,
        )

        result = await adapter.recognize("https://example.test/toc.png", task="page_text")

        assert result.pages[0].evidence_level == "text_only"
        assert result.pages[0].markdown == "# Contents\n\n- Intro 1"
        assert result.pages[0].raw == {}

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
